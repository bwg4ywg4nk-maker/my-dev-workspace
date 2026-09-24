# Milestone 2, Phase 2C: exact quantities and derivations

Phase 2C adds an in-memory quantity graph over retained Phase 2B CSV
verification objects. It uses only the standard library and Python 3.9-compatible
syntax and APIs. EvidenceRecord, the normalized evidence schema, ev1 identity,
and all earlier phases remain unchanged.

## Public API and data model

```python
from presentation_agent.evidence import CSVLocator
from presentation_agent.quantities import (
    NumericType, UnitKind, Operation, Unit, DirectQuantity, DerivedQuantity,
    QuantityLimits, QuantityGraph,
)

# verification is an existing EvidenceVerification for a rectangle containing
# absolute logical CSV row 2, columns 3 and 4.
graph = QuantityGraph(limits=QuantityLimits())
left = graph.add_fact(
    verification,
    cell=CSVLocator(2, 2, 3, 3),
    numeric_type=NumericType.DECIMAL,
    unit=Unit(UnitKind.NAMED, "kg"),
)
right = graph.add_fact(
    verification,
    cell=CSVLocator(2, 2, 4, 4),
    numeric_type=NumericType.DECIMAL,
    unit=Unit(UnitKind.NAMED, "kg"),
)
difference = graph.derive(
    Operation.SUBTRACT, left_id=left.quantity_id, right_id=right.quantity_id,
)
assert graph.get(difference.quantity_id) is difference
assert graph.nodes == (left, right, difference)
```

All value records are frozen dataclasses:

| Record | Stored fields |
| --- | --- |
| `Unit` | `kind: UnitKind`, `name: Optional[str] = None` |
| `DirectQuantity` | `verification: EvidenceVerification`, `cell: CSVLocator`, `numeric_type: NumericType`, `unit: Unit`, `value: Decimal` |
| `DerivedQuantity` | `operation: Operation`, `input_ids: Tuple[str, str]`, `unit: Unit`, `value: Decimal` |
| `QuantityLimits` | `max_direct_facts`, `max_derivations`, `max_graph_depth`, `max_provenance_bytes` |

Direct facts expose computed `raw_text`, `snapshot_id`, `evidence_id`, and
`quantity_id` properties. Derived quantities expose computed `quantity_id`.
There are no stored copies of extraction cells, provenance, display labels,
transformation metadata, or arithmetic parameters. Values are canonical Decimal
instances; source spelling remains available through `raw_text`.

`QuantityGraph` is a controller, not a serializable evidence record. Its public
operations are `add_fact`, `derive`, `get`, and the read-only `nodes` property.
`nodes` returns an immutable tuple in insertion order. Existing tuple snapshots
do not change when later nodes are added.

## Direct quantities and trust boundary

Intake requires concrete `EvidenceVerification`, `EvidenceRecord`,
`CSVExtraction`, `CSVLocator`, `NumericType`, and `Unit` types. CSV statuses must
be `NOT_ASSESSED` for text reproduction, `AVAILABLE` for structured cells, and
`UNVERIFIED` for qualifications. Record and extraction snapshot IDs and locators
must match. Retained rows must be rectangular nested tuples of strings and
satisfy Phase 2A's maximum selected-cell, field-length, selected-codepoint, row,
and column bounds. Retained strings must support strict UTF-8 encoding.

The caller selects exactly one absolute logical CSV row and column inside the
retained rectangle. Numeric text comes solely from `CSVExtraction.rows`.
Evidence prose never supplies or overrides the numeric value. The original
verification, record, extraction, qualifications, and selected string object
remain retained. `raw_text` means the exact decoded CSV field, without the CSV
quote delimiters and escaping that Phase 2A already parsed.

Structural checks cannot prove that a manually fabricated verification actually
passed through `verify_evidence()`. Phase 2C performs no source reread and makes
no new credibility, truth, prose-support, or qualification-verification claim.
Use verification objects returned by Phase 2B for its reproduction guarantees.

DirectQuantity construction validates its supplied Decimal against the retained
cell and rejects mismatches. DerivedQuantity construction validates its local
shape, unit, and numeric constraints; without a graph it cannot establish an
arithmetic relationship to its input IDs. Only `graph.derive()` computes and
publishes graph derivations. There is no import API for constructed nodes.

## Numeric and arithmetic contract

`NumericType.INTEGER = "integer"` accepts `[+-]?[0-9]+`.
`NumericType.DECIMAL = "decimal"` accepts `[+-]?[0-9]+(?:\.[0-9]+)?`.
Both grammars match the entire string and use ASCII digits only.

Leading zeros, explicit plus, negative numbers, and integer-shaped DECIMAL
strings are accepted. Whitespace, `.5`, `1.`, scientific notation, grouping,
currency and percent symbols, Unicode digits/minus, NaN, and Infinity fail.
There is no trimming, inference, conversion, scaling, or rounding.

