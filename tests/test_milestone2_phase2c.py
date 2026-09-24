"""Phase 2C contract tests; no repetition of the Phase 2A CSV parser suite."""
import ast
from dataclasses import FrozenInstanceError, fields, replace
from decimal import (
    Decimal, Inexact, ROUND_DOWN, Rounded, localcontext,
)
from pathlib import Path
import unittest
from unittest.mock import patch

from presentation_agent import quantities as q
from presentation_agent.evidence import (
    CSVLocator, EvidenceRecord, TextLocator, canonical_bytes, encode_records,
    snapshot_identity,
)
from presentation_agent.evidence_verification import (
    EvidenceVerification, QualificationVerification, StructuredCells,
    TextReproduction, verify_evidence,
)
from presentation_agent.source_extraction import CSVExtraction, TextExtraction


SNAPSHOT = 'sha256:' + '0' * 64
KG = q.Unit(q.UnitKind.NAMED, 'kg')
RATIO = q.Unit(q.UnitKind.RATIO)
CELL = CSVLocator(2, 2, 3, 3)
FACT_VECTOR = 'qf1:3b2c6627769f7173b9c02934f05a61e51b1962537de0eceba7b17e9fd569f0ac'


def verification(raw='1', *, rows=None, locator=CELL, text='reported',
                 qualifications=('unverified',), snapshot=SNAPSHOT):
    record = EvidenceRecord(snapshot, locator, text, qualifications)
    extraction = CSVExtraction(snapshot, locator, ((raw,),) if rows is None else rows)
    return EvidenceVerification(record, extraction, TextReproduction.NOT_ASSESSED,
                                StructuredCells.AVAILABLE,
                                QualificationVerification.UNVERIFIED)


def add(graph, raw='1', *, verification_result=None, cell=CELL,
        numeric_type=q.NumericType.DECIMAL, unit=KG, **kwargs):
    result = verification(raw, **kwargs) if verification_result is None else verification_result
    return graph.add_fact(result, cell=cell, numeric_type=numeric_type, unit=unit)


def state(graph):
    # Include accounting/depth state, so failures cannot silently consume limits.
    return (graph.nodes, dict(graph._depths), graph._direct_count,
            graph._derived_count, graph._provenance_bytes,
            set(graph._record_ids), set(graph._extraction_ids), set(graph._string_ids))


class NumericTests(unittest.TestCase):
    def test_integer_grammar_acceptance(self):
        for raw, expected in [('0', '0'), ('-0', '0'), ('+000', '0'),
                              ('0012', '12'), ('-012', '-12'), ('+12', '12')]:
            with self.subTest(raw=raw):
                fact = add(q.QuantityGraph(), raw, numeric_type=q.NumericType.INTEGER)
                self.assertEqual(fact.value, Decimal(expected))
                self.assertEqual(fact.raw_text, raw)

    def test_decimal_grammar_acceptance(self):
        for raw in ['1', '+001.2500', '-0.010', '000.000', '-17.9']:
            with self.subTest(raw=raw):
                self.assertEqual(add(q.QuantityGraph(), raw).value, Decimal(raw))

    def test_strict_grammar_rejections(self):
        for numeric_type in q.NumericType:
            for raw in ['', '.5', '1.', ' 1', '1 ', '1\n', '\t1', '1e2', '1E-2',
                        '1,000', '$1', '1%', '١', '１', '−1', 'NaN', 'Infinity',
                        '+', '--1', '1_000', '1\x00', '\ufeff1']:
                with self.subTest(numeric_type=numeric_type, raw=raw):
                    with self.assertRaisesRegex(ValueError, '^invalid_numeric_syntax:'):
                        add(q.QuantityGraph(), raw, numeric_type=numeric_type)

    def test_integer_rejects_fraction_spelling(self):
        with self.assertRaisesRegex(ValueError, '^invalid_numeric_syntax:'):
            add(q.QuantityGraph(), '1.0', numeric_type=q.NumericType.INTEGER)

    def test_numeric_type_not_inferred_or_coerced(self):
        for value in [None, 'decimal', 1, True]:
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, '^invalid_numeric_type:'):
                    add(q.QuantityGraph(), numeric_type=value)

    def test_source_length_boundary(self):
        self.assertEqual(add(q.QuantityGraph(), '0' * 1023 + '1').value, 1)
        with self.assertRaisesRegex(ValueError, '^numeric_limit_exceeded:'):
            add(q.QuantityGraph(), '0' * 1024 + '1')

    def test_significant_digit_boundary(self):
        self.assertEqual(add(q.QuantityGraph(), '1' * 128).value, Decimal('1' * 128))
        with self.assertRaisesRegex(ValueError, '^numeric_limit_exceeded:'):
            add(q.QuantityGraph(), '1' * 129)
        self.assertEqual(add(q.QuantityGraph(), '1' + '0' * 1000).value, Decimal('1e1000'))

    def test_canonical_zero_and_trailing_zeros(self):
        fact = add(q.QuantityGraph(), '-000.000')
        self.assertEqual(fact.value.as_tuple(), Decimal('0').as_tuple())
        fact = add(q.QuantityGraph(), '+00120.000')
        self.assertEqual(fact.value.as_tuple(), Decimal('1.2e2').as_tuple())

    def test_no_universal_fractional_place_limit(self):
        fact = add(q.QuantityGraph(), '0.' + '0' * 1021 + '1')
        self.assertEqual(fact.value, Decimal('1e-1022'))

    def test_canonical_exponent_boundaries(self):
        for raw in ['1e-1024', '1e1024', '9e1024', '1.23e1024']:
            with self.subTest(raw=raw):
                self.assertEqual(q._normalized(Decimal(raw)), Decimal(raw))
        for raw in ['1e-1025', '1e1025', '1.1e-1024', '99e1024']:
            with self.subTest(raw=raw):
                with self.assertRaisesRegex(ValueError, '^numeric_limit_exceeded:'):
                    q._normalized(Decimal(raw))

    def test_non_decimal_or_nonfinite_values_rejected(self):
        for value in [1, 1.0, True, '1', Decimal('NaN'), Decimal('sNaN'), Decimal('Infinity')]:
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, '^invalid_numeric_value:'):
                    q.DirectQuantity(verification(), CELL, q.NumericType.DECIMAL, KG, value)

    def test_direct_value_mismatch(self):
        with self.assertRaisesRegex(ValueError, '^result_mismatch:'):
            q.DirectQuantity(verification('1'), CELL, q.NumericType.DECIMAL, KG, Decimal('2'))

    def test_caller_decimal_context_isolation(self):
        baseline = q.QuantityGraph()
        a, b = add(baseline, '1.25'), add(baseline, '8')
        expected = baseline.derive(q.Operation.RATIO, left_id=a.quantity_id,
                                   right_id=b.quantity_id)
        with localcontext() as context:
            context.prec, context.Emin, context.Emax = 1, -1, 1
            context.rounding = ROUND_DOWN
            context.clamp = 1
            for signal in context.traps:
                context.traps[signal] = True
            context.flags[Inexact] = True
            before = (context.copy(), dict(context.flags), dict(context.traps))
            graph = q.QuantityGraph()
            a, b = add(graph, '1.25'), add(graph, '8')
            result = graph.derive(q.Operation.RATIO, left_id=a.quantity_id,
                                  right_id=b.quantity_id)
            self.assertEqual(result.quantity_id, expected.quantity_id)
            self.assertEqual(result.value, Decimal('0.15625'))
            self.assertEqual(context.prec, before[0].prec)
            self.assertEqual(context.flags, before[1])
            self.assertEqual(context.traps, before[2])


