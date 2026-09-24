"""Temporary, in-memory projection of selected normalized evidence into M1.

No verification or semantic role inference occurs here. See milestone2_phase2d.md
for the trust boundary and deterministic logical metadata accounting.
"""
from dataclasses import dataclass, fields, is_dataclass
from decimal import Decimal
from enum import Enum
import re
from typing import Optional, Tuple, Union

from .evidence import CSVLocator, EvidenceRecord, TextLocator
from .evidence_verification import (
    EvidenceVerification, QualificationVerification, StructuredCells, TextReproduction,
)
from .source_extraction import CSVExtraction, TextExtraction
from .quantities import (
    ARITHMETIC_CONTRACT, NORMALIZER_CONTRACT, OPERATION_VERSION, PARSER_CONTRACT,
    UNIT_CONTRACT, DerivedQuantity, DirectQuantity, NumericType, Operation,
    QuantityGraph, Unit, UnitKind,
)


class DemoProfile(Enum):
    SYNTHETIC_HANDLING_TIME_V1 = "synthetic_handling_time_v1"


class ProjectionContract(Enum):
    DECIMAL_TO_INTEGER_V1 = "decimal_to_integer_v1"
    RATIO_TO_PERCENT_INTEGER_V1 = "ratio_to_percent_integer_v1"
    EXACT_TEXT_V1 = "exact_text_v1"
    AUTHORED_TEXT_V1 = "authored_text_v1"


class LegacyField(Enum):
    S1_TITLE = "sources.S1.title"
    S1_DETAIL = "sources.S1.detail"
    S1_DETAIL_SAMPLE_SIZE = "sources.S1.detail.sample_size"
    S1_DETAIL_TOTAL = "sources.S1.detail.total"
    S2_TITLE = "sources.S2.title"
    S2_DETAIL = "sources.S2.detail"
    S2_DETAIL_SAMPLE_SIZE = "sources.S2.detail.sample_size"
    S2_DETAIL_TOTAL = "sources.S2.detail.total"
    S3_TITLE = "sources.S3.title"
    S3_DETAIL = "sources.S3.detail"
    E1_VALUE = "evidence.E1.value"
    E1_SAMPLE_SIZE = "evidence.E1.sample_size"
    E2_VALUE = "evidence.E2.value"
    E2_SAMPLE_SIZE = "evidence.E2.sample_size"
    E3_TEXT = "evidence.E3.text"
    D1_VALUE = "calculations.D1.value"
    D2_VALUE = "calculations.D2.value"


@dataclass(frozen=True)
class SourcePresentation:
    snapshot_id: str
    title: str
    detail: str


@dataclass(frozen=True)
class Milestone1DemoMapping:
    profile: DemoProfile
    synthetic: bool
    s1: SourcePresentation
    s2: SourcePresentation
    s3: SourcePresentation
    e1_value_id: str
    e1_sample_size_id: str
    s1_total_id: str
    e2_value_id: str
    e2_sample_size_id: str
    s2_total_id: str
    difference_id: str
    reduction_ratio_id: str
    e3_evidence_id: str


@dataclass(frozen=True)
class EvidenceCapture:
    evidence_id: str
    snapshot_id: str
    locator: Union[CSVLocator, TextLocator]
    text: str
    qualifications: Tuple[str, ...]
    text_reproduction: TextReproduction
    structured_cells: StructuredCells
    qualification_verification: QualificationVerification


@dataclass(frozen=True)
class FactCapture:
    quantity_id: str
    evidence_id: str
    snapshot_id: str
    cell: CSVLocator
    raw_text: str
    numeric_type: NumericType
    unit: Unit
    value: Decimal
    parser_contract: str
    normalizer_contract: str
    unit_contract: str


@dataclass(frozen=True)
class DerivedCapture:
    quantity_id: str
    operation: Operation
    input_ids: Tuple[str, str]
    unit: Unit
    value: Decimal
    operation_version: int
    arithmetic_contract: str
    normalizer_contract: str
    unit_contract: str


