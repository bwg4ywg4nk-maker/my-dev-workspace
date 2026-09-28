"""Offline identity prerequisite: synthetic font/mounts never qualify a runtime."""
from hashlib import sha256
import json
import unittest
from unittest.mock import patch

from presentation_agent import _deployment_binding as binding, _pillow_basic, layout
from presentation_agent._provider_manifests import _build_manifest_id, _runtime_manifest_id
from presentation_agent.evidence import canonical_bytes
import test_milestone3_phase3c2b_binding as support
from test_milestone3_phase3c2b_pillow import sfnt


class ProviderIdentityTests(unittest.TestCase):
    def setUp(self):
        self.fixture = support.BindingTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.font = self.fixture.fixture.root / 'explicit-font.ttf'
        self.font.write_bytes(bytes(sfnt()))
        self.digest = sha256(self.font.read_bytes()).hexdigest()
        # Only the synthetic font trust anchor is replaced; the real identity,
        # SFNT parser, evidence verification and protected lifecycle execute.
        for module in (layout, _pillow_basic):
            override = patch.object(module, '_FONT_SHA256', self.digest)
            override.start()
            self.addCleanup(override.stop)

    def collect(self):
        return binding.collect(*self.fixture.args, font_file=self.font)

    def test_derived_identities_exact_files_and_closed_provider(self):
        raw = self.collect()
        package = json.loads(raw)
        self.assertEqual(package['kind'], 'trusted-admin-deployment-binding-v2')
        p = package['provider_identity']
        build = json.loads(bytes.fromhex(p['build_manifest']['bytes_hex']))
        runtime = json.loads(bytes.fromhex(p['runtime_manifest']['bytes_hex']))
        profile = json.loads(bytes.fromhex(p['profile']['bytes_hex']))
        self.assertEqual(_build_manifest_id(build), profile['provider']['build_id'])
        self.assertEqual(_runtime_manifest_id(runtime), profile['provider']['runtime_id'])
        self.assertEqual(profile['font']['sha256'], self.digest)
        self.assertEqual(p['profile']['sha256'], sha256(
            layout._NAMESPACE + canonical_bytes(profile)).hexdigest())
        records = {role: (path, digest) for role, path, digest in p['artifacts']}
        self.assertEqual(records['build:measurement-adapter'][1], p['adapter_sha256'])
        self.assertEqual(records['font'], (str(self.font), self.digest))
        self.assertEqual(p['build_evidence_sha256'], self.fixture.fixture.pins['build_sha256'])
        self.assertEqual(raw, self.collect())
        self.assertIsNone(binding.verify(raw, *self.fixture.args, font_file=self.font))
        with self.assertRaises(ValueError):
            layout._open_provider(None)

    def test_changed_font_rejects_and_latches(self):
        self.font.write_bytes(b'wrong font')
        with self.assertRaises(ValueError):
            self.collect()
        self.font.write_bytes(bytes(sfnt()))
        with self.assertRaisesRegex(ValueError, 'lifecycle invalid'):
            self.collect()

    def test_python_runtime_claim_cannot_replace_pinned_evidence(self):
        self.fixture.args[0]['runtime_id'] = 'sha256:' + '1' * 64
        with self.assertRaises(ValueError):
            self.collect()

    def test_missing_font_and_partial_package_reject(self):
        with self.assertRaises((ValueError, FileNotFoundError)):
            binding.collect(*self.fixture.args, font_file=self.font.with_name('missing'))

    def test_changed_identity_document_rejects(self):
        package = json.loads(self.collect())
        package['provider_identity']['build_manifest']['sha256'] = '1' * 64
        with self.assertRaisesRegex(ValueError, 'package mismatch'):
            binding.verify(canonical_bytes(package), *self.fixture.args, font_file=self.font)

    def test_no_python_provider_claim_argument(self):
        with self.assertRaises(TypeError):
            binding.collect(*self.fixture.args, font_file=self.font,
                            provider_build_id='sha256:' + '1' * 64)
