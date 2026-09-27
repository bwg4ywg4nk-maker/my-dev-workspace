"""Local codesign integration; never execute a signed test image."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from presentation_agent import _launch_policy as p

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == 'darwin', 'requires macOS codesign')
class SigningTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / 'build/signing-unit'
        parent.mkdir(parents=True, exist_ok=True)
        self.work = Path(tempfile.mkdtemp(dir=parent))
        source = self.work / 'main.c'
        source.write_text('int main(void) { return 78; }\n')
        self.launcher = self.work / 'launcher'
        subprocess.run(['clang', str(source), '-o', str(self.launcher)],
                       check=True, capture_output=True)
        subprocess.run(['/usr/bin/codesign', '--remove-signature', str(self.launcher)],
                       check=True, capture_output=True)

    def sign(self, path=None, identifier='org.professionalpresentationagent.launcher'):
        subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-',
                        '--options', 'runtime', '--identifier', identifier, '--timestamp=none',
                        str(path or self.launcher)], check=True, capture_output=True)

    def test_unsigned_and_invalid_reject(self):
        with self.assertRaises(ValueError):
            p._signature(self.launcher)
        self.sign()
        data = bytearray(self.launcher.read_bytes())
        data[4096] ^= 1
        self.launcher.write_bytes(data)
        with self.assertRaises(ValueError):
            p._signature(self.launcher)

    def test_reproducible_identity_and_resigned_substitution(self):
        copy = self.work / 'copy'
        shutil.copyfile(self.launcher, copy)
        self.sign()
        self.sign(copy)
        expected = p._signature(self.launcher)
        self.assertEqual(expected, p._signature(self.launcher))
        self.assertEqual(expected, p._signature(copy))
        self.assertEqual(expected['file_sha256'], p._observation(self.launcher)['sha256'])
        self.sign(identifier='substituted')
        self.assertNotEqual(expected, p._signature(self.launcher))

    def test_missing_tool_and_timeout_reject(self):
        for error in (FileNotFoundError(), subprocess.TimeoutExpired('codesign', 30)):
            with patch.object(p.subprocess, 'run', side_effect=error):
                with self.assertRaises(ValueError):
                    p._signature(self.launcher)

    def test_replacement_during_verification_rejects(self):
        self.sign()
        run = subprocess.run
        def replace(*args, **kwargs):
            result = run(*args, **kwargs)
            copy = self.work / 'replacement'
            shutil.copyfile(self.launcher, copy)
            copy.replace(self.launcher)
            return result
        with patch.object(p.subprocess, 'run', side_effect=replace):
            with self.assertRaises(ValueError):
                p._signature(self.launcher)
