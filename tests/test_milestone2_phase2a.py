from dataclasses import FrozenInstanceError, fields
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from presentation_agent.evidence import CSVLocator, TextLocator, snapshot_identity
from presentation_agent.source_capture import SourceStore
from presentation_agent.source_extraction import (
    CSVLimits, TextLimits, _csv_rows, _decode, extract_csv, extract_text,
)


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        runtime = Path(__file__).resolve().parents[1] / ".runtime"
        runtime.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="phase2a-", dir=runtime)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = SourceStore(self.root)

    def capture(self, data):
        (self.root / "source.txt").write_bytes(data)
        return self.store.capture("source.txt")

    def text(self, data, start=1, end=1, limits=TextLimits()):
        snapshot = self.capture(data)
        return extract_text(self.store, snapshot.snapshot_id, TextLocator(start, end), limits).text

    def csv(self, data, locator=CSVLocator(1, 1, 1, 1), limits=CSVLimits()):
        snapshot = self.capture(data)
        return extract_csv(self.store, snapshot.snapshot_id, locator, limits).rows

    def test_text_mixed_separators_and_exact_ranges(self):
        data = b"first\r\n second \n\rfinal\r"
        self.assertEqual(self.text(data, 1, 4), "first\r\n second \n\rfinal")
        self.assertEqual(self.text(data, 2, 3), " second \n")
        self.assertEqual(self.text(data, 3, 3), "")
        self.assertEqual(self.text(data, 4, 4), "final")
        with self.assertRaisesRegex(ValueError, "bounds"):
            self.text(data, 1, 5)

    def test_text_only_physical_separators(self):
        self.assertEqual(self.text("a\v\f\x85\u2028\u2029\x00e\u0301".encode()),
                         "a\v\f\x85\u2028\u2029\x00e\u0301")

    def test_exactly_one_bom_removed(self):
        data = '\ufeff\ufeffa\ufeff'.encode()
        self.assertEqual(self.text(data), '\ufeffa\ufeff')
        self.assertEqual(self.csv(data), (('\ufeffa\ufeff',),))
        self.assertEqual(self.csv('\ufeff"a"'.encode()), (("a",),))
        with self.assertRaisesRegex(ValueError, "field start"):
            self.csv('\ufeff\ufeff"a"'.encode())

    def test_empty_and_bom_only_text_have_no_lines(self):
        for data in (b"", b"\xef\xbb\xbf"):
            with self.subTest(data=data), self.assertRaisesRegex(ValueError, "bounds"):
                self.text(data)

    def test_text_terminal_separator_has_no_extra_line(self):
        for data in (b"\r\n", b"\n", b"\r"):
            with self.subTest(data=data):
                self.assertEqual(self.text(data), "")
                with self.assertRaisesRegex(ValueError, "bounds"):
                    self.text(data, 2, 2)
        self.assertEqual(self.text(b"\n\n", 1, 2), "\n")

    def test_strict_utf8_including_unselected_content(self):
        for bad in (b'\xff', b'\xc0\xaf', b'\xed\xa0\x80', b'\xe2\x82'):
            for method in (self.text, self.csv):
                with self.subTest(bad=bad, method=method), self.assertRaises(UnicodeDecodeError):
                    method(b"valid\n" + bad)

    def test_csv_contractual_distinctions(self):
        # Parser-level assertions are necessary: zero-field rows cannot be
        # selected with the contract's positive, nonempty rectangle locators.
        cases = [(b"", ()), (b"\xef\xbb\xbf", ()), (b"\n", ((),)),
                 (b'""', (("",),)), (b",", (("", ""),)),
                 (b"a\n", (("a",),)), (b"a\n\n", (("a",), ()))]
        for data, expected in cases:
            with self.subTest(data=data):
                self.assertEqual(tuple(_csv_rows(_decode(data), CSVLimits())), expected)

    def test_csv_quotes_multiline_and_exact_rectangle(self):
        data = b'head,head,z\r\n01,"a\r\nb\rc\nd",tail\n02,"say ""hi""",end\r'
        self.assertEqual(self.csv(data, CSVLocator(2, 3, 1, 2)),
                         (("01", "a\r\nb\rc\nd"), ("02", 'say "hi"')))
        self.assertEqual(self.csv(data, CSVLocator(1, 1, 1, 3)), (("head", "head", "z"),))

    def test_csv_no_conversion_or_trimming(self):
        self.assertEqual(self.csv(' 1 ,001,1e3,\\,é,e\u0301,\x00'.encode(), CSVLocator(1, 1, 1, 7)),
                         ((" 1 ", "001", "1e3", "\\", "é", "e\u0301", "\x00"),))

    def test_csv_separators_blank_rows_and_trailing_empty_fields(self):
        for separator in ("\r", "\n", "\r\n"):
            with self.subTest(separator=separator):
                self.assertEqual(tuple(_csv_rows('a,' + separator + separator + ',""' + separator,
                                                CSVLimits())),
                                 (("a", ""), (), ("", "")))
                self.assertEqual(self.csv(('a' + separator + separator + 'z').encode(),
                                          CSVLocator(3, 3, 1, 1)), (("z",),))

    def test_csv_ragged_unselected_rows_are_valid(self):
        self.assertEqual(self.csv(b'x\n\na,b,c\ny,z', CSVLocator(3, 4, 1, 2)),
                         (("a", "b"), ("y", "z")))

    def test_csv_missing_columns_and_rows_fail_without_padding(self):
        for data, locator in [(b'', CSVLocator(1, 1, 1, 1)),
                              (b'\n', CSVLocator(1, 1, 1, 1)),
                              (b'a,b\nx', CSVLocator(1, 2, 1, 2)),
                              (b'a,b\n\nx,y', CSVLocator(1, 3, 1, 2)),
                              (b'a\n', CSVLocator(2, 2, 1, 1)),
                              (b'a', CSVLocator(1, 1, 2, 2))]:
            with self.subTest(data=data), self.assertRaisesRegex(ValueError, 'bounds'):
                self.csv(data, locator)

    def test_csv_malformed_even_after_selected_rectangle(self):
        for bad in (b'a"b', b' "a"', b'"a" ', b'"a"x', b'"a"\\',
                    b'"a', b'"a""', b'"a"\t', b'"a"\x00'):
            for prefix in (b'', b'ok\n'):
                with self.subTest(bad=bad, prefix=prefix), self.assertRaises(ValueError):
                    self.csv(prefix + bad)

    def test_csv_malformed_before_selection_and_after_missing_column(self):
        with self.assertRaisesRegex(ValueError, 'Unterminated'):
            self.csv(b'"bad\ngood', CSVLocator(2, 2, 1, 1))
        with self.assertRaisesRegex(ValueError, 'Unterminated'):
            self.csv(b'\n"bad')

    def test_exact_quote_escaping(self):
        self.assertEqual(self.csv(b'"""",x', CSVLocator(1, 1, 1, 2)), (('"', 'x'),))
        self.assertEqual(self.csv(b'"a,b",x', CSVLocator(1, 1, 1, 2)), (('a,b', 'x'),))

    def test_results_retain_identity_locator_and_are_immutable(self):
        snapshot = self.capture(b'a,b\nc,d')
        for operation, locator, attribute in [(extract_text, TextLocator(1, 2), 'text'),
                                               (extract_csv, CSVLocator(1, 2, 1, 2), 'rows')]:
            result = operation(self.store, snapshot.snapshot_id, locator)
            self.assertEqual(result.snapshot_id, snapshot.snapshot_id)
            self.assertIs(result.locator, locator)
            with self.assertRaises(FrozenInstanceError):
                setattr(result, attribute, 'changed')
            with self.assertRaises(FrozenInstanceError):
                result.locator = None
        self.assertIsInstance(result.rows, tuple)
        self.assertTrue(all(type(row) is tuple for row in result.rows))
        with self.assertRaises(TypeError):
            result.rows[0][0] = 'changed'

    def test_extraction_reads_verified_snapshot_not_original(self):
        snapshot = self.capture(b'original')
        (self.root / 'source.txt').write_bytes(b'changed')
        with patch.object(self.store, 'read', wraps=self.store.read) as read:
            self.assertEqual(extract_text(self.store, snapshot.snapshot_id, TextLocator(1, 1)).text,
                             'original')
            self.assertEqual(extract_csv(self.store, snapshot.snapshot_id, CSVLocator(1, 1, 1, 1)).rows,
                             (('original',),))
            self.assertEqual(read.call_count, 2)
        path = self.root / snapshot.storage_path
        path.chmod(0o600)
        path.write_bytes(b'corrupt')
        for operation, locator in [(extract_text, TextLocator(1, 1)),
                                   (extract_csv, CSVLocator(1, 1, 1, 1))]:
            with self.assertRaisesRegex(ValueError, 'integrity'):
                operation(self.store, snapshot.snapshot_id, locator)

    def test_read_absent_runtime_does_not_create_storage(self):
        with self.assertRaises(FileNotFoundError):
            self.store.read(snapshot_identity(b''))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_read_absent_snapshots_does_not_create_storage(self):
        (self.root / '.runtime').mkdir()
        with self.assertRaises(FileNotFoundError):
            self.store.read(snapshot_identity(b''))
        self.assertEqual(list((self.root / '.runtime').iterdir()), [])

    def test_extraction_missing_storage_does_not_create_it(self):
        for operation, locator in [(extract_text, TextLocator(1, 1)),
                                   (extract_csv, CSVLocator(1, 1, 1, 1))]:
            with self.assertRaises(FileNotFoundError):
                operation(self.store, snapshot_identity(b''), locator)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_read_rejects_symlink_storage_directories(self):
        for component in ('.runtime', '.runtime/snapshots'):
            with tempfile.TemporaryDirectory(dir=self.root) as directory:
                root = Path(directory)
                target = root / 'target'
                target.mkdir()
                link = root / component
                link.parent.mkdir(exist_ok=True)
                link.symlink_to(target, target_is_directory=True)
                with self.assertRaises(OSError):
                    SourceStore(root).read(snapshot_identity(b''))
                self.assertEqual(list(target.iterdir()), [])

    def test_read_errors_propagate(self):
        for error in (PermissionError('denied'), OSError('I/O failure')):
            with patch.object(self.store, 'read', side_effect=error):
                with self.assertRaises(type(error)):
                    extract_text(self.store, snapshot_identity(b''), TextLocator(1, 1))
                with self.assertRaises(type(error)):
                    extract_csv(self.store, snapshot_identity(b''), CSVLocator(1, 1, 1, 1))

    def test_wrong_locator_and_limits_types(self):
        for operation, locator, limits in [(extract_text, CSVLocator(1, 1, 1, 1), TextLimits()),
                                          (extract_csv, TextLocator(1, 1), CSVLimits()),
                                          (extract_text, TextLocator(1, 1), CSVLimits()),
                                          (extract_csv, CSVLocator(1, 1, 1, 1), TextLimits())]:
            with self.assertRaises(ValueError):
                operation(self.store, snapshot_identity(b''), locator, limits)

    def test_coordinate_validation(self):
        for bad in (0, -1, True, 1.0, '1', None, 2**53):
            for position in range(2):
                coordinates = [1, 1]
                coordinates[position] = bad
                with self.assertRaises(ValueError):
                    TextLocator(*coordinates)
            for position in range(4):
                coordinates = [1, 1, 1, 1]
                coordinates[position] = bad
                with self.assertRaises(ValueError):
                    CSVLocator(*coordinates)
        for construct in (lambda: TextLocator(2, 1), lambda: CSVLocator(2, 1, 1, 1),
                          lambda: CSVLocator(1, 1, 2, 1)):
            with self.assertRaises(ValueError):
                construct()

    def test_limits_cannot_exceed_ceilings_or_coerce_types(self):
        for model in (TextLimits, CSVLimits):
            for field in fields(model):
                for bad in (0, -1, True, 1.0, '1', None, field.default + 1):
                    with self.subTest(model=model, field=field.name, bad=bad), self.assertRaises(ValueError):
                        model(**{field.name: bad})
                self.assertEqual(getattr(model(**{field.name: 1}), field.name), 1)
            with self.assertRaises(FrozenInstanceError):
                setattr(model(), fields(model)[0].name, 1)

    def test_text_line_count_boundary(self):
        for limit in (2, 100_000):
            limits = TextLimits(max_lines=limit)
            self.assertEqual(self.text(b'x\n' * limit, limits=limits), 'x')
            with self.assertRaisesRegex(ValueError, 'line limit'):
                self.text(b'x\n' * (limit + 1), limits=limits)

    def test_text_line_codepoint_boundary(self):
        for limit in (2, 100_000):
            limits = TextLimits(max_line_codepoints=limit)
            self.assertEqual(self.text(('é' * limit).encode(), limits=limits), 'é' * limit)
            with self.assertRaisesRegex(ValueError, 'code point'):
                self.text(('ok\n' + 'é' * (limit + 1)).encode(), limits=limits)

    def test_csv_row_boundary(self):
        for limit in (2, 100_000):
            limits = CSVLimits(max_rows=limit)
            self.assertEqual(self.csv(b'x\n' * limit, limits=limits), (('x',),))
            for extra in (b'x', b'\n'):
                with self.assertRaisesRegex(ValueError, 'row limit'):
                    self.csv(b'x\n' * limit + extra, limits=limits)

    def test_csv_fields_per_row_boundary(self):
        for limit in (2, 1_000):
            limits = CSVLimits(max_fields_per_row=limit)
            self.assertEqual(self.csv(b',' * (limit - 1), limits=limits), (('',),))
            with self.assertRaisesRegex(ValueError, 'fields per row'):
                self.csv(b'ok\n' + b',' * limit, limits=limits)

    def test_csv_total_fields_boundary(self):
        for limit, data in [(3, b'x,y,z'), (1_000_000, (b',' * 999 + b'\n') * 1000)]:
            limits = CSVLimits(max_total_fields=limit)
            expected = (('x',),) if limit == 3 else (('',),)
            self.assertEqual(self.csv(data, limits=limits), expected)
            with self.assertRaisesRegex(ValueError, 'total fields'):
                self.csv(data + b'\nx', limits=limits)

    def test_csv_field_codepoint_boundary(self):
        for limit in (2, 100_000):
            limits = CSVLimits(max_field_codepoints=limit)
            self.assertEqual(self.csv(('"' + 'é' * limit + '"').encode(), limits=limits),
                             (('é' * limit,),))
            with self.assertRaisesRegex(ValueError, 'field code point'):
                self.csv(('ok\n"' + 'é' * (limit + 1) + '"').encode(), limits=limits)
        self.assertEqual(self.csv(b'"\r\n"', limits=CSVLimits(max_field_codepoints=2)), (('\r\n',),))
        with self.assertRaisesRegex(ValueError, 'field code point'):
            self.csv(b'"\r\n"', limits=CSVLimits(max_field_codepoints=1))
        self.assertEqual(self.csv(b'""""', limits=CSVLimits(max_field_codepoints=1)), (('"',),))

    def test_csv_selected_cells_boundary(self):
        for limit in (2, 10_000):
            limits = CSVLimits(max_selected_cells=limit)
            data = b'x\n' * (limit + 1)
            self.assertEqual(self.csv(data, CSVLocator(1, limit, 1, 1), limits), (('x',),) * limit)
            with self.assertRaisesRegex(ValueError, 'cell limit'):
                self.csv(data, CSVLocator(1, limit + 1, 1, 1), limits)
        with self.assertRaisesRegex(ValueError, 'cell limit'):
            self.csv(b'a,b\nc,d', CSVLocator(1, 2, 1, 2), CSVLimits(max_selected_cells=3))

    def test_csv_selected_codepoints_boundary(self):
        for limit, width in [(4, 2), (1_000_000, 100_000)]:
            count = limit // width
            data = (('é' * width + ',') * count).encode()
            limits = CSVLimits(max_selected_codepoints=limit)
            self.assertEqual(self.csv(data, CSVLocator(1, 1, 1, count + 1), limits),
                             (('é' * width,) * count + ('',),))
            with self.assertRaisesRegex(ValueError, 'Selected CSV code point'):
                self.csv(data + b'x', CSVLocator(1, 1, 1, count + 1), limits)

    def test_selected_codepoints_exclude_unselected_cells(self):
        self.assertEqual(self.csv(b'long,x\nlong,y', CSVLocator(1, 2, 2, 2),
                                  CSVLimits(max_selected_codepoints=2)), (('x',), ('y',)))

    def test_snapshot_byte_ceiling_boundary(self):
        limit = 8 * 1024 * 1024
        snapshot = self.capture(b'x' * limit)
        self.assertEqual(snapshot.size_bytes, 8_388_608)
        self.assertEqual(len(self.store.read(snapshot.snapshot_id)), 8_388_608)
        with self.assertRaisesRegex(ValueError, 'byte limit'):
            self.capture(b'x' * (limit + 1))
        with self.assertRaisesRegex(ValueError, 'byte limit'):
            SourceStore(self.root, max_source_bytes=limit - 1).read(snapshot.snapshot_id)


if __name__ == '__main__':
    unittest.main()
