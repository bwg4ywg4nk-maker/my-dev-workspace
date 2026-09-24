"""Bounded, exact quantities over retained Phase 2B CSV verification objects.

Structural validation is not proof that a verification was produced by the
verifier. No source is reread, and manually constructed derived records cannot
be imported into a graph.
"""
from dataclasses import dataclass, fields
from decimal import (
    Context, Decimal, DecimalException, DivisionByZero, Inexact,
    InvalidOperation, Overflow, ROUND_HALF_EVEN, Rounded, Underflow, localcontext,
)
from enum import Enum
import hashlib
import re
from typing import Optional, Tuple

from .evidence import CSVLocator, EvidenceRecord, canonical_bytes
from .evidence_verification import (
    EvidenceVerification, QualificationVerification, StructuredCells,
    TextReproduction,
)
from .source_extraction import CSVExtraction, CSVLimits


PARSER_CONTRACT = "phase2a-csv-v1+ascii-number-v1"
NORMALIZER_CONTRACT = "bounded-decimal-v1"
UNIT_CONTRACT = "quantity-unit-v1"
ARITHMETIC_CONTRACT = "exact-decimal-v1"
OPERATION_VERSION = 1
_ID = re.compile(r"(?:qf1|qd1):[0-9a-f]{64}\Z")
_INTEGER = re.compile(r"[+-]?[0-9]+\Z")
_DECIMAL = re.compile(r"[+-]?[0-9]+(?:\.[0-9]+)?\Z")
_UNIT_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}\Z")


class NumericType(Enum):
    INTEGER = "integer"
    DECIMAL = "decimal"


class UnitKind(Enum):
    NAMED = "named"
    RATIO = "ratio"


class Operation(Enum):
    ADD = "add"
    SUBTRACT = "subtract"
    RATIO = "ratio"


@dataclass(frozen=True)
class Unit:
    kind: UnitKind
    name: Optional[str] = None

    def __post_init__(self):
        if type(self.kind) is not UnitKind:
            raise ValueError("invalid_unit: expected UnitKind")
        if self.kind is UnitKind.NAMED:
            if type(self.name) is not str or not _UNIT_NAME.fullmatch(self.name):
                raise ValueError("invalid_unit: named unit requires an ASCII identifier")
        elif self.name is not None:
            raise ValueError("invalid_unit: ratio name must be None")


def _check_unit(unit):
    if type(unit) is not Unit:
        raise ValueError("invalid_unit: expected Unit")
    unit.__post_init__()


def _canonical(value):
    """Canonical components without context-sensitive Decimal operations."""
    if type(value) is not Decimal or not value.is_finite():
        raise ValueError("invalid_numeric_value: expected finite Decimal")
    sign, digits, exponent = value.as_tuple()
    coefficient = ''.join(str(digit) for digit in digits).lstrip('0')
    if not coefficient:
        return dict(sign=0, coefficient="0", exponent=0)
    trimmed = coefficient.rstrip('0')
    exponent += len(coefficient) - len(trimmed)
    if (len(trimmed) > 128 or not -1024 <= exponent <= 1024 or
            not -1024 <= exponent + len(trimmed) - 1 <= 1024):
        raise ValueError("numeric_limit_exceeded: canonical digits or exponent")
    return dict(sign=sign, coefficient=trimmed, exponent=exponent)


def _normalized(value):
    parts = _canonical(value)
    return Decimal((parts['sign'], tuple(map(int, parts['coefficient'])),
                    parts['exponent']))


def _parse(raw, numeric_type):
    if type(numeric_type) is not NumericType:
        raise ValueError("invalid_numeric_type: expected NumericType")
    if type(raw) is not str:
        raise ValueError("invalid_numeric_syntax: expected string")
    if len(raw) > 1024:
        raise ValueError("numeric_limit_exceeded: source exceeds 1024 characters")
    grammar = _INTEGER if numeric_type is NumericType.INTEGER else _DECIMAL
    if not grammar.fullmatch(raw):
        raise ValueError("invalid_numeric_syntax: expected full ASCII number")
    return _normalized(Decimal(raw))


