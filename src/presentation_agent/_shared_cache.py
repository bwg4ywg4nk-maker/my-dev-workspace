"""Read-only evidence for the active Monterey dyld v1 split cache.

No extraction, dlopen, qualification, or caller-supplied memory observations.
Format reference: Apple's include/mach-o/dyld_cache_format.h. Only the
456-byte header / 24-byte subcache-entry layout is supported; others reject.
"""
from contextlib import ExitStack
from hashlib import sha256
from pathlib import Path
import ctypes as c
import os
import struct
import sys

from ._provider_manifests import _require
from .evidence import canonical_bytes

_CHUNK = 1024 * 1024
_DIRECTORIES = (Path('/System/Library/dyld'),
                Path('/System/Volumes/Preboot/Cryptexes/OS/System/Library/dyld'))


class _Memory:
    """Read our task through Mach; invalid addresses produce errors, not crashes."""

    def __init__(self):
        _require(sys.platform == 'darwin', 'shared cache requires Darwin')
        self.lib = c.CDLL(None)
        self.task = c.c_uint.in_dll(self.lib, 'mach_task_self_').value
        self.lib._dyld_get_shared_cache_range.argtypes = [c.POINTER(c.c_size_t)]
        self.lib._dyld_get_shared_cache_range.restype = c.c_uint64
        size = c.c_size_t()
        self.base = self.lib._dyld_get_shared_cache_range(c.byref(size))
        self.size = size.value
        _require(self.base and self.size >= 456, 'active shared cache unavailable')
        self.lib.mach_vm_read_overwrite.argtypes = [c.c_uint, c.c_uint64,
            c.c_uint64, c.c_void_p, c.POINTER(c.c_uint64)]
        self.lib.mach_vm_region_recurse.argtypes = [c.c_uint,
            c.POINTER(c.c_uint64), c.POINTER(c.c_uint64), c.POINTER(c.c_uint),
            c.c_void_p, c.POINTER(c.c_uint)]

    def read(self, address, size):
        _require(self.base <= address and 0 < size <= _CHUNK and
                 address + size <= self.base + self.size, 'active cache read bounds')
        buf = c.create_string_buffer(size)
        actual = c.c_uint64()
        result = self.lib.mach_vm_read_overwrite(self.task, address, size, buf,
                                                c.byref(actual))
        _require(result == 0 and actual.value == size, 'active cache read failed')
        return buf.raw

    def protection(self, address):
        # SDK vm_region_submap_info_64 is packed to four-byte alignment.
        depth = c.c_uint(0)
        for _ in range(32):
            start, size = c.c_uint64(address), c.c_uint64()
            info, count = (c.c_uint * 19)(), c.c_uint(19)
            result = self.lib.mach_vm_region_recurse(self.task, c.byref(start),
                c.byref(size), c.byref(depth), info, c.byref(count))
            _require(result == 0 and count.value >= 16 and
                     start.value <= address < start.value + size.value,
                     'active cache mapping unavailable')
            if not info[12]:
                return start.value + size.value, info[0], info[1]
            depth.value += 1
        raise ValueError('active cache mapping depth')


class _File:
    def __init__(self, path, stack):
        _require(path.is_absolute() and path.resolve() == path and path.is_file(),
                 'shared cache regular resolved file unavailable: ' + str(path))
        self.path = path
        self.stream = stack.enter_context(path.open('rb'))
        self.before = os.fstat(self.stream.fileno())
        self.size = self.before.st_size
        self.header = self.read(0, 456)
        _require(struct.unpack_from('<I', self.header, 16)[0] == 456,
                 'unsupported shared cache header')

    def read(self, offset, size):
        _require(0 <= offset <= self.size and 0 <= size <= self.size - offset,
                 'shared cache file bounds')
        self.stream.seek(offset)
        data = self.stream.read(size)
        _require(len(data) == size, 'truncated shared cache')
        return data

    def unchanged(self):
        def stamp(value):
            return (value.st_dev, value.st_ino, value.st_size,
                    value.st_mtime_ns, value.st_ctime_ns)
        _require(stamp(self.before) == stamp(os.fstat(self.stream.fileno())) ==
                 stamp(self.path.stat()), 'shared cache changed during collection')

    def digest(self):
        digest = sha256()
        for offset in range(0, self.size, _CHUNK):
            digest.update(self.read(offset, min(_CHUNK, self.size - offset)))
        return digest.hexdigest()


def _table(file, offset, count, fmt, limit):
    width = struct.calcsize(fmt)
    _require(0 <= count <= limit, 'shared cache table count')
    data = file.read(offset, count * width)
    return list(struct.iter_unpack(fmt, data))