| Numeric constraint | Ceiling or range |
| --- | --- |
| Source numeric string | 1,024 ASCII characters, including sign and decimal point |
| Canonical significant digits | 128 |
| Canonical coefficient exponent | -1024 through +1024 |
| Nonzero adjusted exponent | -1024 through +1024 |
| Arithmetic working precision | 2050 decimal digits |
| Arithmetic context | `Emin=-1024`, `Emax=1025`, `clamp=0` |

Canonical values are `(-1)^sign × coefficient × 10^exponent`. Leading
coefficient zeros are removed. Trailing zeros are removed and transferred into
the exponent. Zero is always `{sign: 0, coefficient: "0", exponent: 0}`.
For nonzero values, adjusted exponent is exponent plus coefficient length minus
one. Canonicalization uses Decimal tuple components and never `normalize()`.
There is no universal fractional-place limit.

Every calculation uses a fresh, explicitly configured local Decimal context.
Caller precision, rounding, exponent limits, flags, and traps are not inherited
or changed. The configured rounding mode is `ROUND_HALF_EVEN`, but any rounding
is rejected: `Inexact`, `Rounded`, `InvalidOperation`, `DivisionByZero`,
`Overflow`, and `Underflow` are trapped. Canonical output ceilings are checked
after successful arithmetic and before publication.

`1 / 8` is exactly `0.125`; `1 / 3` fails. `1 / 10^1000` is accepted as
`1E-1000`. A terminating result can still exceed the precision limit: the
reciprocal of valid input `2^400` requires 280 significant digits and fails.
`2^1000` itself exceeds the input significant-digit ceiling, so a graph cannot
admit that denominator in the first place.

## Units and operations

`UnitKind.NAMED = "named"` requires a case-sensitive ASCII name matching
`[A-Za-z][A-Za-z0-9_]{0,63}`. Names are opaque caller declarations.
`UnitKind.RATIO = "ratio"` requires `name=None` and represents a dimensionless
ratio with no percentage interpretation.

| Operation | Required input units | Result |
| --- | --- | --- |
| `ADD = "add"` | Identical kind and name | Exact left + right, same unit |
| `SUBTRACT = "subtract"` | Identical kind and name | Exact left - right, same unit |
| `RATIO = "ratio"` | Identical kind and name; nonzero right value | Exact left / right, RATIO unit |

Each operation has exactly two ordered operands. RATIO inputs may themselves
have RATIO units. Different named units cannot be combined. There are no
aliases, dimensional analysis, unit conversions, or compound units.

## Identities

Both identities use existing `evidence.canonical_bytes()` unchanged. Digests
are SHA-256 over namespace bytes, one NUL byte, and canonical payload bytes.

| Identity | Namespace | Prefix |
| --- | --- | --- |
| Direct | `presentation-agent:quantity-fact:v1` | `qf1:` |
| Derived | `presentation-agent:quantity-derived:v1` | `qd1:` |

The exact qf1 payload fields are:

```text
schema_version: 1
snapshot_id: retained snapshot identity
evidence_id: retained record's ev1 identity
cell: {kind: "csv", row_start, row_end, column_start, column_end}
raw_text: exact selected decoded CSV field
numeric_type: "integer" or "decimal"
parser_contract: "phase2a-csv-v1+ascii-number-v1"
normalizer_contract: "bounded-decimal-v1"
unit_contract: "quantity-unit-v1"
unit: {kind: "named" or "ratio", name: string or null}
value: {sign: 0 or 1, coefficient: canonical ASCII digits, exponent: integer}
```

The exact qd1 payload fields are:

```text
schema_version: 1
operation: "add", "subtract", or "ratio"
operation_version: 1
input_ids: [left machine ID, right machine ID]
arithmetic_contract: "exact-decimal-v1"
normalizer_contract: "bounded-decimal-v1"
unit_contract: "quantity-unit-v1"
unit: {kind: "named" or "ratio", name: string or null}
value: {sign: 0 or 1, coefficient: canonical ASCII digits, exponent: integer}
```

Input order matters even for ADD; operands are never sorted. The versioned
contracts are fixed module constants, not caller-selectable options. Paths,
timestamps, display labels, titles, presentation formatting, graph position,
limits, and depth are absent. Exact source spelling is included as `raw_text`;
for example, `1` and `+1` have different direct identities despite equal values.

The surrounding extraction rectangle is not a separate qf1 field. However,
unchanged ev1 includes the EvidenceRecord locator, so changing that locator
can change qf1 through `evidence_id`. Phase 2C does not deduplicate physical
source cells across different EvidenceRecords. Within a fixed snapshot/parser
contract, absolute logical row and column identify the selected cell.