def _bound_raw(verification, cell):
    """Validate retained CSV provenance and return its selected string object."""
    if type(verification) is not EvidenceVerification:
        raise ValueError("invalid_verification_binding: expected EvidenceVerification")
    record, extraction = verification.record, verification.extraction
    if (type(record) is not EvidenceRecord or type(extraction) is not CSVExtraction or
            type(record.locator) is not CSVLocator or
            type(extraction.locator) is not CSVLocator or
            verification.text_reproduction is not TextReproduction.NOT_ASSESSED or
            verification.structured_cells is not StructuredCells.AVAILABLE or
            verification.qualification_verification is not QualificationVerification.UNVERIFIED):
        raise ValueError("invalid_verification_binding: expected CSV verification semantics")
    try:
        record.__post_init__()
        record.locator.__post_init__()
        extraction.locator.__post_init__()
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid_verification_binding: invalid record or locator") from exc
    if (extraction.snapshot_id != record.snapshot_id or
            type(extraction.snapshot_id) is not str or
            extraction.locator != record.locator):
        raise ValueError("invalid_verification_binding: snapshot or locator mismatch")
    locator = extraction.locator
    height = locator.row_end - locator.row_start + 1
    width = locator.column_end - locator.column_start + 1
    bounds = CSVLimits()
    if (locator.row_end > bounds.max_rows or
            locator.column_end > bounds.max_fields_per_row or
            height * width > bounds.max_selected_cells or
            type(extraction.rows) is not tuple or len(extraction.rows) != height):
        raise ValueError("invalid_verification_binding: extraction shape or limits")
    codepoints = 0
    for row in extraction.rows:
        if type(row) is not tuple or len(row) != width:
            raise ValueError("invalid_verification_binding: extraction must be rectangular")
        for text in row:
            if type(text) is not str or len(text) > bounds.max_field_codepoints:
                raise ValueError("invalid_verification_binding: invalid extraction cell")
            codepoints += len(text)
            if codepoints > bounds.max_selected_codepoints:
                raise ValueError("invalid_verification_binding: extraction text limit")
            try:
                text.encode('utf-8', errors='strict')
            except UnicodeError as exc:
                raise ValueError("invalid_verification_binding: invalid UTF-8 text") from exc
    if type(cell) is not CSVLocator:
        raise ValueError("invalid_cell: expected singleton CSVLocator")
    try:
        cell.__post_init__()
    except ValueError as exc:
        raise ValueError("invalid_cell: invalid coordinates") from exc
    if cell.row_start != cell.row_end or cell.column_start != cell.column_end:
        raise ValueError("invalid_cell: expected singleton CSVLocator")
    if not (locator.row_start <= cell.row_start <= locator.row_end and
            locator.column_start <= cell.column_start <= locator.column_end):
        raise ValueError("cell_outside_extraction: absolute cell is outside rectangle")
    return extraction.rows[cell.row_start - locator.row_start][
        cell.column_start - locator.column_start]


def _unit_payload(unit):
    return dict(kind=unit.kind.value, name=unit.name)


def _identity(prefix, namespace, payload):
    return prefix + hashlib.sha256(namespace + b'\0' + canonical_bytes(payload)).hexdigest()


@dataclass(frozen=True)
class DirectQuantity:
    verification: EvidenceVerification
    cell: CSVLocator
    numeric_type: NumericType
    unit: Unit
    value: Decimal

    def __post_init__(self):
        raw = _bound_raw(self.verification, self.cell)
        _check_unit(self.unit)
        expected = _parse(raw, self.numeric_type)
        actual = _normalized(self.value)
        if actual != expected:
            raise ValueError("result_mismatch: value differs from retained cell")
        object.__setattr__(self, 'value', expected)

    @property
    def raw_text(self):
        extraction = self.verification.extraction
        return extraction.rows[self.cell.row_start - extraction.locator.row_start][
            self.cell.column_start - extraction.locator.column_start]

    @property
    def snapshot_id(self):
        return self.verification.extraction.snapshot_id

    @property
    def evidence_id(self):
        return self.verification.record.evidence_id

    @property
    def quantity_id(self):
        payload = dict(
            schema_version=1, snapshot_id=self.snapshot_id, evidence_id=self.evidence_id,
            cell=self.cell.to_dict(), raw_text=self.raw_text,
            numeric_type=self.numeric_type.value, parser_contract=PARSER_CONTRACT,
            normalizer_contract=NORMALIZER_CONTRACT, unit_contract=UNIT_CONTRACT,
            unit=_unit_payload(self.unit), value=_canonical(self.value),
        )
        return _identity('qf1:', b'presentation-agent:quantity-fact:v1', payload)


@dataclass(frozen=True)
class DerivedQuantity:
    operation: Operation
    input_ids: Tuple[str, str]
    unit: Unit
    value: Decimal

    def __post_init__(self):
        if type(self.operation) is not Operation:
            raise ValueError("unsupported_unit_operation: expected Operation")
        if (type(self.input_ids) is not tuple or len(self.input_ids) != 2 or
                any(type(item) is not str or not _ID.fullmatch(item)
                    for item in self.input_ids)):
            raise ValueError("invalid_inputs: expected two ordered quantity IDs")
        _check_unit(self.unit)
        if self.operation is Operation.RATIO and self.unit.kind is not UnitKind.RATIO:
            raise ValueError("result_mismatch: ratio result requires ratio unit")
        object.__setattr__(self, 'value', _normalized(self.value))

    @property
    def quantity_id(self):
        payload = dict(
            schema_version=1, operation=self.operation.value,
            operation_version=OPERATION_VERSION, input_ids=list(self.input_ids),
            arithmetic_contract=ARITHMETIC_CONTRACT,
            normalizer_contract=NORMALIZER_CONTRACT, unit_contract=UNIT_CONTRACT,
            unit=_unit_payload(self.unit), value=_canonical(self.value),
        )
        return _identity('qd1:', b'presentation-agent:quantity-derived:v1', payload)


