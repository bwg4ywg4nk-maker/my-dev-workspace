# Milestone 1: synthetic pilot presentation

Milestone 2 Phase 1 adds an independent local evidence contract and immutable
source capture API. See [the Phase 1 contract](docs/milestone2_phase1.md) for
encoding, identity, locator, storage and security rules. It does not change the
Milestone 1 build or extract evidence. The test command below discovers both
milestones' tests; all temporary test files remain inside this repository.

Builds exactly six slides, entirely offline after dependency installation. Every source is invented and prominently labeled synthetic. The deck supports a controlled follow-up decision, not a real-world effectiveness claim.

## Run and verify

Use the approved local virtual environment; no project installation is needed:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m presentation_agent.build
```

`PYTHONPATH=src` makes the local package importable. `PYTHONDONTWRITEBYTECODE=1` avoids generated Python cache files. Tests use the standard library's unittest. The only direct dependency is python-pptx 1.0.2. Rebuilding replaces the four generated deliverables; original fixtures remain unchanged.

## Artifact boundaries

- `fixtures/evidence.json`: three synthetic sources, stable evidence IDs, units, samples, qualification and explicit absolute/relative derivations.
- `fixtures/content.json`: substantive claims, evidence links and semantic chart selection.
- `fixtures/presentation_plan.json`: ordered messages, content selections, layout names and purposes, without coordinates.
- `fixtures/theme.json`: Arial, palette and typography tokens.
- `output/milestone1/composition.json`: resolved JSON geometry, text, chart values and citation relationships.

`validate.py` checks content independently of rendering; `compose.py` uses six fixture-scoped communication strategies; qualifications remain verbatim and quantitative display fragments resolve validated evidence/calculations. Only `pptx_renderer.py` imports and manipulates python-pptx objects. It returns plain observations to `qa.py` after reopening a deck. `models.py` handles JSON input and semantic manifests; `build.py` orchestrates the pipeline. No theme framework, online evidence retrieval or future milestone features are included.

## Deterministic composition grammar

Composition schema version 3 records the principal message, visual intent, information hierarchy, communication strategy, relationships, and resolved geometry. It remains JSON-only and renderer-neutral. The six strategies are deliberately scoped to this fixture:

- `hero_metric`: a single headline, 88-point percentage, adjacent 12 → 9 context, and subordinate decision/sampling qualifications.
- `structured_framework`: a full-width decision above scope and evaluation criteria, with unmeasured quality/cost separated typographically.
- `direct_comparison`: aligned 64-point values, units and sample sizes, with a shared full-width sampling qualification.
- `quantitative_evidence`: native editable chart beside a concise finding and qualification. Zero baseline, unchanged data, light gridlines, restrained axes, and larger value labels.
- `evidence_to_interpretation`: vertically ordered finding, interpretation, and limits, with connecting arrows and a separate sampling qualification.
- `references`: separate source identifiers, titles and details with aligned rows and subtle rules.

16:9, Arial, off-white background, navy text and teal emphasis remain unchanged. Native rectangular rules provide restrained grouping. Text remains editable; no raster assets, shadows, decorative charts or automatic text shrinking are used. Citations are 12-point text, subordinate to the quantitative content. Chart labels are 22 points, axes 14 and title 16. The chart scale starts at zero and ends at at least 15 minutes per case (or 125% of the maximum value), in steps of 3.

Each selected claim retains its original ID, verbatim `source_text`, evidence links and visible markers in a content anchor. Display fragments carry `derived_from_content_id` and the same evidence/source links. The comparison splits validated values, units, sample sizes and source details into separate text elements. The finding displays `3 fewer min/case • 25% lower than A`, derived from D2/D1, while the complete arithmetic wording remains in the content anchor and unchanged input artifacts. Other substantive wording, including all qualifications and epistemic limits, is preserved. Tests assert these contracts, not aesthetic quality.

## Calculation and reproducibility

A: 12 minutes per case, n=30 (synthetic log total: 360 minutes).
B: 9 minutes per case, n=30 (synthetic log total: 270 minutes).
Relative reduction: `(12 - 9) / 12 * 100 = 25%`; absolute difference: 3 minutes per case. Both stored derivations (D1 relative percent and D2 absolute minutes per case) are recomputed and incorrect results are rejected. Fixture-scoped validation compares quantitative claims, sample prose, the percentage headline and source totals with structured evidence. A 16/12 mutation with stale 12/9/3-minute prose is rejected, even after correcting D2 to 4. Values must be finite, positive with A greater than B, in minutes per case; this fixture requires equal positive integer sample sizes. No uncertainty or causal estimate is calculated.

Semantic equivalence compares canonical validated inputs and composition, preserving all source/content relationships, calculation values, slide order, layouts, typography and geometry. QA also renders a second deck and compares reopened text, chart data and geometry. ZIP timestamps and other packaging details are not compared; byte-identical PPTX files are not required.

## QA boundaries

A. Automated structural correctness: tests and `structural_qa.json`.
B. Rendering correctness: pending human inspection in Microsoft PowerPoint for macOS, the authoritative renderer.
C. Communication/design review: pending human inspection.

Structural checks cannot establish text fit, line wrapping, font availability/substitution, actual chart appearance or communication quality. The validator handles this fixed Milestone 1 schema; quantitative wording uses explicit consistency rules, not a general narrative fact-checker. New quantitative narratives require a corresponding fixture-scoped rule. Arbitrary natural-language semantics, including spelled-out numerical claims, are outside this validator. No macOS rendering or visual acceptance is claimed. See `reviews/milestone1_review.md` for the checklist.

## Selection, provenance and verification contracts

Each plan's `content_ids` selects and orders content anchors within the fixed layout capacity; recognized fixture roles determine their communication positions; overflow and duplicates are rejected. `chart_id`, `metric_id` and reference-slide `source_ids` explicitly select the remaining substantive elements. Metrics resolve a stable calculation ID, never list position. Chart categories and values follow the selected chart's ordered evidence IDs.

Composition retains `evidence_ids` and resolved `source_ids` on substantive claims, headlines, metrics, metric labels and charts. Visible markers use a separate `visible_citation_ids` field; reference entries use `reference_source_id`. The semantic manifest includes all validated inputs, so calculation-to-input-to-source chains remain traceable. Structural QA reports evidence/source relationships, exact visible markers (including missing/extra/duplicate detection) and reference entries separately.

Reproducibility tests compare repeated approved input builds. Correctness tests separately assert literal fixture values (12/9, minutes per case, n=30 each, difference 3, reduction 25%), chart categories/title/series/units/type/zero baseline, and workbook cells. QA reads workbook OOXML independently of chart cached values; a test changes only workbook B2 to 16 and requires rejection while the cached values remain 12/9. Mutation tests cover semantic drift, plan selections/order, stale quantitative prose and provenance.

PPTX author/last-modified-by are normalized to `Presentation Agent`. Package byte determinism is not a goal. Generated `output/`, virtual environments, caches and common build/temporary files are ignored by the root `.gitignore`; generated deliverables remain on disk. Build and tests use only repository code and existing local tooling, with temporary render artifacts contained under `output/milestone1/`.
