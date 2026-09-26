"""Synthetic declaration tests; no loaded-artifact or deployment acceptance."""
import ast
from copy import deepcopy
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from presentation_agent import _provider_manifests as m
from presentation_agent import evidence


BUILD_BYTES = (
    b'{"artifacts":[["adapter","0000000000000000000000000000000000000000000000000000000000000000"]],'
    b'"build_configuration_sha256":"1111111111111111111111111111111111111111111111111111111111111111",'
    b'"kind":"pillow-basic-build-v1"}'
)
BUILD_ID = 'sha256:218705825d3a874af8e72a78144220e221f7948fb464bd9f269c592d73a2f521'
RUNTIME_BYTES = (
    b'{"architecture":"arm64","byteorder":"little","kind":"pillow-basic-runtime-v1",'
    b'"native_runtime_artifacts":[["python","0000000000000000000000000000000000000000000000000000000000000000"]],'
    b'"os":"Darwin","os_release":"24.0","pointer_bits":64,"python_abi":"cp313",'
    b'"python_implementation":"CPython","python_version":[3,13,0]}'
)
RUNTIME_ID = 'sha256:33fd0befb61d1ee310b3df65a94a621d060e0af01083945720301ba019e30ba2'


def build():
    return dict(kind='pillow-basic-build-v1', artifacts=[['adapter', '0' * 64]],
                build_configuration_sha256='1' * 64)


def runtime():
    return dict(kind='pillow-basic-runtime-v1', python_implementation='CPython',
                python_version=[3, 13, 0], python_abi='cp313', os='Darwin',
                os_release='24.0', architecture='arm64', byteorder='little',
                pointer_bits=64, native_runtime_artifacts=[['python', '0' * 64]])


class String(str):
    pass


class Integer(int):
    pass


class List(list):
    pass


class Dict(dict):
    pass


CASES = ((build, m._build_manifest_id, 'artifacts', BUILD_BYTES, BUILD_ID),
         (runtime, m._runtime_manifest_id, 'native_runtime_artifacts', RUNTIME_BYTES, RUNTIME_ID))


