import copy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from presentation_agent.evidence import (
    CSVLocator, EvidenceRecord, TextLocator, canonical_bytes, decode_records,
    encode_records, snapshot_identity,
)
from presentation_agent.source_capture import SourceStore

ROOT = Path(__file__).resolve().parents[1]


class EvidenceContractTests(unittest.TestCase):
    def setUp(self):
        self.record = EvidenceRecord(snapshot_identity(b"abc"), TextLocator(1, 2),
                                     "Observed text", ("Synthetic",))

    def test_literal_sha256_vector(self):
        self.assertEqual(snapshot_identity(b"abc"),
                         "sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")

    def test_literal_canonical_encoding(self):
        self.assertEqual(canonical_bytes({"z": [True, None, 2], "a": "é\n"}),
                         b'{"a":"\xc3\xa9\\n","z":[true,null,2]}')
        self.assertNotEqual(canonical_bytes("é"), canonical_bytes("e\u0301"))
        self.assertNotEqual(snapshot_identity(b"a\n"), snapshot_identity(b"a\r\n"))

    def test_canonical_rejects_unsupported_values(self):
        nested = None
        for _ in range(34):
            nested = [nested]
        for value in [1.0, float("nan"), float("inf"), 2**53, {1: "a"},
                      (1,), "\ud800", "x" * 100001, [0] * 10001, nested]:
            with self.subTest(type=type(value)), self.assertRaises(ValueError):
                canonical_bytes(value)

    def test_identity_preimage_and_mutations(self):
        preimage = (b'presentation-agent:evidence:v1\x00' +
                    b'{"locator":{"kind":"text","line_end":2,"line_start":1},'
                    b'"qualifications":["Synthetic"],"schema_version":1,'
                    b'"snapshot_id":"sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",'
                    b'"text":"Observed text"}')
        self.assertEqual(self.record.evidence_id, "ev1:" + hashlib.sha256(preimage).hexdigest())
        for change in [dict(text="Other"), dict(locator=TextLocator(1, 3)),
                       dict(snapshot_id=snapshot_identity(b"changed")),
                       dict(qualifications=("Different",))]:
            fields = dict(snapshot_id=self.record.snapshot_id, locator=self.record.locator,
                          text=self.record.text, qualifications=self.record.qualifications)
            fields.update(change)
            self.assertNotEqual(self.record.evidence_id, EvidenceRecord(**fields).evidence_id)

    def test_encoded_document_size_limit(self):
        # Many references to the same valid string still exceed the wire limit.
        with self.assertRaisesRegex(ValueError, "byte limit"):
            canonical_bytes(["x" * 100000] * 168)
        with self.assertRaisesRegex(ValueError, "size"):
            decode_records(b" " * (16 * 1024 * 1024 + 1))

    def test_roundtrip_and_order_independence(self):
        other = EvidenceRecord(self.record.snapshot_id, CSVLocator(1, 2, 1, 3), "CSV statement")
        first = encode_records([self.record, other])
        self.assertEqual(first, encode_records([other, self.record]))
        self.assertEqual(first, encode_records(decode_records(first)))
        self.assertEqual(decode_records(encode_records([])), ())

    def test_immutable_models(self):
        with self.assertRaises(FrozenInstanceError):
            self.record.text = "changed"
        with self.assertRaises(FrozenInstanceError):
            self.record.locator.line_end = 3
        with self.assertRaises(ValueError):
            EvidenceRecord(self.record.snapshot_id, TextLocator(1, 1), "a", ["mutable"])

    def test_bad_locators_and_records(self):
        for args in [(0, 1), (2, 1), (True, 1), (1.0, 2), (1, 2**53)]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                TextLocator(*args)
        for args in [(1, 1, 0, 1), (2, 1, 1, 1), (1, 1, 2, 1), (1, 1, True, 2)]:
            with self.assertRaises(ValueError):
                CSVLocator(*args)
        for text in ["", " \n", "x" * 100001, 5]:
            with self.assertRaises(ValueError):
                EvidenceRecord(self.record.snapshot_id, TextLocator(1, 1), text)
        with self.assertRaises(ValueError):
            EvidenceRecord("sha256:BAD", TextLocator(1, 1), "text")

    def test_strict_document_validation(self):
        good = json.loads(encode_records([self.record]))
        mutations = []
        for key, value in [("schema_version", True), ("extra", 1), ("evidence", {})]:
            mutated = copy.deepcopy(good)
            mutated[key] = value
            mutations.append(mutated)
        for key, value in [("evidence_id", "ev1:" + "0" * 64), ("schema_version", 2),
                           ("qualifications", "text"), ("extra", 1),
                           ("locator", {"kind": []}), ("text", "changed")]:
            mutated = copy.deepcopy(good)
            mutated["evidence"][0][key] = value
            mutations.append(mutated)
        for mutated in mutations:
            with self.subTest(mutated=mutated), self.assertRaises(ValueError):
                decode_records(json.dumps(mutated).encode())
        for data in [b'{"schema_version":1,"schema_version":1,"evidence":[]}',
                     b'{"schema_version":NaN,"evidence":[]}', b'\xff', b'{']:
            with self.assertRaises(ValueError):
                decode_records(data)
        with self.assertRaises(ValueError):
            encode_records([self.record, self.record])
        with self.assertRaises(ValueError):
            decode_records(json.dumps(dict(schema_version=1, evidence=[self.record.to_dict()] * 2)).encode())

    def test_schema_shape_matches_models(self):
        schema = json.loads((ROOT / "schemas/normalized_evidence.schema.json").read_text())
        record_schema = schema["properties"]["evidence"]["items"]
        self.assertEqual(set(record_schema["required"]), set(self.record.to_dict()))
        for model, shape in zip([TextLocator(1, 2), CSVLocator(1, 2, 1, 3)],
                                record_schema["properties"]["locator"]["oneOf"]):
            self.assertEqual(set(shape["required"]), set(model.to_dict()))