def _mappings(file):
    offset, count = struct.unpack_from('<II', file.header, 16)
    _require(0 < count <= 32, 'shared cache mapping count')
    maps = _table(file, offset, count, '<QQQII', 32)
    for address, size, offset, maximum, initial in maps:
        _require(size > 0 and address + size < 2**64 and
                 offset + size <= file.size and initial & 1 and
                 maximum in (1, 3, 5) and initial & ~maximum == 0,
                 'shared cache mapping bounds/protection')
    for index, first in enumerate(maps):
        for second in maps[index + 1:]:
            for location in (0, 2):
                _require(first[location] + first[1] <= second[location] or
                         second[location] + second[1] <= first[location],
                         'overlapping shared cache mappings')
    _require(maps[0][2] == 0 and maps[0][1] >= 456 and maps[0][3] == 5,
             'shared cache header mapping')
    return maps


def _compare(memory, file, mapping, slide):
    address, size, offset, maximum, initial = mapping
    cursor = 0
    digest = sha256()
    while cursor < size:
        live = address + slide + cursor
        end, protection, max_protection = memory.protection(live)
        if maximum & 2:
            # Private writable/COW regions can have a broader kernel maximum.
            # They are not immutable observations and are never byte-compared.
            _require(protection & 1 and not protection & 4,
                     'active mutable cache protection mismatch')
        else:
            _require(protection == initial and max_protection == maximum,
                     'active cache protection mismatch')
        amount = min(_CHUNK, size - cursor, end - live)
        _require(amount > 0, 'active cache mapping extent')
        # Writable / rebased data is bound by whole-file identity, not claimed
        # to agree with runtime state. Only immutable ranges compare verbatim.
        if not maximum & 2:
            data = file.read(offset + cursor, amount)
            _require(memory.read(live, amount) == data, 'immutable cache byte mismatch')
            digest.update(data)
        cursor += amount
    return digest.hexdigest() if not maximum & 2 else None