class ManifestTests(unittest.TestCase):
    def rejected(self, function, value):
        before = deepcopy(value)
        with patch.object(m, 'sha256', side_effect=AssertionError('hash before validation')):
            with self.assertRaises(ValueError):
                function(value)
        self.assertEqual(value, before)

    def test_literal_vectors_and_dictionary_order(self):
        for factory, function, _, literal, identity in CASES:
            with self.subTest(factory=factory.__name__):
                value = factory()
                before = deepcopy(value)
                self.assertEqual(evidence.canonical_bytes(value), literal)
                self.assertEqual(function(value), identity)
                self.assertEqual(function(dict(reversed(list(value.items())))), identity)
                self.assertEqual(function(value), identity)
                self.assertEqual(value, before)
                with patch.object(m, 'canonical_bytes', wraps=evidence.canonical_bytes) as encoder:
                    self.assertEqual(function(value), identity)
                    self.assertIs(encoder.call_args.args[0], value)

    def test_exact_objects_keys_and_kinds(self):
        for factory, function, _, _, _ in CASES:
            for value in (None, [], (), Dict(factory()), list(factory().items())):
                self.rejected(function, value)
            for key in factory():
                value = factory()
                del value[key]
                self.rejected(function, value)
            for key in ('extra', 1, String('extra')):
                value = factory()
                value[key] = None
                self.rejected(function, value)
            value = {String(key): item for key, item in factory().items()}
            self.rejected(function, value)
            for kind in (None, 1, String(factory()['kind']), 'wrong',
                         'pillow-basic-runtime-v1' if factory is build else 'pillow-basic-build-v1'):
                value = factory()
                value['kind'] = kind
                self.rejected(function, value)

    def test_artifact_shapes_order_and_duplicates(self):
        for factory, function, field, _, _ in CASES:
            for entries in (None, [], (), List([['a', '0' * 64]]),
                            [('a', '0' * 64)], [List(['a', '0' * 64])],
                            [None], [['a']], [['a', '0' * 64, 'extra']],
                            [['b', '0' * 64], ['a', '1' * 64]],
                            [['a', '0' * 64], ['a', '1' * 64]]):
                value = factory()
                value[field] = entries
                self.rejected(function, value)
            value = factory()
            value[field] = [['A', '0' * 64], ['a', '0' * 64]]
            before = deepcopy(value)
            function(value)  # Repeated binary digests under distinct names are valid.
            self.assertEqual(value, before)

    def test_component_names(self):
        for factory, function, field, _, _ in CASES:
            for name in ('', 'a' * 101, 'a/b', 'a\\b', '\x1f', '\x7f', '\n',
                         '\t', 'é', '\ud800', String('a'), None, 1):
                value = factory()
                value[field][0][0] = name
                self.rejected(function, value)
            for name in (' ', '~', '.', '..', ' x ', 'a' * 100, 'a:"b'):
                value = factory()
                value[field][0][0] = name
                function(value)  # No invented trimming or filename rules.

    def test_digests(self):
        for factory, function, field, _, _ in CASES:
            for digest in ('', '0' * 63, '0' * 65, 'A' * 64, 'g' * 64,
                           'sha256:' + '0' * 64, '0' * 63 + '\n',
                           String('0' * 64), None, 0, b'0' * 64):
                value = factory()
                value[field][0][1] = digest
                self.rejected(function, value)
                if factory is build:
                    value = build()
                    value['build_configuration_sha256'] = digest
                    self.rejected(function, value)

    def test_runtime_strings(self):
        for field in ('python_implementation', 'python_abi', 'os', 'os_release', 'architecture'):
            for text in ('', 'x' * 101, '\x00', '\x1f', '\x7f', 'é', '\udfff',
                         '\n', String('x'), None, 1, b'x'):
                value = runtime()
                value[field] = text
                self.rejected(m._runtime_manifest_id, value)
            for text in (' ', '~', 'x' * 100, 'a/b\\c'):
                value = runtime()
                value[field] = text
                m._runtime_manifest_id(value)

    def test_versions_pointer_and_byteorder(self):
        for version in (None, (3, 13, 0), List([3, 13, 0]), [], [3, 13], [3, 13, 0, 0]):
            value = runtime()
            value['python_version'] = version
            self.rejected(m._runtime_manifest_id, value)
        for index in range(3):
            for part in (-1, True, False, 1.0, '3', Integer(3), 2**53, None):
                value = runtime()
                value['python_version'][index] = part
                self.rejected(m._runtime_manifest_id, value)
        for field, invalid, valid in (
                ('pointer_bits', (0, 16, 128, True, 32.0, Integer(32), '64', None), (32, 64)),
                ('byteorder', ('Little', '', 'middle', String('little'), None, 1), ('little', 'big'))):
            for item in invalid:
                value = runtime()
                value[field] = item
                self.rejected(m._runtime_manifest_id, value)
            for item in valid:
                value = runtime()
                value[field] = item
                m._runtime_manifest_id(value)
        for version in ([0, 0, 0], [2**53 - 1] * 3):
            value = runtime()
            value['python_version'] = version
            m._runtime_manifest_id(value)

    def test_collection_and_encoder_boundaries(self):
        self.assertEqual(evidence.MAX_RECORDS, 10000)
        for factory, function, field, _, _ in CASES:
            value = factory()
            value[field] = [[str(i).zfill(5), 'f' * 64] for i in range(10000)]
            function(value)
            value[field].append(['10000', 'f' * 64])
            self.rejected(function, value)
            value = factory()
            size = len(evidence.canonical_bytes(value))
            with patch.object(evidence, 'MAX_CANONICAL_BYTES', size):
                function(value)
            with patch.object(evidence, 'MAX_CANONICAL_BYTES', size - 1):
                self.rejected(function, value)
        # Valid fixed shapes cannot reach the encoder's depth or 16 MiB ceiling.

    def test_every_field_binds_identity(self):
        for factory, function, field, _, expected in CASES:
            for key in factory():
                if key == 'kind':
                    continue  # Only the literal versioned kind is accepted.
                value = factory()
                if key == field:
                    value[key][0][1] = 'f' * 64
                elif key == 'python_version':
                    value[key][2] = 1
                elif key == 'pointer_bits':
                    value[key] = 32
                elif key == 'byteorder':
                    value[key] = 'big'
                elif key == 'build_configuration_sha256':
                    value[key] = 'f' * 64
                else:
                    value[key] += 'x'
                self.assertNotEqual(function(value), expected, key)
            value = factory()
            value[field][0][0] += 'x'
            self.assertNotEqual(function(value), expected)

    def test_operational_exceptions_propagate(self):
        for factory, function, _, _, _ in CASES:
            for error in (MemoryError, KeyboardInterrupt):
                with patch.object(m, 'canonical_bytes', side_effect=error):
                    with self.assertRaises(error):
                        function(factory())

    def test_fresh_import_and_calls_do_not_touch_provider(self):
        source = '''
import sys
class BlockProvider:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'PIL' or fullname.startswith('PIL.') or fullname in (
            'presentation_agent.layout', 'presentation_agent._pillow_basic'):
            raise AssertionError('Provider import: ' + fullname)
sys.meta_path.insert(0, BlockProvider())
from presentation_agent._provider_manifests import _build_manifest_id, _runtime_manifest_id
_build_manifest_id(BUILD)
_runtime_manifest_id(RUNTIME)
assert not any(k == 'PIL' or k.startswith('PIL.') for k in sys.modules)
'''.replace('BUILD', repr(build())).replace('RUNTIME', repr(runtime()))
        result = subprocess.run([sys.executable, '-B', '-c', source], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_production_gate_is_unconditionally_closed_and_python39_syntax(self):
        from presentation_agent import layout
        for factory, function, _, _, _ in CASES:
            identity = function(factory())
            for profile in (None, factory(), identity, object()):
                with self.assertRaisesRegex(ValueError, 'binding unavailable'):
                    layout._open_provider(profile)
        ast.parse(Path(m.__file__).read_text(), feature_version=(3, 9))


if __name__ == '__main__':
    unittest.main()
