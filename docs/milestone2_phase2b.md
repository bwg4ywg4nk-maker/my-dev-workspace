# Milestone 2, Phase 2B: evidence reproduction verification

Phase 2B adds an offline, in-memory dispatcher over Phase 2A extraction. It
does not change evidence records, evidence IDs, or the evidence schema. There
is no persistence, network, LLM, new dependency, Phase 2C work, or Milestone 1
adapter. The implementation uses the standard library and Python 3.9-compatible
syntax and APIs.

## Public API

```python
from presentation_agent.evidence_verification import (
    EvidenceVerification, TextReproduction, StructuredCells,
    QualificationVerification, verify_evidence,
)

result = verify_evidence(store, record)
# Optional keyword-only argument: limits=None.
# For a TextLocator: verify_evidence(store, record, limits=TextLimits(...))
# For a CSVLocator: verify_evidence(store, record, limits=CSVLimits(...))
```

`store` is a `SourceStore`; `record` must be an existing `EvidenceRecord`.
Dispatch uses the concrete locator type, not a filename, media type, or content
sniffing. Omitting `limits` or passing `None` calls the selected extractor without
a limits argument, using its normal Phase 2A defaults. A `TextLocator` accepts
only concrete `TextLimits`; a `CSVLocator` accepts only concrete `CSVLimits`.
The supplied object is forwarded unchanged to that parser. Cross-parser limits
and any other non-`None` limit objects raise `ValueError` before
`SourceStore.read()`. Invalid record types also raise `ValueError` before reading.
Limit value validation remains in Phase 2A.

## Minimal result model

`EvidenceVerification` is a frozen dataclass with exactly five fields:

| Field | Type and meaning |
| --- | --- |
| `record` | The original `EvidenceRecord` object, unchanged, including qualifications and identity. |
| `extraction` | The exact `TextExtraction` or `CSVExtraction` object returned by Phase 2A; never reconstructed. |
| `text_reproduction` | `TextReproduction.EXACT_MATCH`, `.MISMATCH`, or `.NOT_ASSESSED`. |
| `structured_cells` | `StructuredCells.AVAILABLE` for CSV; `.NOT_APPLICABLE` for TEXT. Cells themselves remain solely in `extraction.rows`. |
| `qualification_verification` | Always `QualificationVerification.UNVERIFIED`. |

These statuses are standard `Enum` members with lowercase string values
(`exact_match`, `mismatch`, `not_assessed`, `available`, `not_applicable`,
`unverified`). Callers should compare members explicitly; enum truthiness is
not a verification decision. No aggregate verified, trusted, or confidence flag
exists. There is no serialization or storage API for this result.

Successful return from `verify_evidence()` already establishes that
`SourceStore.read()` and Phase 2A extraction succeeded. A stored integrity or
extraction-success status would duplicate this invariant and is omitted.
Structured cell availability describes access to selected source values, not
support for the prose or factual truth. Source credibility and interpretation
are **NOT ASSESSED BY THIS PHASE**; there are no fields for these out-of-scope
judgments or any current downstream need to store them.

As with the Phase 2A extraction dataclasses, directly constructing a result
does not perform verification. The guarantees here apply to results returned
by `verify_evidence()` using `SourceStore`.

## TEXT behavior

The dispatcher calls `extract_text()` exactly once. It reports `EXACT_MATCH`
if and only if `record.text == extraction.text` using Python string equality;
otherwise it reports `MISMATCH`. A mismatch is a successful comparison result,
not an exception. It is not a judgment about whether the claim is true or false.

All source selection and decoding behavior belongs to Phase 2A: strict UTF-8,
removal of exactly one initial BOM, one-based inclusive physical lines,
preserved internal separators, and exclusion of the final selected line's
terminating separator. Phase 2B does not strip whitespace, change case,
normalize newlines or Unicode, coerce numbers, paraphrase, or interpret content.
Empty selected content can be extracted but cannot match the current schema's
nonblank evidence text. `structured_cells` is `NOT_APPLICABLE`.

## CSV behavior

The dispatcher calls `extract_csv()` exactly once and retains its selected
rectangle of string cells in `extraction.rows`. `structured_cells` is
`AVAILABLE`; `text_reproduction` is always `NOT_ASSESSED`. This holds even when
`record.text` equals one cell, a joined row, or a serialization of the selection.
There is no contract mapping CSV cells to evidence prose, so CSV prose is never
verified. Phase 2B performs no joining, numeric conversion, header inference,
normalization, or duplicated parsing.

## Qualifications and failures

Qualifications are preserved on the original record and always explicitly
`UNVERIFIED`, including an empty tuple, qualifications appearing verbatim in
the source, TEXT matches and mismatches, and CSV results. They are not searched
for, interpreted, or independently checked.

The dispatcher catches no source or extraction exceptions. Missing storage or
snapshots raise `FileNotFoundError`; permission and other OS errors propagate;
corrupt hashes, invalid bounds, malformed CSV, and exceeded limits propagate
as `ValueError`; invalid UTF-8 propagates as `UnicodeDecodeError`. The original
exception is retained, with no failure result or partial result returned.
Whole-snapshot validation and all Phase 1 read protections remain in force.
Failures in unselected content also prevent a successful return.

Verification only reads snapshots through Phase 2A; it never captures sources,
consults the original source file, creates missing storage, writes results, or
changes evidence. Hash verification establishes byte identity at read time,
not continuing integrity or source credibility.

## Validation

The focused tests cover exact TEXT reproduction and non-normalizing mismatches,
CSV cells and non-verification of prose, qualifications, immutable minimal
results, unchanged record/ID/encoding, dispatcher reuse, parser defaults,
parser-specific limit forwarding, rejection of cross-parser and arbitrary
invalid limits before source reads,
source isolation, no writes, missing/corrupt snapshots, and unchanged exception
propagation. Phase 2A's existing parser and resource-boundary tests remain the
authoritative detailed extraction suite.

Run from the repository root with the existing environment:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_milestone2_phase2b.py' -v
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
git diff --check
git status --short
```

Tests use temporary fixtures under ignored repository `.runtime` storage, in
the same manner as Phase 2A. Fixture setup captures snapshots; verification
itself does not persist anything.
