# Milestone 1 review

## A. Structural correctness — automated

Correction verification: 29 unittest tests passed; all 12 structural QA checks passed.

Independent correctness assertions cover evidence 12/9 minutes per case, n=30 each, absolute difference 3, relative reduction 25%, categories, series name, title, displayed units, clustered column type and zero baseline. Mutation tests reject inconsistent 16/12 evidence with stale prose, stale totals/headlines, missing provenance, missing/extra/duplicate markers, changed semantic text, and a workbook-only value change. Plan selection/order is tested across all five content layouts, with chart, metric and reference selection tests. Reproducibility is checked separately through semantic and reopened render comparisons.

Read-only architecture review after corrections:

- Renderer boundary: only `pptx_renderer.py` imports or manipulates python-pptx; QA receives plain observations.
- Plan authority: composition loops over ordered content IDs and resolves chart, metric and reference IDs. Fixed layout capacities are validated.
- Quantities: chart and hero values derive from structured evidence/calculations; stored quantitative prose and source totals must match explicit fixture-scoped rules. This deliberately implements rejection option B for stale prose.
- Provenance: quantitative headlines, hero value/label and takeaway retain evidence/source links; visible markers and reference entries have separate fields and QA maps. The manifest preserves derivation inputs.
- Git hygiene: `.gitignore` excludes output, virtual environment and caches; outputs remain reproducible and present. No staging or commit was performed.
- Reproducibility versus correctness: repeated-build comparisons do not substitute for independent literal expectations and corruption tests.
- No repository code depends on external scaffolding. The external stale scaffolding file was left untouched.

Reproduce with the two commands in README.md. Machine-readable results: `output/milestone1/structural_qa.json`. Corrections are ready for human PowerPoint acceptance review; automated checks do not grant visual acceptance. The schema and prose rules remain intentionally fixture-scoped and are not a general narrative validation engine.

## Visual composition correction

Human inspection of the preceding deck found correct rendering and strong information structure, but communication/design QA was not accepted: the slides looked programmatically assembled. This revision changes only the deterministic composition and its native rendering support. Evidence, content, plan and theme fixtures are unchanged.

The composer now records six communication strategies, content hierarchy, and explicit relationships. Hero headline duplication is removed; the percentage and 12 → 9 context receive stronger scale. Decision, scope and criteria have distinct positions. Direct comparison emphasizes the values and shared qualification. The native chart retains its data and zero baseline with lighter axes/gridlines. Finding, interpretation and limits follow a vertical sequence. Reference identifiers, titles and details have separate typography. Complete quantitative wording remains in source artifacts and composition anchors; concise displays resolve validated calculations.

All 29 tests and 12 structural checks pass, including unchanged corruption/provenance checks and new composition-contract assertions. Structural QA also verifies native rule geometry/color and text boldness. These results do not establish text fit, rendering quality or design acceptance.

## B. Revised deck rendering correctness — PENDING human review

Authoritative application: Microsoft PowerPoint for macOS.
Reviewer: pending. PowerPoint version: pending. Review date: pending.

- [ ] Open deck.pptx without repair warnings.
- [ ] Check all six slides in editing mode and slideshow for clipping, unintended overlap and wrapping.
- [ ] Confirm Arial is present and no font substitution occurs.
- [ ] Inspect chart rendering, axis labels, data labels and source markers on slide 4.
- [ ] Use Chart Design → Edit Data to confirm editable categories Approach A/B and values 12/9.
- [ ] Select and edit a text box to confirm native text editing.
- [ ] Check citation readability and reference resolution on slide 6.

## C. Communication/design review — PENDING human review

- [ ] Check hierarchy, information density, alignment, spacing, typography and consistency across slides.
- [ ] Slide 1: one principal message without duplication; 25% is a major focal point, followed by 12 → 9 and a visible non-rollout qualification.
- [ ] Slide 2: decision, scope and criteria form a clear framework; unmeasured quality/cost are distinct.
- [ ] Slide 3: both approaches use common units and sample sizes with visible source relationships.
- [ ] Slide 4: chart is readable, zero-based, clearly labeled in minutes per case; qualification remains visible.
- [ ] Slide 5: finding → interpretation → limits form a clear sequence; sampling qualification remains visible.
- [ ] Slide 6: every cited source resolves to a readable synthetic reference.
- [ ] Each visual treatment supports its principal slide message.
- [ ] Synthetic labeling and non-randomized sampling limitation are unmistakable.

Human acceptance status: preceding deck NOT ACCEPTED for communication/design; revised deck PENDING another human PowerPoint review. Record issues and requested adjustments here after inspection.
