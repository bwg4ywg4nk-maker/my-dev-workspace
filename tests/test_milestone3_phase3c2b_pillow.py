"""Phase 2A primitives, not deployment qualification.

External-font checks run ONLY with PRESENTATION_AGENT_ARIAL_FONT explicitly set
to a lawfully provisioned exact-digest font. They read it without copying it.
Skipped checks do not constitute real-provider or controlled-runtime acceptance.
"""
import ast
from contextlib import contextmanager
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
import os
from pathlib import Path
from struct import pack, pack_into
import subprocess
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from presentation_agent import _pillow_basic as p
from presentation_agent import layout as l
from test_milestone3_phase3c2b_layout import fixture, profile, DoubleFont, DoubleProvider


def changed(data, offset, fmt, value):
    result = bytearray(data)
    pack_into('>' + fmt, result, offset, value)
    return bytes(result)


def name_table(extra=(), omit=()):
    records = [(3, 1, 0x409, key, value.encode('utf-16-be'))
               for key, value in p._NAMES.items() if key not in omit]
    records.extend(extra)
    strings = bytearray()
    entries = bytearray()
    for platform, encoding, language, key, raw in records:
        entries.extend(pack('>6H', platform, encoding, language, key, len(raw), len(strings)))
        strings.extend(raw)
    return pack('>3H', 0, len(records), 6 + 12 * len(records)) + entries + strings


def format4(start=32, end=126, delta=-31, glyphs=None):
    # Two segments: printable ASCII and required terminal .notdef segment.
    array = b'' if glyphs is None else pack('>' + 'H' * len(glyphs), *glyphs)
    return (pack('>7H', 4, 32 + len(array), 0, 4, 4, 1, 0) +
            pack('>3H', end, 65535, 0) + pack('>2H', start, 65535) +
            pack('>2h', delta, 1) + pack('>2H', 0 if glyphs is None else 4, 0) + array)


def format12(groups=((32, 126, 1),)):
    return (pack('>HHIII', 12, 0, 16 + 12 * len(groups), 0, len(groups)) +
            b''.join(pack('>III', *group) for group in groups))


def cmap_table(records=None):
    if records is None:
        records = ((0, 3, format4()), (3, 10, format12()))
    entries, subtables = bytearray(), bytearray()
    base = 4 + 8 * len(records)
    for platform, encoding, data in records:
        entries.extend(pack('>HHI', platform, encoding, base + len(subtables)))
        subtables.extend(data)
    return pack('>HH', 0, len(records)) + entries + subtables


def tables():
    head = bytearray(54)
    for offset, fmt, value in ((0, 'I', 0x10000), (12, 'I', 0x5F0F3CF5), (18, 'H', 2048)):
        pack_into('>' + fmt, head, offset, value)
    maxp = bytearray(32)
    pack_into('>IH', maxp, 0, 0x10000, 512)
    os2 = bytearray(96)
    pack_into('>H', os2, 0, 4)
    pack_into('>H', os2, 62, 64)
    return {b'head': bytes(head), b'maxp': bytes(maxp), b'OS/2': bytes(os2),
            b'name': bytes(name_table()), b'cmap': bytes(cmap_table())}


def sfnt(items=None):
    items = list(tables().items()) if items is None else list(items)
    directory, payload = bytearray(), bytearray()
    base = 12 + 16 * len(items)
    for tag, data in items:
        directory.extend(pack('>4sIII', tag, 0, base + len(payload), len(data)))
        payload.extend(data)
    return pack('>I4H', 0x10000, len(items), 0, 0, 0) + directory + payload