class SourceCaptureTests(unittest.TestCase):
    def setUp(self):
        runtime = ROOT / ".runtime"
        runtime.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="phase1-tests-", dir=runtime)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source.txt"
        self.source.write_bytes(b"original\r\n\xff")
        self.store = SourceStore(self.root)

    def test_exact_capture_and_source_preservation(self):
        before = self.source.stat()
        result = self.store.capture("source.txt")
        self.assertEqual(self.store.read(result.snapshot_id), b"original\r\n\xff")
        self.assertEqual(result.source_path, "source.txt")
        self.assertEqual(result.media_type, "text/plain")
        self.assertEqual(result.size_bytes, 11)
        self.assertEqual((self.source.stat().st_mtime_ns, self.source.stat().st_mode),
                         (before.st_mtime_ns, before.st_mode))
        self.assertEqual(stat.S_IMODE((self.root / result.storage_path).stat().st_mode), 0o400)
        self.assertEqual(stat.S_IMODE((self.root / ".runtime").stat().st_mode), 0o700)
        with self.assertRaises(FrozenInstanceError):
            result.source_path = "other"

    def test_deduplication_and_modified_source(self):
        first = self.store.capture("source.txt")
        original_inode = (self.root / first.storage_path).stat().st_ino
        self.assertEqual(self.store.capture("source.txt"), first)
        self.assertEqual((self.root / first.storage_path).stat().st_ino, original_inode)
        (self.root / "copy.csv").write_bytes(self.source.read_bytes())
        self.assertEqual(self.store.capture("copy.csv").snapshot_id, first.snapshot_id)
        self.source.write_bytes(b"changed")
        second = self.store.capture("source.txt")
        self.assertNotEqual(first.snapshot_id, second.snapshot_id)
        self.assertEqual(self.store.read(first.snapshot_id), b"original\r\n\xff")
        self.assertEqual(len(list((self.root / ".runtime/snapshots").iterdir())), 2)

    def test_empty_file_and_csv_capture_without_parsing(self):
        (self.root / "empty.txt").write_bytes(b"")
        self.assertEqual(self.store.capture("empty.txt").size_bytes, 0)
        (self.root / "data.CSV").write_bytes(b'a,"unterminated')
        self.assertEqual(self.store.capture("data.CSV").media_type, "text/csv")

    def test_concurrent_capture_publishes_one_complete_snapshot(self):
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(lambda _: self.store.capture("source.txt"), range(12)))
        self.assertTrue(all(result == results[0] for result in results))
        self.assertEqual(self.store.read(results[0].snapshot_id), self.source.read_bytes())
        self.assertEqual(len(list((self.root / ".runtime/snapshots").iterdir())), 1)

    def test_failed_write_does_not_publish_partial_snapshot(self):
        with patch("presentation_agent.source_capture.os.fsync", side_effect=OSError("write failed")):
            with self.assertRaisesRegex(OSError, "write failed"):
                self.store.capture("source.txt")
        self.assertEqual(list((self.root / ".runtime/snapshots").iterdir()), [])
        self.assertEqual(self.source.read_bytes(), b"original\r\n\xff")

    def test_snapshot_read_tolerates_link_metadata_change(self):
        result = self.store.capture("source.txt")
        original_fstat = os.fstat
        calls = 0
        def changing_ctime(fd):
            nonlocal calls
            calls += 1
            info = original_fstat(fd)
            return SimpleNamespace(st_mode=info.st_mode, st_size=info.st_size,
                                   st_mtime_ns=info.st_mtime_ns,
                                   st_ctime_ns=info.st_ctime_ns + calls)
        with patch("presentation_agent.source_capture.os.fstat", side_effect=changing_ctime):
            self.assertEqual(self.store.read(result.snapshot_id), self.source.read_bytes())
            with self.assertRaisesRegex(ValueError, "changed"):
                self.store.capture("source.txt")

    def test_reject_unsafe_paths_and_formats(self):
        for path in [str(self.source), "../source.txt", "a/../source.txt", "./source.txt",
                     "a//b.txt", "a\\b.txt", "source.txt/", "\x00.txt", "",
                     ".runtime/a.txt", ".git/a.txt", ".venv/a.txt", "https://host/a.txt",
                     "file.pdf", "file.docx", "file.json"]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.store.capture(path)
        self.assertFalse((self.root / ".runtime").exists())

    def test_nested_source(self):
        (self.root / "nested").mkdir()
        (self.root / "nested/data.txt").write_bytes(b"nested")
        result = self.store.capture("nested/data.txt")
        self.assertEqual(self.store.read(result.snapshot_id), b"nested")

    def test_reject_symlink_source_and_parent(self):
        (self.root / "alias.txt").symlink_to(self.source)
        (self.root / "aliasdir").symlink_to(self.root, target_is_directory=True)
        for path in ["alias.txt", "aliasdir/source.txt"]:
            with self.assertRaises(OSError):
                self.store.capture(path)

    def test_reject_symlink_runtime(self):
        (self.root / ".runtime").symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(OSError):
            self.store.capture("source.txt")
        self.assertFalse((self.root / "snapshots").exists())

    def test_reject_symlink_snapshot_directory(self):
        (self.root / ".runtime").mkdir()
        (self.root / ".runtime/snapshots").symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(OSError):
            self.store.capture("source.txt")

    def test_corrupt_snapshot_is_never_overwritten(self):
        result = self.store.capture("source.txt")
        stored = self.root / result.storage_path
        stored.chmod(0o600)
        stored.write_bytes(b"corrupt")
        for operation in [lambda: self.store.read(result.snapshot_id),
                          lambda: self.store.capture("source.txt")]:
            with self.assertRaisesRegex(ValueError, "integrity"):
                operation()
        self.assertEqual(stored.read_bytes(), b"corrupt")

    def test_reject_symlink_existing_snapshot(self):
        directory = self.root / ".runtime/snapshots"
        directory.mkdir(parents=True)
        identity = snapshot_identity(self.source.read_bytes())
        (directory / identity.split(":")[1]).symlink_to(self.source)
        with self.assertRaises(OSError):
            self.store.capture("source.txt")
        with self.assertRaises(OSError):
            self.store.read(identity)

    def test_file_limits_and_nonregular_files(self):
        with self.assertRaisesRegex(ValueError, "limit"):
            SourceStore(self.root, max_source_bytes=10).capture("source.txt")
        self.assertEqual(SourceStore(self.root, max_source_bytes=11).capture("source.txt").size_bytes, 11)
        for limit in [True, 0, -1, 8 * 1024 * 1024 + 1]:
            with self.assertRaises(ValueError):
                SourceStore(self.root, max_source_bytes=limit)
        (self.root / "directory.txt").mkdir()
        os.mkfifo(self.root / "pipe.txt")
        for name in ["directory.txt", "pipe.txt"]:
            with self.assertRaisesRegex(ValueError, "regular"):
                self.store.capture(name)

    def test_detect_source_change_during_read(self):
        original_read = os.read
        changed = False
        def changing_read(fd, size):
            nonlocal changed
            data = original_read(fd, size)
            if not changed:
                changed = True
                self.source.write_bytes(b"changed length")
            return data
        with patch("presentation_agent.source_capture.os.read", side_effect=changing_read):
            with self.assertRaisesRegex(ValueError, "changed"):
                self.store.capture("source.txt")
        self.assertFalse((self.root / ".runtime").exists())

    def test_invalid_identity_and_missing_source(self):
        for identity in ["../source.txt", "sha256:" + "A" * 64, "sha256:" + "a" * 64 + "\n"]:
            with self.assertRaises(ValueError):
                self.store.read(identity)
        with self.assertRaises(FileNotFoundError):
            self.store.capture("missing.txt")

    def test_git_ignores_runtime(self):
        result = subprocess.run(["git", "check-ignore", ".runtime/snapshots/example"],
                                cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
