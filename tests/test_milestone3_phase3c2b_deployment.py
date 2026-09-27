"""Offline deployment evidence tests; synthetic Mach-O, no qualification."""
from hashlib import sha256
from importlib.machinery import SourceFileLoader
from importlib.util import cache_from_source
from pathlib import Path
import py_compile
import struct
import tempfile
import unittest

from presentation_agent import _deployment_evidence as d
from presentation_agent._build_evidence import configuration_id
from test_milestone3_phase3c2b_build import evidence


def macho(dependencies=()):
    commands = []
    for dependency in dependencies:
        raw = dependency.encode() + b'\0'
        size = (24 + len(raw) + 7) // 8 * 8
        commands.append(struct.pack('<6I', 0xC, size, 24, 0, 0, 0) + raw +
                        bytes(size - 24 - len(raw)))
    body = b''.join(commands)
    return struct.pack('<8I', 0xFEEDFACF, 0x1000007, 0, 2, len(commands),
                       len(body), 0, 0) + body


def fat(payload, endian='>', wide=False):
    """Two slices, with x86_64 second so selection cannot use the first image."""
    magic = 0xCAFEBABF if wide else 0xCAFEBABE
    fmt = endian + ('IIQQII' if wide else 'IIIII')
    entries = []
    for cpu, offset, size in ((0x100000C, 128, 32), (0x1000007, 256, len(payload))):
        fields = [cpu, 0, offset, size, 0] + ([0] if wide else [])
        entries.append(struct.pack(fmt, *fields))
    result = bytearray(256 + len(payload))
    table = struct.pack(endian + 'II', magic, 2) + b''.join(entries)
    result[:len(table)] = table
    arm = bytearray(macho())
    struct.pack_into('<I', arm, 4, 0x100000C)
    result[128:160] = arm
    result[256:] = payload
    return bytes(result)


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.modules = self.root / 'modules'
        self.modules.mkdir()
        self.native = {name: self.root / name for name in d._REQUIRED}
        self.native['bootstrap'] = self.native['launcher']
        for name in ('imaging', 'imagingft'):
            self.native[name] = self.modules / name
        for name, path in self.native.items():
            deps = [] if name in ('loader', 'c-runtime') else [str(self.native['c-runtime'])]
            if name == 'python-interpreter':
                deps += [str(self.native['python-framework']), str(self.native['loader'])]
            path.write_bytes(macho(deps))
        self.build = evidence()
        self.build_files = {}
        for name, _ in self.build['artifacts']:
            path = self.native.get(name, self.root / name)
            if not path.exists():
                path.write_bytes(name.encode())
            self.build_files[name] = path
        for relative in d._REQUIRED_MODULES:
            path = self.modules / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('# synthetic source: ' + relative + '\n')
        for name, relative in d._BUILD_MODULES.items():
            self.build_files[name] = self.modules / relative
        self.refresh_build()
        self.runtime = dict(kind='pillow-basic-runtime-v1', python_implementation='CPython',
                            python_version=[3, 14, 0], python_abi='cpython-314',
                            os='Darwin', os_release='test', architecture='x86_64',
                            byteorder='little', pointer_bits=64)

    def refresh_build(self):
        self.build['configuration_sha256'] = configuration_id(self.build['configuration'])
        self.build['artifacts'] = sorted([name, sha256(path.read_bytes()).hexdigest()]
                                        for name, path in self.build_files.items())

    def collect(self):
        return d.collect(self.build, self.build_files, self.native,
                         [self.modules], self.runtime)

    def test_determinism_and_verification(self):
        first = self.collect()
        self.native = dict(reversed(list(self.native.items())))
        self.assertEqual(first, self.collect())
        self.assertEqual(first['runtime_id'], d.verify(first, self.build,
                         self.build_files, self.native, [self.modules], self.runtime))
        self.assertNotIn(str(self.root), str(first))

    def test_fat_formats_bind_whole_file_and_selected_slice(self):
        path = self.native['launcher']
        payload = path.read_bytes()
        thin = self.collect()
        self.assertNotIn('native_slices', thin['deployment'])
        for endian in ('>', '<'):
            for wide in (False, True):
                with self.subTest(endian=endian, wide=wide):
                    data = fat(payload, endian, wide)
                    path.write_bytes(data)
                    result = self.collect()
                    self.assertEqual(thin['deployment']['native_dependencies'],
                                     result['deployment']['native_dependencies'])
                    records = dict(result['deployment']['native_artifacts'])
                    self.assertEqual(records['launcher'], sha256(data).hexdigest())
                    self.assertEqual(records['bootstrap'], records['launcher'])
                    slices = dict(result['deployment']['native_slices'])
                    self.assertEqual(slices['launcher'], dict(
                        architecture='x86_64', cpu_subtype=0, offset=256,
                        size=len(payload), sha256=sha256(payload).hexdigest()))
                    self.assertEqual(slices['bootstrap'], slices['launcher'])
                    self.assertEqual(result['runtime_id'], d.verify(
                        result, self.build, self.build_files, self.native,
                        [self.modules], self.runtime))
                    # Changes outside the selected slice still invalidate evidence.
                    changed = bytearray(data)
                    changed[180] ^= 1
                    path.write_bytes(changed)
                    self.assertNotEqual(result['runtime_id'], self.collect()['runtime_id'])
                    with self.assertRaisesRegex(ValueError, 'deployment evidence mismatch'):
                        d.verify(result, self.build, self.build_files, self.native,
                                 [self.modules], self.runtime)
                    path.write_bytes(data)
                    slices['launcher']['offset'] += 1
                    with self.assertRaisesRegex(ValueError, 'deployment evidence mismatch'):
                        d.verify(result, self.build, self.build_files, self.native,
                                 [self.modules], self.runtime)

    def test_malformed_fat_tables_and_slices_reject(self):
        for endian in ('>', '<'):
            for wide in (False, True):
                entry_size = 32 if wide else 20
                second = 8 + entry_size
                integer = 'Q' if wide else 'I'
                cases = [
                    (4, 'I', 0, 'fat table bounds'),
                    (4, 'I', 0xffffffff, 'fat table bounds'),
                    (second, 'I', 0x100000C, 'missing or duplicate'),
                    (8, 'I', 0x1000007, 'missing or duplicate'),
                    (second + 8, integer, 128, 'overlapping'),
                    (second + 8, integer, 0, 'fat slice bounds'),
                    (second + 8, integer, 10000, 'fat slice bounds'),
                    (second + (16 if wide else 12), integer, 10000, 'fat slice bounds'),
                    (second + (16 if wide else 12), integer, 0, 'fat slice bounds'),
                    (second + (24 if wide else 16), 'I', 64, 'alignment'),
                    (second + (24 if wide else 16), 'I', 9, 'alignment'),
                    (second + 4, 'I', 3, 'architecture mismatch'),
                ]
                if wide:
                    cases.append((second + 28, 'I', 1, 'reserved'))
                for offset, fmt, value, error in cases:
                    with self.subTest(endian=endian, wide=wide, offset=offset, value=value):
                        data = bytearray(fat(macho(), endian, wide))
                        struct.pack_into(endian + fmt, data, offset, value)
                        self.native['loader'].write_bytes(data)
                        with self.assertRaisesRegex(ValueError, error):
                            self.collect()
                for offset, value in ((256, 0), (260, 0x100000C), (264, 3)):
                    data = bytearray(fat(macho(), endian, wide))
                    struct.pack_into('<I', data, offset, value)
                    self.native['loader'].write_bytes(data)
                    with self.assertRaisesRegex(ValueError, 'architecture mismatch'):
                        self.collect()
                for length in (4, 7, 8 + 2 * entry_size - 1, 270):
                    self.native['loader'].write_bytes(fat(macho(), endian, wide)[:length])
                    with self.assertRaises(ValueError):
                        self.collect()

    def test_fat_selected_load_commands_and_unbound_modules_reject(self):
        path = self.native['loader']
        for payload in (macho(['@rpath/untrusted']), macho(['/missing'])):
            path.write_bytes(fat(payload))
            with self.assertRaises(ValueError):
                self.collect()
        path.write_bytes(macho())
        for wide in (False, True):
            for endian in ('>', '<'):
                (self.modules / 'unbound-native').write_bytes(fat(macho(), endian, wide))
                with self.assertRaisesRegex(ValueError, 'unbound native module'):
                    self.collect()

    def test_contradictory_platform_declarations_reject(self):
        for field, value in (('os', 'Linux'), ('byteorder', 'big'),
                             ('pointer_bits', 32), ('architecture', 'arm64'),
                             ('python_implementation', 'PyPy'),
                             ('python_version', [3, 13, 0])):
            with self.subTest(field=field):
                original = self.runtime[field]
                self.runtime[field] = value
                with self.assertRaisesRegex(ValueError, 'mismatch'):
                    self.collect()
                self.runtime[field] = original

    def test_build_runtime_and_native_architectures_must_agree(self):
        self.build['configuration']['target']['architecture'] = 'arm64'
        self.refresh_build()
        with self.assertRaisesRegex(ValueError, 'runtime/build architecture mismatch'):
            self.collect()
        self.runtime['architecture'] = 'arm64'
        with self.assertRaisesRegex(ValueError, 'thin native architecture'):
            self.collect()
        for path in set(self.native.values()):
            data = bytearray(path.read_bytes())
            struct.pack_into('<I', data, 4, 0x100000C)
            path.write_bytes(data)
        self.refresh_build()
        self.collect()  # Matching arm64 is supported, not just x86_64.
        self.native['loader'].write_bytes(macho())
        with self.assertRaisesRegex(ValueError, 'thin native architecture'):
            self.collect()

    def test_required_runtime_sources_cannot_be_omitted(self):
        # Explicit sentinels prevent an accidentally empty inventory from
        # making this rejection matrix pass vacuously.
        self.assertTrue({'PIL/ImageFont.py', 'PIL/Image.py', 'PIL/_version.py',
                         'presentation_agent/_pillow_basic.py',
                         'presentation_agent/layout.py',
                         'presentation_agent/_build_evidence.py',
                         'encodings/__init__.py', 'encodings/aliases.py',
                         'encodings/utf_8.py', 'dataclasses.py'} <= d._REQUIRED_MODULES)
        for relative in sorted(d._REQUIRED_MODULES):
            with self.subTest(module=relative):
                path = self.modules / relative
                displaced = self.root / 'displaced-source'
                path.rename(displaced)
                removed = {name: location for name, location in self.build_files.items()
                           if location == path}
                for name in removed:
                    self.build_files.pop(name)
                self.refresh_build()
                with self.assertRaisesRegex(ValueError, 'missing or duplicate runtime module'):
                    self.collect()
                displaced.rename(path)
                self.build_files.update(removed)
                self.refresh_build()

    def test_required_build_source_bindings_cannot_be_omitted_or_redirected(self):
        for name in sorted(d._BUILD_MODULES):
            with self.subTest(artifact=name):
                path = self.build_files.pop(name)
                self.refresh_build()
                with self.assertRaisesRegex(ValueError, 'missing implementation evidence'):
                    self.collect()
                substitute = self.root / 'substitute-source'
                substitute.write_bytes(path.read_bytes())
                self.build_files[name] = substitute
                self.refresh_build()
                with self.assertRaisesRegex(ValueError, 'runtime implementation binding'):
                    self.collect()
                self.build_files[name] = path
                self.refresh_build()

    def test_duplicate_or_split_packages_reject(self):
        other = self.root / 'other-modules'
        (other / 'PIL').mkdir(parents=True)
        original = self.modules / 'PIL/Image.py'
        duplicate = other / 'PIL/Image.py'
        duplicate.write_bytes(original.read_bytes())
        with self.assertRaisesRegex(ValueError, 'missing or duplicate runtime module'):
            d.collect(self.build, self.build_files, self.native,
                      [self.modules, other], self.runtime)
        original.rename(self.root / 'displaced-source')
        self.build_files['PIL.Image.py'] = duplicate
        self.refresh_build()
        with self.assertRaisesRegex(ValueError, 'split runtime package'):
            d.collect(self.build, self.build_files, self.native,
                      [self.modules, other], self.runtime)

    def test_earlier_root_module_cannot_shadow_required_package(self):
        earlier = self.root / 'earlier-modules'
        earlier.mkdir()
        (earlier / 'PIL.py').write_text('# shadows the verified package\n')
        with self.assertRaisesRegex(ValueError, 'runtime module resolution mismatch: PIL/'):
            d.collect(self.build, self.build_files, self.native,
                      [earlier, self.modules], self.runtime)
        # A later module cannot override the already selected regular package.
        d.collect(self.build, self.build_files, self.native,
                  [self.modules, earlier], self.runtime)

    def test_alternate_loaders_cannot_redirect_required_source(self):
        for index, relative in enumerate(('PIL.pyc', 'PIL.so',
                                          'PIL.cpython-314-darwin.so',
                                          'PIL.abi3.so', 'PIL/__init__.pyc',
                                          'dataclasses/__init__.py')):
            with self.subTest(shadow=relative):
                earlier = self.root / ('shadow-' + str(index))
                path = earlier / relative
                path.parent.mkdir(parents=True)
                # Resolution must reject before loading or parsing this file.
                path.write_bytes(b'not executable')
                with self.assertRaisesRegex(ValueError, 'runtime module resolution mismatch'):
                    d.collect(self.build, self.build_files, self.native,
                              [earlier, self.modules], self.runtime)

    def test_submodule_package_shape_and_extension_redirection_reject(self):
        package = self.modules / 'PIL/ImageFont'
        package.mkdir()
        (package / '__init__.py').write_text('# package overrides ImageFont.py\n')
        with self.assertRaisesRegex(ValueError, 'runtime module resolution mismatch: PIL/ImageFont.py'):
            self.collect()
        package.rename(self.root / 'displaced-package')
        (self.modules / 'PIL/ImageFont.so').write_bytes(b'not executable')
        with self.assertRaisesRegex(ValueError, 'runtime module resolution mismatch: PIL/ImageFont.py'):
            self.collect()

    def test_regular_package_precedes_same_root_module_and_namespace_portion(self):
        (self.modules / 'PIL.py').write_text('# regular package wins in this root\n')
        earlier = self.root / 'namespace-root'
        (earlier / 'PIL').mkdir(parents=True)
        (earlier / 'PIL/unrelated.py').write_text('# namespace portion\n')
        d.collect(self.build, self.build_files, self.native,
                  [earlier, self.modules], self.runtime)

    def test_unchecked_hash_cache_cannot_replace_verified_source(self):
        source = self.modules / 'PIL/ImageFont.py'
        alternate = self.root / 'alternate.py'
        alternate.write_text('marker = "redirected cached code"\n')
        cache = Path(cache_from_source(str(source)))
        py_compile.compile(str(alternate), cfile=str(cache), doraise=True,
                           invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
        # Reproduce the loader behavior without executing the alternate code.
        code = SourceFileLoader('PIL.ImageFont', str(source)).get_code('PIL.ImageFont')
        self.assertIn('redirected cached code', code.co_consts)
        with self.assertRaisesRegex(ValueError, 'unverified runtime bytecode cache: PIL/ImageFont.py'):
            self.collect()
        cache.rename(self.root / 'displaced-cache')
        self.collect()  # The same verified source remains valid without a cache.

    def test_package_and_optimized_caches_reject_without_trusting_headers(self):
        for index, relative in enumerate((
                'PIL/__pycache__/__init__.cpython-314.pyc',
                'PIL/__pycache__/ImageFont.cpython-314.opt-1.pyc',
                'PIL/__pycache__/ImageFont.cpython-314.opt-2.pyc',
                'PIL/ImageFont.pyc')):
            with self.subTest(cache=relative):
                cache = self.modules / relative
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_bytes(b'cache headers are not trusted')
                with self.assertRaisesRegex(ValueError, 'unverified runtime bytecode cache'):
                    self.collect()
                cache.rename(self.root / ('displaced-cache-' + str(index)))
        self.collect()

    def test_missing_extra_duplicate_and_changed_artifacts(self):
        original = self.native.copy()
        for mutate in (lambda: self.native.pop('loader'),
                       lambda: self.native.update(extra=self.native['loader']),
                       lambda: self.native.update(extra=self.root / 'absent')):
            self.native = original.copy()
            mutate()
            with self.assertRaises((ValueError, OSError)):
                self.collect()
        self.native = original
        before = self.collect()
        self.native['loader'].write_bytes(macho() + b'changed')
        with self.assertRaises(ValueError):
            d.verify(before, self.build, self.build_files, self.native,
                     [self.modules], self.runtime)

    def test_transitive_dependency_required_and_bound(self):
        path = self.root / 'transitive'
        path.write_bytes(macho())
        self.native['c-runtime'].write_bytes(macho([str(path)]))
        with self.assertRaises(ValueError):
            self.collect()
        self.native['transitive'] = path
        self.assertIn(['c-runtime', ['transitive']],
                      self.collect()['deployment']['native_dependencies'])

    def test_module_inventory_changes_identity_and_rejects_symlinks(self):
        first = self.collect()
        module = self.modules / 'implementation.py'
        module.write_text('value = 1\n')
        self.assertNotEqual(first['runtime_id'], self.collect()['runtime_id'])
        (self.modules / 'alias').symlink_to(module)
        with self.assertRaises(ValueError):
            self.collect()

    def test_missing_or_duplicate_search_paths(self):
        for paths in ([], [self.modules, self.modules], [self.root / 'missing']):
            with self.assertRaises(ValueError):
                d.collect(self.build, self.build_files, self.native, paths, self.runtime)

    def test_unsupported_native_and_search_dependencies(self):
        path = self.native['loader']
        for data in (b'bad', macho(['@rpath/untrusted']), macho(['/missing']),
                     macho(['/same', '/same'])):
            path.write_bytes(data)
            with self.assertRaises(ValueError):
                self.collect()

    def test_build_mismatch_and_expected_extra_fields(self):
        expected = self.collect()
        expected['unexpected'] = True
        with self.assertRaises(ValueError):
            d.verify(expected, self.build, self.build_files, self.native,
                     [self.modules], self.runtime)
        self.build_files['freetype-static'].write_bytes(b'changed')
        with self.assertRaises(ValueError):
            self.collect()

    def test_unexpected_native_artifact_and_unbound_extension(self):
        extra = self.root / 'extra'
        extra.write_bytes(macho())
        self.native['extra'] = extra
        with self.assertRaises(ValueError):
            self.collect()
        self.native.pop('extra')
        (self.modules / 'extra.so').write_bytes(macho())
        with self.assertRaises(ValueError):
            self.collect()

    def test_malformed_load_commands(self):
        path = self.native['loader']
        for body in (struct.pack('<II', 0xC, 0), struct.pack('<II', 0xC, 80)):
            path.write_bytes(struct.pack('<8I', 0xFEEDFACF, 0x1000007,
                                        0, 2, 1, len(body), 0, 0) + body)
            with self.assertRaises(ValueError):
                self.collect()


if __name__ == '__main__':
    unittest.main()
