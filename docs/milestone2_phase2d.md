# Milestone 2 Phase 2D.1: temporary Milestone 1 evidence projection

Phase 2D.1 accepts existing normalized verified inputs and an explicit versioned
demo mapping. It returns a legacy Milestone 1 evidence dictionary and immutable
field-level provenance captured at adaptation time. This is a temporary bridge
with a deletion path: remove this module and its bridge-specific tests when the
presentation consumer accepts normalized evidence directly. Normalized modules
have no dependency on the bridge or Milestone 1.

The adapter performs no source capture, extraction, `verify_evidence()`, graph
construction, `add_fact()`, `derive()`, composition, rendering, presentation QA,
content/plan/theme compatibility orchestration, persistence, filesystem or
network I/O, autonomous research, or LLM inference. Importing the module only
defines its types and functions. No dependencies or package exports are added.

## API and fixed profile

```python
from presentation_agent.milestone1_adapter import adapt_milestone1_demo

# All selected nodes already exist in graph. mapping and
# qualitative_verification are concrete contract objects supplied by the caller.
result = adapt_milestone1_demo(
    graph=graph,
    qualitative_verification=qualitative_verification,
    mapping=mapping,
)
legacy_evidence = result.legacy_evidence
provenance = result.provenance
```

The keyword-only API requires concrete `QuantityGraph`, `EvidenceVerification`,
and `Milestone1DemoMapping` types. It does not coerce dictionaries, lists,
strings, booleans-as-integers, subclasses, or duck-typed controllers. Mapping
validation occurs at adaptation time. All mapping fields are required without
defaults; there is no configurable limits object.

`DemoProfile.SYNTHETIC_HANDLING_TIME_V1` has value
`synthetic_handling_time_v1` and is the only supported profile. `synthetic` must
be exactly `True`. Profile units are fixed conventions:

| Role | Required normalized unit |
| --- | --- |
| E1/E2 means and D2 difference | `Unit(UnitKind.NAMED, "minutes_per_case")` |
| E1/E2 sample sizes | `Unit(UnitKind.NAMED, "cases")` |
| S1/S2 supplied totals | `Unit(UnitKind.NAMED, "minutes")` |
| Reduction ratio | `Unit(UnitKind.RATIO)` |

These declarations do not establish source semantics.

## Explicit mapping

`SourcePresentation(snapshot_id, title, detail)` supplies each source's complete
authored presentation text. `Milestone1DemoMapping` contains:

- `profile`, `synthetic`, and `s1`, `s2`, `s3` source presentations.
- `e1_value_id`, `e1_sample_size_id`, `s1_total_id`.
- `e2_value_id`, `e2_sample_size_id`, `s2_total_id`.
- `difference_id`, `reduction_ratio_id`, `e3_evidence_id`.

The six direct quantity IDs must identify distinct graph-owned `DirectQuantity`
nodes at six distinct physical `(snapshot_id, row, column)` cells. They must
also have six distinct evidence identities; E3 supplies a seventh. Equal values
in different roles are allowed. Extra graph nodes are neither selected nor
captured. S1's snapshot must match its mean, sample, and total origins; the same
holds for S2. S3 must match E3's snapshot, and E3's mapped evidence ID must match
the supplied qualitative verification.

No role is inferred from filenames, paths, headers, locators, prose, or numeric
values. The mapping contains no numeric overrides. Titles and S3 detail remain
authored text even when their snapshots match normalized evidence.

S1 and S2 details must equal this exact template after projecting their selected
sample and supplied total:

```text
Invented fixture; {sample_size} cases; total handling time {supplied_total} minutes.
```

The caller supplies the complete string. The adapter compares it with the
expected string and returns the supplied string unchanged. It checks
`mean * sample_size == supplied_total` using integer arithmetic as a compatibility
invariant. It creates no multiplication node; the selected total fact remains
authoritative.

## Exact projections and lineage

`ProjectionContract.DECIMAL_TO_INTEGER_V1` examines the normalized Decimal's
sign, coefficient digits, and exponent. Integer division must leave no remainder.
It emits a Python `int`, without float conversion, rounding, truncation,
quantization, or Decimal-context-dependent arithmetic. Means and totals may use
INTEGER or DECIMAL source syntax; sample sizes must use `NumericType.INTEGER`.

`ProjectionContract.RATIO_TO_PERCENT_INTEGER_V1` applies an exact base-ten
exponent shift of +2 to the existing ratio's components, then requires an exact
integer. `0.25` projects to `25`; `0.125` fails. This is a bridge projection,
recorded in D1's field binding, without a new normalized quantity or identity.
Caller Decimal precision, exponent bounds, rounding, traps, flags, and capitals
are neither inherited nor changed.