class UnitAndArithmeticTests(unittest.TestCase):
    def test_unit_grammar(self):
        for name in ['kg', 'KG', 'a', 'A0_1', 'a' * 64]:
            self.assertEqual(q.Unit(q.UnitKind.NAMED, name).name, name)
        for name in [None, '', '1kg', ' kg', 'kg ', 'kg/m', '%', 'é', 'a' * 65, 1, True]:
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, '^invalid_unit:'):
                    q.Unit(q.UnitKind.NAMED, name)
        for unit_kind in ['named', None, 1]:
            with self.assertRaisesRegex(ValueError, '^invalid_unit:'):
                q.Unit(unit_kind, 'kg')
        with self.assertRaisesRegex(ValueError, '^invalid_unit:'):
            q.Unit(q.UnitKind.RATIO, 'ratio')
        self.assertEqual(list(q.UnitKind), [q.UnitKind.NAMED, q.UnitKind.RATIO])

    def test_all_exact_operations(self):
        graph = q.QuantityGraph()
        a, b = add(graph, '1'), add(graph, '8')
        for operation, value, unit in [(q.Operation.ADD, '9', KG),
                                      (q.Operation.SUBTRACT, '-7', KG),
                                      (q.Operation.RATIO, '0.125', RATIO)]:
            result = graph.derive(operation, left_id=a.quantity_id, right_id=b.quantity_id)
            self.assertEqual((result.value, result.unit), (Decimal(value), unit))

    def test_ratio_unit_operands(self):
        graph = q.QuantityGraph()
        a, b = add(graph, '2', unit=RATIO), add(graph, '4', unit=RATIO)
        for operation, expected in [(q.Operation.ADD, '6'), (q.Operation.SUBTRACT, '-2'),
                                    (q.Operation.RATIO, '0.5')]:
            result = graph.derive(operation, left_id=a.quantity_id, right_id=b.quantity_id)
            self.assertEqual((result.unit, result.value), (RATIO, Decimal(expected)))

    def test_incompatible_units_all_operations(self):
        for other in [q.Unit(q.UnitKind.NAMED, 'KG'), q.Unit(q.UnitKind.NAMED, 'g'), RATIO]:
            graph = q.QuantityGraph()
            a, b = add(graph, '1'), add(graph, '2', unit=other)
            for operation in q.Operation:
                with self.assertRaisesRegex(ValueError, '^incompatible_units:'):
                    graph.derive(operation, left_id=a.quantity_id, right_id=b.quantity_id)

    def test_nonterminating_ratio(self):
        graph = q.QuantityGraph()
        a, b = add(graph, '1'), add(graph, '3')
        with localcontext() as context:
            context.traps[Inexact] = False
            context.traps[Rounded] = False
            with self.assertRaisesRegex(ValueError, '^non_exact_result:'):
                graph.derive(q.Operation.RATIO, left_id=a.quantity_id, right_id=b.quantity_id)

    def test_division_by_signed_zero(self):
        graph = q.QuantityGraph()
        a, b = add(graph, '1'), add(graph, '-000.0')
        with self.assertRaisesRegex(ValueError, '^division_by_zero:'):
            graph.derive(q.Operation.RATIO, left_id=a.quantity_id, right_id=b.quantity_id)

    def test_exact_tiny_ratio(self):
        graph = q.QuantityGraph()
        a, b = add(graph, '1'), add(graph, '1' + '0' * 1000)
        result = graph.derive(q.Operation.RATIO, left_id=a.quantity_id, right_id=b.quantity_id)
        self.assertEqual(result.value, Decimal('1e-1000'))

    def test_exact_but_overprecision_ratio(self):
        graph = q.QuantityGraph()
        # 2**400 is a valid 121-digit input; its terminating reciprocal needs 280 digits.
        a, b = add(graph, '1'), add(graph, str(2 ** 400))
        with self.assertRaisesRegex(ValueError, '^numeric_limit_exceeded:'):
            graph.derive(q.Operation.RATIO, left_id=a.quantity_id, right_id=b.quantity_id)

    def test_addition_overprecision(self):
        graph = q.QuantityGraph()
        a, b = add(graph, '1' + '0' * 128), add(graph, '1')
        with self.assertRaisesRegex(ValueError, '^numeric_limit_exceeded:'):
            graph.derive(q.Operation.ADD, left_id=a.quantity_id, right_id=b.quantity_id)

    def test_result_exponent_upper_boundary(self):
        graph = q.QuantityGraph()
        a = add(graph, '1' + '0' * 1000, unit=RATIO)
        b = add(graph, '0.' + '0' * 23 + '1', unit=RATIO)
        tenth = add(graph, '0.1', unit=RATIO)
        result = graph.derive(q.Operation.RATIO, left_id=a.quantity_id, right_id=b.quantity_id)
        self.assertEqual(result.value, Decimal('1e1024'))
        with self.assertRaisesRegex(ValueError, '^numeric_limit_exceeded:'):
            graph.derive(q.Operation.RATIO, left_id=result.quantity_id, right_id=tenth.quantity_id)

    def test_result_exponent_lower_boundary(self):
        graph = q.QuantityGraph()
        a = add(graph, '0.' + '0' * 1021 + '1', unit=RATIO)
        hundred = add(graph, '100', unit=RATIO)
        ten = add(graph, '10', unit=RATIO)
        result = graph.derive(q.Operation.RATIO, left_id=a.quantity_id, right_id=hundred.quantity_id)
        self.assertEqual(result.value, Decimal('1e-1024'))
        with self.assertRaisesRegex(ValueError, '^numeric_limit_exceeded:'):
            graph.derive(q.Operation.RATIO, left_id=result.quantity_id, right_id=ten.quantity_id)

    def test_arithmetic_overflow_trapped(self):
        graph = q.QuantityGraph()
        a = add(graph, '1' + '0' * 1000)
        b = add(graph, '0.' + '0' * 999 + '1')
        with self.assertRaisesRegex(ValueError, '^non_exact_result:'):
            graph.derive(q.Operation.RATIO, left_id=a.quantity_id, right_id=b.quantity_id)

    def test_exact_cancellation(self):
        graph = q.QuantityGraph()
        a = add(graph, '-' + '1' * 128)
        result = graph.derive(q.Operation.SUBTRACT, left_id=a.quantity_id, right_id=a.quantity_id)
        self.assertEqual(result.value.as_tuple(), Decimal('0').as_tuple())

    def test_unsupported_operations(self):
        graph = q.QuantityGraph()
        a = add(graph)
        for operation in ['add', 'multiply', None, True]:
            with self.assertRaisesRegex(ValueError, '^unsupported_unit_operation:'):
                graph.derive(operation, left_id=a.quantity_id, right_id=a.quantity_id)


