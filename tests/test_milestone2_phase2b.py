from dataclasses import FrozenInstanceError, fields
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from presentation_agent.evidence import (
    CSVLocator, EvidenceRecord, TextLocator, encode_records, snapshot_identity,
)
from presentation_agent.evidence_verification import (
    EvidenceVerification, QualificationVerification, StructuredCells,
    TextReproduction, verify_evidence,
)
from presentation_agent.source_capture import SourceStore
from presentation_agent.source_extraction import (
    CSVExtraction, CSVLimits, TextExtraction, TextLimits, extract_csv, extract_text,
)


class VerificationTests(unittest.TestCase):
    def setUp(self):
        runtime = Path(__file__).resolve().parents[1] / '.runtime'
        runtime.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='phase2b-', dir=runtime)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = SourceStore(self.root)

    def record(self, data, text, locator=TextLocator(1, 1), qualifications=()):
        (self.root / 'source.txt').write_bytes(data)
        snapshot = self.store.capture('source.txt')
        return EvidenceRecord(snapshot.snapshot_id, locator, text, qualifications)

    def test_minimal_frozen_result_and_unchanged_evidence(self):
        self.assertEqual([field.name for field in fields(EvidenceVerification)],
                         ['record', 'extraction', 'text_reproduction',
                          'structured_cells', 'qualification_verification'])
        for locator in (TextLocator(1, 1), CSVLocator(1, 1, 1, 1)):
            with self.subTest(locator=locator):
                record = self.record(b'claim', 'claim', locator, ('caveat',))
                before = record.to_dict(), record.evidence_id, encode_records([record])
                result = verify_evidence(self.store, record)
                self.assertIs(result.record, record)
                self.assertIs(result.extraction.locator, record.locator)
                self.assertEqual(result.extraction.snapshot_id, record.snapshot_id)
                self.assertEqual((record.to_dict(), record.evidence_id,
                                  encode_records([record])), before)
                for field in fields(result):
                    with self.assertRaises(FrozenInstanceError):
                        setattr(result, field.name, None)

    def test_text_exact_selected_content(self):
        record = self.record(b'ignored\r\n first \r\nsecond\nlast',
                             ' first \r\nsecond', TextLocator(2, 3))
        result = verify_evidence(self.store, record)
        self.assertIsInstance(result.extraction, TextExtraction)
        self.assertEqual(result.extraction.text, ' first \r\nsecond')
        self.assertIs(result.text_reproduction, TextReproduction.EXACT_MATCH)
        self.assertIs(result.structured_cells, StructuredCells.NOT_APPLICABLE)

    def test_text_mismatch_never_normalizes_or_interprets(self):
        cases = [(b' claim ', 'claim'), (b'Claim', 'claim'),
                 (b'a\r\nb', 'a\nb'), (b'a\rb', 'a\nb'),
                 ('é'.encode(), 'e\u0301'), (b'one\ttwo', 'one two'),
                 (b'1000', '1,000'), (b'grew', 'increased'),
                 (b'claim\n', 'claim\n'), (b'a\x00b', 'ab')]
        for data, claimed in cases:
            with self.subTest(data=data, claimed=claimed):
                locator = TextLocator(1, 2) if data in (b'a\r\nb', b'a\rb') else TextLocator(1, 1)
                result = verify_evidence(self.store, self.record(data, claimed, locator))
                self.assertIs(result.text_reproduction, TextReproduction.MISMATCH)

    def test_text_bom_and_unicode_follow_phase2a(self):
        for source, claimed in [('\ufeffé', 'é'), ('\ufeff\ufeffx', '\ufeffx'),
                                ('a\u2028b\x00', 'a\u2028b\x00')]:
            with self.subTest(source=source):
                result = verify_evidence(self.store, self.record(source.encode(), claimed))
                self.assertIs(result.text_reproduction, TextReproduction.EXACT_MATCH)
                self.assertEqual(result.extraction.text, claimed)

    def test_empty_selected_text_is_a_mismatch(self):
        result = verify_evidence(self.store, self.record(b'\n', 'claim'))
        self.assertEqual(result.extraction.text, '')
        self.assertIs(result.text_reproduction, TextReproduction.MISMATCH)

    def test_csv_cells_are_exact_and_prose_is_not_assessed(self):
        data = b'heading,other,skip\r\n001,"a\r\nb",x\n 2 ,"say ""hi""",y'
        record = self.record(data, 'Revenue increased', CSVLocator(2, 3, 1, 2))
        result = verify_evidence(self.store, record)
        self.assertIsInstance(result.extraction, CSVExtraction)
        self.assertEqual(result.extraction.rows, (('001', 'a\r\nb'), (' 2 ', 'say "hi"')))
        self.assertIs(result.text_reproduction, TextReproduction.NOT_ASSESSED)
        self.assertIs(result.structured_cells, StructuredCells.AVAILABLE)

    def test_csv_matching_cell_or_serialization_never_verifies_prose(self):
        for data, claimed, locator in [(b'claim', 'claim', CSVLocator(1, 1, 1, 1)),
                                       (b'a,b', 'a,b', CSVLocator(1, 1, 1, 2)),
                                       (b'a\nb', 'a\nb', CSVLocator(1, 2, 1, 1)),
                                       (b'""', 'claim', CSVLocator(1, 1, 1, 1))]:
            with self.subTest(data=data):
                result = verify_evidence(self.store, self.record(data, claimed, locator))
                self.assertIs(result.text_reproduction, TextReproduction.NOT_ASSESSED)
                self.assertIs(result.structured_cells, StructuredCells.AVAILABLE)

    def test_qualifications_always_explicitly_unverified(self):
        for locator in (TextLocator(1, 1), CSVLocator(1, 1, 1, 1)):
            for claimed in ('claim', 'different'):
                for qualifications in ((), ('claim',), ('unsupported qualification',)):
                    with self.subTest(locator=locator, claimed=claimed, qualifications=qualifications):
                        record = self.record(b'claim', claimed, locator, qualifications)
                        result = verify_evidence(self.store, record)
                        self.assertIs(result.qualification_verification,
                                      QualificationVerification.UNVERIFIED)
                        self.assertIs(result.record.qualifications, qualifications)

    def test_dispatch_reuses_extraction_object_and_forwards_limits(self):
        text_limits = TextLimits(max_lines=2)
        csv_limits = CSVLimits(max_rows=2)
        for name, operation, locator, limits in [
            ('extract_text', extract_text, TextLocator(1, 1), text_limits),
            ('extract_csv', extract_csv, CSVLocator(1, 1, 1, 1), csv_limits),
        ]:
            with self.subTest(name=name):
                record = self.record(b'claim', 'claim', locator)
                extraction = operation(self.store, record.snapshot_id, locator, limits)
                other = 'extract_csv' if name == 'extract_text' else 'extract_text'
                with patch('presentation_agent.evidence_verification.' + name,
                           return_value=extraction) as selected, patch(
                               'presentation_agent.evidence_verification.' + other) as unused:
                    result = verify_evidence(self.store, record, limits=limits)
                selected.assert_called_once_with(self.store, record.snapshot_id, locator, limits)
                unused.assert_not_called()
                self.assertIs(result.extraction, extraction)

    def test_none_and_omitted_limits_use_parser_defaults(self):
        for name, operation, locator in [
            ('extract_text', extract_text, TextLocator(1, 1)),
            ('extract_csv', extract_csv, CSVLocator(1, 1, 1, 1)),
        ]:
            for kwargs in ({}, {'limits': None}):
                with self.subTest(name=name, kwargs=kwargs):
                    record = self.record(b'claim', 'claim', locator)
                    expected = operation(self.store, record.snapshot_id, locator)
                    other = 'extract_csv' if name == 'extract_text' else 'extract_text'
                    with patch('presentation_agent.evidence_verification.' + name,
                               wraps=operation) as selected, patch(
                                   'presentation_agent.evidence_verification.' + other) as unused:
                        result = verify_evidence(self.store, record, **kwargs)
                    selected.assert_called_once_with(self.store, record.snapshot_id, locator)
                    unused.assert_not_called()
                    self.assertEqual(result.extraction, expected)

    def test_lowered_limits_apply_to_unselected_content(self):
        for locator, limits in [(TextLocator(1, 1), TextLimits(max_lines=1)),
                                (CSVLocator(1, 1, 1, 1), CSVLimits(max_rows=1))]:
            with self.subTest(locator=locator):
                record = self.record(b'ok\nextra', 'ok', locator)
                with self.assertRaisesRegex(ValueError, 'limit'):
                    verify_evidence(self.store, record, limits=limits)

    def test_decoding_bounds_and_malformed_csv_fail(self):
        cases = [(b'ok\n\xff', TextLocator(1, 1), UnicodeDecodeError),
                 (b'ok\n\xff', CSVLocator(1, 1, 1, 1), UnicodeDecodeError),
                 (b'ok', TextLocator(2, 2), ValueError),
                 (b'ok', CSVLocator(1, 1, 2, 2), ValueError),
                 (b'ok\n"unterminated', CSVLocator(1, 1, 1, 1), ValueError)]
        for data, locator, error_type in cases:
            with self.subTest(data=data, locator=locator):
                record = self.record(data, 'ok', locator)
                with self.assertRaises(error_type):
                    verify_evidence(self.store, record)

    def test_missing_storage_does_not_create_files(self):
        for locator in (TextLocator(1, 1), CSVLocator(1, 1, 1, 1)):
            record = EvidenceRecord(snapshot_identity(b'absent'), locator, 'claim')
            with self.assertRaises(FileNotFoundError):
                verify_evidence(self.store, record)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_original_source_is_not_used_and_verification_does_not_write(self):
        record = self.record(b'claim', 'claim')
        (self.root / 'source.txt').write_bytes(b'changed')

        def file_state():
            return {path.relative_to(self.root): (path.read_bytes(), path.stat().st_mtime_ns,
                                                  path.stat().st_mode)
                    for path in self.root.rglob('*') if path.is_file()}

        before = file_state()
        with patch.object(self.store, 'read', wraps=self.store.read) as read:
            result = verify_evidence(self.store, record)
        read.assert_called_once_with(record.snapshot_id)
        self.assertIs(result.text_reproduction, TextReproduction.EXACT_MATCH)
        self.assertEqual(file_state(), before)

    def test_corrupt_snapshot_fails_for_both_locators(self):
        record = self.record(b'claim', 'claim')
        path = self.root / '.runtime' / 'snapshots' / record.snapshot_id.split(':')[1]
        path.chmod(0o600)
        path.write_bytes(b'other')
        for locator in (TextLocator(1, 1), CSVLocator(1, 1, 1, 1)):
            with self.assertRaisesRegex(ValueError, 'integrity'):
                verify_evidence(self.store, EvidenceRecord(record.snapshot_id, locator, 'claim'))

    def test_source_and_extraction_exceptions_propagate_unchanged(self):
        for locator, parser in [(TextLocator(1, 1), 'extract_text'),
                                (CSVLocator(1, 1, 1, 1), 'extract_csv')]:
            record = self.record(b'claim', 'claim', locator)
            for error in (FileNotFoundError('missing'), PermissionError('denied'),
                          OSError('I/O failure'), ValueError('extraction failed')):
                for target in ('presentation_agent.source_capture.SourceStore.read',
                               'presentation_agent.evidence_verification.' + parser):
                    with self.subTest(locator=locator, error=error, target=target):
                        with patch(target, side_effect=error), self.assertRaises(type(error)) as caught:
                            verify_evidence(self.store, record)
                        self.assertIs(caught.exception, error)

    def test_invalid_api_arguments_fail_before_read(self):
        with patch.object(self.store, 'read') as read:
            for bad in (None, {}, 'claim'):
                with self.assertRaisesRegex(ValueError, 'EvidenceRecord'):
                    verify_evidence(self.store, bad)
            read.assert_not_called()

    def test_cross_parser_limits_fail_before_read(self):
        for locator, limits in [(TextLocator(1, 1), CSVLimits()),
                                (CSVLocator(1, 1, 1, 1), TextLimits())]:
            with self.subTest(locator=locator):
                record = self.record(b'claim', 'claim', locator)
                with patch.object(self.store, 'read') as read:
                    with self.assertRaisesRegex(ValueError, 'Limits'):
                        verify_evidence(self.store, record, limits=limits)
                    read.assert_not_called()

    def test_arbitrary_invalid_limits_fail_before_read(self):
        for locator in (TextLocator(1, 1), CSVLocator(1, 1, 1, 1)):
            record = self.record(b'claim', 'claim', locator)
            for limits in (object(), {}, 'limits', 0, False):
                with self.subTest(locator=locator, limits=limits):
                    with patch.object(self.store, 'read') as read:
                        with self.assertRaisesRegex(ValueError, 'Limits'):
                            verify_evidence(self.store, record, limits=limits)
                        read.assert_not_called()


if __name__ == '__main__':
    unittest.main()
