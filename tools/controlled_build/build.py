#!/usr/bin/env python3
"""Explicit macOS Phase-1 build; no installer, downloads, or runtime activation.

Uses FreeType's documented INSTALL.ANY compilation route and Pillow's pinned
core source lists. No configure, setuptools, pkg-config, or library discovery.
Run with a CPython >=3.10 whose development headers are already provisioned.
"""
import argparse
import ast
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import sysconfig
import tarfile

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))
from presentation_agent._build_evidence import configuration_id, evidence_id, verify_bytes
from presentation_agent.evidence import canonical_bytes


def digest(path):
    result = sha256()
    with Path(path).open('rb') as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(data)
    return result.hexdigest()


def tree_digest(root):
    """Content inventory with relative names; never timestamps or machine paths."""
    root = Path(root).resolve()
    records = []
    for directory, dirs, files in os.walk(root):
        for name in sorted(dirs + files):
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                if root not in path.resolve().parents and path.resolve() != root:
                    raise ValueError('External identity-tree symlink: ' + relative)
                records.append([relative, 'symlink', os.readlink(path)])
            elif path.is_file():
                records.append([relative, 'file', digest(path)])
    # SDKs may exceed the application's presentation-record ceiling. This is
    # a separate build inventory with a simple fixed three-string row grammar.
    raw = json.dumps(sorted(records), ensure_ascii=True, separators=(',', ':')).encode('ascii')
    return sha256(raw).hexdigest()


def extract(archive, destination, root):
    """Only pinned ordinary files/directories; no archive links or traversal."""
    destination.mkdir()
    with tarfile.open(archive, 'r:gz') as source:
        members = source.getmembers()
        seen = set()
        for entry in members:
            parts = Path(entry.name).parts
            if (not parts or parts[0] != root or '..' in parts or
                    entry.name in seen or not (entry.isfile() or entry.isdir())):
                raise ValueError('Unsupported source archive member')
            seen.add(entry.name)
        for entry in members:
            path = destination / entry.name
            if entry.isdir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(entry) as incoming, path.open('xb') as outgoing:
                    shutil.copyfileobj(incoming, outgoing)
    return destination / root


def prepare_freetype(source, destination, profile):
    shutil.copytree(source / 'include', destination)
    config = destination / 'freetype/config'
    option = config / 'ftoption.h'
    text = option.read_text()
    for name in profile['freetype_undefines']:
        if name not in text:
            raise ValueError('Unknown FreeType option: ' + name)
        text = re.sub(r'^#define\s+' + re.escape(name) + r'\b[^\n]*$',
                      '/* controlled build: ' + name + ' disabled */', text, flags=re.M)
    option.write_text(text)
    (config / 'ftmodule.h').write_text(''.join(
        'FT_USE_MODULE( ' + kind + ', ' + name + ' )\n'
        for kind, name in profile['freetype_modules']))
    # FreeType marks public APIs default-visible even with -fvisibility=hidden.
    public = config / 'public-macros.h'
    text = public.read_text()
    old = '__attribute__(( visibility( "default" ) ))'
    if text.count(old) != 1:
        raise ValueError('FreeType visibility patch context changed')
    public.write_text(text.replace(old, '__attribute__(( visibility( "hidden" ) ))'))


