"""In-memory projection contract tests; no source capture or extraction."""
import ast
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import MISSING, FrozenInstanceError, fields, is_dataclass, replace
from decimal import Decimal, Inexact, ROUND_DOWN, localcontext
from enum import Enum
from pathlib import Path
import traceback
import unittest
from unittest.mock import patch

from presentation_agent import milestone1_adapter as adapter
from presentation_agent import quantities as q
from presentation_agent.evidence import CSVLocator, EvidenceRecord, TextLocator
from presentation_agent.evidence_verification import (
    EvidenceVerification, QualificationVerification as QV, StructuredCells as SC,
    TextReproduction as TR,
)
from presentation_agent.source_extraction import CSVExtraction, TextExtraction


SNAPSHOTS = tuple('sha256:' + str(i) * 64 for i in range(3))
MEAN = q.Unit(q.UnitKind.NAMED, 'minutes_per_case')
CASES = q.Unit(q.UnitKind.NAMED, 'cases')
MINUTES = q.Unit(q.UnitKind.NAMED, 'minutes')
F = adapter.LegacyField
P = adapter.ProjectionContract


def example(*, raws=('12', '30', '360', '9', '30', '270'),
            qualifications=None, texts=None, units=None, numeric_types=None,
            cells=None, extra=False, derive=True):
    """Fabricate structurally valid verification objects, deliberately no verifier."""
    graph = q.QuantityGraph()
    qualifications = ((),) * 7 if qualifications is None else qualifications
    texts = tuple('misleading role: revenue ' + str(i) for i in range(6)) + (
        'Invented observation: fewer handoffs.\nNo causal conclusion.',) if texts is None else texts
    units = (MEAN, CASES, MINUTES) * 2 if units is None else units
    numeric_types = (q.NumericType.DECIMAL, q.NumericType.INTEGER, q.NumericType.DECIMAL) * 2 if numeric_types is None else numeric_types
    cells = tuple(CSVLocator(i + 1, i + 1, 2, 2) for i in range(6)) if cells is None else cells
    facts = []
    for i, raw in enumerate(raws):
        record = EvidenceRecord(SNAPSHOTS[i // 3], cells[i], texts[i], qualifications[i])
        verification = EvidenceVerification(
            record, CSVExtraction(record.snapshot_id, cells[i], ((raw,),)),
            TR.NOT_ASSESSED, SC.AVAILABLE, QV.UNVERIFIED)
        facts.append(graph.add_fact(verification, cell=cells[i],
                                    numeric_type=numeric_types[i], unit=units[i]))
    if extra:
        original = facts[0].verification
        other = replace(original, record=replace(original.record, text='equal value, wrong lineage'))
        graph.add_fact(other, cell=facts[0].cell, numeric_type=facts[0].numeric_type, unit=MEAN)
    locator = TextLocator(4, 5)
    record = EvidenceRecord(SNAPSHOTS[2], locator, texts[6], qualifications[6])
    qualitative = EvidenceVerification(
        record, TextExtraction(record.snapshot_id, locator, record.text),
        TR.EXACT_MATCH, SC.NOT_APPLICABLE, QV.UNVERIFIED)
    if derive:
        difference = graph.derive(q.Operation.SUBTRACT, left_id=facts[0].quantity_id,
                                  right_id=facts[3].quantity_id)
        ratio = graph.derive(q.Operation.RATIO, left_id=difference.quantity_id,
                             right_id=facts[0].quantity_id)
        derived_ids = (difference.quantity_id, ratio.quantity_id)
    else:
        derived_ids = ('qd1:' + 'a' * 64, 'qd1:' + 'b' * 64)
    mapping = adapter.Milestone1DemoMapping(
        adapter.DemoProfile.SYNTHETIC_HANDLING_TIME_V1, True,
        adapter.SourcePresentation(SNAPSHOTS[0], 'after.csv — actually assigned baseline',
            f'Invented fixture; {raws[1]} cases; total handling time {int(Decimal(raws[2]))} minutes.'),
        adapter.SourcePresentation(SNAPSHOTS[1], 'before.csv — actually assigned follow-up',
            f'Invented fixture; {raws[4]} cases; total handling time {int(Decimal(raws[5]))} minutes.'),
        adapter.SourcePresentation(SNAPSHOTS[2], 'Authored title', 'Authored interpretation, unverified.'),
        *(fact.quantity_id for fact in facts), *derived_ids, record.evidence_id)
    return graph, qualitative, mapping


def adapt(case):
    graph, qualitative, mapping = case
    return adapter.adapt_milestone1_demo(graph=graph, qualitative_verification=qualitative, mapping=mapping)


def state(graph):
    return {key: value.copy() if type(value) in (dict, set) else value
            for key, value in vars(graph).items()}


def logical_bytes(value):
    """Independent specification traversal, excluding names and numeric scalars."""
    if isinstance(value, Enum):
        return len(value.value.encode('utf-8'))
    if type(value) is str:
        return len(value.encode('utf-8'))
    if is_dataclass(value):
        return sum(logical_bytes(getattr(value, field.name)) for field in fields(value))
    if type(value) is tuple:
        return sum(map(logical_bytes, value))
    return 0


class ProjectionTests(unittest.TestCase):
    def assertFailure(self, case, prefix):
        graph, verification, mapping = case
        before = state(graph)
        before_input = (verification, mapping)
        with self.assertRaisesRegex(ValueError, '^m1_adapter_' + prefix + ':') as caught:
            adapt(case)
        self.assertEqual(state(graph), before)
        self.assertEqual((verification, mapping), before_input)
        return caught.exception

    def test_independent_complete_expected_dictionary(self):
        result = adapt(example())
        self.assertEqual(result.legacy_evidence, {
            'synthetic': True,
            'sources': [
                {'id': 'S1', 'title': 'after.csv — actually assigned baseline',
                 'detail': 'Invented fixture; 30 cases; total handling time 360 minutes.'},
                {'id': 'S2', 'title': 'before.csv — actually assigned follow-up',
                 'detail': 'Invented fixture; 30 cases; total handling time 270 minutes.'},
                {'id': 'S3', 'title': 'Authored title', 'detail': 'Authored interpretation, unverified.'},
            ],
            'evidence': [
                {'id': 'E1', 'source_id': 'S1', 'value': 12, 'unit': 'minutes per case', 'sample_size': 30},
                {'id': 'E2', 'source_id': 'S2', 'value': 9, 'unit': 'minutes per case', 'sample_size': 30},
                {'id': 'E3', 'source_id': 'S3', 'text': 'Invented observation: fewer handoffs.\nNo causal conclusion.'},
            ],
            'calculations': [
                {'id': 'D1', 'operation': 'relative_reduction_percent', 'input_ids': ['E1', 'E2'], 'value': 25, 'unit': 'percent'},
                {'id': 'D2', 'operation': 'absolute_difference', 'input_ids': ['E1', 'E2'], 'value': 3, 'unit': 'minutes per case'},
            ],
        })
        self.assertEqual(result.provenance.bridge_contract, 'milestone1_evidence_projection_v1')
        self.assertEqual(tuple(map(len, (result.provenance.facts, result.provenance.derivations,
                                       result.provenance.evidence, result.provenance.fields))), (6, 2, 7, 17))

    def test_every_binding_independent_order_origin_projection_and_span(self):
        case = example()
        m = case[2]
        A, Q, T = adapter.AuthoredMappingOrigin, adapter.QuantityOrigin, adapter.ReproducedTextOrigin
        expected = [
            (F.S1_TITLE, m.s1.title, P.AUTHORED_TEXT_V1, A('s1.title'), None),
            (F.S1_DETAIL, m.s1.detail, P.AUTHORED_TEXT_V1, A('s1.detail'), None),
            (F.S1_DETAIL_SAMPLE_SIZE, '30', P.DECIMAL_TO_INTEGER_V1, Q(m.e1_sample_size_id), (18, 20)),
            (F.S1_DETAIL_TOTAL, '360', P.DECIMAL_TO_INTEGER_V1, Q(m.s1_total_id), (48, 51)),
            (F.S2_TITLE, m.s2.title, P.AUTHORED_TEXT_V1, A('s2.title'), None),
            (F.S2_DETAIL, m.s2.detail, P.AUTHORED_TEXT_V1, A('s2.detail'), None),
            (F.S2_DETAIL_SAMPLE_SIZE, '30', P.DECIMAL_TO_INTEGER_V1, Q(m.e2_sample_size_id), (18, 20)),
            (F.S2_DETAIL_TOTAL, '270', P.DECIMAL_TO_INTEGER_V1, Q(m.s2_total_id), (48, 51)),
            (F.S3_TITLE, m.s3.title, P.AUTHORED_TEXT_V1, A('s3.title'), None),
            (F.S3_DETAIL, m.s3.detail, P.AUTHORED_TEXT_V1, A('s3.detail'), None),
            (F.E1_VALUE, 12, P.DECIMAL_TO_INTEGER_V1, Q(m.e1_value_id), None),
            (F.E1_SAMPLE_SIZE, 30, P.DECIMAL_TO_INTEGER_V1, Q(m.e1_sample_size_id), None),
            (F.E2_VALUE, 9, P.DECIMAL_TO_INTEGER_V1, Q(m.e2_value_id), None),
            (F.E2_SAMPLE_SIZE, 30, P.DECIMAL_TO_INTEGER_V1, Q(m.e2_sample_size_id), None),
            (F.E3_TEXT, case[1].record.text, P.EXACT_TEXT_V1, T(m.e3_evidence_id), None),
            (F.D1_VALUE, 25, P.RATIO_TO_PERCENT_INTEGER_V1, Q(m.reduction_ratio_id), None),
            (F.D2_VALUE, 3, P.DECIMAL_TO_INTEGER_V1, Q(m.difference_id), None),
        ]
        bindings = adapt(case).provenance.fields
        self.assertEqual(bindings, tuple(adapter.FieldBinding(*row) for row in expected))
        self.assertEqual(tuple(b.target for b in bindings), tuple(F))
        for binding in bindings:
            if binding.span:
                detail = m.s1.detail if binding.target.name.startswith('S1') else m.s2.detail
                self.assertEqual(detail[slice(*binding.span)], binding.projected_value)

    def test_equal_values_distinct_origins(self):
        result = adapt(example())
        a, b = result.provenance.facts[1], result.provenance.facts[4]
        self.assertEqual(a.value, b.value)
        self.assertNotEqual(a.quantity_id, b.quantity_id)
        self.assertNotEqual((a.snapshot_id, a.cell), (b.snapshot_id, b.cell))
        self.assertNotEqual(result.provenance.fields[11].origin, result.provenance.fields[13].origin)

    def test_explicit_mapping_not_prose_titles_or_headers(self):
        case = example(texts=('follow-up means 999 dollars',) * 6 + ('baseline.csv says nothing numeric',))
        self.assertEqual(adapt(case).legacy_evidence['evidence'][0]['value'], 12)
        # Retain a misleading header in a rectangle before graph intake.
        g, qualitative, mapping = example(derive=False)
        original = g.nodes[0].verification
        rectangle = CSVLocator(1, 1, 1, 2)
        verification = replace(original, record=replace(original.record, locator=rectangle),
                               extraction=CSVExtraction(SNAPSHOTS[0], rectangle, (('total dollars', '12'),)))
        new = g.add_fact(verification, cell=CSVLocator(1, 1, 2, 2), numeric_type=q.NumericType.DECIMAL, unit=MEAN)
        difference = g.derive(q.Operation.SUBTRACT, left_id=new.quantity_id, right_id=mapping.e2_value_id)
        ratio = g.derive(q.Operation.RATIO, left_id=difference.quantity_id, right_id=new.quantity_id)
        mapping = replace(mapping, e1_value_id=new.quantity_id, difference_id=difference.quantity_id,
                          reduction_ratio_id=ratio.quantity_id)
        self.assertEqual(adapt((g, qualitative, mapping)).legacy_evidence['evidence'][0]['value'], 12)

    def test_mapping_snapshot_mismatch_each_source(self):
        g, v, m = example()
        for name in ('s1', 's2', 's3'):
            self.assertFailure((g, v, replace(m, **{name: replace(getattr(m, name), snapshot_id='sha256:' + 'f' * 64)})), 'source_mismatch')

    def test_missing_or_derived_totals(self):
        g, v, m = example()
        for name in ('s1_total_id', 's2_total_id'):
            self.assertFailure((g, v, replace(m, **{name: 'qf1:' + 'f' * 64})), 'missing_quantity')
            self.assertFailure((g, v, replace(m, **{name: m.difference_id})), 'invalid_quantity')

    def test_incorrect_direct_total_is_not_repaired(self):
        self.assertFailure(example(raws=('12', '30', '361', '9', '30', '270')), 'profile_invariant')

    def test_missing_derivations_and_no_intake_state_change(self):
        case = example(derive=False)
        self.assertFailure(case, 'missing_quantity')
        graph = case[0]
        original = graph.nodes[0]
        verification = replace(original.verification, record=replace(original.verification.record, text='another record'))
        graph.add_fact(verification, cell=original.cell, numeric_type=original.numeric_type, unit=MEAN)
        self.assertEqual(len(graph.nodes), 7)

    def test_missing_ratio_in_existing_graph(self):
        g, v, m = example()
        self.assertFailure((g, v, replace(m, reduction_ratio_id='qd1:' + 'f' * 64)), 'missing_quantity')

    def test_wrong_difference_operation_and_reversed_operands(self):
        g, v, m = example()
        for operation, left, right in ((q.Operation.ADD, m.e1_value_id, m.e2_value_id),
                                       (q.Operation.SUBTRACT, m.e2_value_id, m.e1_value_id)):
            node = g.derive(operation, left_id=left, right_id=right)
            self.assertFailure((g, v, replace(m, difference_id=node.quantity_id)), 'derivation_mismatch')

    def test_equal_valued_wrong_difference_lineage(self):
        g, v, m = example(extra=True)
        other = g.nodes[6]
        wrong = g.derive(q.Operation.SUBTRACT, left_id=other.quantity_id, right_id=m.e2_value_id)
        self.assertEqual(wrong.value, Decimal('3'))
        self.assertFailure((g, v, replace(m, difference_id=wrong.quantity_id)), 'derivation_mismatch')

    def test_wrong_ratio_operation_reversal_and_equal_lineage(self):
        g, v, m = example(extra=True)
        other = g.nodes[6]
        for operation, left, right in (
            (q.Operation.SUBTRACT, m.difference_id, m.e1_value_id),
            (q.Operation.RATIO, m.e1_value_id, m.difference_id),
            (q.Operation.RATIO, m.difference_id, other.quantity_id),
        ):
            wrong = g.derive(operation, left_id=left, right_id=right)
            self.assertFailure((g, v, replace(m, reduction_ratio_id=wrong.quantity_id)), 'derivation_mismatch')

    def test_integral_decimal_spellings(self):
        result = adapt(example(raws=('+0012.000', '30', '00360.00', '9.0000', '30', '+0270.000')))
        self.assertEqual([e['value'] for e in result.legacy_evidence['evidence'][:2]], [12, 9])
        self.assertEqual(result.provenance.facts[0].raw_text, '+0012.000')
        for binding in result.provenance.fields:
            if binding.target in (F.E1_VALUE, F.E2_VALUE, F.D1_VALUE, F.D2_VALUE):
                self.assertIs(type(binding.projected_value), int)

    def test_integer_syntax_means_and_totals(self):
        self.assertEqual(adapt(example(numeric_types=(q.NumericType.INTEGER,) * 6)).legacy_evidence['calculations'][0]['value'], 25)

    def test_fractional_means_totals_percentages_rejected(self):
        for raws in [('12.5', '30', '375', '10', '30', '300'),
                     ('12', '30', '360.5', '9', '30', '270'),
                     ('8', '30', '240', '7', '30', '210')]:
            self.assertFailure(example(raws=raws), 'nonintegral_projection')

    def test_sample_sizes_require_integer_syntax(self):
        types = (q.NumericType.DECIMAL,) * 6
        self.assertFailure(example(numeric_types=types), 'invalid_quantity')

    def test_profile_invariants(self):
        for raws in [('12', '30', '360', '9', '20', '180'),
                     ('12', '0', '360', '9', '0', '270'),
                     ('12', '30', '0', '9', '30', '270'),
                     ('12', '30', '360', '12', '30', '360'),
                     ('12', '30', '360', '15', '30', '450'),
                     ('12', '30', '360', '0', '30', '270')]:
            self.assertFailure(example(raws=raws), 'profile_invariant')

    def test_context_hostile_and_unchanged(self):
        case = example()
        expected = adapt(case)
        with localcontext() as context:
            context.prec, context.Emin, context.Emax = 1, -1, 1
            context.rounding, context.clamp, context.capitals = ROUND_DOWN, 1, 0
            for signal in context.traps:
                context.traps[signal] = True
            context.flags[Inexact] = True
            before = str(context), dict(context.flags), dict(context.traps)
            self.assertEqual(adapt(case), expected)
            self.assertEqual((str(context), dict(context.flags), dict(context.traps)), before)

    def test_integer_ceiling_boundary_and_one_over(self):
        # 999999 cannot participate in a successful profile: an integral percent
        # with 0 < b < a requires a (and thus its total) to share a factor with 100.
        self.assertEqual(adapter._integer(Decimal('999999'), 'e1_value'), 999999)
        with self.assertRaisesRegex(ValueError, '^m1_adapter_resource_limit:'):
            adapter._integer(Decimal('1000000'), 'e1_value')
        self.assertEqual(adapt(example(raws=('100', '9999', '999900', '75', '9999', '749925'))).legacy_evidence['evidence'][0]['value'], 100)
        self.assertFailure(example(raws=('100', '10000', '1000000', '75', '10000', '750000')), 'resource_limit')

    def test_exact_template_not_normalized_or_rewritten(self):
        g, v, m = example()
        for detail in (m.s1.detail + ' ', m.s1.detail.replace('360', '0360'), m.s1.detail.replace('30 cases', '30\tcases')):
            self.assertFailure((g, v, replace(m, s1=replace(m.s1, detail=detail))), 'invalid_mapping')

    def test_concrete_inputs_no_coercions(self):
        g, v, m = example()
        for bad in (None, {}, [], True, 'graph'):
            with self.assertRaisesRegex(ValueError, '^m1_adapter_invalid_input:'):
                adapter.adapt_milestone1_demo(graph=bad, qualitative_verification=v, mapping=m)
            with self.assertRaisesRegex(ValueError, '^m1_adapter_invalid_input:'):
                adapter.adapt_milestone1_demo(graph=g, qualitative_verification=bad, mapping=m)
            with self.assertRaisesRegex(ValueError, '^m1_adapter_invalid_input:'):
                adapter.adapt_milestone1_demo(graph=g, qualitative_verification=v, mapping=bad)
        class GraphSubclass(q.QuantityGraph):
            pass
        with self.assertRaisesRegex(ValueError, '^m1_adapter_invalid_input:'):
            adapter.adapt_milestone1_demo(graph=GraphSubclass(), qualitative_verification=v, mapping=m)

    def test_mapping_fields_and_profile_types(self):
        g, v, m = example()
        for bad in (None, True, 'synthetic_handling_time_v1'):
            self.assertFailure((g, v, replace(m, profile=bad)), 'unsupported_profile')
        for bad in (1, False, 'true', None):
            self.assertFailure((g, v, replace(m, synthetic=bad)), 'invalid_mapping')
        for bad in (None, [], {}, True):
            self.assertFailure((g, v, replace(m, e1_value_id=bad)), 'invalid_mapping')
            self.assertFailure((g, v, replace(m, s1=bad)), 'invalid_mapping')
        for kwargs in ({'title': True}, {'detail': []}, {'snapshot_id': 'bad'}, {'title': '\ud800'}):
            self.assertFailure((g, v, replace(m, s1=replace(m.s1, **kwargs))), 'invalid_mapping')
        self.assertTrue(all(field.default is MISSING for field in fields(type(m))))

    def test_distinct_ids_cells_and_evidence(self):
        g, v, m = example()
        self.assertFailure((g, v, replace(m, e2_sample_size_id=m.e1_sample_size_id)), 'invalid_mapping')
        cells = (CSVLocator(1, 1, 2, 2),) * 6
        self.assertFailure(example(cells=cells), 'invalid_mapping')
        # Distinct cells but a single record owns three selected facts.
        g, v, m = example(derive=False)
        rectangle = CSVLocator(8, 8, 1, 3)
        record = EvidenceRecord(SNAPSHOTS[0], rectangle, 'three roles')
        verified = EvidenceVerification(record, CSVExtraction(SNAPSHOTS[0], rectangle, (('12', '30', '360'),)), TR.NOT_ASSESSED, SC.AVAILABLE, QV.UNVERIFIED)
        facts = [g.add_fact(verified, cell=CSVLocator(8, 8, i + 1, i + 1), numeric_type=q.NumericType.INTEGER, unit=unit) for i, unit in enumerate((MEAN, CASES, MINUTES))]
        d = g.derive(q.Operation.SUBTRACT, left_id=facts[0].quantity_id, right_id=m.e2_value_id)
        r = g.derive(q.Operation.RATIO, left_id=d.quantity_id, right_id=facts[0].quantity_id)
        m = replace(m, e1_value_id=facts[0].quantity_id, e1_sample_size_id=facts[1].quantity_id,
                    s1_total_id=facts[2].quantity_id, difference_id=d.quantity_id, reduction_ratio_id=r.quantity_id)
        self.assertFailure((g, v, m), 'invalid_mapping')

    def test_wrong_units(self):
        for index in (1, 2, 4, 5):
            units = list((MEAN, CASES, MINUTES) * 2)
            units[index] = q.Unit(q.UnitKind.NAMED, 'dollars')
            self.assertFailure(example(units=tuple(units)), 'unit_mismatch')
        units = (q.Unit(q.UnitKind.NAMED, 'seconds_per_case'), CASES, MINUTES) * 2
        self.assertFailure(example(units=units), 'unit_mismatch')

    def test_authored_origin_fixed_identifiers(self):
        for invalid in ('s1.snapshot_id', 's1.title.upper', 'sources.S1.title', [], True):
            with self.assertRaisesRegex(ValueError, '^m1_adapter_invalid_mapping:'):
                adapter.AuthoredMappingOrigin(invalid)


class QualitativeAndQualificationTests(unittest.TestCase):
    assertFailure = ProjectionTests.assertFailure

    def test_text_mismatch_and_contradictory_statuses(self):
        g, v, m = example()
        for bad in (replace(v, extraction=replace(v.extraction, text='different')),
                    replace(v, text_reproduction=TR.MISMATCH),
                    replace(v, text_reproduction=TR.NOT_ASSESSED),
                    replace(v, text_reproduction='exact_match'),
                    replace(v, structured_cells=SC.AVAILABLE),
                    replace(v, qualification_verification='unverified')):
            self.assertFailure((g, bad, m), 'qualitative_support')

    def test_text_snapshot_locator_and_concrete_extraction(self):
        g, v, m = example()
        for extraction in (replace(v.extraction, snapshot_id=SNAPSHOTS[0]),
                           replace(v.extraction, locator=TextLocator(1, 2)),
                           replace(v.extraction, locator=CSVLocator(4, 5, 1, 1)),
                           None, {'text': v.record.text}):
            self.assertFailure((g, replace(v, extraction=extraction), m), 'qualitative_support')
        class TextSubclass(TextExtraction):
            pass
        self.assertFailure((g, replace(v, extraction=TextSubclass(v.record.snapshot_id, v.record.locator, v.record.text)), m), 'qualitative_support')

    def test_csv_prose_cannot_supply_e3(self):
        g, v, m = example()
        csv = g.nodes[0].verification
        self.assertFailure((g, csv, replace(m, e3_evidence_id=csv.record.evidence_id)), 'qualitative_support')

    def test_qualitative_identity_mismatch(self):
        g, v, m = example()
        self.assertFailure((g, v, replace(m, e3_evidence_id='ev1:' + 'f' * 64)), 'invalid_mapping')

    def test_invalid_record_or_qualification_container(self):
        g, v, m = example()
        self.assertFailure((g, replace(v, record={}), m), 'invalid_verification')

    def test_manually_fabricated_verification_is_accepted_not_authenticated(self):
        case = example()
        # These constructor-built objects never passed through verify_evidence.
        # Structural consistency cannot establish verifier execution history.
        with patch('presentation_agent.evidence_verification.verify_evidence', side_effect=AssertionError('verifier called')):
            self.assertEqual(adapt(case).legacy_evidence['evidence'][2]['text'], case[1].record.text)

    def test_qualifications_exact_duplicate_unicode_order_owner_and_status(self):
        qualifications = (('  Δ\t🙂  ', 'duplicate', 'duplicate'), (), ('total only',),
                          ('follow-up mean',), ('sample only',), (), ('\nتحفظ\t', 'duplicate'))
        case = example(qualifications=qualifications)
        provenance = adapt(case).provenance
        self.assertEqual(tuple(e.qualifications for e in provenance.evidence), qualifications)
        expected_owners = tuple((record.evidence_id, i) for record in provenance.evidence
                                for i in range(len(record.qualifications)))
        self.assertEqual(tuple((b.owner_evidence_id, b.qualification_index) for b in provenance.qualifications), expected_owners)
        self.assertTrue(all(b.status is QV.UNVERIFIED for b in provenance.qualifications))
        self.assertTrue(all(e.qualification_verification is QV.UNVERIFIED for e in provenance.evidence))

    def test_qualification_reachability_and_total_isolation(self):
        provenance = adapt(example(qualifications=(('q',),) * 7)).provenance
        self.assertEqual(tuple(b.affected_fields for b in provenance.qualifications), (
            (F.E1_VALUE, F.D1_VALUE, F.D2_VALUE),
            (F.S1_DETAIL_SAMPLE_SIZE, F.E1_SAMPLE_SIZE),
            (F.S1_DETAIL_TOTAL,),
            (F.E2_VALUE, F.D1_VALUE, F.D2_VALUE),
            (F.S2_DETAIL_SAMPLE_SIZE, F.E2_SAMPLE_SIZE),
            (F.S2_DETAIL_TOTAL,),
            (F.E3_TEXT,),
        ))
        authored = {F.S1_TITLE, F.S1_DETAIL, F.S2_TITLE, F.S2_DETAIL, F.S3_TITLE, F.S3_DETAIL}
        self.assertFalse(any(authored.intersection(b.affected_fields) for b in provenance.qualifications))

    def test_empty_qualifications(self):
        provenance = adapt(example()).provenance
        self.assertEqual(provenance.qualifications, ())
        self.assertEqual(tuple(record.qualifications for record in provenance.evidence), ((),) * 7)


class ResourceTests(unittest.TestCase):
    assertFailure = ProjectionTests.assertFailure

    def test_title_codepoint_boundary_and_over_each_source(self):
        g, v, m = example()
        for name in ('s1', 's2', 's3'):
            source = replace(getattr(m, name), title='🙂' * 256)
            self.assertEqual(adapt((g, v, replace(m, **{name: source}))).legacy_evidence['sources'][int(name[1]) - 1]['title'], '🙂' * 256)
            self.assertFailure((g, v, replace(m, **{name: replace(source, title='🙂' * 257)})), 'resource_limit')

    def test_detail_boundary_and_over(self):
        g, v, m = example()
        self.assertEqual(adapt((g, v, replace(m, s3=replace(m.s3, detail='🙂' * 1024)))).legacy_evidence['sources'][2]['detail'], '🙂' * 1024)
        for name in ('s1', 's2', 's3'):
            self.assertFailure((g, v, replace(m, **{name: replace(getattr(m, name), detail='x' * 1025)})), 'resource_limit')

    def test_evidence_text_boundary_and_over(self):
        base = ['record ' + str(i) for i in range(7)]
        for index in range(7):
            texts = base.copy()
            texts[index] = 'x' * 8192
            self.assertEqual(adapt(example(texts=tuple(texts))).provenance.evidence[index].text, texts[index])
            texts[index] += 'x'
            self.assertFailure(example(texts=tuple(texts)), 'resource_limit')

    def test_qualification_length_boundary_and_over(self):
        quals = [('é' * 2048,)] + [()] * 6
        self.assertEqual(adapt(example(qualifications=tuple(quals))).provenance.evidence[0].qualifications, quals[0])
        quals[0] = ('é' * 2049,)
        self.assertFailure(example(qualifications=tuple(quals)), 'resource_limit')

    def test_qualification_per_record_boundary_and_over(self):
        for index in range(7):
            quals = [()] * 7
            quals[index] = ('q',) * 32
            self.assertEqual(len(adapt(example(qualifications=tuple(quals))).provenance.qualifications), 32)
            quals[index] += ('q',)
            self.assertFailure(example(qualifications=tuple(quals)), 'resource_limit')

    def test_total_qualification_boundary_and_over(self):
        quals = (('q',) * 32,) * 4 + ((),) * 3
        self.assertEqual(len(adapt(example(qualifications=quals)).provenance.qualifications), 128)
        self.assertFailure(example(qualifications=quals[:4] + (('q',), (), ())), 'resource_limit')

    def test_metadata_exact_utf8_boundary_and_one_byte_over(self):
        texts = ['x'] * 6 + ['🙂' * 2000]
        baseline = adapt(example(texts=tuple(texts))).provenance
        remaining = 65536 - logical_bytes(baseline)
        for index in range(6):
            amount = min(remaining, 8191)
            texts[index] += 'x' * amount
            remaining -= amount
        self.assertEqual(remaining, 0)
        case = example(texts=tuple(texts))
        result = adapt(case)
        self.assertEqual(logical_bytes(result.provenance), 65536)
        for index in range(6):
            if len(texts[index]) < 8192:
                texts[index] += 'x'
                break
        self.assertFailure(example(texts=tuple(texts)), 'resource_limit')

    def test_metadata_equal_strings_not_deduplicated(self):
        texts = ('x' * 8000,) * 6 + ('qualitative',)
        shared = example(texts=texts)
        distinct = example(texts=tuple(bytearray(t.encode()).decode() for t in texts))
        self.assertIs(texts[0], texts[1])
        self.assertEqual(adapt(shared).provenance, adapt(distinct).provenance)
        # Duplication in qualifications counts every occurrence too.
        quals = (('x' * 2048,) * 32,) + ((),) * 6
        self.assertFailure(example(qualifications=quals), 'resource_limit')

    def test_extra_graph_nodes_not_selected_or_counted(self):
        case = example(extra=True)
        g, _, m = case
        g.derive(q.Operation.ADD, left_id=m.e1_value_id, right_id=m.e2_value_id)
        result = adapt(case)
        self.assertEqual(len(g.nodes), 10)
        self.assertEqual(len(result.provenance.facts), 6)
        self.assertEqual(len(result.provenance.derivations), 2)
        self.assertNotIn(g.nodes[6].quantity_id, tuple(f.quantity_id for f in result.provenance.facts))


class IsolationAndBoundaryTests(unittest.TestCase):
    assertFailure = ProjectionTests.assertFailure

    def test_frozen_nested_provenance_no_controllers_or_rectangles(self):
        result = adapt(example())
        def visit(value):
            self.assertNotIsInstance(value, (q.QuantityGraph, EvidenceVerification, CSVExtraction, TextExtraction, list, dict, set))
            if is_dataclass(value):
                self.assertTrue(value.__dataclass_params__.frozen)
                for field in fields(value):
                    with self.assertRaises(FrozenInstanceError):
                        setattr(value, field.name, getattr(value, field.name))
                    visit(getattr(value, field.name))
            elif type(value) is tuple:
                for item in value:
                    visit(item)
        visit(result.provenance)
        with self.assertRaises(FrozenInstanceError):
            result.legacy_evidence = {}
        for cls in (adapter.SourcePresentation, adapter.Milestone1DemoMapping, adapter.EvidenceCapture,
                    adapter.FactCapture, adapter.DerivedCapture, adapter.QuantityOrigin,
                    adapter.ReproducedTextOrigin, adapter.AuthoredMappingOrigin, adapter.FieldBinding,
                    adapter.QualificationBinding, adapter.Milestone1Provenance, adapter.Milestone1Adaptation):
            self.assertTrue(cls.__dataclass_params__.frozen)

    def test_legacy_mutation_isolated_from_provenance_inputs_and_second_result(self):
        case = example()
        before = state(case[0])
        first, second = adapt(case), adapt(case)
        saved = deepcopy(first.provenance)
        expected = deepcopy(second.legacy_evidence)
        first.legacy_evidence['sources'][0]['detail'] = 'changed'
        first.legacy_evidence['calculations'][0]['input_ids'].append('E3')
        first.legacy_evidence['evidence'][2]['text'] = 'changed'
        first.legacy_evidence['sources'].clear()
        self.assertEqual(first.provenance, saved)
        self.assertEqual(second.legacy_evidence, expected)
        self.assertEqual(adapt(case).legacy_evidence, expected)
        self.assertEqual(state(case[0]), before)

    def test_later_supported_graph_addition_cannot_change_capture(self):
        case = example()
        g, _, m = case
        first = adapt(case)
        captured = deepcopy(first.provenance)
        g.derive(q.Operation.ADD, left_id=m.e1_value_id, right_id=m.e2_value_id)
        self.assertEqual(first.provenance, captured)
        self.assertEqual(adapt(case).provenance, captured)

    def test_mapping_only_changes_do_not_change_normalized_identities(self):
        g, v, m = example()
        before = tuple(node.quantity_id for node in g.nodes), tuple(node.evidence_id for node in g.nodes[:6]), v.record.evidence_id
        first = adapt((g, v, m))
        other = replace(m, s1=replace(m.s1, title='New authored title'),
                        s3=replace(m.s3, detail='New authored detail'))
        second = adapt((g, v, other))
        self.assertEqual(first.provenance.facts, second.provenance.facts)
        self.assertEqual(first.provenance.derivations, second.provenance.derivations)
        self.assertEqual(first.provenance.evidence, second.provenance.evidence)
        self.assertNotEqual(first.provenance.mapping, second.provenance.mapping)
        self.assertEqual((tuple(node.quantity_id for node in g.nodes), tuple(node.evidence_id for node in g.nodes[:6]), v.record.evidence_id), before)

    def test_diagnostics_private_bounded_and_chaining_suppressed(self):
        secret = 'PRIVATE_SOURCE_🙂'
        g, v, m = example(qualifications=((secret,),) * 7, texts=(secret,) * 7)
        cases = [((g, v, replace(m, s1=replace(m.s1, detail=secret))), 'invalid_mapping'),
                 ((g, v, replace(m, difference_id='qd1:' + 'f' * 64)), 'missing_quantity'),
                 ((g, replace(v, extraction=replace(v.extraction, text=secret + '!')), m), 'qualitative_support'),
                 ((g, v, replace(m, s3=replace(m.s3, title=secret * 500))), 'resource_limit')]
        for case, prefix in cases:
            error = self.assertFailure(case, prefix)
            self.assertNotIn(secret, str(error))
            self.assertLess(len(str(error)), 100)
            self.assertIsNone(error.__cause__)
            self.assertTrue(error.__suppress_context__)
        # Exercise translation of a normalized validator exception without using
        # unsupported mutation of frozen input objects.
        with patch.object(EvidenceRecord, '__post_init__', side_effect=ValueError(secret)):
            try:
                adapt((g, v, m))
            except ValueError as error:
                formatted = ''.join(traceback.format_exception(type(error), error, error.__traceback__))
                self.assertNotIn(secret, formatted)
                self.assertIsNone(error.__cause__)
                self.assertTrue(error.__suppress_context__)
            else:
                self.fail('expected rejection')

    def test_early_late_and_success_leave_all_graph_state_unchanged(self):
        g, v, m = example()
        before = state(g)
        self.assertFailure((g, v, replace(m, synthetic=False)), 'invalid_mapping')
        self.assertFailure((g, v, replace(m, s2=replace(m.s2, detail='late mismatch'))), 'invalid_mapping')
        adapt((g, v, m))
        self.assertEqual(state(g), before)

    def test_no_io_verification_graph_mutation_or_m1_runtime_calls(self):
        case = example()
        forbidden = [
            'builtins.open', 'io.open', 'os.open', 'socket.socket',
            'presentation_agent.source_capture.SourceStore.read',
            'presentation_agent.source_capture.SourceStore.capture',
            'presentation_agent.quantities.QuantityGraph.__init__',
            'presentation_agent.source_extraction.extract_csv',
            'presentation_agent.source_extraction.extract_text',
            'presentation_agent.evidence_verification.verify_evidence',
            'presentation_agent.quantities.QuantityGraph.add_fact',
            'presentation_agent.quantities.QuantityGraph.derive',
        ]
        # The AST check below additionally excludes all M1 runtime imports.
        with ExitStack() as stack:
            for target in forbidden:
                stack.enter_context(patch(target, side_effect=AssertionError('forbidden call')))
            result = adapt(case)
        self.assertEqual(result.legacy_evidence['calculations'][0]['value'], 25)

    def test_module_ast_boundary_and_python39_syntax(self):
        source = Path(adapter.__file__).read_text()
        tree = ast.parse(source, feature_version=9)
        relative, absolute = set(), set()
        forbidden_calls = {'add_fact', 'derive', 'verify_evidence', 'extract_csv', 'extract_text',
                           'compose', 'render', 'open', 'QuantityGraph'}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                (relative if node.level else absolute).add(node.module)
            elif isinstance(node, ast.Import):
                absolute.update(alias.name for alias in node.names)
            elif isinstance(node, ast.Call):
                called = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ''
                self.assertNotIn(called, forbidden_calls)
        self.assertEqual(relative, {'evidence', 'evidence_verification', 'source_extraction', 'quantities'})
        self.assertLessEqual(absolute, {'dataclasses', 'decimal', 'enum', 're', 'typing'})
        # No executable top-level expressions or assigned function calls.
        for node in tree.body:
            if isinstance(node, ast.Expr):
                self.assertIsInstance(node.value, ast.Constant)
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                self.assertFalse(any(isinstance(child, ast.Call) for child in ast.walk(node)))
        root = Path(adapter.__file__).parent
        for name in ('evidence.py', 'evidence_verification.py', 'source_extraction.py', 'quantities.py', '__init__.py'):
            self.assertNotIn('milestone1_adapter', (root / name).read_text())


if __name__ == '__main__':
    unittest.main()
