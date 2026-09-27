"""Offline deployment byte evidence; never trusted launch or qualification.

Absolute locations are inputs only. Identities use logical roles and relative
module names. Supports thin little-endian 64-bit Mach-O and x86_64 slices of
universal Mach-O, with absolute dependency names only. Missing system images
may bind to the active dyld shared cache through separately verified whole-cache
evidence.
"""
from hashlib import sha256
from importlib.machinery import (ExtensionFileLoader, FileFinder, SourceFileLoader,
                                 SourcelessFileLoader)
from pathlib import Path
import struct

from ._build_evidence import evidence_id, verify_bytes
from ._provider_manifests import _require, _runtime_manifest_id, _string
from .evidence import canonical_bytes

_REQUIRED = {'python-interpreter', 'python-framework', 'launcher', 'bootstrap',
             'loader', 'c-runtime', 'imaging', 'imagingft'}
_ROOTS = _REQUIRED - {'loader', 'c-runtime'}

# Source inventory for the CPython 3.14 / Pillow 12.3 provider path. Built-in
# and frozen bootstrap modules live in the already-bound Python framework;
# _pa_private_bootstrap lives in the launcher, not a Python source file.
_PILLOW_MODULES = (
    '__init__', '_version', 'ImageFont', 'Image', 'ExifTags', 'ImageMode',
    'TiffTags', '_binary', '_deprecate', '_typing', '_util',
)
_PROVIDER_MODULES = (
    '__init__', '_pillow_basic', '_build_evidence', '_provider_manifests',
    'layout', 'display', 'composition', 'planning', 'content', 'content_binding',
    'evidence', 'evidence_verification', 'quantities', 'source_capture',
    'source_extraction',
)
_STDLIB_MODULES = (
    '__future__', '_colorize', '_opcode_metadata', '_weakrefset', 'annotationlib',
    'ast', 'base64', 'bisect', 'codeop', 'collections/__init__', 'collections/abc',
    'contextlib', 'copy', 'copyreg', 'dataclasses', 'decimal', 'dis',
    'encodings/__init__', 'encodings/aliases', 'encodings/ascii',
    'encodings/utf_8', 'encodings/utf_16_be', 'encodings/mac_roman',
    'enum', 'fnmatch', 'fractions', 'functools', 'glob', 'hashlib',
    'importlib/__init__', 'inspect', 'json/__init__', 'json/decoder',
    'json/encoder', 'json/scanner', 'keyword', 'linecache', 'logging/__init__',
    'numbers', 'opcode', 'operator', 'pathlib/__init__', 'pathlib/_os',
    'random', 're/__init__', 're/_compiler', 're/_constants', 're/_parser',
    're/_casefix', 'reprlib', 'shutil', 'string/__init__', 'struct', 'tempfile',
    'textwrap', 'threading', 'token', 'tokenize', 'traceback', 'types', 'typing',
    'uuid', 'warnings', 'weakref',
)
_REQUIRED_MODULES = frozenset(
    ['PIL/' + name + '.py' for name in _PILLOW_MODULES] +
    ['presentation_agent/' + name + '.py' for name in _PROVIDER_MODULES] +
    [name + '.py' for name in _STDLIB_MODULES])
_BUILD_MODULES = {
    **{'PIL.' + name + '.py': 'PIL/' + name + '.py' for name in _PILLOW_MODULES},
    'measurement-adapter': 'presentation_agent/_pillow_basic.py',
    'audit-schema': 'presentation_agent/_build_evidence.py',
}


def _resolve_source(relative, expected, roots, finders):
    """Resolve without executing code or consulting host import hooks/caches.

    Use the supported target's suffixes, not the collecting interpreter's.
    FileFinder preserves package-before-module and loader suffix precedence.
    Namespace portions yield to a later regular package/module, as in PathFinder.
    """
    parts = list(Path(relative).with_suffix('').parts)
    is_package = parts[-1] == '__init__'
    if is_package:
        parts.pop()
    source_root = expected.parents[len(Path(relative).parts) - 1]
    search = roots
    for index in range(len(parts)):
        fullname = '.'.join(parts[:index + 1])
        selected = None
        for directory in search:
            if directory not in finders:
                finders[directory] = FileFinder(
                    str(directory),
                    (ExtensionFileLoader, ['.cpython-314-darwin.so', '.abi3.so', '.so']),
                    (SourceFileLoader, ['.py']), (SourcelessFileLoader, ['.pyc']))
            candidate = finders[directory].find_spec(fullname)
            if candidate is not None and candidate.loader is not None:
                selected = candidate
                break
        package = index < len(parts) - 1 or is_package
        location = source_root.joinpath(*parts[:index + 1])
        location = location / '__init__.py' if package else location.with_suffix('.py')
        _require(selected is not None
                 and isinstance(selected.loader, SourceFileLoader)
                 and selected.origin == str(location)
                 and (selected.submodule_search_locations is not None) == package,
                 'runtime module resolution mismatch: ' + relative)
        # A SourceFileLoader spec still permits cached code to replace source.
        # Reject caches rather than trusting their timestamp/hash headers. Cover
        # all tags and optimization levels, independent of the collector's ABI.
        _require(not location.with_suffix('.pyc').exists()
                 and not any((location.parent / '__pycache__').glob(
                     location.stem + '.*.pyc')),
                 'unverified runtime bytecode cache: ' + relative)
        search = [location.parent] if package else []


