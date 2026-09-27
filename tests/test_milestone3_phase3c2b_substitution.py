"""Narrow substitution rejection tests; synthetic mounts never qualify a provider."""
from hashlib import sha256
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from presentation_agent import _launch_policy as p
import test_milestone3_phase3c2b_deployment as deployment_tests


class SubstitutionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = deployment_tests.DeploymentTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        self.expected = f.collect()
        self.args = (self.expected, f.build, f.build_files, f.native,
                     [f.modules], f.runtime)

    def test_writable_rejects_before_hash_or_signature_verification(self):
        with patch.object(p.os, 'fstatvfs', return_value=SimpleNamespace(f_flag=0)), \
                patch.object(p.deployment, 'verify') as verify, \
                patch.object(p, '_signature') as signature:
            with self.assertRaisesRegex(ValueError, 'writable or substitutable'):
                p.collect(*self.args)
            verify.assert_not_called()
            signature.assert_not_called()

    def test_every_artifact_ancestor_and_empty_resolution_directory_is_required(self):
        f = self.fixture
        empty = f.modules / 'empty' / '__pycache__'
        empty.mkdir(parents=True)
        observe = p._observation
        targets = {Path('/'), f.root, f.modules, empty, empty.parent,
                   f.modules / 'PIL/ImageFont.py', *f.native.values()}
        for target in targets:
            with self.subTest(target=target):
                def observation(path, directory=False):
                    record = observe(path, directory)
                    record['read_only_filesystem'] = Path(path) != target
                    return record
                with patch.object(p, '_observation', side_effect=observation):
                    with self.assertRaisesRegex(ValueError, 'writable or substitutable'):
                        p._resolution_protection(f.native, [f.modules])

    def test_chmod_and_signature_cannot_waive_writable_mount(self):
        self.fixture.native['launcher'].chmod(0o444)
        with patch.object(p.os, 'fstatvfs', return_value=SimpleNamespace(f_flag=0)):
            with self.assertRaisesRegex(ValueError, 'writable or substitutable'):
                p.collect(*self.args)

    def test_missing_paths_symlinks_and_unavailable_mount_evidence_fail_closed(self):
        f = self.fixture
        link = f.root / 'alias'
        link.symlink_to(f.native['launcher'])
        with patch.object(p.os, 'fstatvfs',
                          return_value=SimpleNamespace(f_flag=os.ST_RDONLY)):
            for path in (link, f.root / 'absent'):
                with self.subTest(path=path), self.assertRaises((ValueError, OSError)):
                    p._resolution_protection({'launcher': path}, [])
        with patch.object(p.os, 'fstatvfs', side_effect=OSError('unavailable')):
            with self.assertRaises(OSError):
                p.collect(*self.args)

    def collect_with_mutation(self, mutate):
        launcher = self.fixture.native['launcher']
        signature = {'status': 'valid',
                     'file_sha256': sha256(launcher.read_bytes()).hexdigest()}
        def signed(*args):
            mutate()
            return signature
        # Only mount/signature observations are synthetic. All path identities,
        # permissions, contents and timestamps come from the actual filesystem.
        with patch.object(p.os, 'fstatvfs',
                          return_value=SimpleNamespace(f_flag=os.ST_RDONLY)), \
                patch.object(p, '_signature', side_effect=signed):
            return p.collect(*self.args)

    def test_unrelated_sibling_creation_and_change_during_collection_pass(self):
        sibling = self.fixture.root / 'unrelated'
        self.collect_with_mutation(lambda: sibling.write_text('created'))
        self.collect_with_mutation(lambda: sibling.write_text('changed contents'))
        self.collect_with_mutation(lambda: sibling.rename(sibling.with_name('renamed')))

    def test_unrelated_sibling_creation_during_directory_observation_passes(self):
        root = self.fixture.root
        def mount(fd):
            (root / 'unrelated').write_text('created during observation')
            return SimpleNamespace(f_flag=os.ST_RDONLY)
        with patch.object(p.os, 'fstatvfs', side_effect=mount):
            p._observation(root, directory=True)

    def test_same_byte_artifact_replacement_during_collection_rejects(self):
        launcher = self.fixture.native['launcher']
        def replace():
            replacement = self.fixture.root / 'replacement'
            replacement.write_bytes(launcher.read_bytes())
            replacement.chmod(launcher.stat().st_mode)
            replacement.replace(launcher)
        with self.assertRaisesRegex(ValueError, 'resolution protection changed'):
            self.collect_with_mutation(replace)

    def test_ancestor_permission_change_during_collection_rejects(self):
        root = self.fixture.root
        mode = root.stat().st_mode
        self.addCleanup(root.chmod, mode)
        with self.assertRaisesRegex(ValueError, 'protection observation changed'):
            self.collect_with_mutation(lambda: root.chmod(mode ^ 0o020))

    def test_directory_identity_replacement_during_collection_rejects(self):
        # Replacing an empty resolution directory preserves file inventories
        # and mode bits, but must still invalidate its bound inode identity.
        directory = self.fixture.modules / 'empty'
        directory.mkdir()
        mode = directory.stat().st_mode
        def replace():
            directory.rename(self.fixture.root / 'displaced-empty')
            directory.mkdir()
            directory.chmod(mode)
        with self.assertRaisesRegex(ValueError, 'resolution protection changed'):
            self.collect_with_mutation(replace)

    def test_same_bytes_replacement_changes_protection_snapshot(self):
        f = self.fixture
        with patch.object(p.os, 'fstatvfs',
                          return_value=SimpleNamespace(f_flag=os.ST_RDONLY)):
            before = p._resolution_protection(f.native, [f.modules])
            replacement = f.root / 'replacement'
            launcher = f.native['launcher']
            replacement.write_bytes(launcher.read_bytes())
            replacement.chmod(launcher.stat().st_mode)
            replacement.replace(launcher)
            self.assertNotEqual(before, p._resolution_protection(f.native, [f.modules]))


if __name__ == '__main__':
    unittest.main()
