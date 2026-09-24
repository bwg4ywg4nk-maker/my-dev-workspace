# Milestone 3A: Content and provenance binding

This implementation adds the approved content records, deterministic structural
binding, qualification propagation, and separate citation assessment. It does not
change the evidence, verification, quantity, Milestone 1, adapter, composer,
renderer, or QA contracts. There are no new dependencies or package-root exports.

## Public API

`presentation_agent.content` provides:

- `ContentLimits(max_items=10_000, max_references=10_000, max_binding_steps=100_000)`
- `Claim(text, evidence_ids=(), quantity_ids=(), qualifications=())`
- `QuantitySelection(label, quantity_ids)`
- `ContentBundle(claims=(), quantity_selections=())`
- `SnapshotCitationMetadata(snapshot_id, title=None, bibliographic_detail=None)`
- `QualificationOrigin.EVIDENCE` and `QualificationOrigin.AUTHORED`

`presentation_agent.content_binding` provides:

- `QualificationBinding(owner_id, qualification_index, text, origin, verification)`
- `ContentBinding(content_id, evidence_ids, quantity_ids, snapshot_ids, qualifications)`
- `BoundContent(bundle, bindings, evidence, quantities)`
- `CitationAssessment(referenced_snapshot_ids, metadata, missing_snapshot_ids, incomplete_snapshot_ids, unused_snapshot_ids)`
- `bind_content(bundle, *, evidence=(), quantities=None, limits=ContentLimits())`
- `assess_citations(bound, metadata=(), *, limits=ContentLimits())`

All records are frozen dataclasses with Python 3.9-compatible annotations.
Validation requires concrete types and tuple containers; it does not coerce inputs.
Limits accept positive exact integers, reject booleans, and may only be lowered.
Invalid inputs and missing references raise `ValueError`.

## Content identities

Claims require at least one evidence or quantity reference. Selections require at
least one quantity reference. References must have their complete prefix followed
by 64 lowercase hexadecimal characters. Duplicate references fail before sorting.
Accepted references are stored lexically. Authored qualification order and repeated
text are preserved.

`Claim.identity_payload()` has exactly `schema_version`, `text`, `evidence_ids`,
`quantity_ids`, and `qualifications`. `QuantitySelection.identity_payload()` has
exactly `schema_version`, `label`, and `quantity_ids`. Both use schema version 1
and lists for tuple values in the identity payload.

The unchanged `evidence.canonical_bytes()` encodes these payloads. The identity
preimages are:

```python
b"presentation-agent:claim:v1\0" + canonical_bytes(claim.identity_payload())
b"presentation-agent:quantity-selection:v1\0" + canonical_bytes(selection.identity_payload())
```

The terminal NUL is part of each domain. SHA-256 hexadecimal digests receive the
`cl1:` and `qs1:` prefixes, respectively. Text is preserved exactly, including
whitespace and Unicode representation. Existing evidence text and canonical
encoding ceilings apply; no content-specific text ceilings are introduced.

A bundle is a semantic pool. Claims and selections are separately sorted by
computed identity, and duplicate identities fail. Tuple position does not express
narrative order. Empty bundles are valid.

Citation metadata, binding output, verification status, and future planner roles
do not contribute to content identity. There is no bundle or citation identity.
The identity payload methods are not a persistence or interchange contract. No
codec, loader, JSON schema, or `to_dict`/`from_dict` API is provided.

## Structural binding

Binding first validates the arguments and limits, then indexes every explicit
`EvidenceRecord` by its computed identity. Duplicate explicit identities fail,
even when their records are equal or unused.

Members are processed in lexical content-ID order. Direct evidence references
are examined lexically, followed by direct quantity references. Quantity roots
and ancestors are resolved only through the supplied concrete `QuantityGraph`'s
public `get()` method. Standalone nodes, tuples of nodes, and replacement graph
authorities are not accepted.

Traversal is depth-first. Derived operands are visited in their stored order,
and each quantity identity is expanded at most once per member. Returned nodes
must have the expected concrete type and requested computed identity. Original
direct and derived node objects are retained. Binding neither reconstructs
quantities nor replays arithmetic.

The evidence-resolution pool combines explicit records with records retained by
quantities reachable from any member. After this pool is complete, direct claim
references resolve against it. A claim can therefore reference evidence retained
by another member's selected quantity. It receives that evidence and its
qualifications, without inheriting the other member's quantity ancestry.

