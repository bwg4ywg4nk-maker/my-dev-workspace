"""Private, unqualified Pillow BASIC primitives and narrow SFNT inspection.

No lifecycle qualification is inferred from these primitives. In particular,
candidate agreement is NOT proof of agreement with a loaded native build.
``layout._open_provider`` stays closed pending the artifact-bound bootstrap and
native cmap audit. Nothing here discovers fonts or imports Pillow at module load.
"""
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from struct import unpack_from
import sys
from typing import Tuple


_FONT_SHA256 = '525979822591a3447cfc49d943d6f7683508e25543407871c0ed8fed05fd2bd9'
_MAX_FONT_BYTES = 8388608
_NAMES = {1: 'Arial', 2: 'Regular', 4: 'Arial', 6: 'ArialMT',
          16: 'Arial', 17: 'Regular'}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _buffer(data):
    _require(type(data) is bytes, 'Font must be concrete immutable bytes')
    _require(0 < len(data) <= _MAX_FONT_BYTES, 'Font byte size')


def _region(data, offset, length):
    _require(0 <= offset <= len(data) and 0 <= length <= len(data) - offset,
             'SFNT region outside buffer')
    return data[offset:offset + length]


def _u16(data, offset):
    _require(0 <= offset <= len(data) - 2, 'Truncated SFNT uint16')
    return unpack_from('>H', data, offset)[0]


def _i16(data, offset):
    _require(0 <= offset <= len(data) - 2, 'Truncated SFNT int16')
    return unpack_from('>h', data, offset)[0]


def _u32(data, offset):
    _require(0 <= offset <= len(data) - 4, 'Truncated SFNT uint32')
    return unpack_from('>I', data, offset)[0]


def _verify_identity(data, identity):
    # Also usable independently of layout's pass 9, without importing Pillow.
    from .layout import FontIdentity
    _require(type(identity) is FontIdentity, 'Expected concrete FontIdentity')
    try:
        identity.__post_init__()
        _require((identity.family, identity.style, identity.face_index) ==
                 ('Arial', 'Regular', 0), 'Unsupported Arial Regular face identity')
        _buffer(data)
        _require(sha256(data).hexdigest() == identity.sha256 == _FONT_SHA256,
                 'Font digest mismatch')
    except AttributeError as exc:
        raise ValueError('Malformed FontIdentity') from exc


@dataclass(frozen=True)
class _Inspection:
    num_glyphs: int
    # (platform, encoding, format, subtable offset); directory order preserved.
    candidates: Tuple[Tuple[int, int, int, int], ...]
    # Entry i is the agreed glyph ID for U+0020+i. No font bytes are retained.
    ascii_glyphs: Tuple[int, ...]