def pillow_sources(source):
    # Parse literals only; never execute upstream setup.py or its discovery.
    values = {}
    for node in ast.parse((source / 'setup.py').read_text()).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id in ('_IMAGING', '_LIB_IMAGING'):
                values[target.id] = ast.literal_eval(node.value)
    if set(values) != {'_IMAGING', '_LIB_IMAGING'}:
        raise ValueError('Missing pinned Pillow source lists')
    return (['src/_imaging.c', 'src/libImaging/Mode.c'] +
            ['src/' + name + '.c' for name in values['_IMAGING']] +
            ['src/libImaging/' + name + '.c' for name in values['_LIB_IMAGING']])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', type=Path, required=True,
                        help='Directory containing freetype.tar.gz and pillow.tar.gz')
    parser.add_argument('--output', type=Path, required=True,
                        help='New directory beneath this repository build/')
    parser.add_argument('--sdk', type=Path, required=True, help='Existing macOS SDK root')
    parser.add_argument('--architecture', choices=('arm64', 'x86_64'), required=True)
    parser.add_argument('--deployment-target', default='13.0')
    args = parser.parse_args()
    if sys.platform != 'darwin' or sys.implementation.name != 'cpython' or sys.version_info < (3, 10):
        parser.error('Build requires macOS CPython >=3.10')
    if sysconfig.get_config_var('Py_GIL_DISABLED'):
        parser.error('Phase-1 build supports GIL-enabled CPython only')
    if not re.fullmatch(r'[0-9]{1,2}\.[0-9]{1,2}', args.deployment_target):
        parser.error('Expected numeric major.minor deployment target')
    work = args.output.resolve()
    if ROOT / 'build' not in work.parents or work.exists():
        parser.error('Output must be a new directory under repository build/')
    sdk = args.sdk.resolve(strict=True)
    if not (sdk / 'SDKSettings.json').is_file():
        parser.error('SDKSettings.json missing')
    profile = json.loads((SUPPORT / 'profile.json').read_text())
    sources = {name: args.sources.resolve() / (name + '.tar.gz') for name in ('freetype', 'pillow')}
    source_records = [[name, profile['sources'][name]['sha256']] for name in sorted(sources)]
    verify_bytes(source_records, sources)  # Before extraction or any compilation.
    work.mkdir(parents=True)
    (work / 'tmp').mkdir()
    env = {'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'ZERO_AR_DATE': '1',
           'TMPDIR': str(work / 'tmp')}
    command_log = work / 'commands.jsonl'

    def run(argv, cwd=work):
        argv = [str(arg) for arg in argv]
        with command_log.open('a') as log:
            log.write(json.dumps(argv) + '\n')
        result = subprocess.run(argv, cwd=cwd, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, check=False)
        with (work / 'build.log').open('ab') as log:
            log.write(result.stdout)
        if result.returncode:
            raise RuntimeError('Build command failed; see ' + str(work / 'build.log'))
        return result.stdout

    cc = Path(run(['/usr/bin/xcrun', '--find', 'clang']).decode().strip()).resolve()
    ar = Path(run(['/usr/bin/xcrun', '--find', 'ar']).decode().strip()).resolve()
    ld = Path(run(['/usr/bin/xcrun', '--find', 'ld']).decode().strip()).resolve()
    nm = Path(run(['/usr/bin/xcrun', '--find', 'nm']).decode().strip()).resolve()
    otool = Path(run(['/usr/bin/xcrun', '--find', 'otool']).decode().strip()).resolve()
    ft = extract(sources['freetype'], work / 'ft-source', profile['sources']['freetype']['root'])
    pillow = extract(sources['pillow'], work / 'pillow-source', profile['sources']['pillow']['root'])
    include = work / 'ft-include'
    prepare_freetype(ft, include, profile)
    run(['/usr/bin/patch', '--batch', '--fuzz=0', '-p1', '-i',
         SUPPORT / 'pillow-12.3.0-cmap.patch'], cwd=pillow)
    shutil.copyfile(SUPPORT / 'pa_cmap_audit.h', pillow / 'src/pa_cmap_audit.h')
    cflags = ['-O2', '-fPIC', '-fvisibility=hidden', '-fno-common',
              '-arch', args.architecture, '-isysroot', str(sdk),
              '-mmacosx-version-min=' + args.deployment_target,
              '-ffile-prefix-map=' + str(work) + '=BUILD']
    py_include = Path(sysconfig.get_path('include')).resolve()
    py_platform_include = Path(sysconfig.get_path('platinclude')).resolve()
    ft_flags = ['-DFT2_BUILD_LIBRARY', '-I' + str(include)]
    py_flags = ['-I' + str(py_include), '-I' + str(py_platform_include),
                '-I' + str(pillow / 'src/libImaging'), '-I' + str(include)]
    obj = work / 'objects'
    obj.mkdir()

    def compile_sources(root, names, flags, prefix):
        objects = []
        for index, name in enumerate(names):
            output = obj / (prefix + str(index) + '.o')
            run([cc, *cflags, *flags, '-c', root / name, '-o', output])
            objects.append(output)
        return objects

    ft_objects = compile_sources(ft / 'src', profile['freetype_sources'], ft_flags, 'ft')
    static = work / 'libfreetype.a'
    run([ar, 'rcs', static, *ft_objects])
    # Actual preprocessor state, not just intended disables, is evidence.
    macro_dump = run([cc, *cflags, *ft_flags, '-dM', '-E', '-x', 'c',
                      include / 'freetype/config/ftoption.h'])
    defined = {line.split()[1] for line in macro_dump.decode().splitlines()
               if line.startswith('#define ')}
    if defined.intersection(profile['freetype_undefines']):
        raise ValueError('Disabled FreeType option remains active')
    if not {'TT_CONFIG_CMAP_FORMAT_4', 'TT_CONFIG_CMAP_FORMAT_12',
            'TT_CONFIG_OPTION_BYTECODE_INTERPRETER', 'TT_CONFIG_OPTION_SFNT_NAMES'} <= defined:
        raise ValueError('Required FreeType option missing')
    (work / 'ft-macros.txt').write_bytes(b'\n'.join(sorted(macro_dump.splitlines())) + b'\n')
    names = pillow_sources(pillow)
    pillow_config = {
        'core_sources': names, 'ft_sources': ['src/_imagingft.c', 'src/libImaging/Mode.c'],
        'defines': ['PILLOW_VERSION="12.3.0"'],
        'optional_native_dependencies': [], 'freetype_binding': 'explicit-static-private',
        'disabled': profile['pillow_disabled'], 'extensions': ['_imaging', '_imagingft'],
    }
    (work / 'pillow-configuration.json').write_bytes(canonical_bytes(pillow_config))
    for role, name, extra in (('imaging', 'src/_imaging.c', ['-DPILLOW_VERSION="12.3.0"']),
                              ('imagingft', 'src/_imagingft.c', [])):
        macros = run([cc, *cflags, *py_flags, *extra, '-dM', '-E', pillow / name])
        active = {line.split()[1] for line in macros.decode().splitlines()
                  if line.startswith('#define ')}
        if active.intersection({'HAVE_RAQM', 'HAVE_RAQM_SYSTEM', 'HAVE_FRIBIDI_SYSTEM',
                                'HAVE_LIBZ', 'HAVE_LIBJPEG', 'HAVE_LIBTIFF', 'HAVE_OPENJPEG',
                                'HAVE_LIBIMAGEQUANT', 'HAVE_XCB'}):
            raise ValueError('Optional Pillow native dependency remains enabled')
        (work / (role + '-macros.txt')).write_bytes(b'\n'.join(sorted(macros.splitlines())) + b'\n')
    imaging_objects = compile_sources(pillow, names, py_flags + ['-DPILLOW_VERSION="12.3.0"'], 'im')
    ft_extension_objects = compile_sources(pillow, pillow_config['ft_sources'], py_flags, 'imft')
    package = work / 'python/PIL'
    shutil.copytree(pillow / 'src/PIL', package)
    suffix = sysconfig.get_config_var('EXT_SUFFIX')
    linkflags = ['-bundle', '-undefined', 'dynamic_lookup', '-Wl,-no_uuid']
    artifacts = {'freetype-static': static}
    for name, objects in (('imaging', imaging_objects), ('imagingft', ft_extension_objects + [static])):
        extension = package / ('_' + name + suffix)
        run([cc, *cflags, *linkflags, '-Wl,-exported_symbol,_PyInit__' + name,
             *objects, '-o', extension])
        artifacts[name] = extension
        # Drop otool's first line (the local pathname); retain actual commands.
        dependencies = run([otool, '-L', extension]).splitlines()[1:]
        for line in dependencies:
            if line.strip().split(b' ', 1)[0] != b'/usr/lib/libSystem.B.dylib':
                raise ValueError('Unexpected native dependency: ' + line.decode())
        metadata = work / (name + '-link.txt')
        load_commands = run([otool, '-l', extension]).splitlines()[1:]
        metadata.write_bytes(b'\n'.join(dependencies + load_commands) + b'\n')
        artifacts[name + '-link'] = metadata
        exports = run([nm, '-gUj', extension]).splitlines()
        if exports != [('_PyInit__' + name).encode()]:
            raise ValueError('Unexpected exported native symbol')
        if name == 'imagingft':
            unresolved = run([nm, '-uj', extension]).splitlines()
            if any(symbol.startswith((b'_FT_', b'_TT_', b'_FTC_')) for symbol in unresolved):
                raise ValueError('FreeType symbol escaped static containment')
            symbols = work / 'imagingft-symbols.txt'
            symbols.write_bytes(b'exports\n' + b'\n'.join(exports) + b'\nundefined\n' +
                                b'\n'.join(sorted(unresolved)) + b'\n')
            artifacts['imagingft-symbols'] = symbols

    # Build smoke check only. This is not the deferred trusted runtime bootstrap.
    # It catches unresolved internal Pillow helpers even when the linker permits
    # Python's dynamically resolved symbols. No fonts are opened.
    run([sys.executable, '-I', '-S', '-c',
         'import sys; sys.path.insert(0, sys.argv[1]); '
         'import PIL; from PIL import Image, ImageFont; '
         'assert PIL.__version__ == "12.3.0"; '
         'assert ImageFont.core.freetype2_version == "2.14.3"; '
         'assert not ImageFont.core.HAVE_RAQM; '
         'assert Image.new("L", (1, 1)).size == (1, 1)', str(work / 'python')])

    generated = {path.name: path for path in (include / 'freetype/config').iterdir() if path.is_file()}
    generated.update({'ft-macros': work / 'ft-macros.txt',
                      'imaging-macros': work / 'imaging-macros.txt',
                      'imagingft-macros': work / 'imagingft-macros.txt',
                      'pillow-configuration': work / 'pillow-configuration.json',
                      'patched-imagingft-source': pillow / 'src/_imagingft.c'})
    tools = {name: digest(path) for name, path in
             (('compiler', cc), ('archiver', ar), ('linker', ld), ('nm', nm), ('otool', otool),
              ('python', Path(sys.executable).resolve()), ('patch', Path('/usr/bin/patch')))}
    tools.update({'compiler-version': sha256(run([cc, '--version'])).hexdigest(),
                  'compiler-resources': tree_digest(run([cc, '-print-resource-dir']).decode().strip()),
                  'python-headers': tree_digest(py_include),
                  'python-platform-headers': tree_digest(py_platform_include)})
    # All path-bearing invocation details are represented by symbolic roles.
    configuration = {
        'kind': 'pillow-basic-phase1-configuration-v1',
        'versions': {'pillow': '12.3.0', 'freetype': '2.14.3'},
        'sources': source_records,
        'patches': [[path.name, digest(path)] for path in sorted(SUPPORT.iterdir())
                    if path.suffix in ('.py', '.json', '.patch', '.h')],
        'tools': sorted([name, value] for name, value in tools.items()),
        'target': {'architecture': args.architecture, 'deployment_target': args.deployment_target,
                   'sdk_sha256': tree_digest(sdk)},
        'flags': {
            'compile': [item.replace(str(sdk), 'SDK').replace(str(work), 'BUILD') for item in cflags] +
                       ['FT: -DFT2_BUILD_LIBRARY -IFT_INCLUDE',
                        'PIL: -IPY_INCLUDE -IPY_PLATFORM_INCLUDE -IPIL_LIBIMAGING -IFT_INCLUDE',
                        '_imaging: -DPILLOW_VERSION="12.3.0"'],
            'link': linkflags + ['-Wl,-exported_symbol,_PyInit__EXTENSION',
                                '_imagingft: OBJECTS FREETYPE_STATIC', '_imaging: OBJECTS'],
            'configure': ['INSTALL.ANY explicit sources; no configure/autodetection',
                          'archive: ar rcs; ZERO_AR_DATE=1', 'environment: PATH=/usr/bin:/bin; LC_ALL=C'],
        },
        'modules': sorted(row[1] for row in profile['freetype_modules']),
        'disabled': sorted(profile['freetype_undefines'] + ['Pillow:' + s for s in profile['pillow_disabled']]),
        'generated': sorted([name, digest(path)] for name, path in generated.items()),
    }
    # Include all copied Python implementation files, not just ImageFont.py.
    for path in sorted(package.glob('*.py')):
        artifacts['PIL.' + path.name] = path
    artifacts['measurement-adapter'] = ROOT / 'src/presentation_agent/_pillow_basic.py'
    artifacts['audit-schema'] = ROOT / 'src/presentation_agent/_build_evidence.py'
    evidence = {'kind': 'pillow-basic-phase1-evidence-v1', 'configuration': configuration,
                'configuration_sha256': configuration_id(configuration),
                'artifacts': sorted([name, digest(path)] for name, path in artifacts.items())}
    identity = evidence_id(evidence)
    verify_bytes(evidence['artifacts'], artifacts)
    (work / 'configuration.json').write_bytes(canonical_bytes(configuration))
    (work / 'evidence.json').write_bytes(canonical_bytes(evidence))
    (work / 'evidence.sha256').write_text(identity + '\n')
    print('Phase-1 build evidence: ' + identity)
    print('Byte evidence only; no runtime or production qualification.')


if __name__ == '__main__':
    main()
