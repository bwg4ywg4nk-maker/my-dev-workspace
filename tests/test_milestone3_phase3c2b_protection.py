"""Trusted-admin prerequisite mechanics; synthetic mounts never qualify providers."""
import ctypes
import errno
from hashlib import sha256
import json
import os
from pathlib import Path
import plistlib
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from presentation_agent import _deployment_protection as protection
from presentation_agent import _launch_policy as policy
from presentation_agent import layout
import test_milestone3_phase3c2b_deployment as deployment_tests


class ProtectionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = deployment_tests.DeploymentTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        # Keep every fixture under the TemporaryDirectory cleanup boundary.
        self.pin_file = f.root / 'provisioning/pins.json'
        self.backing = f.root / 'provisioning/image.dmg'
        # The image root must be separate from its backing store and trust anchor.
        original_root = f.root
        image_root = f.root / 'image'
        image_root.mkdir()
        for child in list(original_root.iterdir()):
            if child != image_root:
                child.rename(image_root / child.name)
        f.native = {k: image_root / v.relative_to(original_root) for k, v in f.native.items()}
        f.build_files = {k: image_root / v.relative_to(original_root)
                         for k, v in f.build_files.items()}
        f.modules = image_root / f.modules.relative_to(original_root)
        # Native dependency names are absolute in this fixture; rebuild them.
        for name, path in f.native.items():
            deps = [] if name in ('loader', 'c-runtime') else [str(f.native['c-runtime'])]
            if name == 'python-interpreter':
                deps += [str(f.native['python-framework']), str(f.native['loader'])]
            path.write_bytes(deployment_tests.macho(deps))
        f.refresh_build()
        self.args = (f.collect(), f.build, f.build_files, f.native, [f.modules], f.runtime)
        self.root = image_root
        self.pin_file.parent.mkdir()
        self.backing.write_bytes(b'synthetic immutable image')
        self.mount = ((123, 456), 0, 0x1001, 'hfs', str(self.root), '/dev/disk99s1')
        self.host_mount = ((1, 2), 0, 0x1000, 'apfs', '/', '/dev/disk1')
        self.image = {'image-path': str(self.backing), 'owner-uid': 0,
                      'image-type': 'read-only disk image', 'writeable': False,
                      'system-entities': [{'mount-point': str(self.root),
                                           'dev-entry': self.mount[5]}]}
        self.start_patch(protection, '_PIN_FILE', self.pin_file)
        self.start_patch(protection, '_lifecycle', protection._Lifecycle())
        # Simulate only OS mount/admin/ACL observations, preserving real file
        # descriptors, contents, inode identity, and the production plist parser.
        inspect = protection._inspect
        def observed(path, directory, *, admin=False, mount=None, read=False):
            observed_mount = self.mount if path.is_relative_to(self.root) else self.host_mount
            with patch.object(protection, '_mount', return_value=observed_mount):
                return inspect(path, directory, admin=False, mount=mount, read=read)
        self.start_patch(protection, '_inspect', observed)
        self.start_patch(policy.os, 'fstatvfs', return_value=SimpleNamespace(f_flag=os.ST_RDONLY))
        self.start_patch(policy, '_signature', return_value={
            'status': 'valid', 'file_sha256': sha256(f.native['launcher'].read_bytes()).hexdigest(),
            'metadata': {'Signature': 'adhoc'}})
        self.start_patch(protection.subprocess, 'run', side_effect=lambda *a, **kw:
                         SimpleNamespace(returncode=0, stdout=plistlib.dumps({'images': [self.image]})))
        document = policy._collect(*self.args, resolution=lambda *a: ())
        self.pins = {'kind': 'trusted-admin-readonly-image-v1',
                     'root': str(self.root), 'backing_file': str(self.backing),
                     'backing_sha256': sha256(self.backing.read_bytes()).hexdigest(),
                     'deployment_sha256': protection._digest(self.args[0]),
                     'build_sha256': protection._digest(f.build),
                     'launch_policy_sha256': protection._digest(document),
                     'inputs_sha256': protection._digest(protection._inputs(*self.args[2:]))}
        self.write_pins()

    def start_patch(self, target, name, *args, **kwargs):
        mock = patch.object(target, name, *args, **kwargs)
        result = mock.start()
        self.addCleanup(mock.stop)
        return result

    def write_pins(self):
        self.pin_file.write_text(json.dumps(self.pins))

    def require(self):
        return policy.require_substitution_protection(*self.args)

    def test_verified_prerequisite_rechecks_without_provider_authorization(self):
        self.assertIsNone(self.require())
        self.assertIsNone(self.require())
        with self.assertRaises(ValueError):
            layout._open_provider(None)

    def test_provisioning_candidate_does_not_approve_its_own_pin(self):
        self.pins['launch_policy_sha256'] = '0' * 64
        self.write_pins()
        candidate = protection.collect_protected_evidence(*self.args)
        self.assertNotEqual(protection._digest(candidate), self.pins['launch_policy_sha256'])
        self.assertIsNone(protection._lifecycle.snapshot)
        with self.assertRaisesRegex(ValueError, 'launch-policy evidence-pin mismatch'):
            self.require()

    def test_missing_pins_reject(self):
        with patch.object(protection, '_PIN_FILE', self.pin_file.with_name('missing')):
            with self.assertRaises(FileNotFoundError):
                self.require()

    def test_symlinked_artifact_rejects(self):
        file = self.fixture.modules / 'unexpected.py'
        file.symlink_to(self.backing)
        with self.assertRaisesRegex(ValueError, 'symlinked protected path'):
            self.require()

    def test_unprivileged_attachment_rejects(self):
        self.image['owner-uid'] = 501
        with self.assertRaisesRegex(ValueError, 'non-admin image attachment'):
            self.require()

    def test_writable_mount_rejects(self):
        self.mount = (*self.mount[:2], self.mount[2] & ~1, *self.mount[3:])
        with self.assertRaisesRegex(ValueError, 'writable'):
            self.require()

    def test_shadow_and_union_overlay_reject(self):
        self.image['shadow-path'] = '/protected/readonly-shadow'
        with self.assertRaisesRegex(ValueError, 'shadow/overlay'):
            self.require()

    def test_union_mount_rejects(self):
        self.mount = (*self.mount[:2], self.mount[2] | 0x20, *self.mount[3:])
        with self.assertRaisesRegex(ValueError, 'overlay'):
            self.require()

    def test_backing_store_mismatch_rejects(self):
        self.backing.write_bytes(b'replaced')
        with self.assertRaisesRegex(ValueError, 'backing-store mismatch'):
            self.require()

    def test_attachment_backing_mismatch_rejects(self):
        self.image['image-path'] += '.other'
        with self.assertRaisesRegex(ValueError, 'backing-store mismatch'):
            self.require()

    def test_mount_identity_change_latches(self):
        self.require()
        saved = self.mount
        self.mount = ((124, 456), *self.mount[1:])
        with self.assertRaisesRegex(ValueError, 'identity changed'):
            self.require()
        self.mount = saved
        with self.assertRaisesRegex(ValueError, 'lifecycle invalid'):
            self.require()

    def test_evidence_pin_mismatch_rejects(self):
        self.pins['deployment_sha256'] = '0' * 64
        self.write_pins()
        with self.assertRaisesRegex(ValueError, 'evidence-pin mismatch'):
            self.require()

    def test_launch_policy_pin_mismatch_rejects(self):
        self.pins['launch_policy_sha256'] = '0' * 64
        self.write_pins()
        with self.assertRaisesRegex(ValueError, 'launch-policy evidence-pin mismatch'):
            self.require()

    def test_authenticated_but_escaping_artifact_rejects(self):
        self.args[3]['launcher'] = self.backing
        self.pins['inputs_sha256'] = protection._digest(protection._inputs(*self.args[2:]))
        self.write_pins()
        with self.assertRaisesRegex(ValueError, 'escaping protected deployment'):
            self.require()

    def test_protection_loss_during_verification_rejects_and_cannot_retry(self):
        signature = policy._signature.return_value
        def lose(*args):
            self.image['writeable'] = True
            return signature
        with patch.object(policy, '_signature', side_effect=lose):
            with self.assertRaisesRegex(ValueError, 'writable'):
                self.require()
        self.image['writeable'] = False
        with self.assertRaisesRegex(ValueError, 'lifecycle invalid'):
            self.require()

    def test_fork_identity_rejects(self):
        self.require()
        # Model a parent mutex held by a vanished thread: PID rejection must
        # happen before either check() or its rejection path tries to acquire it.
        with protection._lifecycle._state_lock, \
                patch.object(protection.os, 'getpid', return_value=os.getpid() + 1):
            with self.assertRaisesRegex(ValueError, 'lifecycle invalid'):
                self.require()

    def test_concurrent_invalidation_prevents_inflight_success(self):
        self.require()
        lifecycle = protection._lifecycle
        original_snapshot = lifecycle.snapshot
        observing, resume = threading.Event(), threading.Event()
        outcomes = []
        attachment = protection._attachment

        def paused_attachment(*args):
            result = attachment(*args)
            observing.set()
            if not resume.wait(10):
                raise AssertionError('concurrent invalidation did not complete')
            return result

        def check():
            try:
                lifecycle.check(self.args)
                outcomes.append('success')
            except BaseException as exc:
                outcomes.append(exc)

        # Pause real verification during its I/O phase, then let a second
        # check detect a pin mismatch and latch rejection before resuming it.
        with patch.object(protection, '_attachment', side_effect=paused_attachment):
            worker = threading.Thread(target=check, daemon=True)
            worker.start()
            try:
                self.assertTrue(observing.wait(10), 'observation did not start')
                wrong_args = ({}, *self.args[1:])
                with self.assertRaisesRegex(ValueError, 'evidence-pin mismatch'):
                    lifecycle.check(wrong_args)
            finally:
                resume.set()
                worker.join(10)
            self.assertFalse(worker.is_alive(), 'in-flight check did not finish')
        self.assertEqual(len(outcomes), 1)
        self.assertIsInstance(outcomes[0], ValueError)
        self.assertIn('lifecycle invalid', str(outcomes[0]))
        self.assertIs(lifecycle.snapshot, original_snapshot)
        with self.assertRaisesRegex(ValueError, 'lifecycle invalid'):
            self.require()

    def test_pin_replacement_after_success_rejects(self):
        self.require()
        self.write_pins()  # Same bytes, new file timestamps are still a change.
        with self.assertRaisesRegex(ValueError, 'identity changed'):
            self.require()

    def test_missing_or_ambiguous_attachment_rejects(self):
        self.image['system-entities'][0]['mount-point'] = '/another-image'
        with self.assertRaisesRegex(ValueError, 'missing deployment image'):
            self.require()