def _directory(data):
    _require(len(data) >= 12 and data[:4] == b'\x00\x01\x00\x00',
             'Only standalone TrueType SFNT 1.0 is supported (no collections)')
    count = _u16(data, 4)
    _require(0 < count <= (len(data) - 12) // 16, 'Truncated SFNT table directory')
    tables = {}
    for i in range(count):
        pos = 12 + 16 * i
        tag = bytes(data[pos:pos + 4])
        _require(tag not in tables, 'Duplicate SFNT table')
        offset, length = _u32(data, pos + 8), _u32(data, pos + 12)
        tables[tag] = _region(data, offset, length)
    _require(b'fvar' not in tables, 'Variable fonts are unsupported')
    _require(all(tag in tables for tag in (b'head', b'maxp', b'OS/2', b'name', b'cmap')),
             'Missing required SFNT table')
    return tables


def _face_tables(tables):
    head, maxp, os2 = tables[b'head'], tables[b'maxp'], tables[b'OS/2']
    _require(len(head) == 54, 'Malformed head length')
    _require(_u32(head, 0) == 0x00010000 and _u32(head, 12) == 0x5F0F3CF5,
             'Malformed head version/magic')
    _require(16 <= _u16(head, 18) <= 16384, 'Malformed head unitsPerEm')
    _require(_i16(head, 36) <= _i16(head, 40) and
             _i16(head, 38) <= _i16(head, 42), 'Malformed head bounds')
    _require(_u16(head, 44) & 3 == 0, 'Bold/italic head.macStyle')
    _require(_i16(head, 50) in (0, 1) and _i16(head, 52) == 0,
             'Unsupported head format')
    _require(len(maxp) == 32 and _u32(maxp, 0) == 0x00010000,
             'Malformed TrueType maxp')
    num_glyphs = _u16(maxp, 4)
    _require(num_glyphs > 0, 'Invalid numGlyphs')
    version = _u16(os2, 0)
    lengths = {0: 78, 1: 86, 2: 96, 3: 96, 4: 96, 5: 100}
    _require(version in lengths and len(os2) == lengths[version], 'Malformed OS/2')
    selection = _u16(os2, 62)
    _require(selection & (1 | 32 | 512) == 0 and selection & 64 != 0,
             'OS/2.fsSelection must be Regular, not bold/italic/oblique')
    return num_glyphs


def _names(data):
    _require(_u16(data, 0) == 0, 'Only name format 0 is supported')
    count, storage = _u16(data, 2), _u16(data, 4)
    _require(count <= (len(data) - 6) // 12, 'Truncated name records')
    _require(6 + 12 * count <= storage <= len(data), 'Invalid name string storage')
    found = set()
    for i in range(count):
        pos = 6 + 12 * i
        platform, encoding, language, name_id, length, offset = unpack_from('>6H', data, pos)
        raw = _region(data, storage + offset, length)
        codec = ('utf-16-be' if platform == 3 and encoding in (1, 10) and language == 0x409
                 else 'mac_roman' if (platform, encoding, language) == (1, 0, 0) else None)
        if name_id not in _NAMES or codec is None:
            continue
        expected = _NAMES[name_id]
        # The exact required spellings bound allocation *before* decoding.
        _require(length == len(expected) * (2 if codec == 'utf-16-be' else 1),
                 'Unexpected Arial name string length')
        try:
            value = bytes(raw).decode(codec, errors='strict')
        except UnicodeError as exc:
            raise ValueError('Malformed name encoding') from exc
        _require(value == expected, 'Arial name disagreement')
        found.add(name_id)
    _require({1, 2, 4, 6} <= found, 'Missing required Arial names')


def _format4(data, num_glyphs):
    _require(len(data) >= 16 and len(data) % 2 == 0 and _u16(data, 4) == 0,
             'Malformed cmap format 4 header')
    doubled = _u16(data, 6)
    _require(doubled > 0 and doubled % 2 == 0, 'Invalid cmap segment count')
    count = doubled // 2
    array_start = 16 + 8 * count
    _require(array_start <= len(data), 'Truncated cmap segment arrays')
    power = count.bit_length() - 1
    search = 2 * (1 << power)
    _require((_u16(data, 8), _u16(data, 10), _u16(data, 12)) ==
             (search, power, doubled - search), 'Malformed cmap search parameters')
    _require(_u16(data, 14 + 2 * count) == 0, 'Nonzero cmap reservedPad')
    previous = -1
    for i in range(count):
        end = _u16(data, 14 + 2 * i)
        start = _u16(data, 16 + 2 * count + 2 * i)
        delta = _i16(data, 16 + 4 * count + 2 * i)
        address = 16 + 6 * count + 2 * i
        offset = _u16(data, address)
        _require(previous < start <= end, 'Unordered/overlapping cmap segments')
        previous = end
        if offset:
            first = address + offset
            _require(offset % 2 == 0 and first >= array_start and
                     first + 2 * (end - start + 1) <= len(data),
                     'Invalid cmap idRangeOffset')
            # Nonoverlap bounds total referenced entries by the 16-bit domain;
            # every referenced byte range is checked before traversing it.
            for pos in range(first, first + 2 * (end - start + 1), 2):
                glyph = _u16(data, pos)
                if glyph:
                    glyph = (glyph + delta) & 0xFFFF
                _require(glyph < num_glyphs, 'cmap glyph exceeds numGlyphs')
        else:
            first = (start + delta) & 0xFFFF
            # A modular wrap includes 65535, necessarily outside numGlyphs.
            _require(first + end - start < num_glyphs, 'cmap glyph exceeds numGlyphs')
    _require(start == end == 0xFFFF, 'Missing cmap format 4 terminal segment')
    return (4, data, count)


def _format12(data, num_glyphs):
    _require(len(data) >= 16 and _u16(data, 2) == 0 and _u32(data, 8) == 0,
             'Malformed cmap format 12 header')
    count = _u32(data, 12)
    _require(count <= (len(data) - 16) // 12 and 16 + 12 * count == len(data),
             'Invalid cmap group count/length')
    previous = -1
    for i in range(count):
        start, end, glyph = unpack_from('>3I', data, 16 + 12 * i)
        _require(previous < start <= end <= 0x10FFFF, 'Unordered/invalid cmap groups')
        _require(glyph + end - start < num_glyphs, 'cmap glyph exceeds numGlyphs')
        previous = end
    return (12, data, count)


def _glyph(candidate, codepoint):
    fmt, data, count = candidate
    # Binary search avoids a proportional scan per ASCII codepoint.
    low, high = 0, count
    while low < high:
        mid = (low + high) // 2
        end = (_u16(data, 14 + 2 * mid) if fmt == 4
               else _u32(data, 20 + 12 * mid))
        if end < codepoint:
            low = mid + 1
        else:
            high = mid
    if low == count:
        return 0
    if fmt == 12:
        start, end, glyph = unpack_from('>3I', data, 16 + 12 * low)
        return glyph + codepoint - start if codepoint >= start else 0
    start = _u16(data, 16 + 2 * count + 2 * low)
    if codepoint < start:
        return 0
    delta = _i16(data, 16 + 4 * count + 2 * low)
    address = 16 + 6 * count + 2 * low
    offset = _u16(data, address)
    if not offset:
        return (codepoint + delta) & 0xFFFF
    glyph = _u16(data, address + offset + 2 * (codepoint - start))
    return (glyph + delta) & 0xFFFF if glyph else 0


def _cmaps(data, num_glyphs):
    _require(_u16(data, 0) == 0, 'Malformed cmap version')
    count = _u16(data, 2)
    _require(count <= (len(data) - 4) // 8, 'Truncated cmap records')
    records, candidates, parsed = [], [], {}
    for i in range(count):
        platform, encoding, offset = unpack_from('>HHI', data, 4 + 8 * i)
        _require(offset >= 4 + 8 * count, 'cmap subtable overlaps records')
        fmt = _u16(data, offset)
        _require(fmt != 14, 'Variation cmap is unsupported')
        eligible = platform == 0 or (platform == 3 and encoding in (1, 10))
        _require(platform != 0 or encoding in (0, 1, 2, 3, 4, 6),
                 'Unrecognized platform-0 Unicode cmap')
        # Bounds-check even noncandidate subtable storage without interpreting
        # its glyph semantics. Unknown structures fail closed.
        if fmt in (0, 2, 4, 6):
            length = _u16(data, offset + 2)
            _require(length >= 6, 'Malformed cmap subtable length')
        elif fmt in (8, 10, 12, 13):
            length = _u32(data, offset + 4)
            _require(length >= 16, 'Malformed cmap subtable length')
        else:
            raise ValueError('Unsupported cmap structure')
        subtable = _region(data, offset, length)
        if not eligible:
            continue
        _require(fmt in (4, 12), 'Unsupported Unicode cmap format')
        if offset not in parsed:
            parsed[offset] = (_format4(subtable, num_glyphs) if fmt == 4
                              else _format12(subtable, num_glyphs))
        candidates.append(parsed[offset])
        records.append((platform, encoding, fmt, offset))
    _require(candidates, 'No eligible Unicode cmap')
    mapping = []
    # Exactly 95 rounds, all candidates, irrespective of presentation text.
    for codepoint in range(32, 127):
        agreed = None
        for candidate in candidates:
            glyph = _glyph(candidate, codepoint)
            _require(0 < glyph < num_glyphs, 'Missing/invalid printable ASCII glyph')
            _require(agreed is None or glyph == agreed, 'Unicode cmap candidate disagreement')
            agreed = glyph
        mapping.append(agreed)
    return tuple(records), tuple(mapping)


def _inspect_sfnt(data, face_index=0):
    """Structure-only primitive; synthetic tests need no identity bypass.

    The layout seam calls this only after pass-9 identity validation and pass-10
    runtime qualification. Views avoid copying proportional table data.
    """
    _buffer(data)
    _require(type(face_index) is int and face_index == 0, 'Only face index 0 is supported')
    tables = _directory(memoryview(data))
    num_glyphs = _face_tables(tables)
    _names(tables[b'name'])
    candidates, mapping = _cmaps(tables[b'cmap'], num_glyphs)
    return _Inspection(num_glyphs, candidates, mapping)


def _inspect_font(data, identity):
    """Standalone identity-plus-structure check for explicitly supplied bytes.

    The layout factory already owns identity validation in pass 9 and calls the
    structure primitive directly in pass 11, without replaying that owner.
    """
    _verify_identity(data, identity)
    return _inspect_sfnt(data, identity.face_index)


def _pillow_capability():
    """Observable capability only; never a runtime qualification certificate."""
    _require(sys.version_info >= (3, 10), 'Provider capability requires Python >= 3.10')
    try:
        import PIL
        from PIL import ImageFont
        _require(PIL.__version__ == '12.3.0', 'Pillow version mismatch')
        _require(ImageFont.core.freetype2_version == '2.14.3', 'FreeType version mismatch')
        engine = ImageFont.Layout.BASIC
    except (ImportError, AttributeError, OSError) as exc:
        raise ValueError('Pillow BASIC capability unavailable') from exc
    return ImageFont, engine


class _PillowBasicCore:
    """Unqualified private primitives, matching layout's raw-font seam.

    Loading primitives are individually testable, but inspect_font deliberately
    prevents this object from serving as a complete provider. A future trusted
    bootstrap must bind the native audit proving precisely the inspected cmap
    set and glyph interpretation. No boolean or caller token can open that gate.
    """

    def __init__(self):
        self._image_font, self.basic_engine = _pillow_capability()

    def inspect_font(self, data, profile):
        _inspect_sfnt(data, profile.font.face_index)
        raise ValueError('Native build/font cmap agreement audit is not yet bound')

    def load_font(self, data, *, size, index, encoding, layout_engine):
        # This low-level primitive neither parses nor certifies the font. The
        # production sequence owns identity/inspection before any of its loads.
        _buffer(data)
        _require(type(size) is int and size in (180, 240, 320), 'Unsupported font size')
        _require(type(index) is int and index == 0, 'Only face index 0 is supported')
        _require(type(encoding) is str and encoding == 'unic', 'Unicode encoding required')
        _require(layout_engine is self.basic_engine, 'BASIC engine required')
        try:
            # Direct constructor: never ImageFont.truetype's filesystem fallback.
            return self._image_font.FreeTypeFont(
                BytesIO(data), size=size, index=index, encoding=encoding,
                layout_engine=self.basic_engine)
        except MemoryError:
            raise
        except Exception as exc:
            raise ValueError('Pillow in-memory font load failed: ' + str(exc)) from exc