class BindingTests(unittest.TestCase):
    def test_absolute_cell_and_retained_objects(self):
        locator = CSVLocator(4, 5, 7, 8)
        result = verification(rows=(('header', '12'), ('3', '4')), locator=locator,
                              text='999', qualifications=('Not assessed',))
        fact = add(q.QuantityGraph(), verification_result=result, cell=CSVLocator(4, 4, 8, 8))
        self.assertEqual(fact.value, 12)
        self.assertIs(fact.verification, result)
        self.assertIs(fact.verification.record, result.record)
        self.assertIs(fact.verification.extraction, result.extraction)
        self.assertIs(fact.raw_text, result.extraction.rows[0][1])
        self.assertEqual(fact.evidence_id, result.record.evidence_id)
        self.assertEqual(fact.snapshot_id, result.extraction.snapshot_id)

    def test_non_numeric_prose_cannot_supply_value(self):
        with self.assertRaisesRegex(ValueError, '^invalid_numeric_syntax:'):
            add(q.QuantityGraph(), 'not numeric', text='12')

    def test_concrete_types_and_statuses(self):
        original = verification()
        bad = [None, original.record,
               replace(original, record=None), replace(original, extraction=None),
               replace(original, text_reproduction=TextReproduction.EXACT_MATCH),
               replace(original, text_reproduction='not_assessed'),
               replace(original, structured_cells=StructuredCells.NOT_APPLICABLE),
               replace(original, qualification_verification='unverified')]
        class VerificationSubclass(EvidenceVerification):
            pass
        bad.append(VerificationSubclass(original.record, original.extraction,
                                        original.text_reproduction, original.structured_cells,
                                        original.qualification_verification))
        for result in bad:
            with self.subTest(result=result):
                with self.assertRaisesRegex(ValueError, '^invalid_verification_binding:'):
                    q.QuantityGraph().add_fact(result, cell=CELL,
                                               numeric_type=q.NumericType.DECIMAL, unit=KG)

    def test_text_verification_rejected(self):
        locator = TextLocator(1, 1)
        record = EvidenceRecord(SNAPSHOT, locator, '1')
        result = EvidenceVerification(record, TextExtraction(SNAPSHOT, locator, '1'),
                                      TextReproduction.EXACT_MATCH,
                                      StructuredCells.NOT_APPLICABLE,
                                      QualificationVerification.UNVERIFIED)
        with self.assertRaisesRegex(ValueError, '^invalid_verification_binding:'):
            add(q.QuantityGraph(), verification_result=result)

    def test_snapshot_and_locator_binding(self):
        original = verification()
        for extraction in [replace(original.extraction, snapshot_id='sha256:' + '1' * 64),
                           replace(original.extraction, locator=CSVLocator(1, 1, 1, 1))]:
            with self.assertRaisesRegex(ValueError, '^invalid_verification_binding:'):
                add(q.QuantityGraph(), verification_result=replace(original, extraction=extraction))

    def test_rectangular_shape_and_cell_types(self):
        for rows in [[], [['1']], (('1', '2'),), (), (('1',), ('2',)),
                     ((1,),), ((True,),), (('\ud800',),)]:
            with self.subTest(rows=rows):
                with self.assertRaisesRegex(ValueError, '^invalid_verification_binding:'):
                    add(q.QuantityGraph(), verification_result=verification(rows=rows))

    def test_extraction_bounds(self):
        for result, cell in [
            (verification(locator=CSVLocator(100001, 100001, 1, 1)), CSVLocator(100001, 100001, 1, 1)),
            (verification(locator=CSVLocator(1, 1, 1001, 1001)), CSVLocator(1, 1, 1001, 1001)),
            (verification(rows=(('x' * 100001,),)), CELL),
            (verification(locator=CSVLocator(1, 11, 1, 1000), rows=()), CSVLocator(1, 1, 1, 1)),
            (verification(locator=CSVLocator(1, 1, 1, 11), rows=(('x' * 100000,) * 11,)),
             CSVLocator(1, 1, 1, 1)),
        ]:
            with self.assertRaisesRegex(ValueError, '^invalid_verification_binding:'):
                add(q.QuantityGraph(), verification_result=result, cell=cell)

    def test_singleton_and_containment(self):
        for cell in [None, TextLocator(1, 1), CSVLocator(2, 3, 3, 3), CSVLocator(2, 2, 3, 4)]:
            with self.assertRaisesRegex(ValueError, '^invalid_cell:'):
                add(q.QuantityGraph(), cell=cell)
        for cell in [CSVLocator(1, 1, 3, 3), CSVLocator(3, 3, 3, 3),
                     CSVLocator(2, 2, 2, 2), CSVLocator(2, 2, 4, 4)]:
            with self.assertRaisesRegex(ValueError, '^cell_outside_extraction:'):
                add(q.QuantityGraph(), cell=cell)

    def test_verifier_integration_and_unchanged_ev1(self):
        data = b'other,1\nthree,8\n'
        locator = CSVLocator(1, 2, 1, 2)
        record = EvidenceRecord(snapshot_identity(data), locator, 'prose', ('caveat',))
        class MemoryStore:
            def read(self, snapshot_id):
                if snapshot_id != record.snapshot_id:
                    raise AssertionError('wrong snapshot')
                return data
        result = verify_evidence(MemoryStore(), record)
        before = encode_records([record])
        graph = q.QuantityGraph()
        a = add(graph, verification_result=result, cell=CSVLocator(1, 1, 2, 2))
        b = add(graph, verification_result=result, cell=CSVLocator(2, 2, 2, 2))
        self.assertEqual(graph.derive(q.Operation.RATIO, left_id=a.quantity_id,
                                     right_id=b.quantity_id).value, Decimal('0.125'))
        self.assertEqual(encode_records([record]), before)


