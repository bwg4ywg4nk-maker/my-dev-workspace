# Milestone 2, Phase 2A: deterministic snapshot extraction

Phase 2A adds `source_extraction.py`, using only the Python standard library.
It reads verified immutable snapshot bytes through `SourceStore.read()` and
returns exact source content with its snapshot ID and original locator.
The existing evidence schema, identities and Phase 1 contract are unchanged.
No evidence-text support verification (Phase 2B), prose conversion, quantitative
normalization, derivation, conflict resolution, Milestone 1 adapter, presentation
planning/rendering, LLM, network, web, PDF, DOCX or OCR processing is included.

## API

```python
from presentation_agent.evidence import TextLocator, CSVLocator
from presentation_agent.source_capture import SourceStore
from presentation_agent.source_extraction import (
    extract_text, extract_csv, TextLimits, CSVLimits,
)

store = SourceStore(repository_root)
text_snapshot = store.capture("notes.txt")
text_result = extract_text(store, text_snapshot.snapshot_id, TextLocator(1, 3))
# text_result.text is the exact selected string.

csv_snapshot = store.capture("measurements.csv")
csv_result = extract_csv(store, csv_snapshot.snapshot_id, CSVLocator(2, 4, 1, 2))
# csv_result.rows is a tuple of row tuples containing strings.
```

`TextExtraction` and `CSVExtraction` are frozen dataclasses. Returned contents
are immutable strings or nested tuples; both results retain `snapshot_id` and
`locator`. The API takes the existing frozen locators, whose coordinates are
strict positive integers, one-based and inclusive. Booleans, reversed ranges,
wrong locator types and bounds outside actual content fail. Callers select the
parser explicitly: snapshot identities represent bytes, not a persisted media
type, and identical bytes captured from TXT and CSV share the same identity.

Both parsers use strict UTF-8 decoding and remove exactly one optional initial
UTF-8 BOM. Subsequent U+FEFF characters remain content. Neither parser trims
whitespace, normalizes Unicode or normalizes newlines. The entire decoded
snapshot is parsed before a successful result is returned, including unselected
content. Parsing may stop on the first error; it does not collect all errors.

## TEXT

Only CRLF, LF and CR separate physical lines. CRLF counts as one separator.
Other Unicode separators, vertical tabs, form feeds and NUL remain content.
A terminal separator creates no extra line. Empty and BOM-only inputs have zero
lines. A file consisting of one separator has one empty line.

The selected string preserves original separators between selected lines and
excludes the separator terminating the last selected line. For example,
`b"a\r\nb\nc\r"` selected at lines 1–2 returns `"a\r\nb"`; selecting
line 3 returns `"c"`. Selecting nonexistent line 4 fails. Line limits count
content code points only, excluding physical separators.

## CSV

The explicit state machine has four states:

| State | Meaning and transitions |
| --- | --- |
| START | Field start: quote opens QUOTED; ordinary content enters BARE. |
| BARE | Ordinary unquoted content; any quote is malformed. |
| QUOTED | Every character, including comma/CR/LF, is field content; quote enters CLOSED. |
| CLOSED | Another quote contributes one literal quote and returns to QUOTED; only comma, record separator or EOF may otherwise follow. |

Outside quotes, comma completes a field and CRLF/LF/CR completes a logical row.
CRLF is one record separator. EOF in QUOTED is malformed. A terminal record
separator creates no additional row. A blank logical row has zero fields;
commas and quoted empty fields explicitly create empty strings. In particular:

| Input | Parsed rows |
| --- | --- |
| empty | `()` |
| `"\n"` | `((),)` |
| `'""'` | `(("",),)` |
| `","` | `(("", ""),)` |
| `"a\n"` | `(("a",),)` |
| `"a\n\n"` | `(("a",), ())` |

There is no sniffing, escape character, header treatment, numeric conversion or
padding. Separators inside quotes remain exact decoded field content. Doubled
quotes produce one literal quote. Ragged rows are valid, but every selected row
must contain every requested column. A zero-field blank row cannot be part of
a valid nonempty rectangle. Rows before and after the selection must also be
well formed and satisfy parser limits. The parser retains one bounded row at a
time; extraction retains only selected cells beyond that row.

## Resource limits and units

A code point means one element of a decoded Python `str`, not one UTF-8 byte or
one displayed grapheme. Combining marks count separately. Inside a CSV field,
CRLF counts as two code points, doubled quotes as one, and quote delimiters as
zero. The optional removed initial BOM counts as zero decoded content.

| Limit | Ceiling | Configuration |
| --- | ---: | --- |
| Raw snapshot bytes | 8 MiB = 8,388,608 bytes | `SourceStore(max_source_bytes=...)` |
| Physical text lines | 100,000 | `TextLimits.max_lines` |
| Code points per physical text line | 100,000 | `TextLimits.max_line_codepoints` |
| Logical CSV rows (including blank rows) | 100,000 | `CSVLimits.max_rows` |
| Fields per CSV row | 1,000 | `CSVLimits.max_fields_per_row` |
| Total CSV fields scanned | 1,000,000 | `CSVLimits.max_total_fields` |
| Decoded code points per CSV field | 100,000 | `CSVLimits.max_field_codepoints` |
| Selected CSV cells (rectangle area) | 10,000 | `CSVLimits.max_selected_cells` |
| Total decoded code points in selected cells | 1,000,000 | `CSVLimits.max_selected_codepoints` |

Limits default to these ceilings. Callers may supply lower positive integer
limits via the optional `limits` argument; zero, booleans, non-integers and
values above a ceiling fail. Unselected lines, rows and fields are counted and
checked during parsing. Selected-cell limits apply only to the selected
rectangle. Raw bytes are bounded and hash-verified before decoding. The decoded
snapshot is held in memory; this is bounded parsing, not streaming file I/O.

## Storage, failures and validation

Capture may create `.runtime/snapshots`; read never creates either directory.
Missing directories or objects raise `FileNotFoundError`, preserving missing
storage. Descriptor-relative opens, no-follow protections, regular-file checks,
byte limits and SHA-256 verification remain in force. Original source files are
never consulted during extraction. Store protections and their same-user trust
limitations remain those documented in Phase 1.

Malformed UTF-8 raises `UnicodeDecodeError` (a `ValueError` subclass). Invalid
CSV, limits and source bounds raise `ValueError`. OS errors propagate. Extraction
failures do not publish partial results or modify snapshots.

Run the complete suite with the existing approved environment:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
git diff --check
```

The Phase 2A tests use independent literal semantic expectations, malformed
input and failure paths, and exact limit/limit+1 cases at both lowered limits and
the actual ceilings. Test artifacts stay in ignored repository runtime storage.
The existing Milestone 1 tests still use their already-installed dependency;
Phase 2A itself has no third-party or Milestone 1 dependency.