Tests pin literal qf1 hashes for a signed decimal and signed zero, and literal
qd1 hashes for all three operations. Expected vectors were calculated
independently of the implementation's identity helpers and are stored as fixed
strings in the tests.

## Graph and resource limits

| Limit | Default and maximum |
| --- | ---: |
| `max_direct_facts` | 256 |
| `max_derivations` | 1024 |
| `max_graph_depth` | 16 |
| `max_provenance_bytes` | 67,108,864 (64 MiB) |

Callers may lower each limit using QuantityLimits. Booleans, non-integers, zero,
negative values, and values above these ceilings fail.

Facts must be added before the first successful derivation. Failed derivations
do not close intake. Derivations reference only existing graph nodes; forward
references, arbitrary DAG loading, imported derived nodes, replacement, and
duplicate machine IDs are not supported. Direct depth is zero. Derived depth
is `1 + max(left depth, right depth)`. Depth 16 is permitted; 17 fails.

Provenance accounting counts strict UTF-8 bytes of evidence text,
qualifications, and all retained extraction-cell strings, including unselected
cells inside the retained rectangle. It uses object identity, not text equality:
shared strings count once, while distinct equal strings count separately.
Shared record and extraction objects are tracked so their contents need not be
recounted. Distinct containers sharing the same string objects do not add bytes
for those shared strings. Derived nodes retain IDs and add no provenance text.

Accounting is incremental. Each incoming record/extraction contributes only
previously uncounted strings. Encoding is performed one string at a time; no
complete verification serialization or text copy is made for accounting.
Pending string identities and the byte delta are checked before graph state is
mutated. Append-only retained nodes keep the counted objects alive, preventing
object-ID reuse during the graph's lifetime. This is a retained-text budget,
not a bound on Python process RSS or all object overhead.

All validation, identity calculation, accounting, arithmetic, and depth/count
checks finish before publication. Rejected operations leave nodes, counts,
depths, intake status, and provenance accounting unchanged.

## Failures

Phase 2C validation/calculation failures raise ValueError. Stable diagnostic
prefixes appear before the first colon; explanatory text after it may vary.

| Prefix | Meaning |
| --- | --- |
| `invalid_numeric_syntax` | Source string does not match the selected grammar |
| `invalid_numeric_type` | NumericType was not supplied |
| `invalid_numeric_value` | Supplied value is not a finite Decimal |
| `numeric_limit_exceeded` | Source length or canonical numeric ceilings exceeded |
| `invalid_unit` | Unit type, kind, or name is invalid |
| `invalid_verification_binding` | Verification semantics, binding, shape, or retained text invalid |
| `invalid_cell` | Cell is not a valid singleton CSVLocator |
| `cell_outside_extraction` | Singleton is outside the retained rectangle |
| `incompatible_units` | Operand units differ |
| `unsupported_unit_operation` | Operation is not an allowed enum member |
| `division_by_zero` | RATIO right operand is zero |
| `non_exact_result` | Decimal arithmetic triggered a trapped condition |
| `result_mismatch` | Direct value differs from source, or derived ratio unit is invalid |
| `invalid_inputs` | Derived record does not have two well-formed ordered IDs |
| `missing_or_forward_input` | Derivation operand is absent from this graph |
| `duplicate_quantity_id` | Machine ID is already present |
| `facts_after_derivation` | Direct intake closed after a successful derivation |
| `invalid_limits` | Limits object or field violates the contract |
| `direct_fact_limit_exceeded` | Direct count ceiling reached |
| `derivation_limit_exceeded` | Derivation count ceiling reached |
| `derivation_depth_exceeded` | Proposed depth exceeds the limit |
| `provenance_limit_exceeded` | Proposed retained UTF-8 text exceeds the budget |

Unknown `get()` IDs raise KeyError. No partial result, NaN sentinel, or error
node is returned.

## Scope and validation

No persistence, loaders, catalogs, source rereads, writes, network access,
LLMs, new dependencies, Milestone 1 coupling, charting, or presentation generation
is added. Percent units, percentage calculations, scaling, conversions,
configurable or rounded arithmetic, multiplication, general division,
aggregation, averages, arbitrary formulas, unit ontologies, TEXT extraction,
and inferred units/types remain deferred.

The focused suite covers strict grammar, canonical boundaries, context
isolation, exact/non-exact arithmetic, units, binding, literal hash vectors,
identity mutation/exclusions, immutable records, graph ordering and atomicity,
depth 16/17, direct count 256/257, derived count 1024/1025, lowered limits,
the actual 64 MiB provenance boundary and one byte over, shared/distinct string
accounting, unchanged ev1, and I/O/dependency isolation. Fixtures are in memory;
existing Phase 2A parser tests remain authoritative for CSV parsing behavior.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_milestone2_phase2c.py' -v
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
git diff --check
git status --short --untracked-files=all
```