@dataclass(frozen=True)
class QuantityLimits:
    max_direct_facts: int = 256
    max_derivations: int = 1024
    max_graph_depth: int = 16
    max_provenance_bytes: int = 67_108_864

    def __post_init__(self):
        for field in fields(self):
            value = getattr(self, field.name)
            if type(value) is not int or not 1 <= value <= field.default:
                raise ValueError('invalid_limits: ' + field.name)


def _calculate(operation, left, right):
    if type(operation) is not Operation:
        raise ValueError("unsupported_unit_operation: expected Operation")
    if left.unit != right.unit:
        raise ValueError("incompatible_units: operand units must be identical")
    if operation is Operation.RATIO and right.value.is_zero():
        raise ValueError("division_by_zero: right operand is zero")
    # Explicit traps/flags avoid inheriting either the caller or DefaultContext.
    context = Context(prec=2050, rounding=ROUND_HALF_EVEN, Emin=-1024, Emax=1025,
                      capitals=1, clamp=0, flags=[],
                      traps=[Inexact, Rounded, InvalidOperation, DivisionByZero,
                             Overflow, Underflow])
    try:
        with localcontext(context):
            if operation is Operation.ADD:
                result = left.value + right.value
            elif operation is Operation.SUBTRACT:
                result = left.value - right.value
            else:
                result = left.value / right.value
    except DecimalException as exc:
        raise ValueError("non_exact_result: arithmetic condition " + type(exc).__name__) from exc
    return _normalized(result), (Unit(UnitKind.RATIO) if operation is Operation.RATIO
                                 else left.unit)


class QuantityGraph:
    """Append-only graph. Only add_fact and derive publish nodes."""

    def __init__(self, *, limits=QuantityLimits()):
        if type(limits) is not QuantityLimits:
            raise ValueError("invalid_limits: expected QuantityLimits")
        limits.__post_init__()
        self._limits = limits
        self._nodes = {}
        self._depths = {}
        self._direct_count = 0
        self._derived_count = 0
        self._provenance_bytes = 0
        self._record_ids = set()
        self._extraction_ids = set()
        self._string_ids = set()

    @property
    def nodes(self):
        return tuple(self._nodes.values())

    def get(self, quantity_id):
        if type(quantity_id) is not str:
            raise KeyError(quantity_id)
        return self._nodes[quantity_id]

    def _provenance_delta(self, verification):
        """Stage identity-based accounting; retain no copied provenance text."""
        pending = set()
        added = 0

        def count(text):
            nonlocal added
            identity = id(text)
            if identity in self._string_ids or identity in pending:
                return
            added += len(text.encode('utf-8', errors='strict'))
            if self._provenance_bytes + added > self._limits.max_provenance_bytes:
                raise ValueError("provenance_limit_exceeded: retained UTF-8 text budget")
            pending.add(identity)

        record, extraction = verification.record, verification.extraction
        if id(record) not in self._record_ids:
            count(record.text)
            for qualification in record.qualifications:
                count(qualification)
        if id(extraction) not in self._extraction_ids:
            for row in extraction.rows:
                for text in row:
                    count(text)
        return added, pending

    def add_fact(self, verification, *, cell, numeric_type, unit):
        if self._derived_count:
            raise ValueError("facts_after_derivation: direct intake is closed")
        if self._direct_count >= self._limits.max_direct_facts:
            raise ValueError("direct_fact_limit_exceeded: direct node count")
        raw = _bound_raw(verification, cell)
        fact = DirectQuantity(verification, cell, numeric_type, unit, _parse(raw, numeric_type))
        identity = fact.quantity_id
        if identity in self._nodes:
            raise ValueError("duplicate_quantity_id: " + identity)
        added, pending = self._provenance_delta(verification)
        # Everything above is validation/staging; publish only on success.
        self._nodes[identity] = fact
        self._depths[identity] = 0
        self._direct_count += 1
        self._provenance_bytes += added
        self._record_ids.add(id(verification.record))
        self._extraction_ids.add(id(verification.extraction))
        self._string_ids.update(pending)
        return fact

    def derive(self, operation, *, left_id, right_id):
        if type(operation) is not Operation:
            raise ValueError("unsupported_unit_operation: expected Operation")
        if self._derived_count >= self._limits.max_derivations:
            raise ValueError("derivation_limit_exceeded: derived node count")
        if any(type(item) is not str or item not in self._nodes
               for item in (left_id, right_id)):
            raise ValueError("missing_or_forward_input: operands must already exist")
        depth = 1 + max(self._depths[left_id], self._depths[right_id])
        if depth > self._limits.max_graph_depth:
            raise ValueError("derivation_depth_exceeded: derived node depth")
        value, unit = _calculate(operation, self._nodes[left_id], self._nodes[right_id])
        derived = DerivedQuantity(operation, (left_id, right_id), unit, value)
        identity = derived.quantity_id
        if identity in self._nodes:
            raise ValueError("duplicate_quantity_id: " + identity)
        self._nodes[identity] = derived
        self._depths[identity] = depth
        self._derived_count += 1
        return derived