class IdentityAndModelTests(unittest.TestCase):
    def test_exact_frozen_record_fields(self):
        expected = {
            q.Unit: ['kind', 'name'],
            q.DirectQuantity: ['verification', 'cell', 'numeric_type', 'unit', 'value'],
            q.DerivedQuantity: ['operation', 'input_ids', 'unit', 'value'],
            q.QuantityLimits: ['max_direct_facts', 'max_derivations', 'max_graph_depth',
                               'max_provenance_bytes'],
        }
        graph = q.QuantityGraph()
        fact = add(graph)
        derived = graph.derive(q.Operation.ADD, left_id=fact.quantity_id, right_id=fact.quantity_id)
        for record in [KG, fact, derived, q.QuantityLimits()]:
            self.assertEqual([field.name for field in fields(record)], expected[type(record)])
            with self.assertRaises(FrozenInstanceError):
                setattr(record, fields(record)[0].name, None)

    def test_qf1_literal_vectors(self):
        fact = add(q.QuantityGraph(), '+001.2500')
        self.assertEqual(fact.evidence_id,
                         'ev1:e692fef1f7626a36c4ddd82939b9376157904583b911f03a4e145784df262229')
        self.assertEqual(fact.quantity_id, FACT_VECTOR)
        zero = add(q.QuantityGraph(), '-000', numeric_type=q.NumericType.INTEGER, unit=RATIO)
        self.assertEqual(zero.quantity_id,
                         'qf1:f719723818441c371fb72642292cc7647b50e84fd2343e18900d24f8f82f9081')

    def test_qd1_literal_vectors(self):
        graph = q.QuantityGraph()
        fact = add(graph, '+001.2500')
        for operation, expected in [
            (q.Operation.ADD, 'qd1:2ee3eb70a2548b8ceeddb3b17bb8809a7b04737038dbaf53024f191e72ced2da'),
            (q.Operation.SUBTRACT, 'qd1:ad349f4e74f38676ea790c00cf785eca4cdd01f9e819e35f2c2c18b8a7bfbdb4'),
            (q.Operation.RATIO, 'qd1:23c49f6742c48c28c1456f2e661ca2172e2ae39aad16524c0c6ade8591ebf93f'),
        ]:
            self.assertEqual(graph.derive(operation, left_id=fact.quantity_id,
                                           right_id=fact.quantity_id).quantity_id, expected)

    def test_direct_identity_mutations(self):
        original = add(q.QuantityGraph(), '1')
        variants = [add(q.QuantityGraph(), '+1'),
                    add(q.QuantityGraph(), '1', numeric_type=q.NumericType.INTEGER),
                    add(q.QuantityGraph(), '1', unit=RATIO),
                    add(q.QuantityGraph(), '1', text='different'),
                    add(q.QuantityGraph(), '1', qualifications=('different',)),
                    add(q.QuantityGraph(), '1', snapshot='sha256:' + '1' * 64),
                    add(q.QuantityGraph(), '2')]
        for variant in variants:
            self.assertNotEqual(variant.quantity_id, original.quantity_id)

    def test_cell_coordinates_identity_significant(self):
        result = verification(rows=(('1', '1'),), locator=CSVLocator(2, 2, 3, 4))
        graph = q.QuantityGraph()
        a = add(graph, verification_result=result)
        b = add(graph, verification_result=result, cell=CSVLocator(2, 2, 4, 4))
        self.assertNotEqual(a.quantity_id, b.quantity_id)

    def test_ev1_locator_sensitivity_and_unselected_text_exclusion(self):
        narrow = add(q.QuantityGraph(), '1')
        broad = verification(rows=(('1', 'outside'),), locator=CSVLocator(2, 2, 3, 4))
        a = add(q.QuantityGraph(), verification_result=broad)
        changed = replace(broad, extraction=replace(broad.extraction, rows=(('1', 'changed'),)))
        b = add(q.QuantityGraph(), verification_result=changed)
        self.assertNotEqual(a.evidence_id, narrow.evidence_id)
        self.assertNotEqual(a.quantity_id, narrow.quantity_id)
        self.assertEqual(a.quantity_id, b.quantity_id)

    def test_exact_payloads_and_no_extra_identity_fields(self):
        seen = []
        def capture(payload):
            seen.append(payload)
            return canonical_bytes(payload)
        graph = q.QuantityGraph()
        with patch.object(q, 'canonical_bytes', side_effect=capture):
            fact = add(graph, '+001.2500')
            derived = graph.derive(q.Operation.ADD, left_id=fact.quantity_id,
                                   right_id=fact.quantity_id)
        self.assertEqual(set(seen[0]), {'schema_version', 'snapshot_id', 'evidence_id', 'cell',
                                       'raw_text', 'numeric_type', 'parser_contract',
                                       'normalizer_contract', 'unit_contract', 'unit', 'value'})
        self.assertEqual(seen[0]['value'], dict(sign=0, coefficient='125', exponent=-2))
        self.assertEqual(set(seen[-1]), {'schema_version', 'operation', 'operation_version',
                                        'input_ids', 'arithmetic_contract', 'normalizer_contract',
                                        'unit_contract', 'unit', 'value'})
        self.assertEqual(derived.input_ids, (fact.quantity_id, fact.quantity_id))

    def test_order_is_significant_even_for_add(self):
        graph = q.QuantityGraph()
        a, b = add(graph, '1'), add(graph, '2')
        for operation in q.Operation:
            forward = graph.derive(operation, left_id=a.quantity_id, right_id=b.quantity_id)
            backward = graph.derive(operation, left_id=b.quantity_id, right_id=a.quantity_id)
            self.assertNotEqual(forward.quantity_id, backward.quantity_id)

    def test_graph_position_and_limits_excluded(self):
        graph = q.QuantityGraph()
        add(graph, '17')
        a = add(graph, '+001.2500')
        b = graph.derive(q.Operation.ADD, left_id=a.quantity_id, right_id=a.quantity_id)
        small = q.QuantityGraph(limits=q.QuantityLimits(1, 1, 1, 100))
        x = add(small, '+001.2500')
        y = small.derive(q.Operation.ADD, left_id=x.quantity_id, right_id=x.quantity_id)
        self.assertEqual((a.quantity_id, b.quantity_id), (x.quantity_id, y.quantity_id))

    def test_derived_value_unit_and_operation_identity(self):
        ids = (FACT_VECTOR, FACT_VECTOR)
        original = q.DerivedQuantity(q.Operation.ADD, ids, KG, Decimal('1'))
        for variant in [replace(original, operation=q.Operation.SUBTRACT),
                        replace(original, value=Decimal('2')), replace(original, unit=RATIO)]:
            self.assertNotEqual(variant.quantity_id, original.quantity_id)
        self.assertEqual(replace(original, value=Decimal('1.000')).quantity_id,
                         original.quantity_id)

    def test_derived_record_validation(self):
        for ids in [[], (FACT_VECTOR,), (FACT_VECTOR,) * 3, [FACT_VECTOR, FACT_VECTOR],
                    ('bad', FACT_VECTOR), (1, FACT_VECTOR)]:
            with self.assertRaisesRegex(ValueError, '^invalid_inputs:'):
                q.DerivedQuantity(q.Operation.ADD, ids, KG, Decimal('1'))
        with self.assertRaisesRegex(ValueError, '^result_mismatch:'):
            q.DerivedQuantity(q.Operation.RATIO, (FACT_VECTOR, FACT_VECTOR), KG, Decimal('1'))