The existing difference must be `Operation.SUBTRACT` with ordered inputs
`(e1_value_id, e2_value_id)`. The existing ratio must be `Operation.RATIO` with
ordered inputs `(difference_id, e1_value_id)`. Equal-valued nodes with different
lineage fail. The adapter checks exact integer result consistency but never
constructs or repairs derivations.

All emitted numeric values must be positive integers at most 999999. E1's mean
must exceed E2's positive mean; samples must be equal and positive; both supplied
totals must be positive. These joint constraints make some isolated ceiling
boundaries unreachable in a successful profile. For example, a mean or total of
999999 cannot support a positive reduction below 100 with an exact integer
percentage: 999999 has no common factor with 100. Tests cover the isolated
projection boundary and whole-profile rejection above the ceiling.

`EXACT_TEXT_V1` projects E3's exact record text. E3 requires concrete TEXT record
locator and extraction types, matching snapshot and locator, extraction text
equal to record text, `TextReproduction.EXACT_MATCH`,
`StructuredCells.NOT_APPLICABLE`, and
`QualificationVerification.UNVERIFIED`. CSV prose or authored interpretation
cannot substitute for reproduced E3 support. `AUTHORED_TEXT_V1` identifies the
source titles and whole detail strings.

## Legacy output and immutable provenance

The new mutable dictionary contains precisely `synthetic`, `sources`, `evidence`,
and `calculations`. Sources are S1, S2, S3 with only `id`, `title`, and `detail`.
E1/E2 have `id`, `source_id`, integer `value`, unit `minutes per case`, and integer
`sample_size`. E3 has `id`, `source_id`, and exact reproduced `text`.

Calculations are D1 then D2. Both have input IDs `["E1", "E2"]`. D1 uses
`relative_reduction_percent` and unit `percent`; D2 uses `absolute_difference`
and unit `minutes per case`. Neither qualifications nor bridge metadata are
inserted into legacy records. Every adaptation allocates fresh dictionaries and
lists, including calculation input lists.

All public bridge records are frozen dataclasses. Nested provenance collections
are tuples or frozen values. `Milestone1Provenance` contains:

| Field | Capture |
| --- | --- |
| `bridge_contract` | Exactly `milestone1_evidence_projection_v1` |
| `mapping` | Validated frozen caller mapping |
| `evidence` | Seven `EvidenceCapture` values in direct-role order, then E3 |
| `facts` | Six `FactCapture` values in mapping role order |
| `derivations` | Difference then ratio `DerivedCapture` values |
| `fields` | Exactly 17 `FieldBinding` values in `LegacyField` declaration order |
| `qualifications` | Ordered `QualificationBinding` values by evidence owner and original index |

Evidence captures retain evidence ID, snapshot, frozen locator, exact text,
qualifications, and the three verification statuses. Fact captures retain
quantity/evidence/snapshot IDs, singleton cell, raw text, numeric type, unit,
Decimal value, parser contract, normalizer contract, and unit contract. Derived
captures retain quantity ID, operation, ordered input IDs, unit, Decimal value,
operation version, arithmetic contract, normalizer contract, and unit contract.

The graph controller, verification objects, and extraction objects/rectangles
are not retained as provenance authority. Frozen locators and units may be
shared safely. Captures remain unchanged after supported graph additions.
Mutating legacy dictionaries cannot affect captures, normalized inputs, the
mapping, or another adaptation.

Each field binding contains a target, projected value, projection contract,
origin, and span. Origins distinguish `QuantityOrigin(quantity_id)`,
`ReproducedTextOrigin(evidence_id)`, and
`AuthoredMappingOrigin(mapping_field)`. Authored mapping identifiers are limited
to `s1.title`, `s1.detail`, `s2.title`, `s2.detail`, `s3.title`, and `s3.detail`;
they are fixed identifiers, not executable paths.

Binding order is S1 title/detail/sample substring/total substring, then the same
four S2 fields, S3 title/detail, E1 value/sample, E2 value/sample, E3 text, D1, D2.
Numeric source-detail subfields are spans inside the emitted strings, not extra
legacy keys. Their projected values are exact decimal-digit substrings and
spans are zero-based half-open Python string ranges. Every other span is `None`.
Whole details have authored origins; numeric slots independently reference the
selected sample or total fact.

## Qualifications

Every selected record's qualifications are captured exactly, including whitespace,
Unicode, duplicates, original order/index, and original owner. Empty tuples
remain empty. Status remains `UNVERIFIED`; nothing is deduplicated, truncated,
filtered, or promoted to verified.

`affected_fields` expresses normalized lineage reachability only. A mean's
qualification reaches its evidence value, D1, and D2. A sample's qualification
reaches its evidence sample size and source-detail sample substring. A total's
qualification reaches only its total substring. E3 qualifications reach E3 text.
No qualification scope is invented for authored titles or surrounding detail
prose. This does not claim semantic interpretation of qualification scope.
Visible presentation is deferred to Phase 2D.2.