def _module_inventory(roots, trees, build_files):
    # A package cannot be assembled from different sys.path roots: its first
    # regular package fixes __path__. Require a single source root per package.
    inventory = {}
    for root, tree in zip(roots, trees):
        for relative, _ in tree:
            inventory.setdefault(relative, []).append(root / relative)
    packages = {}
    for relative in sorted(_REQUIRED_MODULES):
        paths = inventory.get(relative, [])
        _require(len(paths) == 1, 'missing or duplicate runtime module: ' + relative)
        if '/' in relative:
            package = relative.split('/')[0]
            root = paths[0].parents[len(Path(relative).parts) - 2]
            _require(packages.setdefault(package, root) == root,
                     'split runtime package: ' + package)
    _require(_BUILD_MODULES.keys() <= build_files.keys(), 'missing implementation evidence')
    bindings = dict(_BUILD_MODULES)
    bindings.update({name: 'PIL/' + name[4:] for name in build_files
                     if name.startswith('PIL.')})
    for name, relative in bindings.items():
        _require(inventory.get(relative) == [_file(build_files[name])],
                 'runtime implementation binding: ' + name)
    finders = {}
    for relative in sorted(_REQUIRED_MODULES | set(bindings.values())):
        _resolve_source(relative, inventory[relative][0], roots, finders)


def _file(location):
    path = Path(location)
    _require(path.is_absolute() and path.resolve() == path and path.is_file(),
             'absolute regular artifact without symlinks')
    return path


def _hash(path):
    digest = sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


_FAT_FORMATS = {
    b'\xca\xfe\xba\xbe': ('>', False),
    b'\xbe\xba\xfe\xca': ('<', False),
    b'\xca\xfe\xba\xbf': ('>', True),
    b'\xbf\xba\xfe\xca': ('<', True),
}