class SfntTests(unittest.TestCase):
    def inspect_table(self, tag, data):
        items = tables()
        items[tag] = data
        return p._inspect_sfnt(bytes(sfnt(items.items())))

    def test_valid_formats_and_all_candidates(self):
        result = p._inspect_sfnt(bytes(sfnt()))
        self.assertEqual(result.num_glyphs, 512)
        self.assertEqual(result.ascii_glyphs, tuple(range(1, 96)))
        self.assertEqual(tuple(x[:3] for x in result.candidates), ((0, 3, 4), (3, 10, 12)))
        for platform, encodings in ((0, (0, 1, 2, 3, 4, 6)), (3, (1, 10))):
            for encoding in encodings:
                for subtable in (format4(), format12()):
                    result = self.inspect_table(b'cmap', cmap_table(((platform, encoding, subtable),)))
                    self.assertEqual(result.ascii_glyphs, tuple(range(1, 96)))

    def test_signature_collections_and_truncated_directory(self):
        for signature in (b'ttcf', b'OTTO', b'true', b'\0\0\0\0'):
            with self.subTest(signature=signature), self.assertRaises(ValueError):
                p._inspect_sfnt(signature + bytes(sfnt())[4:])
        for size in range(12):
            with self.assertRaises(ValueError):
                p._inspect_sfnt(bytes(sfnt())[:size])
        with patch.object(p, '_region', side_effect=AssertionError('traversed')):
            with self.assertRaisesRegex(ValueError, 'directory'):
                p._inspect_sfnt(changed(bytes(sfnt()), 4, 'H', 65535))

    def test_duplicate_missing_fvar_and_out_of_bounds_tables(self):
        items = list(tables().items())
        for malformed in (items + [items[0]], items + [(b'fvar', b'')]):
            with self.assertRaises(ValueError):
                p._inspect_sfnt(bytes(sfnt(malformed)))
        for tag in tables():
            with self.subTest(missing=tag), self.assertRaises(ValueError):
                p._inspect_sfnt(bytes(sfnt((k, v) for k, v in items if k != tag)))
        for offset in (20, 24):
            with self.assertRaises(ValueError):
                p._inspect_sfnt(changed(bytes(sfnt()), offset, 'I', 0xFFFFFFFF))

    def test_head_semantics(self):
        raw = tables()[b'head']
        bad = [raw[:-1], raw + b'\0']
        for offset, fmt, values in ((0, 'I', (0,)), (12, 'I', (0,)), (18, 'H', (0, 16385)),
                                    (44, 'H', (1, 2, 3)), (50, 'h', (-1, 2)), (52, 'h', (1,)),
                                    (36, 'h', (1,)), (38, 'h', (1,))):
            bad.extend(changed(raw, offset, fmt, v) for v in values)
        for data in bad:
            with self.subTest(data=data), self.assertRaises(ValueError):
                self.inspect_table(b'head', data)

    def test_maxp_and_os2_semantics(self):
        raw = tables()[b'maxp']
        for bad in (raw[:6], changed(raw, 0, 'I', 0x5000), changed(raw, 4, 'H', 0)):
            with self.assertRaises(ValueError):
                self.inspect_table(b'maxp', bad)
        raw = tables()[b'OS/2']
        for bad in (b'', raw[:64], changed(raw, 0, 'H', 6),
                    *(changed(raw, 62, 'H', value) for value in (0, 1, 32, 512, 65, 96, 576))):
            with self.assertRaises(ValueError):
                self.inspect_table(b'OS/2', bad)

    def test_names_mac_windows_optional_and_conflicts(self):
        mac = tuple((1, 0, 0, key, value.encode('mac_roman')) for key, value in p._NAMES.items())
        self.inspect_table(b'name', name_table(extra=mac))
        self.inspect_table(b'name', name_table(extra=mac, omit=tuple(p._NAMES)))
        self.inspect_table(b'name', name_table(omit=(16, 17)))
        for key, spelling in ((1, b'Other'), (2, b'Italic'), (4, b'ArialX'),
                              (6, b'ArialXX'), (16, b'Other'), (17, b'Italic')):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.inspect_table(b'name', name_table(extra=((1, 0, 0, key, spelling),)))
        for key in (1, 2, 4, 6):
            with self.assertRaises(ValueError):
                self.inspect_table(b'name', name_table(omit=(key,)))
        # Other languages/IDs have no naming authority, but their bounds matter.
        self.inspect_table(b'name', name_table(extra=((3, 1, 0x411, 1, b'\xff'), (3, 1, 0x409, 9, b'\xff'))))

    def test_malformed_names_counts_storage_encoding_and_string_lengths(self):
        raw = bytes(name_table())
        for offset, value in ((0, 1), (2, 65535), (4, 0), (4, 65535), (14, 65535), (16, 65535)):
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                self.inspect_table(b'name', changed(raw, offset, 'H', value))
        bad_utf16 = b'\xd8\x00' + 'rial'.encode('utf-16-be')
        with self.assertRaisesRegex(ValueError, 'encoding'):
            self.inspect_table(b'name', name_table(extra=((3, 1, 0x409, 1, bad_utf16),)))
        with patch.object(p, '_region', side_effect=AssertionError('record traversal')):
            with self.assertRaisesRegex(ValueError, 'records'):
                p._names(memoryview(changed(raw, 2, 'H', 65535)))
        # A large but in-bounds authoritative name must reject before decoding.
        with self.assertRaisesRegex(ValueError, 'string length'):
            self.inspect_table(b'name', name_table(extra=((1, 0, 0, 1, b'A' * 65535),)))

    def test_cmap_bad_headers_records_offsets_and_unsupported_formats(self):
        raw = bytes(cmap_table())
        for offset, fmt, value in ((0, 'H', 1), (2, 'H', 65535), (8, 'I', 0),
                                    (8, 'I', 0xFFFFFFFF)):
            with self.assertRaises(ValueError):
                self.inspect_table(b'cmap', changed(raw, offset, fmt, value))
        for platform, encoding, subtable in ((0, 5, format4()), (0, 7, format4()),
                (3, 1, pack('>3H', 6, 6, 0)), (1, 0, pack('>3H', 14, 6, 0)),
                (3, 10, changed(format12(), 0, 'H', 13)), (3, 1, pack('>3H', 99, 6, 0))):
            with self.assertRaises(ValueError):
                self.inspect_table(b'cmap', cmap_table(((platform, encoding, subtable),)))
        with self.assertRaisesRegex(ValueError, 'No eligible'):
            self.inspect_table(b'cmap', cmap_table(((1, 0, pack('>3H', 0, 6, 0)),)))
        with patch.object(p, '_format4', side_effect=AssertionError('parsed')):
            with self.assertRaisesRegex(ValueError, 'records'):
                p._cmaps(memoryview(changed(raw, 2, 'H', 65535)), 512)

    def test_ascii_coverage_zero_glyph_out_of_range_and_disagreement(self):
        for subtable in (format4(start=33), format4(end=125), format4(delta=-32),
                         format4(delta=500), format12(((33, 126, 1),)),
                         format12(((32, 125, 1),)), format12(((32, 126, 0),)),
                         format12(((32, 126, 512),))):
            with self.assertRaises(ValueError):
                self.inspect_table(b'cmap', cmap_table(((3, 1, subtable),)))
        with self.assertRaisesRegex(ValueError, 'disagreement'):
            self.inspect_table(b'cmap', cmap_table(((0, 3, format4()), (3, 10, format12(((32, 126, 2),))))))

    def test_format4_range_offsets_delta_modulo_and_zero_handling(self):
        good = format4(delta=-1, glyphs=tuple(range(2, 97)))
        result = self.inspect_table(b'cmap', cmap_table(((3, 1, good),)))
        self.assertEqual(result.ascii_glyphs, tuple(range(1, 96)))
        # idDelta applies only to nonzero glyph-array entries.
        for value in (0, 1, 513):
            with self.assertRaises(ValueError):
                self.inspect_table(b'cmap', cmap_table(((3, 1, changed(good, 32, 'H', value)),)))
        for offset, value in ((6, 65534), (6, 3), (8, 0), (10, 0), (12, 1), (18, 1),
                              (22, 126), (16, 65534), (28, 1), (28, 2), (28, 65534)):
            with self.subTest(offset=offset, value=value), self.assertRaises(ValueError):
                self.inspect_table(b'cmap', cmap_table(((3, 1, changed(good, offset, 'H', value)),)))
        # 0xFFFF + 2 wraps to 1, an accepted mapping.
        wrapped = format4(delta=2, glyphs=(65535,) * 95)
        self.assertEqual(self.inspect_table(b'cmap', cmap_table(((3, 1, wrapped),))).ascii_glyphs, (1,) * 95)
        # A bad non-ASCII reference must not escape ASCII-only checks.
        with self.assertRaises(ValueError):
            self.inspect_table(b'cmap', cmap_table(((3, 1, format4(end=127, delta=400)),)))

    def test_format12_groups_validated_without_expanding_codepoint_ranges(self):
        raw = format12()
        for offset, value in ((2, 1), (8, 1), (12, 0xFFFFFFFF), (16, 127),
                              (20, 0x110000), (24, 0xFFFFFFFF)):
            with self.assertRaises(ValueError):
                self.inspect_table(b'cmap', cmap_table(((3, 10, changed(raw, offset, 'H' if offset == 2 else 'I', value)),)))
        for groups in (((32, 126, 1), (126, 127, 1)), ((32, 126, 1), (1000, 1000, 512))):
            with self.assertRaises(ValueError):
                self.inspect_table(b'cmap', cmap_table(((3, 10, format12(groups)),)))
        with patch.object(p, 'unpack_from', side_effect=AssertionError('group traversal')):
            with self.assertRaisesRegex(ValueError, 'count/length'):
                # Header readers also use unpack_from; substitute only them.
                with patch.object(p, '_u16', side_effect=(0,)), patch.object(p, '_u32', side_effect=(0, 0xFFFFFFFF)):
                    p._format12(memoryview(raw), 512)

    def test_shared_subtable_parsed_once_and_95_rounds(self):
        raw = pack('>HH', 0, 2) + pack('>HHI', 0, 3, 20) + pack('>HHI', 3, 1, 20) + format4()
        with patch.object(p, '_format4', wraps=p._format4) as parse, patch.object(p, '_glyph', wraps=p._glyph) as lookup:
            self.inspect_table(b'cmap', raw)
        self.assertEqual(parse.call_count, 1)
        self.assertEqual(lookup.call_count, 190)
        self.assertEqual([call.args[1] for call in lookup.call_args_list], [cp for cp in range(32, 127) for _ in range(2)])

    def test_immutable_bytes_and_size_bounds_before_parse(self):
        for data in (bytearray(sfnt()), memoryview(bytes(sfnt())), b'', b'x' * (p._MAX_FONT_BYTES + 1)):
            with patch.object(p, '_directory', side_effect=AssertionError('parsed')):
                with self.assertRaises(ValueError):
                    p._inspect_sfnt(data)
        with patch.object(p, '_directory', side_effect=RuntimeError('size accepted')):
            with self.assertRaisesRegex(RuntimeError, 'size accepted'):
                p._inspect_sfnt(b'x' * p._MAX_FONT_BYTES)
        for face in (True, -1, 1, 0.0):
            with self.assertRaises(ValueError):
                p._inspect_sfnt(bytes(sfnt()), face)

    def test_exact_identity_before_parsing(self):
        identity = profile(p._FONT_SHA256).font
        for bad in (replace(identity, family='Other'), replace(identity, style='Italic'),
                    replace(identity, face_index=1), replace(identity, sha256='a' * 64), identity):
            with patch.object(p, '_inspect_sfnt', side_effect=AssertionError('parsed')):
                with self.assertRaises(ValueError):
                    p._inspect_font(bytes(sfnt()), bad)
        with patch.object(p, 'sha256', side_effect=AssertionError('hashed oversized')):
            with self.assertRaises(ValueError):
                p._verify_identity(b'x' * (p._MAX_FONT_BYTES + 1), identity)