def _collect(required, architecture, memory, directories):
    """Private test seam; production obtains its own observation in collect()."""
    from ._deployment_evidence import _dependencies_bytes
    header = memory.read(memory.base, 456)
    magics = {'x86_64': (b'dyld_v1  x86_64\0', b'dyld_v1 x86_64h\0'),
              'arm64': (b'dyld_v1   arm64\0', b'dyld_v1  arm64e\0')}
    _require(header[:16] in magics.get(architecture, ()), 'active cache architecture')
    _require(struct.unpack_from('<I', header, 16)[0] == 456,
             'unsupported active cache header')
    name = 'dyld_shared_cache_' + header[:16].rstrip(b'\0').split()[-1].decode('ascii')
    matches = []
    for directory in directories:
        path = directory / name
        if path.is_file():
            with path.open('rb') as stream:
                candidate = stream.read(456)
            if candidate == header:
                matches.append(path)
    _require(len(matches) == 1, 'active cache file missing or ambiguous')
    with ExitStack() as stack:
        main = _File(matches[0], stack)
        main_maps = _mappings(main)
        origin = main_maps[0][0]
        slide = memory.base - origin
        _require(0 <= slide <= struct.unpack_from('<Q', header, 240)[0],
                 'active cache slide mismatch')
        files = [('main', main, main_maps)]
        offset, count = struct.unpack_from('<II', header, 392)
        entries = _table(main, offset, count, '<16sQ', 64)
        uuids = {header[88:104]}
        for index, (uuid, displacement) in enumerate(entries, 1):
            _require(uuid != bytes(16) and uuid not in uuids and displacement > 0,
                     'shared subcache declaration')
            uuids.add(uuid)
            file = _File(Path(str(main.path) + '.' + str(index)), stack)
            maps = _mappings(file)
            _require(file.header[:16] == header[:16] and file.header[88:104] == uuid
                     and maps[0][0] == origin + displacement,
                     'shared subcache identity/mapping mismatch')
            _require(memory.read(maps[0][0] + slide, 456) == file.header,
                     'active subcache header mismatch')
            files.append(('subcache-' + str(index), file, maps))
        symbol_uuid = header[400:416]
        if symbol_uuid != bytes(16):
            symbols = _File(Path(str(main.path) + '.symbols'), stack)
            _require(symbols.header[:16] == header[:16] and
                     symbols.header[88:104] == symbol_uuid and symbol_uuid not in uuids,
                     'shared symbols identity mismatch')
            files.append(('symbols', symbols, []))
        all_maps = sorted(((mapping[0], file, mapping)
                           for _, file, maps in files for mapping in maps),
                          key=lambda item: item[0])
        for address, _, mapping in all_maps:
            _require(memory.base <= address + slide and
                     address + slide + mapping[1] <= memory.base + memory.size,
                     'shared cache mapping outside active range')
        for first, second in zip(all_maps, all_maps[1:]):
            _require(first[0] + first[2][1] <= second[0], 'overlapping subcache mappings')
        records, mapped = [], []
        for role, file, maps in files:
            records.append([role, file.digest()])
            for mapping in maps:
                digest = _compare(memory, file, mapping, slide)
                mapped.append([role, *mapping, digest])

        def virtual(address, size):
            selected = [(file, m) for _, file, m in all_maps
                        if m[0] <= address and address + size <= m[0] + m[1]]
            _require(len(selected) == 1 and not selected[0][1][3] & 2,
                     'image outside immutable cache mapping')
            file, m = selected[0]
            return file.read(m[2] + address - m[0], size)

        image_offset, image_count = struct.unpack_from('<II', header, 448)
        _require(image_count > 0, 'empty shared cache image table')
        images = {}
        for address, _, _, path_offset, _ in _table(
                main, image_offset, image_count, '<QQQII', 100000):
            raw = main.read(path_offset, min(4096, main.size - path_offset))
            _require(b'\0' in raw, 'unterminated cache image path')
            path = raw.split(b'\0', 1)[0].decode('utf-8', errors='strict')
            _require(path.startswith('/') and path not in images, 'cache image membership')
            images[path] = address
        result, pending = {}, list(required)
        while pending:
            path = pending.pop()
            if path in result:
                continue
            _require(path in images, 'required shared cache image missing: ' + path)
            address = images[path]
            mh = virtual(address, 32)
            magic, cpu, subtype, kind, commands, size, flags, _ = struct.unpack('<8I', mh)
            _require(kind == 6 and flags & 0x80000000 and 0 < size <= _CHUNK - 32,
                     'cached Mach-O identity')
            data = virtual(address, 32 + size)
            dependencies = _dependencies_bytes(data, architecture)
            offset, install_names, image_uuids, segments, text_segments = 32, [], [], [], []
            for _ in range(commands):
                command, length = struct.unpack_from('<II', data, offset)
                if command == 0xD:
                    _require(length >= 24, 'cached install name command')
                    start = struct.unpack_from('<I', data, offset + 8)[0]
                    _require(24 <= start < length, 'cached install name offset')
                    raw = data[offset + start:offset + length]
                    _require(b'\0' in raw, 'cached install name terminator')
                    install_names.append(raw.split(b'\0', 1)[0].decode('utf-8'))
                if command == 0x1B:
                    _require(length == 24, 'cached image UUID command')
                    image_uuids.append(data[offset + 8:offset + 24].hex())
                if command == 0x19:
                    _require(length >= 72, 'cached segment command')
                    vm, vs, fo, fs, mp, ip, ns, sf = struct.unpack_from('<4Q4I', data, offset + 24)
                    _require(length == 72 + ns * 80 and fs <= vs, 'cached segment bounds')
                    segment_name = data[offset + 8:offset + 24].rstrip(b'\0')
                    if segment_name == b'__TEXT':
                        _require(vm == address and fs >= len(data) and mp == ip == 5,
                                 'cached image header segment mismatch')
                        text_segments.append(vm)
                    if vs:
                        matches = [m for _, _, m in all_maps
                                   if m[0] <= vm and vm + vs <= m[0] + m[1]
                                   and ip & ~m[3] == 0
                                   and (not fs or fo == m[2] + vm - m[0])]
                        _require(len(matches) == 1, 'cached segment mapping mismatch')
                    segments.append([vm, vs, fo, fs, mp, ip])
                offset += length
            _require(install_names == [path] and len(image_uuids) == 1 and
                     len(text_segments) == 1,
                     'cached image name/UUID/segments mismatch')
            image = {'path': path, 'address': address, 'cpu_subtype': subtype,
                     'uuid': image_uuids[0], 'load_commands_sha256': sha256(data).hexdigest(),
                     'segments': segments, 'dependencies': dependencies}
            result[path] = image
            pending.extend(dependencies)
        for _, file, _ in files:
            file.unchanged()
        _require(memory.read(memory.base, 456) == header, 'active cache changed')
        evidence = {'kind': 'dyld-shared-cache-evidence-v1', 'files': records,
                    'mappings': mapped, 'images': [result[p] for p in sorted(result)]}
        cache_id = sha256(canonical_bytes(evidence)).hexdigest()
        artifacts = {path: sha256(canonical_bytes([cache_id, image])).hexdigest()
                     for path, image in result.items()}
        return evidence, artifacts, {p: v['dependencies'] for p, v in result.items()}


def collect(required, architecture):
    """Verify the active cache set and the required images' cache dependency closure.

    This observes the collecting process only. Whole files bind mutable data on
    disk; no agreement of rebased/writable live data or future load is claimed.
    """
    try:
        return _collect(required, architecture, _Memory(), _DIRECTORIES)
    except (OSError, AttributeError) as exc:
        raise ValueError('Shared cache observation unavailable: ' + str(exc)) from exc
