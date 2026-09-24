# Milestone 3B: frozen presentation planning

3B assigns trusted bound content to authored slides and establishes composition
obligations. It does not compose or render slides. Import its API directly from
`presentation_agent.planning`; package-root exports are unchanged.

## Public contract

All four records are frozen concrete dataclasses with exactly these fields:

```python
@dataclass(frozen=True)
class SlidePlan:
    content_ids: Tuple[str, ...]

@dataclass(frozen=True)
class PlanningSpec:
    slides: Tuple[SlidePlan, ...] = ()
    omitted_content_ids: Tuple[str, ...] = ()

@dataclass(frozen=True)
class PresentationPlan:
    bound_content: BoundContent
    specification: PlanningSpec

@dataclass(frozen=True)
class PlanningLimits:
    max_slides: int = 1_000
    max_placements: int = 10_000
```

```python
plan_presentation(
    bound_content: BoundContent,
    specification: PlanningSpec,
    *,
    limits: PlanningLimits = PlanningLimits(),
) -> PresentationPlan

PresentationPlan.bindings_for_slide(
    slide_index: int,
) -> Tuple[ContentBinding, ...]
```

There is no public `validate_plan()`, plan identity, persistence API, or
serialization API. Direct `PresentationPlan` construction also checks validity
and default ceilings. The factory additionally enforces caller-lowered limits.
All containers are exact tuples; validation rejects coercion and subclasses.
Invalid structure, references, coverage, or limits raise `ValueError`.

## Placement and coverage

Let C be bundle member identities, P distinct placed identities, and O explicitly
omitted identities. Require `P | O == C` and `P & O == set()`.

Every reference must resolve to a bundle member. Duplicate identities within a
single slide are prohibited, whether adjacent or separated and whether `cl1` or
`qs1`. Duplicate input fails; it is never silently deduplicated. Repetition on
different slides is allowed, and each occurrence counts toward placements.
Slide order and within-slide order remain exactly authored.

Omission IDs must be unique. Their tuple is sorted lexically only after duplicate
rejection. Unknown omissions, unknown placements, incomplete coverage, and a
placed-and-omitted identity fail. Empty slides are structurally valid. An empty
bundle with an empty specification is valid. A nonempty bundle with zero slides
is valid when every item is explicitly omitted.

Limits accept exact positive integers only, rejecting bool and integer subclasses.
Callers may only lower defaults. Exactly-at-limit succeeds; over-limit fails.
There is no `max_validation_steps`. Slide/placement counts are checked before
content correspondence work. The existing 3A default 10,000 member ceiling is
also enforced before member iteration.

## Reduced trust boundary

3A remains provenance authority. Supported authority is a successful
`bind_content()` result or equivalent trusted producer output. Fabricated or
tampered `BoundContent` is outside the complete provenance-validation guarantee.

3B performs only these content-to-binding correspondence checks:

1. Require concrete `BoundContent`, `ContentBundle`, exact tuple member
   containers, and tuple bindings.
2. Reject bundle member counts above the existing 3A 10,000 ceiling.
3. Require binding count to equal member count before iteration.
4. Require concrete `Claim`, `QuantitySelection`, and `ContentBinding` entries.
5. Compute each member identity once and require unique member identities.
6. Require valid content IDs in bindings and strictly lexical binding order.
7. Require exact equality of binding and bundle member identity sets.

3B does not invoke 3A semantic validators or reconstruct quantity ancestry,
evidence closure, snapshot closure, qualification propagation, retained evidence
or quantity unions, arithmetic, or source verification. Member identity access
uses the existing 3A identity properties. Retained provenance and obligation
fields are not independently revalidated by planning.

## Binding lookup and mandatory obligations

`bindings_for_slide` takes a zero-based exact integer. Non-exact integers,
including bool, raise `ValueError`; negative and out-of-range indices raise
`IndexError`. Lookup returns one original `ContentBinding` object per placement,
in exact within-slide order, or `()` for an empty slide. Repeated content on
different slides can return the same binding object on separate calls.

For every valid placement, that binding is authoritative:

- Every `snapshot_ids` entry is a mandatory same-slide citation composition
  obligation.
- Every `qualifications` occurrence is a mandatory same-slide qualification
  composition obligation, including occurrences with identical text.

3B establishes these obligations. 3C must satisfy them on every slide where the
content occurs. Rendering/QA later verifies artifact preservation, visibility,
fit, and legibility. No citation metadata is copied, and no
`CitationRequirement` or `QualificationRequirement` records are created.

## Determinism, scope, and verification

Planning is deterministic and atomic: success and failure preserve input objects.
The result retains the original bound content and specification. There is no
filesystem or network access, graph traversal, rebinding, arithmetic replay,
source extraction, rendering, or composition. Implementation uses Python 3.9
syntax, the standard library, and existing project modules only.

Run focused tests using the existing environment:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p test_milestone3_phase3b_planning.py -v
```

Run the full regression suite:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

Tests cover the public records, strict containers/types, duplicate rejection,
coverage, omissions, correspondence, ordered binding lookup, repeated obligations,
resource boundaries, determinism, and input preservation. Static import/access
checks and runtime forbidden-call guards protect the reduced boundary. Parsing
with Python's 3.9 grammar checks syntax compatibility; it is not an execution test
on a Python 3.9 interpreter. Tests intentionally do not duplicate 3A ancestry,
closure, or propagation validation.