class GraphTests(unittest.TestCase):
    def test_limits_defaults_and_ceiling_validation(self):
        limits = q.QuantityLimits()
        self.assertEqual(tuple(getattr(limits, field.name) for field in fields(limits)),
                         (256, 1024, 16, 67108864))
        for field in fields(limits):
            for invalid in [True, False, 0, -1, 1.0, '1', None, field.default + 1]:
                with self.subTest(field=field.name, invalid=invalid):
                    with self.assertRaisesRegex(ValueError, '^invalid_limits:'):
                        q.QuantityLimits(**{field.name: invalid})
            self.assertEqual(getattr(q.QuantityLimits(**{field.name: 1}), field.name), 1)
        with self.assertRaisesRegex(ValueError, '^invalid_limits:'):
            q.QuantityGraph(limits=None)

    def test_nodes_in_order_and_immutable_snapshot(self):
        graph = q.QuantityGraph()
        a = add(graph, '1')
        saved = graph.nodes
        b = add(graph, '2')
        derived = graph.derive(q.Operation.ADD, left_id=a.quantity_id, right_id=b.quantity_id)
        self.assertEqual(saved, (a,))
        self.assertEqual(graph.nodes, (a, b, derived))
        self.assertIs(graph.get(a.quantity_id), a)
        with self.assertRaises(AttributeError):
            graph.nodes = ()

    def test_unknown_lookup_keyerror(self):
        for key in ['missing', None, [], 1]:
            with self.assertRaises(KeyError):
                q.QuantityGraph().get(key)

    def test_missing_forward_inputs_atomic(self):
        graph = q.QuantityGraph()
        a = add(graph)
        before = state(graph)
        for left, right in [(a.quantity_id, 'qd1:' + 'f' * 64), ('missing', a.quantity_id),
                            ([], a.quantity_id)]:
            with self.assertRaisesRegex(ValueError, '^missing_or_forward_input:'):
                graph.derive(q.Operation.ADD, left_id=left, right_id=right)
            self.assertEqual(state(graph), before)
        add(graph, '2')  # Failed derivations must not close intake.

    def test_intake_closes_only_on_success(self):
        graph = q.QuantityGraph()
        a, b = add(graph, '1'), add(graph, '3')
        before = state(graph)
        with self.assertRaisesRegex(ValueError, '^non_exact_result:'):
            graph.derive(q.Operation.RATIO, left_id=a.quantity_id, right_id=b.quantity_id)
        self.assertEqual(state(graph), before)
        add(graph, '4')
        graph.derive(q.Operation.ADD, left_id=a.quantity_id, right_id=b.quantity_id)
        before = state(graph)
        with self.assertRaisesRegex(ValueError, '^facts_after_derivation:'):
            add(graph, '5')
        self.assertEqual(state(graph), before)

    def test_duplicate_fact_and_derived_ids_atomic(self):
        graph = q.QuantityGraph()
        a = add(graph, '1')
        before = state(graph)
        with self.assertRaisesRegex(ValueError, '^duplicate_quantity_id:'):
            add(graph, '1')
        self.assertEqual(state(graph), before)
        graph.derive(q.Operation.ADD, left_id=a.quantity_id, right_id=a.quantity_id)
        before = state(graph)
        with self.assertRaisesRegex(ValueError, '^duplicate_quantity_id:'):
            graph.derive(q.Operation.ADD, left_id=a.quantity_id, right_id=a.quantity_id)
        self.assertEqual(state(graph), before)

    def test_failed_facts_atomic(self):
        graph = q.QuantityGraph()
        before = state(graph)
        for raw, kwargs in [('bad', {}), ('1' * 129, {}), ('1', {'unit': 'kg'}),
                            ('1', {'cell': CSVLocator(1, 1, 1, 1)})]:
            with self.assertRaises(ValueError):
                add(graph, raw, **kwargs)
            self.assertEqual(state(graph), before)

    def test_failed_calculations_atomic(self):
        graph = q.QuantityGraph()
        a, zero, three = add(graph, '1'), add(graph, '0'), add(graph, '3')
        huge = add(graph, '1' + '0' * 128)
        other = add(graph, '1', unit=RATIO)
        before = state(graph)
        for operation, left, right in [(q.Operation.RATIO, a, zero),
                                       (q.Operation.RATIO, a, three),
                                       (q.Operation.ADD, a, huge),
                                       (q.Operation.ADD, a, other), ('multiply', a, a)]:
            with self.assertRaises(ValueError):
                graph.derive(operation, left_id=left.quantity_id, right_id=right.quantity_id)
            self.assertEqual(state(graph), before)

    def test_depth_16_and_17(self):
        graph = q.QuantityGraph()
        a = add(graph)
        current = a
        self.assertEqual(graph._depths[a.quantity_id], 0)
        for depth in range(1, 17):
            current = graph.derive(q.Operation.ADD, left_id=a.quantity_id,
                                   right_id=current.quantity_id)
            self.assertEqual(graph._depths[current.quantity_id], depth)
        before = state(graph)
        with self.assertRaisesRegex(ValueError, '^derivation_depth_exceeded:'):
            graph.derive(q.Operation.ADD, left_id=current.quantity_id, right_id=a.quantity_id)
        self.assertEqual(state(graph), before)

    def test_lowered_depth_boundary(self):
        graph = q.QuantityGraph(limits=q.QuantityLimits(max_graph_depth=1))
        a = add(graph)
        b = graph.derive(q.Operation.ADD, left_id=a.quantity_id, right_id=a.quantity_id)
        with self.assertRaisesRegex(ValueError, '^derivation_depth_exceeded:'):
            graph.derive(q.Operation.ADD, left_id=a.quantity_id, right_id=b.quantity_id)

    def test_direct_count_256_and_257(self):
        graph = q.QuantityGraph()
        for i in range(256):
            add(graph, str(i))
        before = state(graph)
        with self.assertRaisesRegex(ValueError, '^direct_fact_limit_exceeded:'):
            add(graph, '256')
        self.assertEqual(state(graph), before)

    def test_derivation_count_1024_and_1025(self):
        graph = q.QuantityGraph()
        facts = [add(graph, str(i)) for i in range(32)]
        for a in facts:
            for b in facts:
                graph.derive(q.Operation.ADD, left_id=a.quantity_id, right_id=b.quantity_id)
        before = state(graph)
        with self.assertRaisesRegex(ValueError, '^derivation_limit_exceeded:'):
            graph.derive(q.Operation.SUBTRACT, left_id=facts[0].quantity_id,
                         right_id=facts[1].quantity_id)
        self.assertEqual(state(graph), before)

    def test_lowered_count_limits(self):
        graph = q.QuantityGraph(limits=q.QuantityLimits(max_direct_facts=1, max_derivations=1))
        a = add(graph)
        with self.assertRaisesRegex(ValueError, '^direct_fact_limit_exceeded:'):
            add(graph, '2')
        graph.derive(q.Operation.ADD, left_id=a.quantity_id, right_id=a.quantity_id)
        with self.assertRaisesRegex(ValueError, '^derivation_limit_exceeded:'):
            graph.derive(q.Operation.SUBTRACT, left_id=a.quantity_id, right_id=a.quantity_id)

    def test_no_import_api(self):
        graph = q.QuantityGraph()
        derived = q.DerivedQuantity(q.Operation.ADD, (FACT_VECTOR, FACT_VECTOR), KG, Decimal('1'))
        with self.assertRaisesRegex(ValueError, '^invalid_verification_binding:'):
            graph.add_fact(derived, cell=CELL, numeric_type=q.NumericType.DECIMAL, unit=KG)
        self.assertFalse(hasattr(graph, 'add_node'))
        self.assertFalse(hasattr(graph, 'load'))


