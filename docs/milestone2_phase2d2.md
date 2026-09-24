# Phase 2D.2: fixed offline normalized-evidence demo

Run from the repository with the existing environment:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m presentation_agent.milestone2_demo
```

The optional `--root` selects a trusted repository-shaped root. Sources, mapping,
configuration and destination are fixed; there is no recipe or output-path API.
The final artifact is `output/milestone2_phase2d2/deck.pptx` beneath that root.
Importing the module performs no capture, build, rendering or other I/O.

## Flow and fixed sources

`SourceStore.capture()` captures all three UTF-8, LF-terminated files in
`fixtures/milestone2_phase2d2/` before verification begins. The six CSV records
and one TEXT record pass through real `verify_evidence()`, six real
`QuantityGraph.add_fact()` calls, two `derive()` calls, and the temporary
`adapt_milestone1_demo()` bridge. Existing M1 validation, composition, renderer
and structural QA then produce the six-slide deck.

| Source | Selector | Explicit Python role | Raw value / statement |
| --- | --- | --- | --- |
| pilot_a.csv | CSVLocator(2, 2, 1, 1) | Mean | 12 |
| pilot_a.csv | CSVLocator(2, 2, 2, 2) | Sample size | 30 |
| pilot_a.csv | CSVLocator(2, 2, 3, 3) | Supplied total | 360 |
| pilot_b.csv | CSVLocator(2, 2, 1, 1) | Mean | 9 |
| pilot_b.csv | CSVLocator(2, 2, 2, 2) | Sample size | 30 |
| pilot_b.csv | CSVLocator(2, 2, 3, 3) | Supplied total | 270 |
| protocol.txt | TextLocator(1, 1) | E3 reproduced text | Convenience samples were not randomized; case mix may differ. |

CSV headers are descriptive only. Roles and units are assigned explicitly in
Python. CSV record text is authored role description, not reproduced prose.
All six CSV verifications have `NOT_ASSESSED / AVAILABLE / UNVERIFIED` statuses
for text reproduction, structured cells and qualifications, respectively. Their
qualification tuples are empty. E3 has `EXACT_MATCH / NOT_APPLICABLE / UNVERIFIED`.
The protocol contains only the reproduced E3 statement and its terminating LF.

Means use `NumericType.DECIMAL` and named unit `minutes_per_case`. Sample sizes
use `NumericType.INTEGER` and named unit `cases`. Totals use
`NumericType.DECIMAL` and named unit `minutes`. Totals are supplied source facts;
there is no multiplication or aggregation node. Ordered derivations are
`SUBTRACT(A mean, B mean) = 3`, followed by `RATIO(difference, A mean) = 0.25`.
The adapter projects the ratio to integer 25 percent; there is no normalized
percentage quantity. Existing adapter profile, provenance and resource limits
remain in force, including consistent supplied totals and equal sample sizes.

## Evidence authority and qualification boundary

Adapter output is the exclusive M1 evidence authority. Only `content.json`,
`presentation_plan.json` and `theme.json` are loaded from the M1 fixtures.
Runtime never loads historical `fixtures/evidence.json`, `models.load_inputs()`
or the M1 `build()` wrapper. Both compositions receive the same authoritative
inputs; semantic equality with adapter output is required, not object identity.
Incompatible sources, profile values or stale M1 prose fail without repair or
fallback.

E3 carries the authored metadata tuple `("Quality and cost remain unmeasured.",)`.
This text is absent from the protocol and remains **UNVERIFIED**. The demo reads
it from captured adapter provenance using the normalized E3 owner and original
qualification index 0. The prefix `Unverified qualification: ` is authored
presentation text. Only freshly loaded in-memory C4 text is changed, to:

> Compare minutes per case, sample size, and strength of inference. Unverified qualification: Quality and cost remain unmeasured.

The fixed SL2 / C4 / C4-unmeasured element displays exactly:

> Unverified qualification: Quality and cost remain unmeasured.

A frozen `QualificationContentBinding` records the normalized owner, index 0,
UNVERIFIED status, exact qualification text, content/slide/element IDs and exact
labeled display text. This is a demo placement record, not a normalized schema,
semantic-scope inference or evidence verification. Missing, duplicate, additional,
wrong-owner, wrong-index, wrong-text, unlabeled or misbound qualifications are
rejected before publication. The primary composition is checked before rendering;
the rebuild is checked as well. No qualifications are silently dropped,
truncated, deduplicated, relabeled or relocated. Original content is unchanged.

## Result, retained provenance and publication

`build_demo(root) -> DemoBuildResult` returns a frozen dataclass with exactly:

- `deck_path`: fixed published deck path.
- `snapshots`: three immutable source snapshot descriptors.
- `adaptation`: legacy evidence and captured normalized provenance.
- `qa_report`: the existing structural QA report.
- `qualification_content_bindings`: the single fixed presentation binding.

Adapter provenance retains normalized evidence identities, snapshots, selectors,
authored text and qualifications, verification statuses, direct raw cells,
numeric types and units, derived identities and ordered lineage, projection
contracts and field bindings. These remain in memory. Frozen dataclasses do not
make nested legacy dictionaries or the QA dictionary immutable. Inputs and
composition are transient and are not public result fields. There is no sidecar,
serialized result, persisted provenance or persisted legacy evidence.

After validation and primary composition checks, an ordinary temporary directory
is created below the fixed output directory. The primary deck is rendered there.
A second composition from the same authoritative inputs is rendered separately.
Existing `structural_qa()` receives both paths, and `qa_report['passed']` must be
exactly `True`. Only then does `os.replace()` atomically publish the primary deck.
A failed replacement is a failure, not a partial success result.

Every pre-publication failure preserves an existing final deck byte-for-byte,
or leaves it absent if it did not exist. Temporary build files receive ordinary
temporary-directory cleanup. Captured immutable snapshots remain in
`.runtime/snapshots/` after downstream failure. Atomic publication is promised;
crash-durable storage is not. Repository root is trusted, the destination is
fixed, and hostile concurrent filesystem mutation is outside scope.
Existing ignore rules cover `.runtime/` and `output/`; generated files remain
untracked. Tests use isolated repository-shaped roots and never overwrite a
user's generated deck.

## QA and trust limits

Automated QA checks structural OOXML/native text/chart/workbook properties,
including six slides, chart values, workbook cells, citations, declared geometry,
typography metadata and semantic/rendered rebuild structural equivalence.
Unchanged sources and configuration reproduce normalized identities, adaptation
and provenance, and semantic/structural observations. PPTX ZIP byte identity is
not required.

QA does not establish desktop PowerPoint editing behavior, visual fit, wrapping,
font substitution, chart appearance or communication quality. Those require
human review. Source reproduction does not establish source credibility, claim
truth, role semantics or qualification validity. All sources are synthetic;
there is no real-world effectiveness or causal conclusion.

Explicit non-goals include new schemas, JSON recipes, configurable mappings or
output paths, generalized qualification layout, network, LLMs, OCR, PDF/DOCX
ingestion, inference and new dependencies. M1 core and normalized modules remain
unchanged; normalized modules have no M1 or adapter dependency.

## Deletion and migration

When generalized normalized-evidence planning replaces this temporary bridge,
remove `milestone1_adapter.py`, bridge-specific adapter tests, fixed
`Milestone1DemoMapping` use, `milestone2_demo.py` if no longer useful,
bridge-specific Phase 2D.2 integration assertions, fixed legacy C4/C7
compatibility rules and the legacy evidence handoff. Synthetic source fixtures
may remain for generalized normalized integration tests. Retain Phase 1 evidence
and capture, Phase 2A extraction, Phase 2B verification and Phase 2C quantities
and derivations. No persisted bridge artifacts require migration.