@dataclass(frozen=True)
class QuantityOrigin:
    quantity_id: str


@dataclass(frozen=True)
class ReproducedTextOrigin:
    evidence_id: str


@dataclass(frozen=True)
class AuthoredMappingOrigin:
    mapping_field: str

    def __post_init__(self):
        if type(self.mapping_field) is not str or self.mapping_field not in (
                's1.title', 's1.detail', 's2.title', 's2.detail', 's3.title', 's3.detail'):
            _fail('invalid_mapping', 'authored_origin')


@dataclass(frozen=True)
class FieldBinding:
    target: LegacyField
    projected_value: Union[str, int]
    projection: ProjectionContract
    origin: Union[QuantityOrigin, ReproducedTextOrigin, AuthoredMappingOrigin]
    span: Optional[Tuple[int, int]]


@dataclass(frozen=True)
class QualificationBinding:
    owner_evidence_id: str
    qualification_index: int
    status: QualificationVerification
    affected_fields: Tuple[LegacyField, ...]


@dataclass(frozen=True)
class Milestone1Provenance:
    bridge_contract: str
    mapping: Milestone1DemoMapping
    evidence: Tuple[EvidenceCapture, ...]
    facts: Tuple[FactCapture, ...]
    derivations: Tuple[DerivedCapture, ...]
    fields: Tuple[FieldBinding, ...]
    qualifications: Tuple[QualificationBinding, ...]


@dataclass(frozen=True)
class Milestone1Adaptation:
    legacy_evidence: dict
    provenance: Milestone1Provenance


def _fail(category, reason):
    raise ValueError('m1_adapter_' + category + ': ' + reason) from None


def _text(value, ceiling, role):
    if type(value) is not str:
        _fail('invalid_mapping', role + '_type')
    if len(value) > ceiling:
        _fail('resource_limit', role + '_length')
    try:
        value.encode('utf-8', errors='strict')
    except UnicodeError:
        _fail('invalid_mapping', role + '_encoding')


class _MetadataBudget:
    """Count every logical string/enum-value occurrence; never deduplicate."""
    def __init__(self):
        self.used = 0

    def add(self, value):
        if isinstance(value, Enum):
            self.add(value.value)
        elif type(value) is str:
            self.used += len(value.encode('utf-8', errors='strict'))
            if self.used > 65536:
                _fail('resource_limit', 'metadata_bytes')
        elif is_dataclass(value):
            for field in fields(value):
                self.add(getattr(value, field.name))
        elif type(value) is tuple:
            for item in value:
                self.add(item)


def _integer(value, role, shift=0):
    # Decimal tuple inspection and Python integer arithmetic never use Context.
    if type(value) is not Decimal or not value.is_finite():
        _fail('invalid_quantity', role + '_value')
    sign, digits, exponent = value.as_tuple()
    exponent += shift
    coefficient = 0
    for digit in digits:
        coefficient = coefficient * 10 + digit
    if exponent < 0:
        coefficient, remainder = divmod(coefficient, 10 ** -exponent)
        if remainder:
            _fail('nonintegral_projection', role)
    else:
        coefficient *= 10 ** exponent
    result = -coefficient if sign else coefficient
    if result <= 0:
        _fail('profile_invariant', role + '_positive')
    if result > 999999:
        _fail('resource_limit', role + '_integer')
    return result


