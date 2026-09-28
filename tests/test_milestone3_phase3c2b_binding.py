"""Binding derivation only: synthetic OS/inventory observations grant no trust."""
from hashlib import sha256
import json
import unittest
from unittest.mock import patch

from presentation_agent import _deployment_binding as binding
from presentation_agent import _deployment_protection as protection
from presentation_agent import _launch_policy as policy
from presentation_agent import _startup_inventory as inventory
from presentation_agent import layout
from presentation_agent.evidence import canonical_bytes
import test_milestone3_phase3c2b_protection as fixtures


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ProtectionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        self.policy = policy._collect(*f.args, resolution=lambda *a: ())
        self.args = (f.args[0], self.policy, *f.args[1:])
        self.data = self.startup()
        # Startup inventory generation has its own native-format tests. Here
        # replace only that collector; pin authentication, deployment/policy
        # recollection, path inspection and lifecycle are the real code.
        self.collector = patch.object(inventory, 'collect', side_effect=lambda *a: self.data)
        self.collector.start()
        self.addCleanup(self.collector.stop)

    def startup(self, loader=None):
        f = self.fixture
        records = []
        for kind, name in enumerate(('launcher', 'loader')):
            path = loader if name == 'loader' and loader else str(f.args[3][name])
            records.append(inventory.IMAGE.pack(kind, path.encode(), b'a' * 32,
                                                 b'b' * 32, 4096))
        return (inventory.HEADER.pack(b'PAEXEC01', bytes.fromhex(f.pins['deployment_sha256']),
                                      b'c' * 20, 2, 1) + b''.join(records) +
                inventory.MAPPING.pack(4096, 4096, 5, 5, b'd' * 32))

    def collect(self):
        return binding.collect(*self.args)

    def test_deterministic_authenticated_package_and_closed_provider(self):
        raw = self.collect()
        self.assertEqual(raw, self.collect())
        package = json.loads(raw)
        self.assertEqual(raw, canonical_bytes(package))
        self.assertEqual(package['protected_deployment'], self.fixture.pins)
        self.assertEqual(package['attachment_pin_sha256'],
                         sha256(self.fixture.pin_file.read_bytes()).hexdigest())
        self.assertEqual(package['deployment_sha256'], self.fixture.pins['deployment_sha256'])
        self.assertEqual(package['launch_policy_sha256'], self.fixture.pins['launch_policy_sha256'])
        self.assertEqual(package['startup_inventory']['sha256'], sha256(self.data).hexdigest())
        self.assertEqual(bytes.fromhex(package['startup_inventory']['bytes_hex']), self.data)
        self.assertEqual(package['launcher'], str(self.fixture.args[3]['launcher']))
        self.assertEqual(package['python_framework'], str(self.fixture.args[3]['python-framework']))
        self.assertEqual(package['module_paths'], [str(self.fixture.args[4][0])])
        self.assertIsNone(binding.verify(raw, *self.args))
        with self.assertRaises(ValueError):
            layout._open_provider(None)

    def test_policy_pin_cannot_be_self_approved(self):
        self.fixture.pins['launch_policy_sha256'] = '0' * 64
        self.fixture.write_pins()
        with self.assertRaisesRegex(ValueError, 'policy evidence-pin'):
            self.collect()

    def test_unpinned_workspace_inputs_reject(self):
        self.fixture.args[3]['python-framework'] = self.fixture.backing
        with self.assertRaisesRegex(ValueError, 'evidence-pin mismatch'):
            self.collect()

    def test_even_pinned_outside_paths_reject(self):
        self.fixture.args[3]['python-framework'] = self.fixture.backing
        self.fixture.pins['inputs_sha256'] = protection._digest(
            protection._inputs(*self.fixture.args[2:]))
        self.fixture.write_pins()
        with self.assertRaisesRegex(ValueError, 'escaping protected deployment'):
            self.collect()

    def test_startup_system_path_has_no_exception(self):
        self.data = self.startup(loader=str(self.fixture.backing))
        with self.assertRaisesRegex(ValueError, 'outside or noncanonical'):
            self.collect()

    def test_startup_deployment_mismatch_latches(self):
        original = self.data
        self.data = original[:8] + b'x' * 32 + original[40:]
        with self.assertRaisesRegex(ValueError, 'startup inventory mismatch'):
            self.collect()
        self.data = original
        with self.assertRaisesRegex(ValueError, 'lifecycle invalid'):
            self.collect()

    def test_truncated_inventory_rejects(self):
        self.data = self.data[:-1]
        with self.assertRaisesRegex(ValueError, 'startup inventory mismatch'):
            self.collect()

    def test_wrong_startup_launcher_rejects(self):
        offset = inventory.HEADER.size
        kind, path, digest, text, extent = inventory.IMAGE.unpack_from(self.data, offset)
        record = inventory.IMAGE.pack(kind, str(self.fixture.args[3]['python-interpreter']).encode(),
                                      digest, text, extent)
        self.data = self.data[:offset] + record + self.data[offset + inventory.IMAGE.size:]
        with self.assertRaisesRegex(ValueError, 'startup launcher mismatch'):
            self.collect()

    def test_changed_pins_during_inventory_derivation_reject(self):
        def change(*args):
            self.fixture.pins['launch_policy_sha256'] = 'f' * 64
            self.fixture.write_pins()
            return self.data
        with patch.object(inventory, 'collect', side_effect=change):
            with self.assertRaisesRegex(ValueError, 'identity changed'):
                self.collect()

    def test_package_tampering_rejects_and_latches(self):
        package = json.loads(self.collect())
        package['module_paths'] = ['/untrusted/modules']
        with self.assertRaisesRegex(ValueError, 'package mismatch'):
            binding.verify(canonical_bytes(package), *self.args)
        with self.assertRaisesRegex(ValueError, 'lifecycle invalid'):
            self.collect()

    def test_missing_admin_pins_reject(self):
        with patch.object(protection, '_PIN_FILE', self.fixture.pin_file.parent / 'absent'):
            with self.assertRaises((ValueError, FileNotFoundError)):
                self.collect()

    def test_fork_identity_rejects(self):
        self.collect()
        with patch.object(protection.os, 'getpid', return_value=-1):
            with self.assertRaises(ValueError):
                self.collect()