class NativeObservationTests(unittest.TestCase):
    def test_untrusted_pin_permissions_reject_before_reading(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'pins.json'
            path.write_text('{}')
            path.chmod(0o666)
            with patch.object(protection, '_mount', return_value=(
                    (1, 2), 0, 0x1000, 'apfs', '/', '/dev/disk1')):
                with self.assertRaisesRegex(ValueError, 'administrator-owned'):
                    protection._inspect(path, False, admin=True, read=True)

    @unittest.skipUnless(sys.platform == 'darwin', 'Darwin filesystem ABI')
    def test_real_statfs_agrees_with_statvfs(self):
        fd = os.open('/Library', os.O_RDONLY | os.O_DIRECTORY)
        try:
            mount = protection._mount(fd)
            self.assertEqual(bool(mount[2] & 1), bool(os.fstatvfs(fd).f_flag & os.ST_RDONLY))
            self.assertIn(mount[3], ('apfs', 'hfs'))
            self.assertTrue(mount[4].startswith('/'))
            self.assertTrue(mount[5].startswith('/dev/'))
        finally:
            os.close(fd)

    def test_acl_entry_is_rejected_and_empty_acl_is_accepted(self):
        for present in (True, False):
            def entry(*args):
                ctypes.set_errno(0 if present else errno.EINVAL)
                return 0 if present else -1
            lib = SimpleNamespace(acl_get_fd_np=lambda *a: 1, acl_get_entry=entry,
                                  acl_free=lambda *a: 0)
            with patch.object(protection, '_libc', return_value=lib):
                if present:
                    with self.assertRaisesRegex(ValueError, 'empty ACL'):
                        protection._no_acl(0)
                else:
                    protection._no_acl(0)


if __name__ == '__main__':
    unittest.main()
