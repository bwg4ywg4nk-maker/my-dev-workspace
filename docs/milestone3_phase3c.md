# Milestone 3C.1 — Semantic composition integration

## Purpose and boundary

3C.1 converts a trusted 3B `PresentationPlan` into an immutable semantic
composition. Every planned placement has exactly one content representation.
Every mandatory citation and qualification occurrence has exact associations to
its affected placements on that slide.

Same-slide obligations are represented **semantically** here. This does not
satisfy visible presentation requirements. Citation blocks are neither visible
markers nor bibliographic entries. Qualification blocks do not establish visible
qualification text. Actual visual representation, geometry, typography, fit,
legibility, and visibility belong to 3C.2 or later work. Chart semantics also
remain outside this milestone.

The existing M1/M2 pipelines are unchanged. M1 composition remains fixture-specific
and renderer-ready; 3C.1 is an earlier generalized semantic boundary. There is no
adapter to the M1 renderer.

## Public API

Import directly from `presentation_agent.composition`; package-root exports are
unchanged. The only public exports are:

- `ContentBlock(placement_index, content_id, content)`
- `CitationBlock(snapshot_id, placement_indices)`
- `QualificationBlock(qualification, placement_indices)`
- `SlideComposition(slide_index, content_blocks, citation_blocks, qualification_blocks)`
- `PresentationComposition(plan, slides)`
- `CompositionLimits(max_slides=1000, max_placements=10000, max_obligation_associations=100000)`
- `compose_presentation(plan, *, limits=CompositionLimits())`

All six records are frozen dataclasses. Collections are exact tuples. Indices are
zero-based local coordinates, not identities. There are no additional public
models, validators, serializers, metadata APIs, persistence APIs, configurations,
certification flags, or renderer interfaces.

## Constructor guarantees

Constructors establish local structural validity only. They reject invalid input;
they never coerce, sort, deduplicate, or repair it.

`ContentBlock` requires an exact nonnegative integer index (excluding booleans),
a complete valid content ID, and a concrete `Claim` or `QuantitySelection` with
the corresponding ID prefix. It does not recompute the member's identity.

`CitationBlock` requires a complete snapshot ID and a nonempty exact tuple of
strictly increasing exact nonnegative placement indices.

`QualificationBlock` requires a concrete `QualificationBinding`, validates its
five locally consumed fields, and requires the same index-tuple structure.
Evidence occurrences require an evidence owner ID and `UNVERIFIED` status;
authored occurrences require a claim owner ID and no verification status. No
owner resolution or propagation reconstruction takes place.

`SlideComposition` requires exact tuples of concrete child records, contiguous
placement indices, unique content IDs, unique snapshot IDs, unique qualification
occurrence keys, and locally resolving associations. Obligations must be in
first-encounter order: first affected placement, then the existing binding's
canonical order for ties (snapshot lexical order; evidence before authored,
then owner ID and qualification index). Citation and qualification orderings are
independent.

`PresentationComposition` requires a concrete plan, an exact tuple of concrete
slides, contiguous slide indices, and aggregate counts within default ceilings.
It does not compare the supplied slides against the plan.

**Direct construction does not establish factory provenance or correspondence.**
A structurally valid manually assembled composition can omit planned content or
contain unrelated semantic representations. No token, flag, or hash distinguishes
factory output. The API relies on the caller's trusted production path.

## Factory guarantees

Supported input is a valid concrete `PresentationPlan` over successful
`bind_content()` output or equivalent trusted producer output.

The factory retains the original plan by identity, preserves the exact slide
sequence (including empty slides), and creates exactly one block for each authored
placement in its original order. Omitted content creates no blocks. Repeated
content across slides creates separate placement records referring to the same
retained semantic member.

Each block retains the original `Claim` or `QuantitySelection` by identity.
Claims retain exact authored whitespace and Unicode through `Claim.text`.
Selections retain their label and quantity IDs without formatting values,
inferring chart/category/series semantics, or traversing quantity graphs.

Citations come exclusively from authoritative `ContentBinding.snapshot_ids`.
Each distinct snapshot gets one block per slide, associated with every affected
placement exactly once. Citation metadata is neither required nor invented.

Qualification grouping uses exactly:

```python
(qualification.origin, qualification.owner_id, qualification.qualification_index)
```

Occurrences sharing a key must agree on all five fields: origin, owner ID,
qualification index, exact text, and verification. Equivalent distinct objects
may group. Conflicting text or verification raises `ValueError`, including
conflicts across slides. Only encountered placed occurrences participate;
obligations belonging solely to omitted content are not inspected. Equal text
under different keys remains separate.

The representative is the original qualification object encountered at the
first affected placement **on that slide**. This deterministic choice confers no
greater evidentiary authority. Associations are ascending placement indices.

The factory performs bounded checks for consumed structure and correspondence.
It does not call `bind_content()`, replay full 3B validation, authenticate
provenance, reread sources, reverify evidence, reconstruct evidence ancestry or
snapshot closure, replay arithmetic, traverse quantity provenance, or infer
semantics. No network, rendering imports, filesystem persistence, timestamps,
random IDs, or input mutation are involved. Failure returns no partial result.
Repeated successful calls on the same supported input produce equal structures.

## Resource policy

Limits accept exact positive integers only, excluding booleans and subclasses.
Caller overrides may only lower the defaults:

| Resource | Default ceiling |
| --- | ---: |
| Slides | 1,000 |
| Placements | 10,000 |
| Obligation associations | 100,000 |

Association cost is:

```text
A = sum(len(binding.snapshot_ids) + len(binding.qualifications)
        for every planned placement)
```

Cross-slide repetition counts again. Grouping shared obligations does not
discount their cost. Omitted content contributes zero. Exactly at a ceiling
succeeds; exceeding it fails. Successful output has exactly `A` associations
across all citation and qualification blocks.

Enforcement order is fixed:

1. Validate limits and shallow input/container types.
2. Check slide/placement counts and consumed bounded member/binding structures.
3. Build bounded member/binding lookups and resolve placements.
4. Count obligation tuple lengths without traversing entries.
5. Fail immediately when the running count exceeds the budget.
6. Only after the complete count succeeds, traverse obligations and allocate
   grouping maps, association collections, consistency maps, and output blocks.

No work proportional to `A` is allocated before count preflight succeeds.
The **100,000-association ceiling is engineering policy, not an empirical
performance guarantee**.

## Validation

Focused suite:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p test_milestone3_phase3c_composition.py -v
```

Full regression suite:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

Tests cover the public contract, strict local constructors, trusted factory
correspondence, identity retention, authored text, quantities, exact associations,
qualification consistency, ordering, omissions, empty slides, limits, preflight,
atomicity, determinism, and forbidden calls/imports. Tampered objects are reserved
for rejection and documented trust-boundary probes, not successful provenance
claims. Python 3.9 compatibility uses the established `ast.parse(...,
feature_version=9)` grammar check; this is not execution on a Python 3.9 runtime.