def _native_slice(data, architecture):
    """Validate the complete fat table before selecting exactly one x86_64 slice."""
    if data[:4] not in _FAT_FORMATS:
        return data, None
    endian, wide = _FAT_FORMATS[data[:4]]
    _require(len(data) >= 8, 'fat header')
    count = struct.unpack_from(endian + 'I', data, 4)[0]
    entry_size = 32 if wide else 20
    _require(0 < count <= (len(data) - 8) // entry_size, 'fat table bounds')
    table_end = 8 + count * entry_size
    ranges, selected = [], []
    for index in range(count):
        entry = struct.unpack_from(endian + ('IIQQII' if wide else 'IIIII'),
                                   data, 8 + index * entry_size)
        cpu, subtype, offset, size, alignment = entry[:5]
        _require(not wide or entry[5] == 0, 'fat reserved field')
        _require(alignment < (64 if wide else 32)
                 and offset % (1 << alignment) == 0, 'fat slice alignment')
        _require(size > 0 and table_end <= offset <= len(data)
                 and size <= len(data) - offset, 'fat slice bounds')
        ranges.append((offset, offset + size))
        if cpu == 0x1000007:
            selected.append((subtype, offset, size))
    ranges.sort()
    _require(all(left[1] <= right[0] for left, right in zip(ranges, ranges[1:])),
             'overlapping fat slices')
    _require(architecture == 'x86_64', 'unsupported fat architecture')
    _require(len(selected) == 1, 'missing or duplicate x86_64 slice')
    subtype, offset, size = selected[0]
    payload = data[offset:offset + size]
    _require(len(payload) >= 32, 'fat slice Mach-O header')
    magic, cpu, actual_subtype = struct.unpack_from('<III', payload)
    _require(magic == 0xFEEDFACF and cpu == 0x1000007 and actual_subtype == subtype,
             'fat slice architecture mismatch')
    return payload, {'architecture': architecture, 'cpu_subtype': subtype,
                     'offset': offset, 'size': size,
                     'sha256': sha256(payload).hexdigest()}


def _dependencies(path, architecture):
    """Read load commands, not external tool output or caller dependency claims."""
    payload, _ = _native_slice(path.read_bytes(), architecture)
    return _dependencies_bytes(payload, architecture)


def _dependencies_bytes(data, architecture):
    _require(len(data) >= 32, 'Mach-O header')
    magic, cpu, _, _, count, size, _, _ = struct.unpack_from('<8I', data)
    _require(magic == 0xFEEDFACF and cpu == {'x86_64': 0x1000007,
                                          'arm64': 0x100000C}.get(architecture),
             'thin native architecture')
    end = 32 + size
    _require(end <= len(data) and count <= size // 8, 'load command bounds')
    offset, dependencies = 32, []
    for _ in range(count):
        _require(offset + 8 <= end, 'load command header')
        command, length = struct.unpack_from('<II', data, offset)
        _require(length >= 8 and length % 8 == 0 and offset + length <= end,
                 'load command size')
        # Ordinary, weak, reexport, upward, lazy libraries; dylinker as well.
        if command in (0xC, 0x80000018, 0x8000001F, 0x80000023, 0x20, 0xE):
            minimum = 12 if command == 0xE else 24
            _require(length >= minimum, 'dependency command')
            start = struct.unpack_from('<I', data, offset + 8)[0]
            _require(minimum <= start < length, 'dependency name offset')
            raw = data[offset + start:offset + length]
            _require(b'\0' in raw, 'dependency terminator')
            name = raw.split(b'\0', 1)[0].decode('utf-8', errors='strict')
            _require(name.startswith('/') and name not in dependencies,
                     'absolute unique dependency')
            dependencies.append(name)
        # Reject search-path and environment loader configuration, even unused.
        _require(command not in (0x8000001C, 0x27), 'unsupported loader configuration')
        offset += length
    _require(offset == end, 'load command extent')
    return dependencies


def _tree(location):
    root = Path(location)
    _require(root.is_absolute() and root.resolve() == root and root.is_dir(),
             'absolute module directory without symlinks')
    records = []
    for path in sorted(root.rglob('*')):
        _require(not path.is_symlink(), 'module symlink')
        if path.is_dir():
            continue
        _require(path.is_file(), 'module regular file')
        records.append([path.relative_to(root).as_posix(), _hash(path)])
    _require(bool(records), 'empty module path')
    return records


def collect(build, build_files, native_files, module_paths, runtime):
    """Collect deterministic evidence from an explicitly selected deployment.

    runtime supplies the frozen manifest's platform fields (a declaration, not
    observation of a loaded interpreter). native_files maps logical names to
    exact absolute files; module_paths is an ordered list of absolute directories.
    No discovery, imports, execution, downloads, or provider activation occurs.
    """
    build_identity = evidence_id(build)
    verify_bytes(build['artifacts'], build_files)
    _require(type(native_files) is dict and _REQUIRED <= native_files.keys(),
             'required native roles')
    for name in native_files:
        _string(name, 'native role')
        _require('/' not in name and '\\' not in name and name != 'deployment-evidence',
                 'native role')
    _require(type(runtime) is dict and 'native_runtime_artifacts' not in runtime,
             'runtime platform declaration')
    missing = {name: Path(value) for name, value in native_files.items()
               if not Path(value).exists()}
    _require(not (missing.keys() & (_ROOTS | {'bootstrap', 'loader'})),
             'required standalone native artifact missing')
    for path in missing.values():
        _require(path.is_absolute() and str(path).startswith(('/usr/lib/', '/System/Library/')),
                 'missing non-system native artifact')
    cache_evidence, cache_artifacts, cache_dependencies = None, {}, {}
    if missing:
        from ._shared_cache import collect as collect_cache
        cache_evidence, cache_artifacts, cache_dependencies = collect_cache(
            [str(path) for path in missing.values()], runtime.get('architecture'))
    files = {name: missing[name] if name in missing else _file(value)
             for name, value in native_files.items()}
    for path in sorted(cache_artifacts):
        if Path(path) not in files.values():
            role = 'shared-cache-image-' + sha256(path.encode('utf-8')).hexdigest()
            _require(role not in files, 'shared cache role collision')
            files[role] = Path(path)
    # Bootstrap is compiled into launcher; that sole alias is intentional.
    _require(files['bootstrap'] == files['launcher'], 'embedded bootstrap binding')
    inverse = {}
    for name, path in files.items():
        if name == 'bootstrap':
            continue
        _require(str(path) not in inverse, 'duplicate native artifact')
        inverse[str(path)] = name
    for name in ('imaging', 'imagingft'):
        _require(files[name] == _file(build_files[name]), 'controlled Pillow binding')
    _require('freetype-static' in build_files, 'static FreeType evidence')
    # Validate metadata before walking dependency closure.
    _runtime_manifest_id(dict(runtime, native_runtime_artifacts=[['check', '0' * 64]]))
    _require(runtime['os'] == 'Darwin' and runtime['byteorder'] == 'little'
             and runtime['pointer_bits'] == 64, 'runtime platform mismatch')
    _require(runtime['architecture'] == build['configuration']['target']['architecture'],
             'runtime/build architecture mismatch')
    _require(runtime['python_implementation'] == 'CPython'
             and runtime['python_version'][:2] == [3, 14], 'bootstrap Python mismatch')
    _require(type(module_paths) is list and bool(module_paths), 'module search paths')
    roots = [Path(path) for path in module_paths]
    _require(len(set(roots)) == len(roots), 'duplicate module path')
    for first in roots:
        _require(not any(first != second and first in second.parents for second in roots),
                 'overlapping module paths')
    trees = [_tree(path) for path in roots]
    _module_inventory(roots, trees, build_files)
    graph, native_hashes, slices = {}, {}, {}
    module_natives = {name for name, path in files.items()
                      if any(path.is_relative_to(root) for root in roots)}
    pending = list(sorted((_ROOTS | module_natives) - {'bootstrap'}))
    while pending:
        name = pending.pop()
        if name in graph:
            continue
        if str(files[name]) in cache_dependencies:
            dependencies = cache_dependencies[str(files[name])]
        else:
            data = files[name].read_bytes()
            payload, selected = _native_slice(data, runtime['architecture'])
            dependencies = _dependencies_bytes(payload, runtime['architecture'])
            native_hashes[name] = sha256(data).hexdigest()
            if selected is not None:
                slices[name] = selected
        _require(all(path in inverse for path in dependencies), 'missing native dependency')
        roles = sorted(inverse[path] for path in dependencies)
        graph[name] = roles
        pending.extend(roles)
    _require(set(graph) == set(files) - {'bootstrap'}, 'unexpected native artifact')
    # Controlled extensions may depend on libSystem only; FreeType is static.
    for name in ('imaging', 'imagingft'):
        _require(graph[name] == ['c-runtime'], 'controlled static linkage')
    # Every importable native image must participate in the checked closure.
    # Do not silently hash an extension while omitting its native dependencies.
    native_paths = set(files.values())
    for root, tree in zip(roots, trees):
        for relative, _ in tree:
            path = root / relative
            with path.open('rb') as stream:
                magic = stream.read(4)
            if path.suffix in ('.so', '.dylib') or magic in (
                    b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf',
                    *_FAT_FORMATS):
                _require(path in native_paths, 'unbound native module')
    for name in ('imaging', 'imagingft'):
        _require(any(files[name].is_relative_to(root) for root in roots),
                 'Pillow outside verified search paths')
    native_hashes['bootstrap'] = native_hashes['launcher']
    if 'launcher' in slices:
        slices['bootstrap'] = slices['launcher']
    records = sorted([name, cache_artifacts[str(path)] if str(path) in cache_artifacts
                      else native_hashes[name]] for name, path in files.items())
    deployment = {'kind': 'pillow-basic-deployment-evidence-v1',
                  'build_evidence_sha256': build_identity,
                  'native_artifacts': records,
                  'native_dependencies': sorted([name, roles] for name, roles in graph.items()),
                  'module_search_paths': trees,
                  'bootstrap_container': 'launcher'}
    if cache_evidence is not None:
        deployment['shared_cache'] = cache_evidence
    if slices:
        deployment['native_slices'] = sorted([name, record] for name, record in slices.items())
    identity = sha256(canonical_bytes(deployment)).hexdigest()
    manifest = dict(runtime, native_runtime_artifacts=sorted(
        records + [['deployment-evidence', identity]]))
    return {'deployment': deployment, 'runtime_manifest': manifest,
            'runtime_id': _runtime_manifest_id(manifest)}


def verify(expected, build, build_files, native_files, module_paths, runtime):
    """Recollect and compare every byte binding; no lifecycle qualification.

    Expected evidence must come from the deployment owner. This is an offline
    check, not protection against replacement between verification and loading.
    """
    actual = collect(build, build_files, native_files, module_paths, runtime)
    _require(canonical_bytes(expected) == canonical_bytes(actual),
             'deployment evidence mismatch')
    return actual['runtime_id']
