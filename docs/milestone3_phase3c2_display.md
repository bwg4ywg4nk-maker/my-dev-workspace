# Milestone 3C.2a: frozen display resolution

## Purpose and handoff

`presentation_agent.display.resolve_display()` converts a trusted 3C.1
`PresentationComposition` into an immutable, complete display payload.

"Visible" in 3C.2a means required audience-facing content, not proof of
rendered visibility.

Success establishes exact text, complete citation fields, qualification status
obligations, source associations, deterministic per-role ordering, and bounded
visible-text expansion. It does not establish geometry, typography, fit,
clipping, legibility, measurement, rendering, or total audience reading order.
Those capabilities belong downstream in 3C.2b.

3C.2b remains deliberately unfrozen until the text-layout capability
contract is selected and tested.

## Public model

The module exports exactly these names; package-root exports are unchanged:

- `BlockKind`: `CONTENT = "content"`, `QUALIFICATION = "qualification"`,
  `CITATION = "citation"`.
- `DisplayStatusLabel`: `UNVERIFIED = "Unverified"`.
- `BlockRef(slide_index, kind, block_index)`.
- `DisplayText(source, text, status_label=None)`.
- `DisplayCitation(source, metadata)`.
- `SlideDisplay(slide_index, content, qualifications, citations)`.
- `DisplayLimits(max_slides=1_000, max_placements=10_000,
  max_obligation_associations=100_000, max_metadata_records=100_000,
  max_text_chars=2_000_000)`.
- `PresentationDisplay(composition, slides)`.
- `resolve_display(composition, *, citation_metadata=(), limits=DisplayLimits())`.

All six data classes are frozen. Collections are exact tuples; children and
enums must be concrete declared types. Indices are exact nonnegative built-in
integers. Boolean and integer-subclass indices are rejected. Strings satisfy
the existing exact-string, nonblank, UTF-8-valid, 100,000-character local text
contract. Validation never normalizes their stored values.

`PresentationDisplay.composition` retains the supplied composition by identity.
Each `BlockRef` indexes its slide and then the appropriate semantic block tuple.
This recovers the exact block, all placement associations, and the retained
plan/bindings/provenance chain without copying provenance into display records.
No generated P/S/Q markers, hashes, owner IDs, or placement IDs enter visible
text. Block references are nonvisible local coordinates.

## Exact display mappings

Every placed `Claim` produces one content `DisplayText` whose text is exactly
`Claim.text` and whose status label is `None`. Whitespace, Unicode, punctuation,
and prose mentioning quantities are preserved. Quantities are never looked up.
Placed `QuantitySelection` raises `ValueError`; omitted selections are not
inspected.

Every semantic qualification block produces one qualification `DisplayText`:

| Origin and verification | Text | Separate status label |
| --- | --- | --- |
| EVIDENCE + UNVERIFIED | Exact `QualificationBinding.text` | `DisplayStatusLabel.UNVERIFIED` |
| AUTHORED + None | Exact `QualificationBinding.text` | None |

The generated label is exactly `Unverified`. Authored text starting with that
word does not create or satisfy a generated status obligation. There is no
"Authored qualification" label. Distinct occurrence keys remain separate even
when their text is identical.

Every semantic citation block produces one same-slide `DisplayCitation`.
Its concrete `SnapshotCitationMetadata` is retained by identity. Its snapshot
identity must match the semantic block. Both `title` and `bibliographic_detail`
are complete, required audience-facing fields, kept separate and exact. No
punctuation synthesis, style normalization, author/year extraction, association
markers, or hash fallback occurs. Distinct snapshots remain separate even when
the two visible fields match. Grouping retains the original block's complete
placement association tuple through the reference.

## Bounded metadata superset

The input must be an exact tuple of concrete `SnapshotCitationMetadata` records.
All supplied records satisfy their existing local shape contract, including
unused records. Unused optional title/detail fields may be absent.