class ProvenanceAndScopeTests(unittest.TestCase):
    def test_default_64_mib_boundary_and_one_byte_over(self):
        graph = q.QuantityGraph()
        # Shared 'r' and '1' cost two bytes total. Each distinct extraction
        # adds 999,999 ASCII bytes, within Phase 2A's one-million-codepoint cap.
        for row_number in range(1, 68):
            texts = tuple(bytearray(b'x' * size).decode()
                          for size in [100000] * 9 + [99999])
            result = verification(rows=(('1',) + texts,),
                                  locator=CSVLocator(row_number, row_number, 1, 11),
                                  text='r', qualifications=())
            add(graph, verification_result=result,
                cell=CSVLocator(row_number, row_number, 1, 1))
        expected = 2 + 67 * 999999
        self.assertEqual(graph._provenance_bytes, expected)
        remainder = 67108864 - expected
        texts = (bytearray(b'y' * 100000).decode(),
                 bytearray(b'y' * (remainder - 100000)).decode())
        result = verification(rows=(('1',) + texts,), locator=CSVLocator(68, 68, 1, 3),
                              text='r', qualifications=())
        add(graph, verification_result=result, cell=CSVLocator(68, 68, 1, 1))
        self.assertEqual(graph._provenance_bytes, 67108864)
        # Another numeric declaration retaining only existing text still fits.
        add(graph, verification_result=result, cell=CSVLocator(68, 68, 1, 1),
            numeric_type=q.NumericType.INTEGER)
        before = state(graph)
        extra = verification(rows=(('1', 'z'),), locator=CSVLocator(69, 69, 1, 2),
                             text='r', qualifications=())
        with self.assertRaisesRegex(ValueError, '^provenance_limit_exceeded:'):
            add(graph, verification_result=extra, cell=CSVLocator(69, 69, 1, 1))
        self.assertEqual(state(graph), before)

    def test_utf8_exact_budget_and_failure_atomicity(self):
        result = verification('1', text='é', qualifications=('🙂',))
        graph = q.QuantityGraph(limits=q.QuantityLimits(max_provenance_bytes=7))
        add(graph, verification_result=result)
        self.assertEqual(graph._provenance_bytes, 7)
        small = q.QuantityGraph(limits=q.QuantityLimits(max_provenance_bytes=6))
        before = state(small)
        with self.assertRaisesRegex(ValueError, '^provenance_limit_exceeded:'):
            add(small, verification_result=result)
        self.assertEqual(state(small), before)
        add(small, '2', text='ok', qualifications=())

    def test_all_extraction_cells_counted(self):
        result = verification(rows=(('1', 'not selected'),), locator=CSVLocator(2, 2, 3, 4),
                              text='text', qualifications=())
        graph = q.QuantityGraph(limits=q.QuantityLimits(max_provenance_bytes=16))
        before = state(graph)
        with self.assertRaisesRegex(ValueError, '^provenance_limit_exceeded:'):
            add(graph, verification_result=result)
        self.assertEqual(state(graph), before)

    def test_shared_record_and_extraction_count_once(self):
        result = verification(rows=(('1', '2'),), locator=CSVLocator(2, 2, 3, 4),
                              text='text', qualifications=('qual',))
        graph = q.QuantityGraph(limits=q.QuantityLimits(max_provenance_bytes=10))
        a = add(graph, verification_result=result)
        b = add(graph, verification_result=replace(result), cell=CSVLocator(2, 2, 4, 4))
        self.assertEqual(graph._provenance_bytes, 10)
        before = graph._provenance_bytes
        graph.derive(q.Operation.ADD, left_id=a.quantity_id, right_id=b.quantity_id)
        self.assertEqual(graph._provenance_bytes, before)

    def test_shared_strings_across_distinct_containers_count_once(self):
        result = verification('12345', text='long text', qualifications=('qualifier',))
        second = replace(result, record=replace(result.record), extraction=replace(result.extraction))
        graph = q.QuantityGraph()
        add(graph, verification_result=result)
        before = graph._provenance_bytes
        add(graph, verification_result=second, numeric_type=q.NumericType.INTEGER)
        self.assertEqual(graph._provenance_bytes, before)

    def test_distinct_equal_string_objects_count_separately(self):
        first = bytearray(b'equal string').decode()
        second = bytearray(b'equal string').decode()
        self.assertEqual(first, second)
        self.assertIsNot(first, second)
        result = verification('1', text=first, qualifications=(second,))
        graph = q.QuantityGraph(limits=q.QuantityLimits(max_provenance_bytes=25))
        add(graph, verification_result=result)
        self.assertEqual(graph._provenance_bytes, 25)
        small = q.QuantityGraph(limits=q.QuantityLimits(max_provenance_bytes=24))
        with self.assertRaisesRegex(ValueError, '^provenance_limit_exceeded:'):
            add(small, verification_result=result)

    def test_distinct_equal_extraction_strings_count_separately(self):
        first, second = bytearray(b'12345').decode(), bytearray(b'12345').decode()
        self.assertIsNot(first, second)
        result = verification(rows=((first, second),), locator=CSVLocator(2, 2, 3, 4),
                              text='text', qualifications=())
        graph = q.QuantityGraph()
        add(graph, verification_result=result)
        self.assertEqual(graph._provenance_bytes, 14)

    def test_incremental_accounting_does_not_reencode_shared_provenance(self):
        result = verification(rows=(('1', '2'),), locator=CSVLocator(2, 2, 3, 4))
        graph = q.QuantityGraph()
        add(graph, verification_result=result)
        self.assertEqual(graph._provenance_delta(result), (0, set()))
        add(graph, verification_result=result, cell=CSVLocator(2, 2, 4, 4))
        self.assertEqual(len(graph._record_ids), 1)
        self.assertEqual(len(graph._extraction_ids), 1)

    def test_no_writes_network_or_source_reread(self):
        result = verification('8')
        with patch('builtins.open', side_effect=AssertionError('file I/O')), \
                patch('os.open', side_effect=AssertionError('file I/O')), \
                patch('socket.socket', side_effect=AssertionError('network')), \
                patch('presentation_agent.source_capture.SourceStore.read',
                      side_effect=AssertionError('source reread')):
            graph = q.QuantityGraph()
            a = add(graph, verification_result=result)
            derived = graph.derive(q.Operation.RATIO, left_id=a.quantity_id, right_id=a.quantity_id)
            self.assertEqual(graph.get(derived.quantity_id).value, 1)

    def test_standard_library_and_only_phase2_dependencies(self):
        source = Path(q.__file__).read_text()
        tree = ast.parse(source, feature_version=9)
        imports = set()
        relative = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                (relative if node.level else imports).add(node.module)
        self.assertEqual(relative, {'evidence', 'evidence_verification', 'source_extraction'})
        self.assertLessEqual(imports, {'dataclasses', 'decimal', 'enum', 'hashlib', 're', 'typing'})
        self.assertNotIn('.normalize(', source)
        self.assertNotIn('DerivationParameters', source)


if __name__ == '__main__':
    unittest.main()
