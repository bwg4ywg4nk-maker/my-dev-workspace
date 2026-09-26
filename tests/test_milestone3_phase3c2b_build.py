"""Phase-1 unit/schema and fake-face native tests, never font qualification."""
from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from presentation_agent import _build_evidence as b
from presentation_agent import layout
from presentation_agent._pillow_basic import _PillowBasicCore
from presentation_agent.evidence import canonical_bytes

ROOT = Path(__file__).resolve().parents[1]
SUPPORT = ROOT / 'tools/controlled_build'
GLYPHS = tuple(range(32, 127))


def config():
    return {
        'kind': 'pillow-basic-phase1-configuration-v1',
        'versions': {'pillow': '12.3.0', 'freetype': '2.14.3'},
        'sources': [['freetype', '0' * 64], ['pillow', '1' * 64]],
        'patches': [[name, '2' * 64] for name in sorted(b._PATCHES)],
        'tools': [[name, '3' * 64] for name in sorted(b._TOOLS)],
        'target': {'architecture': 'x86_64', 'deployment_target': '13.0', 'sdk_sha256': '4' * 64},
        'flags': {'compile': ['-O2', '-fPIC'], 'link': ['-bundle'], 'configure': ['explicit']},
        'modules': ['sfnt', 'truetype'], 'disabled': ['raqm', 'zlib'],
        'generated': [[name, '5' * 64] for name in sorted(b._GENERATED)],
    }


def evidence():
    value = config()
    return {'kind': 'pillow-basic-phase1-evidence-v1', 'configuration': value,
            'configuration_sha256': b.configuration_id(value),
            'artifacts': [[name, '6' * 64] for name in
                          ('freetype-static', 'imaging', 'imaging-link', 'imagingft',
                           'imagingft-link', 'imagingft-symbols')]}


def audit():
    return (2, ((0, 3, 1, 0x756e6963, 4, GLYPHS),
                (1, 3, 10, 0x756e6963, 12, GLYPHS)), 0, GLYPHS, 0, GLYPHS)


def scratch():
    parent = ROOT / 'build/phase1-unit'
    parent.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(dir=parent))


class BuildEvidenceTests(unittest.TestCase):
    def test_configuration_identity_is_canonical_and_nonmutating(self):
        value = config()
        before = deepcopy(value)
        expected = sha256(canonical_bytes(value)).hexdigest()
        self.assertEqual(b.configuration_id(value), expected)
        self.assertEqual(b.configuration_id(dict(reversed(list(value.items())))), expected)
        self.assertEqual(value, before)

    def test_evidence_identity_and_configuration_binding(self):
        value = evidence()
        self.assertEqual(b.evidence_id(value), sha256(canonical_bytes(value)).hexdigest())
        value['configuration']['flags']['compile'].append('-g')
        with self.assertRaises(ValueError):
            b.evidence_id(value)

    def test_malformed_shapes_and_missing_artifacts(self):
        for function, factory in ((b.configuration_id, config), (b.evidence_id, evidence)):
            for item in (None, [], (), True):
                with self.assertRaises(ValueError):
                    function(item)
            for field in factory():
                value = factory()
                del value[field]
                with self.assertRaises(ValueError):
                    function(value)
            value = factory()
            value['extra'] = 1
            with self.assertRaises(ValueError):
                function(value)
        value = evidence()
        value['artifacts'].pop()
        with self.assertRaises(ValueError):
            b.evidence_id(value)

    def test_source_patch_tool_generated_and_artifact_digest_validation(self):
        for field in ('sources', 'patches', 'tools', 'generated', 'artifacts'):
            for invalid in ('A' * 64, 'g' * 64, '0' * 63, '0' * 65, None, True):
                value = evidence() if field == 'artifacts' else config()
                value[field][0][1] = invalid
                with self.assertRaises(ValueError):
                    (b.evidence_id if field == 'artifacts' else b.configuration_id)(value)

    def test_artifact_order_and_duplicates_rejected(self):
        for field in ('sources', 'patches', 'tools', 'generated', 'artifacts'):
            for records in ([['b', '0' * 64], ['a', '1' * 64]],
                            [['a', '0' * 64], ['a', '0' * 64]]):
                value = evidence() if field == 'artifacts' else config()
                value[field] = records
                with self.assertRaises(ValueError):
                    (b.evidence_id if field == 'artifacts' else b.configuration_id)(value)

    def test_module_and_option_canonicalization(self):
        for field in ('modules', 'disabled'):
            for values in ([], ['b', 'a'], ['a', 'a'], ('a',), [True]):
                value = config()
                value[field] = values
                with self.assertRaises(ValueError):
                    b.configuration_id(value)
        value = config()
        value['flags']['compile'].reverse()
        self.assertNotEqual(b.configuration_id(value), b.configuration_id(config()))

    def test_versions_and_target_rejected(self):
        for field, invalid in (('architecture', 'universal2'), ('sdk_sha256', 'no'),
                               ('deployment_target', '')):
            value = config()
            value['target'][field] = invalid
            with self.assertRaises(ValueError):
                b.configuration_id(value)
        value = config()
        value['versions']['pillow'] = '12.2.0'
        with self.assertRaises(ValueError):
            b.configuration_id(value)

    def test_required_generated_configuration_and_tool_evidence(self):
        for field in ('generated', 'tools', 'patches'):
            for index in range(len(config()[field])):
                value = config()
                value[field].pop(index)
                with self.assertRaises(ValueError):
                    b.configuration_id(value)

    def test_declaration_does_not_verify_bytes(self):
        directory = scratch()
        for role in ('source', 'patch', 'artifact'):
            path = directory / role
            path.write_bytes(b'actual bytes')
            records = [[role, sha256(b'actual bytes').hexdigest()]]
            b.verify_bytes(records, {role: path})
            path.write_bytes(b'changed bytes')
            with self.assertRaises(ValueError):
                b.verify_bytes(records, {role: path})
            with self.assertRaises(ValueError):
                b.verify_bytes(records, {})

    def test_ordinary_provider_stays_closed(self):
        for item in (evidence(), b.evidence_id(evidence()), audit()):
            with self.assertRaisesRegex(ValueError, 'binding unavailable'):
                layout._open_provider(item)
        core = _PillowBasicCore.__new__(_PillowBasicCore)
        with patch('presentation_agent._pillow_basic._inspect_sfnt') as inspect:
            result = core.inspect_font(b'unit test', SimpleNamespace(font=SimpleNamespace(face_index=0)))
            self.assertIs(result, inspect.return_value)