Each required snapshot must have exactly one complete record. Missing,
incomplete, and duplicate required records fail, including identical duplicates.
Valid unused records and duplicate unused snapshot IDs are ignored and not
retained in the display. Metadata input order and changes confined to valid
unused records within limits cannot affect output. Selection uses bounded
identity lookups, without `assess_citations()`, acquisition, or catalog lookup.

## Resource accounting and preflight

All limits are exact positive built-in integers, reject booleans and integer
subclasses, and permit only lower overrides relative to the defaults above.
Equality with a ceiling succeeds; exceeding it fails.

Structural accounting counts composition slides, content placements, every
citation and qualification affected-placement association, and all supplied
metadata records (including unused duplicates). Association accounting is
independent of text accounting.

Visible text cost is Python string length:

```
T = sum(len(item.text) for each content and qualification occurrence)
  + sum(len(item.status_label.value) for each labeled occurrence)
  + sum(len(entry.metadata.title) + len(entry.metadata.bibliographic_detail)
        for each citation occurrence)
```

Repeated occurrences on different slides count again. Equal strings are never
discounted. Grouped obligations count once per slide for text, regardless of
the number of affected placements. IDs, references, other nonvisible metadata,
and unused metadata do not count. Exactly 2,000,000 characters succeeds.

The factory follows these passes:

1. Validate limits and shallow container types.
2. Check slide, placement, metadata-record, and association counts.
3. Validate consumed canonical composition blocks; reject placed selections.
4. Identify required snapshots and validate/select metadata through lookups.
5. Count existing strings and fixed status labels, failing immediately when
   the complete payload cannot fit the text budget.
6. Only after successful preflight, construct display records and return the
   complete result.

There are no concatenated display strings, partial results, or input mutations.

## Constructor and factory boundary

Leaf constructors validate local shapes. `DisplayText` accepts content or
qualification references and forbids content status labels. `DisplayCitation`
requires a citation reference and complete locally valid metadata.

`SlideDisplay` validates exact tuples, concrete children, matching slide indices,
correct role kinds, contiguous block indices starting at zero, and no duplicate
citation snapshot within a slide.

`PresentationDisplay` validates the concrete retained composition and exact
slide tuple, default structural ceilings (including retained composition
association counts), contiguous display slide indices, local child structures,
and default visible-text ceiling. Display obligation and citation entry counts
are also bounded by the corresponding default ceilings. These are local checks;
constructors do not compare display text, coverage, or references against the
retained composition. A manually built local-valid mismatch is not evidence of
factory correspondence.

Only `resolve_display()` establishes exact completeness, source correspondence,
claim and qualification text, status mapping, citation matching, slide/block
ordering, and caller-lowered limits. There are no factory tokens, hashes,
certification flags, persistence, or serialization.

## Trust boundary and determinism

Supported input is successful `compose_presentation()` output or equivalent
trusted producer output. The factory validates consumed local canonical block
structure without replaying correspondence against the plan. It does not bind
content, verify evidence, reconstruct provenance, recompute semantic identities,
traverse quantity graphs, replay arithmetic, reread sources, acquire metadata,
or authenticate bibliographic accuracy.

Composition slide order, each role's block order, and empty slides are preserved.
Each block reference index is exactly the source index within that role's tuple.
Separate content, qualification, and citation tuples establish model ordering
only. No unordered-container iteration determines output order.

Identical supported inputs produce equal structures. There are no timestamps,
randomness, locale-dependent formatting, filesystem writes, network operations,
or rendering imports. Upstream contracts, dependencies, fixtures, and package
exports remain unchanged.

## Validation

Run the focused suite and full regression suite from the repository root:

```
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p test_milestone3_phase3c2_display.py -v
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
git diff --check
```

The focused suite covers mapping, traceability, superset policy, deterministic
ordering, constructor boundaries, default and lowered limits, count/text
preflight before output construction, forbidden operations, input preservation,
and unchanged package-root exports. Python compatibility follows repository
practice: `ast.parse(source, feature_version=9)` for the implementation and test
module. This verifies Python 3.9 grammar, not execution on a Python 3.9 runtime.