Each member binds only its direct evidence and the evidence reached through its
own quantity ancestry. Equal evidence records merge by identity. Different
records sharing an identity fail, including explicit-versus-retained conflicts.
Unrelated graph nodes are never scanned. Unused explicit evidence is excluded
from the result.

The result contains bindings sorted by content ID, actually bound evidence sorted
by evidence ID, and reachable nodes sorted by quantity ID. Per-member evidence,
quantity, and snapshot IDs are unique lexical tuples. No graph controller is
retained. All work is local to the call; a result is returned only after every
check succeeds. Inputs are not mutated on success or failure.

## Qualifications

Evidence qualifications retain their evidence owner ID, original occurrence
index, exact text, `EVIDENCE` origin, and the existing
`QualificationVerification.UNVERIFIED` status. Claim-authored qualifications
retain the claim ID, original index, exact text, `AUTHORED` origin, and `None`
verification.

Every bound evidence record contributes every qualification to the member.
Selecting one quantity carries all qualifications on its owning record; no
narrower scope is inferred. Repeated provenance paths deduplicate only the same
`(owner_ev1, qualification_index)` occurrence. Identical text under different
owners or indices remains distinct. Repeated authored text remains distinct.

The ordering key is exactly:

```python
(0 if origin is QualificationOrigin.EVIDENCE else 1,
 owner_id,
 qualification_index)
```

Evidence qualifications precede authored qualifications. No status is promoted.

## Citation assessment

Binding does not require citation metadata. `assess_citations()` separately
validates all supplied metadata, including unused entries, and rejects duplicate
snapshot IDs. Optional title and bibliographic detail fields may be `None`.
Supplied strings must be exact nonblank strings; empty placeholders are invalid.

Referenced snapshots are the union of binding snapshot IDs. The assessment
retains supplied metadata sorted by snapshot ID and reports lexical unique tuples:

- Missing: referenced snapshots without metadata.
- Incomplete: referenced snapshots whose title or bibliographic detail is `None`.
- Unused: supplied metadata for snapshots absent from the bindings.

`is_complete` is true exactly when missing and incomplete tuples are both empty.
Unused incomplete metadata does not affect completeness. An empty bound result
is complete, including when valid unused metadata is supplied.

Completeness establishes field presence only. It does not establish bibliographic
accuracy or upgrade evidence or claim verification.

## Resource accounting

Content item accounting is `len(claims) + len(quantity_selections)`. Reference
accounting sums direct evidence and quantity occurrences across claims and direct
quantity occurrences across selections, before cross-member deduplication.

Each binding step is charged before its action. Exactly-at-limit succeeds; the
next step fails. The successful total is:

```text
number of explicit evidence records
+ sum for each member:
    1
    + direct reference occurrences
    + distinct reachable quantity identities
    + ordered derivation operand positions
    + distinct bound evidence identities
    + propagated evidence qualification occurrences
    + authored qualification occurrences
    + distinct bound snapshot associations
```

Both positions count when a derived node uses the same operand twice. Repeated
paths do not re-expand a node or evidence identity for one member. Shared
ancestry is charged separately for each member. Explicit evidence indexing and
later per-member evidence visits are separate charges. Repeated authored text
counts per occurrence. Snapshot associations count once per member and snapshot.

Citation assessment validates every limit field but accounts only for
`len(metadata)` against `max_items`. It introduces no reference or binding-step
charges.

## Trust boundary

Successful binding establishes structural provenance and reference resolution
only. It does not establish claim truth, semantic entailment, source credibility,
interpretation validity, recommendation validity, or numerical correctness of
authored prose. Deliberately false prose and incorrect prose numbers can bind to
valid references. Tests explicitly preserve this boundary.

Binding performs no source reread, extraction, verification operation, network
access, semantic inference, rendering, or arithmetic replay. Tests guard these
boundaries and restrict implementation imports to the approved integration
modules and Python standard library.

## Validation

Run the focused contract tests:

```bash
PYTHONPATH=src .venv/bin/python -m unittest \
  tests.test_milestone3_phase3a_content \
  tests.test_milestone3_phase3a_binding -v
```

Then run regression and workspace checks:

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
git diff --check
git status --short
```

The focused tests cover strict models, literal independently established identity
digests, canonical preimages, Python 3.9 syntax, binding ancestry and conflicts,
cross-member resolution, qualifications, citations, exact resource budgets,
atomicity, and trust boundaries. Python 3.9 syntax is checked with the AST parser;
the test runtime is the project's existing virtual environment.