class AuditSchemaTests(unittest.TestCase):
    def test_valid_immutable_shape(self):
        value = audit()
        self.assertIs(b.validate_audit(value), value)

    def test_exact_tuple_limits_and_integer_types(self):
        for value in (None, [], list(audit()), audit() + (True,)):
            with self.assertRaises(ValueError):
                b.validate_audit(value)
        for count in (0, 257, True, 2.0):
            with self.assertRaises(ValueError):
                b.validate_audit((count,) + audit()[1:])

    def test_exactly_95_ascii_glyphs(self):
        for invalid in ((), GLYPHS[:-1], GLYPHS + (127,), list(GLYPHS),
                        (0,) + GLYPHS[1:], (65536,) + GLYPHS[1:], (True,) + GLYPHS[1:]):
            value = list(audit())
            value[3] = value[5] = invalid
            with self.assertRaises(ValueError):
                b.validate_audit(tuple(value))

    def test_descriptor_order_and_duplicate_rejection(self):
        value = audit()
        for maps in (value[1][::-1], (value[1][0], value[1][0]), value[1][:1]):
            with self.assertRaises(ValueError):
                b.validate_audit((2, maps) + value[2:])

    def test_restoration_and_disagreement(self):
        value = audit()
        for index, item in ((4, 1), (5, (1,) + GLYPHS[1:])):
            changed = list(value)
            changed[index] = item
            with self.assertRaisesRegex(ValueError, 'restoration'):
                b.validate_audit(tuple(changed))
        maps = (value[1][0], value[1][1][:-1] + ((1,) + GLYPHS[1:],))
        with self.assertRaisesRegex(ValueError, 'disagreement'):
            b.validate_audit((2, maps) + value[2:])

    def test_descriptor_format_encoding_and_bounds(self):
        value = audit()
        for position, invalid in ((0, True), (1, -1), (2, 65536), (3, 2**32),
                                   (3, 0), (4, 14), (4, 6), (5, GLYPHS[:-1])):
            descriptor = list(value[1][0])
            descriptor[position] = invalid
            with self.assertRaises(ValueError):
                b.validate_audit((2, (tuple(descriptor), value[1][1])) + value[2:])

    def test_ineligible_map_has_no_glyph_query_data(self):
        value = audit()
        descriptor = (1, 1, 0, 0, 4, ())
        b.validate_audit((2, (value[1][0], descriptor)) + value[2:])
        with self.assertRaises(ValueError):
            b.validate_audit((2, (value[1][0], descriptor[:-1] + (GLYPHS,))) + value[2:])

    def test_no_pointer_setter_or_qualification_interface_added(self):
        patch = (SUPPORT / 'pillow-12.3.0-cmap.patch').read_text()
        added = [line for line in patch.splitlines() if line.startswith('+    {')]
        self.assertEqual(added, ['+    {"_pa_cmap_audit", (PyCFunction)pa_cmap_audit, METH_NOARGS},'])
        source = (SUPPORT / 'pa_cmap_audit.h').read_text()
        for forbidden in ('FT_New_Face', 'FT_New_Memory_Face', 'FT_Init_FreeType',
                          'PyCapsule', 'PyLong_FromVoidPtr', 'PyArg_Parse', 'FT_Property_Set'):
            self.assertNotIn(forbidden, source)


class NativeAuditUnitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if sys.platform != 'darwin' or sys.version_info < (3, 10) or not shutil.which('clang'):
            raise unittest.SkipTest('Native fake-face harness requires macOS CPython >=3.10 and clang')
        if sysconfig.get_config_var('Py_GIL_DISABLED'):
            raise unittest.SkipTest('Phase-1 supports GIL-enabled CPython')
        directory = scratch()
        extension = directory / ('_phase1_cmap_harness' + sysconfig.get_config_var('EXT_SUFFIX'))
        result = subprocess.run(['clang', '-bundle', '-undefined', 'dynamic_lookup',
                                 '-I' + sysconfig.get_path('include'), '-I' + str(SUPPORT),
                                 str(ROOT / 'tests/phase1_cmap_harness.c'), '-o', str(extension)],
                                capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stderr)
        spec = importlib.util.spec_from_file_location('_phase1_cmap_harness', extension)
        cls.native = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.native)

    def test_native_success_schema_and_restoration(self):
        value, error, index, calls, allocations = self.native.exercise(0, 0)
        self.assertIsNone(error)
        self.assertEqual(b.validate_audit(value), audit())
        self.assertEqual((index, calls), (0, 3))

    def test_native_switch_missing_glyph_disagreement_and_format_errors_restore(self):
        for mode in (1, 3, 4, 6):
            value, error, index, calls, allocations = self.native.exercise(mode, 0)
            self.assertIsNone(value)
            self.assertIsInstance(error, str)
            self.assertEqual(index, 0)
            self.assertGreaterEqual(calls, 2)

    def test_native_restore_failure_returns_no_result(self):
        value, error, index, calls, allocations = self.native.exercise(2, 0)
        self.assertIsNone(value)
        self.assertIn('restoration failed', error)

    def test_native_nonzero_original_map_is_restored(self):
        value, error, index, calls, allocations = self.native.exercise(8, 0)
        self.assertIsNone(error)
        b.validate_audit(value)
        self.assertEqual((value[2], value[4], index), (1, 1, 1))

    def test_native_ineligible_map_and_duplicate_selected_map(self):
        value, error, index, calls, allocations = self.native.exercise(9, 0)
        self.assertIsNone(error)
        b.validate_audit(value)
        self.assertEqual(value[1][1][-1], ())
        self.assertEqual(calls, 2)
        value, error, index, calls, allocations = self.native.exercise(10, 0)
        self.assertIsNone(value)
        self.assertIn('Duplicate', error)
        self.assertEqual(index, 0)

    def test_native_restored_glyphs_rechecked(self):
        value, error, index, calls, allocations = self.native.exercise(5, 0)
        self.assertIsNone(value)
        self.assertIn('glyphs changed', error)
        self.assertEqual(index, 0)

    def test_native_count_limit_before_traversal(self):
        value, error, index, calls, allocations = self.native.exercise(7, 0)
        self.assertIsNone(value)
        self.assertEqual((calls, allocations), (0, 0))

    def test_every_native_allocation_failure_restores(self):
        total = self.native.exercise(0, 0)[4]
        self.assertGreater(total, 380)
        for allocation in range(1, total + 1):
            value, error, index, calls, count = self.native.exercise(0, allocation)
            self.assertIsNone(value, allocation)
            self.assertIsInstance(error, str)
            self.assertEqual(index, 0, allocation)
            self.assertGreaterEqual(calls, 1)


if __name__ == '__main__':
    unittest.main()
