"""Phase 4.5A4 bindings and negative protection observations, no activation."""
from copy import deepcopy
from hashlib import sha256
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from presentation_agent import _launch_policy as p
from presentation_agent import layout
from presentation_agent.evidence import canonical_bytes
import test_milestone3_phase3c2b_deployment as deployment_tests


class LaunchPolicyTests(unittest.TestCase):
    def setUp(self):
        self.fixture = deployment_tests.DeploymentTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        self.expected = f.collect()
        self.args = (self.expected, f.build, f.build_files, f.native,
                     [str(f.modules)], f.runtime)
        # Synthetic read-only mount observations; no host protection claim.
        self.mounts = patch.object(p.os, 'fstatvfs',
                                   return_value=SimpleNamespace(f_flag=os.ST_RDONLY))
        self.mounts.start()
        self.addCleanup(self.mounts.stop)
        self.signatures = patch.object(p, '_signature', return_value={'status': 'valid', 'file_sha256': sha256(f.native['launcher'].read_bytes()).hexdigest(), 'metadata': {'Signature': 'adhoc'}})
        self.signatures.start()
        self.addCleanup(self.signatures.stop)

    def test_policy_exact_empty_environment_and_order(self):
        policy = p.policy()
        self.assertEqual(policy['environment']['accepted_name_value_pairs'], [])
        self.assertTrue(policy['environment']['reject_unlisted'])
        self.assertFalse(policy['environment']['sanitize_before_admission'])
        self.assertEqual(policy['environment']['ascii_case_insensitive_rejected_prefixes'],
                         ['FREETYPE_', 'FT2_'])
        self.assertEqual(policy['initialization_sequence'], [
            'launcher-admission', 'artifact-runtime-verification',
            'deferred-python-load', 'isolated-python-bootstrap',
            'lifecycle-establishment', 'provider-initialization'])
        policy['environment']['accepted_name_value_pairs'].append(['PATH', '/bin'])
        self.assertEqual(p.policy()['environment']['accepted_name_value_pairs'], [])

    def test_binding_is_deterministic_and_does_not_change_inputs(self):
        before = deepcopy(self.expected)
        result = p.collect(*self.args)
        self.assertEqual(result, p.collect(*self.args))
        self.assertEqual(p.verify(result, *self.args), result['evidence_sha256'])
        self.assertEqual(self.expected, before)
        self.assertEqual(result['deployment']['deployment_evidence_sha256'],
                         sha256(canonical_bytes(before)).hexdigest())
        self.assertEqual(result['deployment']['build_configuration_sha256'],
                         sha256(canonical_bytes(result['build_configuration'])).hexdigest())

    def test_readonly_observations_are_not_lifetime_protection(self):
        document = p.collect(*self.args)['deployment']
        self.assertEqual(document['qualification'], 'not-established')
        self.assertEqual(document['substitution_protection']['through_last_use'],
                         'not-established')
        with self.assertRaisesRegex(ValueError, 'through last use not established'):
            p.require_substitution_protection(*self.args)
        self.assertIn('fresh-exec-loader-state-not-observed', document['protection_gaps'])
        roles = document['artifact_protection_observations']
        self.assertIn('native:launcher', roles)
        self.assertIn('native:bootstrap', roles)
        self.assertIn('native:python-framework', roles)
        self.assertTrue(any(role.startswith('module:0:') for role in roles))

    def test_valid_signature_is_not_preload_or_substitution_proof(self):
        gaps = p.collect(*self.args)['deployment']['protection_gaps']
        self.assertIn('preload-prevention-before-entry-not-established', gaps)
        self.assertIn('substitution-prevention-through-last-use-not-established', gaps)

    def test_signature_digest_and_metadata_are_bound(self):
        result = p.collect(*self.args)
        for key, value in (('file_sha256', '0' * 64), ('metadata', {})):
            altered = deepcopy(result)
            altered['deployment']['launcher_signature'][key] = value
            with self.assertRaises(ValueError):
                p.verify(altered, *self.args)
        with patch.object(p, '_signature', return_value={
                'status': 'valid', 'file_sha256': '0' * 64}):
            with self.assertRaises(ValueError):
                p.collect(*self.args)
        with patch.object(p, '_signature', return_value={'status': 'invalid-or-unsigned'}):
            with self.assertRaises(ValueError):
                p.collect(*self.args)

    def test_policy_order_environment_or_success_tampering_rejects(self):
        result = p.collect(*self.args)
        for change in ('sequence', 'environment', 'qualification', 'gaps'):
            altered = deepcopy(result)
            if change == 'sequence':
                altered['build_configuration']['launch_policy']['initialization_sequence'].reverse()
            elif change == 'environment':
                altered['build_configuration']['launch_policy']['environment']['accepted_name_value_pairs'] = [['FT2_X', '']]
            elif change == 'qualification':
                altered['deployment']['qualification'] = 'qualified'
            else:
                altered['deployment']['protection_gaps'] = []
            with self.assertRaises(ValueError):
                p.verify(altered, *self.args)

    def test_changed_artifact_symlink_or_cache_rejects(self):
        launcher = self.fixture.native['launcher']
        original = launcher.read_bytes()
        launcher.write_bytes(original + b'changed')
        with self.assertRaises(ValueError):
            p.collect(*self.args)
        launcher.write_bytes(original)
        link = self.fixture.root / 'launcher-link'
        link.symlink_to(launcher)
        with self.assertRaises(ValueError):
            p._path_observation(link)
        (self.fixture.modules / 'unexpected.pyc').write_bytes(b'cache')
        with self.assertRaises(ValueError):
            p.collect(*self.args)

    def test_permissions_change_changes_evidence(self):
        result = p.collect(*self.args)
        self.fixture.native['launcher'].chmod(0o400)
        with self.assertRaises(ValueError):
            p.verify(result, *self.args)

    def test_namespace_change_during_signature_check_rejects(self):
        # Introduce an empty directory: file hashes and tree records do not
        # change, but future package/cache resolution could change there.
        signature = p._signature.return_value
        def change_namespace(*args):
            (self.fixture.modules / 'new-empty-package').mkdir()
            return signature
        with patch.object(p, '_signature', side_effect=change_namespace):
            with self.assertRaisesRegex(ValueError, 'resolution protection changed'):
                p.collect(*self.args)

    def test_mount_becomes_writable_during_verification_rejects(self):
        signature = p._signature.return_value
        def writable(*args):
            p.os.fstatvfs.return_value = SimpleNamespace(f_flag=0)
            return signature
        with patch.object(p, '_signature', side_effect=writable):
            with self.assertRaisesRegex(ValueError, 'native protection observation changed'):
                p.collect(*self.args)

    def test_ordinary_provider_remains_closed(self):
        with self.assertRaises(ValueError):
            layout._open_provider(None)


if __name__ == '__main__':
    unittest.main()