## Resource ceilings and logical accounting

| Resource | Fixed bound |
| --- | ---: |
| Selected direct facts | Exactly 6 |
| Selected derived nodes | Exactly 2 |
| Distinct selected evidence records | Exactly 7 |
| Source presentations | Exactly 3 |
| Field bindings | Exactly 17 |
| Source title | 256 Unicode code points |
| Source detail | 1024 Unicode code points |
| Captured evidence text per record | 8192 Unicode code points |
| Qualification text per item | 2048 Unicode code points |
| Qualifications per record | 32 |
| Qualifications across selected records | 128 |
| Immutable metadata text | 65536 UTF-8 bytes |
| Positive legacy integer, including detail substrings | 999999 |

Metadata accounting walks the logical `Milestone1Provenance` value. Each string
leaf and string-valued enum contributes its strict UTF-8 byte length at each
occurrence. Frozen dataclass fields and tuple elements are traversed in order.
Field names, container delimiters, numeric scalars (including Decimal values),
booleans, and `None` add no text bytes. IDs, units' textual fields, contracts,
authored origins, qualification bindings' enum fields, and repeated projected
text are included. The mutable legacy dictionary is outside this accounting.
Shared strings count repeatedly, exactly like distinct equal strings. This is
logical text accounting, not object-identity accounting, serialization size, or
an RSS claim.

Per-item and qualification-count ceilings are checked before capture collections
are built. The metadata budget is checked before each capture is appended.
Failure rejects the whole adaptation and never drops qualifications. Fixed
selection counts apply to the mapping/result, not the size of the supplied graph.

## Stable failures and atomicity

Expected contract failures raise `ValueError` with these stable prefixes:

| Prefix | Meaning |
| --- | --- |
| `m1_adapter_invalid_input` | Wrong concrete top-level contract type |
| `m1_adapter_unsupported_profile` | Unsupported profile or profile type |
| `m1_adapter_invalid_mapping` | Invalid mapping fields, identities, uniqueness, or exact detail template |
| `m1_adapter_missing_quantity` | Mapped quantity absent from supplied graph |
| `m1_adapter_invalid_verification` | Invalid evidence structure or CSV verification semantics |
| `m1_adapter_invalid_quantity` | Wrong node kind or numeric syntax declaration |
| `m1_adapter_source_mismatch` | Declared source snapshot differs from selected origin |
| `m1_adapter_unit_mismatch` | Unit differs from fixed profile convention |
| `m1_adapter_derivation_mismatch` | Wrong operation, ordered lineage, or result consistency |
| `m1_adapter_nonintegral_projection` | Nonzero fractional remainder |
| `m1_adapter_profile_invariant` | Nonpositive values or inconsistent profile quantities |
| `m1_adapter_qualitative_support` | E3 lacks exact matching TEXT support |
| `m1_adapter_resource_limit` | Fixed resource ceiling exceeded |

Diagnostics use only fixed roles and bounded reason codes. They omit source
text, raw cells, qualifications, mapping text, extraction representations, and
input-object representations. Translated exceptions suppress chained diagnostic
messages. Failures return no partial result and leave graph nodes, intake state,
accounting, and inputs unchanged. There is no logging, global cache, callback,
background work, or filesystem operation.

## Trust limits and Phase 2D.2 deferrals

The adapter cannot establish:

- Whether a manually fabricated but structurally consistent
  `EvidenceVerification` actually came from `verify_evidence()`.
- Whether selected cells semantically represent their mapped roles.
- Whether declared units accurately describe source meaning.
- Source credibility or claim truth.
- Continued snapshot availability or integrity after prior verification.

It relies on the existing graph's supported append-only API and frozen normalized
contracts. Bypassing frozen dataclasses or modifying graph private state is not
a supported input-construction path. The tests explicitly accept constructor-built
consistent verification objects to demonstrate the verifier trust boundary.

Snapshot sha256, ev1, qf1, and qd1 identities and schemas remain unchanged.
Bridge contracts, profile names, legacy IDs, mapping prose, and percentage
projections do not enter normalized identity payloads. Mapping-only changes leave
all selected normalized captures and identities unchanged.

Phase 2D.2 will address visible qualifications and downstream integration.
Composition, rendering, presentation QA, and content/plan/theme compatibility
orchestration remain deferred. Producing the legacy evidence shape is not a
claim of complete Milestone 1 pipeline compatibility.

## Verification

Tests construct synthetic normalized inputs entirely in memory, without source
capture or extraction. They cover independent expected output, all field bindings,
lineage rejection, exact projections, context isolation, qualification preservation,
resource boundaries, mutation isolation, privacy, and architectural boundaries.
Existing tests and fixtures are unchanged. No compose/render/QA tests are added.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_milestone2_phase2d.py'
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
git diff --check
git status --short
```