@contextmanager
def fake_pillow():
    pil, image_font = ModuleType('PIL'), ModuleType('PIL.ImageFont')
    pil.__version__ = '12.3.0'
    image_font.core = SimpleNamespace(freetype2_version='2.14.3', HAVE_RAQM=False)
    image_font.Layout = SimpleNamespace(BASIC=object())
    image_font.FreeTypeFont = Mock()
    image_font.truetype = Mock(side_effect=AssertionError('fallback/discovery'))
    pil.ImageFont = image_font
    with patch.dict(sys.modules, {'PIL': pil, 'PIL.ImageFont': image_font}):
        yield pil, image_font


class ProviderTests(unittest.TestCase):
    def test_python_gate_precedes_pillow_import(self):
        with patch.object(sys, 'version_info', (3, 9, 99)), patch('builtins.__import__', side_effect=AssertionError('imported')):
            with self.assertRaisesRegex(ValueError, 'Python >= 3.10'):
                p._PillowBasicCore()

    def test_versions_basic_and_missing_dependency(self):
        with patch.dict(sys.modules, {'PIL': None}):
            with self.assertRaisesRegex(ValueError, 'unavailable'):
                p._PillowBasicCore()
        for kind in ('pillow', 'freetype', 'basic'):
            with fake_pillow() as (pil, image_font):
                if kind == 'pillow':
                    pil.__version__ = '12.2.0'
                elif kind == 'freetype':
                    image_font.core.freetype2_version = '2.14.2'
                else:
                    del image_font.Layout.BASIC
                with self.assertRaises(ValueError):
                    p._PillowBasicCore()

    def test_exact_in_memory_loads_without_raqm_or_discovery(self):
        with fake_pillow() as (_, image_font):
            del image_font.core.HAVE_RAQM  # Must not even require the attribute.
            core = p._PillowBasicCore()
            data = bytes(sfnt())
            for size in (180, 240, 320):
                core.load_font(data, size=size, index=0, encoding='unic', layout_engine=core.basic_engine)
            calls = image_font.FreeTypeFont.call_args_list
            self.assertEqual(len(calls), 3)
            streams = [call.args[0] for call in calls]
            self.assertEqual(len({id(stream) for stream in streams}), 3)
            for size, call in zip((180, 240, 320), calls):
                self.assertIs(type(call.args[0]), BytesIO)
                self.assertEqual(call.args[0].getvalue(), data)
                self.assertEqual(call.kwargs, dict(size=size, index=0, encoding='unic', layout_engine=core.basic_engine))
            image_font.truetype.assert_not_called()

    def test_invalid_load_options_reject_before_native_load(self):
        with fake_pillow() as (_, image_font):
            core = p._PillowBasicCore()
            kwargs = dict(size=180, index=0, encoding='unic', layout_engine=core.basic_engine)
            for key, values in (('size', (18, 181, 180.0, True)), ('index', (1, True)),
                                ('encoding', ('', 'symb')), ('layout_engine', (None, object()))):
                for value in values:
                    with self.assertRaises(ValueError):
                        core.load_font(b'data', **dict(kwargs, **{key: value}))
            image_font.FreeTypeFont.assert_not_called()

    def test_load_failure_no_retry_and_operational_exception(self):
        with fake_pillow() as (_, image_font):
            core = p._PillowBasicCore()
            for error in (OSError('bad font'), RuntimeError('bad native state'), MemoryError()):
                image_font.FreeTypeFont.reset_mock()
                image_font.FreeTypeFont.side_effect = error
                with self.assertRaises(MemoryError if isinstance(error, MemoryError) else ValueError):
                    core.load_font(b'data', size=180, index=0, encoding='unic', layout_engine=core.basic_engine)
                self.assertEqual(image_font.FreeTypeFont.call_count, 1)
            image_font.truetype.assert_not_called()

    def test_unproved_native_agreement_blocks_seam_before_loads(self):
        with fake_pillow() as (_, image_font):
            core = p._PillowBasicCore()
            # A valid synthetic inspection cannot confer native qualification.
            with self.assertRaisesRegex(ValueError, 'cmap agreement audit'):
                l._load_fonts(core, bytes(sfnt()), profile())
            image_font.FreeTypeFont.assert_not_called()

    def test_raw_fonts_feed_existing_exact_measurement_seam(self):
        # A synthetic provider and synthetic native fonts exercise integration;
        # no new production switch or token authorizes these doubles.
        with fake_pillow() as (_, image_font):
            core = p._PillowBasicCore()
            double = DoubleProvider()
            double.basic_engine = core.basic_engine
            double.advance = 5.125
            double.bounds = (-1.25, -7.5, 4, 1)
            image_font.FreeTypeFont.side_effect = lambda stream, **kw: DoubleFont(double, kw['size'])
            with patch.object(core, 'inspect_font', side_effect=double.inspect_font):
                fonts = l._load_fonts(core, bytes(sfnt()), profile())
            display, specification = fixture(('A  B\n\nC\n',))
            required = l._enumerate_fields(display)
            spans = l._text_preflight(required, l.LayoutLimits())
            first = l._measure(fonts, required, specification, spans)
            first_calls = list(double.calls)
            second = l._measure(fonts, required, specification, spans)
            self.assertEqual(first, second)
            measured = first[0][0]
            self.assertEqual(measured[2:4], (8, 2))
            line = measured[4][0]
            self.assertEqual(line[4], l.Fraction(41, 8))
            self.assertEqual(line[5][0], l.Fraction(-5, 4))
            self.assertEqual(line[-1], (-125, 0, 513, 1000))
            self.assertEqual([c[1] for c in first_calls if c[0] == 'metrics'], [180, 240, 320])
            self.assertEqual([c[2] for c in first_calls if c[0] == 'length'], ['A  B', 'C'])
            for call in first_calls:
                if call[0] in ('length', 'bbox'):
                    expected = dict(mode='L', direction=None, features=None, language=None)
                    if call[0] == 'bbox':
                        expected.update(stroke_width=0, anchor='ls')
                    self.assertEqual(call[3], expected)
            # Negative raw descent is rejected, not normalized with abs().
            double.metrics[180] = (8, -2)
            with self.assertRaises(ValueError):
                l._measure(fonts, required, specification, spans)

    def test_measurement_error_propagation_no_retry(self):
        from test_milestone3_phase3c2b_layout import FONT_BYTES, TEST_DIGEST
        display, spec = fixture()
        for operation in ('length', 'bbox'):
            double = DoubleProvider()
            double.failure = ('Hello', operation)
            with patch.object(l, '_FONT_SHA256', TEST_DIGEST), patch.object(l, '_open_provider', return_value=double):
                with self.assertRaisesRegex(ValueError, 'pass 12: controlled failure'):
                    l.layout_presentation(display, spec, font_bytes=FONT_BYTES, profile=profile())
            self.assertEqual(sum(c[0] == operation for c in double.calls), 1)
            if operation == 'length':
                self.assertFalse(any(c[0] == 'bbox' for c in double.calls))

    def test_default_production_path_stays_closed_before_pillow(self):
        # Identity is a test double; the production provider gate is untouched.
        data = bytes(sfnt())
        digest = sha256(data).hexdigest()
        with patch.object(l, '_FONT_SHA256', digest), patch.object(p, '_pillow_capability', side_effect=AssertionError('imported')):
            with self.assertRaisesRegex(ValueError, 'pass 10: Controlled fresh-process'):
                l.layout_presentation(*fixture(), font_bytes=data, profile=profile(digest))

    def test_import_is_lazy_and_python39_grammar(self):
        for path in (Path(p.__file__), Path(l.__file__)):
            ast.parse(path.read_text(), feature_version=(3, 9))
        # Fresh interpreter avoids sys.modules from other test modules hiding imports.
        source = "import sys; import presentation_agent; import presentation_agent.layout; import presentation_agent._pillow_basic; assert not any(k == 'PIL' or k.startswith('PIL.') for k in sys.modules)"
        result = subprocess.run([sys.executable, '-B', '-c', source], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


class ExternalArialCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = os.environ.get('PRESENTATION_AGENT_ARIAL_FONT')
        if not path:
            raise unittest.SkipTest('Explicit PRESENTATION_AGENT_ARIAL_FONT not supplied; no deployment acceptance')
        with open(path, 'rb') as stream:
            cls.data = stream.read(p._MAX_FONT_BYTES + 1)
        cls.identity = profile(p._FONT_SHA256).font
        cls.inspection = p._inspect_font(cls.data, cls.identity)

    def test_exact_font_inspection_and_raw_metrics_all_sizes(self):
        core = p._PillowBasicCore()
        self.assertEqual(len(self.inspection.ascii_glyphs), 95)
        observations = []
        for size in (180, 240, 320):
            font = core.load_font(self.data, size=size, index=0, encoding='unic', layout_engine=core.basic_engine)
            self.assertIs(font.layout_engine, core.basic_engine)
            self.assertEqual(font.getname(), ('Arial', 'Regular'))
            metrics = font.getmetrics()
            self.assertIs(type(metrics), tuple)
            self.assertTrue(all(type(value) is int for value in metrics))
            self.assertGreater(metrics[0], 0)
            self.assertGreaterEqual(metrics[1], 0)
            kwargs = dict(mode='L', direction=None, features=None, language=None)
            self.assertGreater(font.getlength('A  B', **kwargs), font.getlength('A B', **kwargs))
            lines = ['A' + chr(cp) + 'B' for cp in range(32, 127)]
            first = [(font.getlength(line, **kwargs), font.getbbox(line, **kwargs, stroke_width=0, anchor='ls')) for line in lines]
            second = [(font.getlength(line, **kwargs), font.getbbox(line, **kwargs, stroke_width=0, anchor='ls')) for line in lines]
            self.assertEqual(first, second)
            for advance, bounds in first:
                l._observation(advance)
                l._bounds(tuple(l._observation(value) for value in bounds))
            observations.append(metrics)
        self.assertEqual(len(set(observations)), 3)

    def test_external_font_does_not_qualify_ordinary_interpreter(self):
        with self.assertRaisesRegex(ValueError, 'pass 10: Controlled fresh-process'):
            l.layout_presentation(*fixture(), font_bytes=self.data, profile=profile(p._FONT_SHA256))