def _record(verification, *, qualitative=False):
    if type(verification) is not EvidenceVerification:
        _fail('invalid_verification', 'verification_type')
    record = verification.record
    if type(record) is not EvidenceRecord:
        _fail('invalid_verification', 'record_type')
    if type(record.text) is not str or type(record.qualifications) is not tuple:
        _fail('invalid_verification', 'record_fields')
    if len(record.text) > 8192 or len(record.qualifications) > 32:
        _fail('resource_limit', 'record_size')
    for qualification in record.qualifications:
        if type(qualification) is not str:
            _fail('invalid_verification', 'qualification_type')
        if len(qualification) > 2048:
            _fail('resource_limit', 'qualification_length')
    try:
        record.__post_init__()
        record.locator.__post_init__()
    except (ValueError, TypeError, UnicodeError):
        _fail('invalid_verification', 'record_structure')
    extraction = verification.extraction
    expected = TextExtraction if qualitative else CSVExtraction
    locator_type = TextLocator if qualitative else CSVLocator
    category = 'qualitative_support' if qualitative else 'invalid_verification'
    if (type(extraction) is not expected or type(record.locator) is not locator_type or
            type(extraction.locator) is not locator_type or
            type(extraction.snapshot_id) is not str or
            extraction.snapshot_id != record.snapshot_id or
            extraction.locator != record.locator):
        _fail(category, 'extraction_binding')
    if verification.qualification_verification is not QualificationVerification.UNVERIFIED:
        _fail(category, 'qualification_status')
    if qualitative:
        if (verification.text_reproduction is not TextReproduction.EXACT_MATCH or
                verification.structured_cells is not StructuredCells.NOT_APPLICABLE or
                type(extraction.text) is not str or extraction.text != record.text):
            _fail(category, 'text_support')
    elif (verification.text_reproduction is not TextReproduction.NOT_ASSESSED or
          verification.structured_cells is not StructuredCells.AVAILABLE):
        _fail(category, 'csv_status')
    return record


def adapt_milestone1_demo(
    *, graph: QuantityGraph, qualitative_verification: EvidenceVerification,
    mapping: Milestone1DemoMapping,
) -> Milestone1Adaptation:
    """Project an explicit selection; read no sources and publish no graph nodes."""
    if (type(graph) is not QuantityGraph or type(mapping) is not Milestone1DemoMapping or
            type(qualitative_verification) is not EvidenceVerification):
        _fail('invalid_input', 'contract_type')
    if mapping.profile is not DemoProfile.SYNTHETIC_HANDLING_TIME_V1:
        _fail('unsupported_profile', 'profile')
    if mapping.synthetic is not True:
        _fail('invalid_mapping', 'synthetic')
    presentations = (mapping.s1, mapping.s2, mapping.s3)
    for source in presentations:
        if type(source) is not SourcePresentation:
            _fail('invalid_mapping', 'source_type')
        if (type(source.snapshot_id) is not str or
                not re.fullmatch(r'sha256:[0-9a-f]{64}', source.snapshot_id)):
            _fail('invalid_mapping', 'snapshot_id')
        _text(source.title, 256, 'source_title')
        _text(source.detail, 1024, 'source_detail')
    roles = ('e1_value', 'e1_sample_size', 's1_total',
             'e2_value', 'e2_sample_size', 's2_total',
             'difference', 'reduction_ratio')
    ids = tuple(getattr(mapping, role + '_id') for role in roles)
    for identity in ids + (mapping.e3_evidence_id,):
        if type(identity) is not str or not re.fullmatch(r'(?:qf1|qd1|ev1):[0-9a-f]{64}', identity):
            _fail('invalid_mapping', 'identity')
    if len(set(ids[:6])) != 6:
        _fail('invalid_mapping', 'distinct_facts')
    selected = []
    for role, identity in zip(roles, ids):
        try:
            node = graph.get(identity)
        except KeyError:
            _fail('missing_quantity', role)
        expected = DirectQuantity if len(selected) < 6 else DerivedQuantity
        if type(node) is not expected:
            _fail('invalid_quantity', role + '_type')
        selected.append(node)
    facts = selected[:6]
    difference, ratio = selected[6:]
    records = tuple(_record(fact.verification) for fact in facts) + (
        _record(qualitative_verification, qualitative=True),)
    if len({record.evidence_id for record in records}) != 7:
        _fail('invalid_mapping', 'distinct_evidence')
    if sum(len(record.qualifications) for record in records) > 128:
        _fail('resource_limit', 'qualification_count')
    if len({(fact.snapshot_id, fact.cell.row_start, fact.cell.column_start)
            for fact in facts}) != 6:
        _fail('invalid_mapping', 'distinct_cells')
    if mapping.e3_evidence_id != records[-1].evidence_id:
        _fail('invalid_mapping', 'e3_identity')
    for index, fact in enumerate(facts):
        if fact.snapshot_id != presentations[index // 3].snapshot_id:
            _fail('source_mismatch', roles[index])
    if records[-1].snapshot_id != mapping.s3.snapshot_id:
        _fail('source_mismatch', 'e3')
    if (difference.operation is not Operation.SUBTRACT or
            difference.input_ids != (mapping.e1_value_id, mapping.e2_value_id)):
        _fail('derivation_mismatch', 'difference')
    if (ratio.operation is not Operation.RATIO or
            ratio.input_ids != (mapping.difference_id, mapping.e1_value_id)):
        _fail('derivation_mismatch', 'reduction_ratio')
    mean_unit = Unit(UnitKind.NAMED, 'minutes_per_case')
    sample_unit = Unit(UnitKind.NAMED, 'cases')
    total_unit = Unit(UnitKind.NAMED, 'minutes')
    expected_units = (mean_unit, sample_unit, total_unit) * 2 + (
        mean_unit, Unit(UnitKind.RATIO))
    for role, node, unit in zip(roles, selected, expected_units):
        if type(node.unit) is not Unit or node.unit != unit:
            _fail('unit_mismatch', role)
    for index in (1, 4):
        if facts[index].numeric_type is not NumericType.INTEGER:
            _fail('invalid_quantity', roles[index] + '_syntax')
    for index in (0, 2, 3, 5):
        if type(facts[index].numeric_type) is not NumericType:
            _fail('invalid_quantity', roles[index] + '_syntax')
    values = tuple(_integer(node.value, role, 2 if role == 'reduction_ratio' else 0)
                   for role, node in zip(roles, selected))
    a, n, total_a, b, m, total_b, delta, percent = values
    if not (a > b > 0 and n == m and a * n == total_a and b * m == total_b):
        _fail('profile_invariant', 'source_values')
    if delta != a - b or percent * a != delta * 100:
        _fail('derivation_mismatch', 'result_consistency')
    for source, sample, total in ((mapping.s1, n, total_a), (mapping.s2, m, total_b)):
        if source.detail != f'Invented fixture; {sample} cases; total handling time {total} minutes.':
            _fail('invalid_mapping', 'source_detail_template')

    budget = _MetadataBudget()
    bridge_contract = 'milestone1_evidence_projection_v1'
    budget.add(bridge_contract)
    budget.add(mapping)

    def capture(collection, item):
        budget.add(item)  # Reject before extending any capture collection.
        collection.append(item)

    evidence_captures, fact_captures, derived_captures = [], [], []
    for record, verification in zip(records, tuple(f.verification for f in facts) +
                                     (qualitative_verification,)):
        capture(evidence_captures, EvidenceCapture(
            record.evidence_id, record.snapshot_id, record.locator, record.text,
            record.qualifications, verification.text_reproduction,
            verification.structured_cells, verification.qualification_verification))
    for identity, fact in zip(ids, facts):
        capture(fact_captures, FactCapture(
            identity, fact.evidence_id, fact.snapshot_id, fact.cell, fact.raw_text,
            fact.numeric_type, fact.unit, fact.value, PARSER_CONTRACT,
            NORMALIZER_CONTRACT, UNIT_CONTRACT))
    for identity, node in zip(ids[6:], selected[6:]):
        capture(derived_captures, DerivedCapture(
            identity, node.operation, node.input_ids, node.unit, node.value,
            OPERATION_VERSION, ARITHMETIC_CONTRACT, NORMALIZER_CONTRACT, UNIT_CONTRACT))
    bindings = []

    def bind(target, value, projection, origin, span=None):
        capture(bindings, FieldBinding(target, value, projection, origin, span))

    for index, source in enumerate(presentations, 1):
        for part in ('title', 'detail'):
            bind(LegacyField[f'S{index}_{part.upper()}'], getattr(source, part),
                 ProjectionContract.AUTHORED_TEXT_V1,
                 AuthoredMappingOrigin(f's{index}.{part}'))
        if index < 3:
            sample, total = (n, total_a) if index == 1 else (m, total_b)
            sample_start = len('Invented fixture; ')
            total_start = sample_start + len(str(sample)) + len(' cases; total handling time ')
            for suffix, number, start, identity in (
                ('SAMPLE_SIZE', sample, sample_start, ids[(index - 1) * 3 + 1]),
                ('TOTAL', total, total_start, ids[(index - 1) * 3 + 2]),
            ):
                bind(LegacyField[f'S{index}_DETAIL_{suffix}'], str(number),
                     ProjectionContract.DECIMAL_TO_INTEGER_V1, QuantityOrigin(identity),
                     (start, start + len(str(number))))
    for target, value, identity in (
        (LegacyField.E1_VALUE, a, ids[0]), (LegacyField.E1_SAMPLE_SIZE, n, ids[1]),
        (LegacyField.E2_VALUE, b, ids[3]), (LegacyField.E2_SAMPLE_SIZE, m, ids[4]),
    ):
        bind(target, value, ProjectionContract.DECIMAL_TO_INTEGER_V1, QuantityOrigin(identity))
    bind(LegacyField.E3_TEXT, records[-1].text, ProjectionContract.EXACT_TEXT_V1,
         ReproducedTextOrigin(records[-1].evidence_id))
    bind(LegacyField.D1_VALUE, percent, ProjectionContract.RATIO_TO_PERCENT_INTEGER_V1,
         QuantityOrigin(ids[7]))
    bind(LegacyField.D2_VALUE, delta, ProjectionContract.DECIMAL_TO_INTEGER_V1,
         QuantityOrigin(ids[6]))
    # The required lineage has already been checked, so its reachability is finite.
    owners = {identity: frozenset((record.evidence_id,))
              for identity, record in zip(ids[:6], records[:6])}
    owners[ids[6]] = owners[ids[0]] | owners[ids[3]]
    owners[ids[7]] = owners[ids[6]] | owners[ids[0]]
    qualifications = []
    for record in records:
        affected = tuple(binding.target for binding in bindings if (
            isinstance(binding.origin, QuantityOrigin) and
            record.evidence_id in owners[binding.origin.quantity_id]) or (
            isinstance(binding.origin, ReproducedTextOrigin) and
            binding.origin.evidence_id == record.evidence_id))
        for index in range(len(record.qualifications)):
            capture(qualifications, QualificationBinding(
                record.evidence_id, index, QualificationVerification.UNVERIFIED, affected))
    provenance = Milestone1Provenance(
        bridge_contract, mapping, tuple(evidence_captures), tuple(fact_captures),
        tuple(derived_captures), tuple(bindings), tuple(qualifications))
    legacy = dict(
        synthetic=True,
        sources=[dict(id=f'S{index}', title=source.title, detail=source.detail)
                 for index, source in enumerate(presentations, 1)],
        evidence=[
            dict(id='E1', source_id='S1', value=a, unit='minutes per case', sample_size=n),
            dict(id='E2', source_id='S2', value=b, unit='minutes per case', sample_size=m),
            dict(id='E3', source_id='S3', text=records[-1].text),
        ],
        calculations=[
            dict(id='D1', operation='relative_reduction_percent', input_ids=['E1', 'E2'],
                 value=percent, unit='percent'),
            dict(id='D2', operation='absolute_difference', input_ids=['E1', 'E2'],
                 value=delta, unit='minutes per case'),
        ],
    )
    return Milestone1Adaptation(legacy, provenance)
