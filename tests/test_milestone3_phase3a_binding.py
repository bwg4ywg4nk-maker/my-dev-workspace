"""Structural binding, qualification, citation, resource, and trust boundaries."""
import ast
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import FrozenInstanceError, fields, replace
from pathlib import Path
import unittest
from unittest.mock import PropertyMock, patch

from presentation_agent import content as c, content_binding as b, quantities as q
from presentation_agent.evidence import CSVLocator, EvidenceRecord, TextLocator
from presentation_agent.evidence_verification import (
    EvidenceVerification, QualificationVerification as QV, StructuredCells, TextReproduction,
)
from presentation_agent.source_extraction import CSVExtraction


S1 = 'sha256:' + '1' * 64
S2 = 'sha256:' + '2' * 64
S3 = 'sha256:' + '3' * 64
MISSING_EV = 'ev1:' + 'f' * 64
MISSING_Q = 'qf1:' + 'f' * 64
CELL = CSVLocator(1, 1, 1, 1)
UNIT = q.Unit(q.UnitKind.NAMED, 'count')


def record(text='evidence', snapshot=S1, qualifications=()):
    return EvidenceRecord(snapshot, TextLocator(1, 1), text, qualifications)


def fact(graph, raw='2', snapshot=S1, qualifications=(), text='reported'):
    owner = EvidenceRecord(snapshot, CELL, text, qualifications)
    verification = EvidenceVerification(
        owner, CSVExtraction(snapshot, CELL, ((raw,),)), TextReproduction.NOT_ASSESSED,
        StructuredCells.AVAILABLE, QV.UNVERIFIED)
    return graph.add_fact(verification, cell=CELL, numeric_type=q.NumericType.INTEGER, unit=UNIT)


def ancestry(qualifications=('same', 'same')):
    graph = q.QuantityGraph()
    a = fact(graph, '2', qualifications=qualifications)
    d = fact(graph, '3', snapshot=S2, qualifications=('same',))
    unused = fact(graph, '7', snapshot=S3)
    middle = graph.derive(q.Operation.SUBTRACT, left_id=d.quantity_id, right_id=a.quantity_id)
    root = graph.derive(q.Operation.ADD, left_id=middle.quantity_id, right_id=a.quantity_id)
    return graph, a, d, middle, root, unused


def selection_bundle(*nodes):
    return c.ContentBundle(quantity_selections=(c.QuantitySelection('selected', tuple(n.quantity_id for n in nodes)),))


def graph_state(graph):
    # Test-only complete snapshot; production accesses only public get().
    return deepcopy(vars(graph))


class BindingTests(unittest.TestCase):
    def test_direct_evidence_and_unused_exclusion(self):
        used, unused = record(), record('unused', S2)
        claim = c.Claim('Authored', (used.evidence_id,))
        bound = b.bind_content(c.ContentBundle((claim,)), evidence=(unused, used))
        self.assertEqual(bound.evidence, (used,))
        self.assertIs(bound.evidence[0], used)
        self.assertEqual(bound.quantities, ())
        self.assertEqual(bound.bindings, (b.ContentBinding(claim.claim_id, (used.evidence_id,), (), (S1,), ()),))

    def test_direct_quantity_retains_original_objects(self):
        graph = q.QuantityGraph()
        node = fact(graph)
        bound = b.bind_content(selection_bundle(node), quantities=graph)
        self.assertIs(bound.quantities[0], node)
        self.assertIs(bound.evidence[0], node.verification.record)
        self.assertEqual(bound.bindings[0].quantity_ids, (node.quantity_id,))
        self.assertEqual(bound.bindings[0].snapshot_ids, (S1,))

    def test_nested_mixed_ancestry_and_ordered_operands(self):
        graph, a, d, middle, root, unused = ancestry()
        original = graph.get
        calls = []
        def get(identity):
            calls.append(identity)
            return original(identity)
        with patch.object(graph, 'get', side_effect=get):
            bound = b.bind_content(selection_bundle(root), quantities=graph)
        self.assertEqual(calls, [root.quantity_id, middle.quantity_id, d.quantity_id, a.quantity_id])
        self.assertEqual(bound.quantities, tuple(sorted((a, d, middle, root), key=lambda n: n.quantity_id)))
        self.assertEqual(bound.bindings[0].snapshot_ids, (S1, S2))
        self.assertNotIn(unused, bound.quantities)
        self.assertNotIn(unused.verification.record, bound.evidence)
        self.assertEqual(middle.input_ids, (d.quantity_id, a.quantity_id))
        self.assertTrue(all(any(n is original_node for n in bound.quantities) for original_node in (a, d, middle, root)))

    def test_mixed_direct_evidence_and_quantity_ancestry(self):
        graph, a, d, middle, root, _ = ancestry()
        explicit = record(snapshot=S3)
        claim = c.Claim('mixed', (explicit.evidence_id,), (root.quantity_id, a.quantity_id))
        bound = b.bind_content(c.ContentBundle((claim,)), evidence=(explicit,), quantities=graph)
        self.assertEqual(bound.bindings[0].snapshot_ids, (S1, S2, S3))
        self.assertEqual(len(bound.bindings[0].quantity_ids), 4)
        self.assertEqual(len(bound.evidence), 3)

    def test_missing_evidence(self):
        with self.assertRaisesRegex(ValueError, 'Missing evidence'):
            b.bind_content(c.ContentBundle((c.Claim('x', (MISSING_EV,)),)))

    def test_missing_root_becomes_value_error(self):
        with self.assertRaisesRegex(ValueError, 'Missing quantity'):
            b.bind_content(c.ContentBundle((c.Claim('x', quantity_ids=(MISSING_Q,)),)), quantities=q.QuantityGraph())

    def test_missing_ancestor_becomes_value_error(self):
        graph, a, _, _, root, _ = ancestry()
        original = graph.get
        def get(identity):
            if identity == a.quantity_id:
                raise KeyError(identity)
            return original(identity)
        with patch.object(graph, 'get', side_effect=get), self.assertRaisesRegex(ValueError, 'Missing quantity'):
            b.bind_content(selection_bundle(root), quantities=graph)

    def test_get_wrong_node_type_and_requested_identity(self):
        graph = q.QuantityGraph()
        a, other = fact(graph), fact(graph, '3')
        class SubNode(q.DirectQuantity):
            pass
        subnode = SubNode(a.verification, a.cell, a.numeric_type, a.unit, a.value)
        for bad in (None, {}, a.verification.record, other, subnode):
            with self.subTest(bad=type(bad)), patch.object(graph, 'get', return_value=bad), self.assertRaises(ValueError):
                b.bind_content(selection_bundle(a), quantities=graph)

    def test_empty_bundle(self):
        bound = b.bind_content(c.ContentBundle(), evidence=(record(),), quantities=q.QuantityGraph())
        self.assertEqual(bound, b.BoundContent(c.ContentBundle(), (), (), ()))

    def test_only_exact_graph_authority(self):
        graph = q.QuantityGraph()
        node = fact(graph)
        derived = graph.derive(q.Operation.ADD, left_id=node.quantity_id, right_id=node.quantity_id)
        class SubGraph(q.QuantityGraph):
            pass
        for bad in (node, derived, (node,), [node], {}, SubGraph()):
            with self.assertRaises(ValueError):
                b.bind_content(selection_bundle(node), quantities=bad)
        with self.assertRaises(ValueError):
            b.bind_content(selection_bundle(node))

    def test_exact_argument_types(self):
        class SubBundle(c.ContentBundle):
            pass
        class SubLimits(c.ContentLimits):
            pass
        class SubEvidence(EvidenceRecord):
            pass
        for bad in (None, (), {}, SubBundle()):
            with self.assertRaises(ValueError):
                b.bind_content(bad)
        for bad in ([], None, record(), (None,), (SubEvidence(S1, TextLocator(1, 1), 'x'),)):
            with self.assertRaises(ValueError):
                b.bind_content(c.ContentBundle(), evidence=bad)
        for bad in (None, {}, SubLimits()):
            with self.assertRaises(ValueError):
                b.bind_content(c.ContentBundle(), limits=bad)

    def test_bundle_invariants_rechecked_without_mutation(self):
        bundle = c.ContentBundle((c.Claim('a', (MISSING_EV,)), c.Claim('b', (MISSING_EV,))))
        object.__setattr__(bundle, 'claims', bundle.claims[::-1])
        before = deepcopy(bundle)
        with self.assertRaises(ValueError):
            b.bind_content(bundle)
        self.assertEqual(bundle, before)

    def test_evidence_and_locator_invariants_rechecked(self):
        for attribute, value in [('text', ''), ('qualifications', []), ('snapshot_id', 'invalid')]:
            bad = record()
            object.__setattr__(bad, attribute, value)
            with self.assertRaises(ValueError):
                b.bind_content(c.ContentBundle(), evidence=(bad,))
        bad = record()
        object.__setattr__(bad.locator, 'line_start', True)
        with self.assertRaises(ValueError):
            b.bind_content(c.ContentBundle(), evidence=(bad,))

    def test_duplicate_explicit_even_equal_unused(self):
        owner = record()
        for duplicate in (owner, replace(owner)):
            with self.assertRaisesRegex(ValueError, 'Duplicate'):
                b.bind_content(c.ContentBundle(), evidence=(owner, duplicate))

    def test_equal_retained_evidence_merges_and_explicit_merge(self):
        graph = q.QuantityGraph()
        a, d = fact(graph, '2'), fact(graph, '3')
        self.assertEqual(a.verification.record, d.verification.record)
        self.assertIsNot(a.verification.record, d.verification.record)
        bound = b.bind_content(selection_bundle(a, d), quantities=graph, evidence=(replace(a.verification.record),))
        self.assertEqual(len(bound.evidence), 1)
        self.assertEqual(len(bound.quantities), 2)

    def test_conflicting_evidence_same_id_explicit_and_retained(self):
        graph = q.QuantityGraph()
        a, d = fact(graph, text='one'), fact(graph, '3', text='two')
        # Simulate a digest collision through the public computed property.
        with patch.object(EvidenceRecord, 'evidence_id', new_callable=PropertyMock, return_value=MISSING_EV):
            for explicit, nodes in [((record('conflict'),), (a,)), ((), (a, d)),
                                    ((record('one'), record('two')), ())]:
                bundle = selection_bundle(*nodes) if nodes else c.ContentBundle()
                lookup = {node.quantity_id: node for node in nodes}
                with patch.object(graph, 'get', side_effect=lookup.__getitem__), self.assertRaisesRegex(ValueError, 'conflicting'):
                    b.bind_content(bundle, evidence=explicit, quantities=graph)

    def test_cross_member_retained_evidence_resolution_without_ancestry_inheritance(self):
        graph = q.QuantityGraph()
        a = fact(graph, qualifications=('caveat',))
        claim = c.Claim('Direct retained reference', (a.evidence_id,))
        selection = c.QuantitySelection('a', (a.quantity_id,))
        bound = b.bind_content(c.ContentBundle((claim,), (selection,)), quantities=graph)
        by_id = {item.content_id: item for item in bound.bindings}
        self.assertEqual(by_id[claim.claim_id].quantity_ids, ())
        self.assertEqual(by_id[claim.claim_id].evidence_ids, (a.evidence_id,))
        self.assertEqual(by_id[selection.selection_id].quantity_ids, (a.quantity_id,))
        self.assertEqual(len(by_id[claim.claim_id].qualifications), 1)

    def test_unrelated_graph_evidence_cannot_resolve_claim(self):
        graph = q.QuantityGraph()
        node = fact(graph)
        claim = c.Claim('x', (node.evidence_id,))
        with patch.object(graph, 'get', side_effect=AssertionError('unrelated lookup')):
            with self.assertRaisesRegex(ValueError, 'Missing evidence'):
                b.bind_content(c.ContentBundle((claim,)), quantities=graph)

    def test_deterministic_member_and_reference_and_explicit_permutations(self):
        graph, a, d, _, root, _ = ancestry()
        e1, e2 = record('a'), record('b', S3)
        claims = (c.Claim('a', (e2.evidence_id, e1.evidence_id), (root.quantity_id,)),
                  c.Claim('b', quantity_ids=(d.quantity_id, a.quantity_id)))
        selections = (c.QuantitySelection('z', (a.quantity_id,)), c.QuantitySelection('a', (root.quantity_id,)))
        first = b.bind_content(c.ContentBundle(claims, selections), evidence=(e1, e2), quantities=graph)
        second = b.bind_content(c.ContentBundle(claims[::-1], selections[::-1]), evidence=(e2, e1), quantities=graph)
        self.assertEqual(first, second)
        self.assertEqual(tuple(x.content_id for x in first.bindings), tuple(sorted(x.content_id for x in first.bindings)))
        self.assertEqual(tuple(x.evidence_id for x in first.evidence), tuple(sorted(x.evidence_id for x in first.evidence)))
        for binding in first.bindings:
            for name in ('evidence_ids', 'quantity_ids', 'snapshot_ids'):
                values = getattr(binding, name)
                self.assertEqual(values, tuple(sorted(set(values))))

    def test_success_and_late_failure_are_atomic_and_pure(self):
        graph, _, _, _, root, _ = ancestry()
        bundle = selection_bundle(root)
        before, bundle_before = graph_state(graph), deepcopy(bundle)
        success = b.bind_content(bundle, quantities=graph)
        retained = deepcopy(success)
        late = c.ContentBundle((c.Claim('unresolved', (MISSING_EV,)),), bundle.quantity_selections)
        with self.assertRaisesRegex(ValueError, 'Missing evidence'):
            b.bind_content(late, quantities=graph)
        self.assertEqual(graph_state(graph), before)
        self.assertEqual(bundle, bundle_before)
        self.assertEqual(success, retained)
        self.assertEqual(b.bind_content(bundle, quantities=graph), success)

    def test_result_does_not_retain_controller_or_follow_future_graph_changes(self):
        graph, a, d, _, root, _ = ancestry()
        bound = b.bind_content(selection_bundle(root), quantities=graph)
        before = deepcopy(bound)
        self.assertNotIn('graph', vars(bound))
        self.assertTrue(all(type(value) is not q.QuantityGraph for value in vars(bound).values()))
        graph.derive(q.Operation.ADD, left_id=d.quantity_id, right_id=a.quantity_id)
        self.assertEqual(bound, before)


class QualificationTests(unittest.TestCase):
    def test_evidence_and_authored_occurrences_exact_order_and_status(self):
        graph, a, d, _, root, _ = ancestry()
        claim = c.Claim('x', (a.evidence_id,), (root.quantity_id,), (' own\n', 'same', 'same'))
        bound = b.bind_content(c.ContentBundle((claim,)), quantities=graph)
        expected = []
        for owner in sorted((a.verification.record, d.verification.record), key=lambda e: e.evidence_id):
            expected.extend(b.QualificationBinding(owner.evidence_id, i, text, c.QualificationOrigin.EVIDENCE, QV.UNVERIFIED)
                            for i, text in enumerate(owner.qualifications))
        expected.extend(b.QualificationBinding(claim.claim_id, i, text, c.QualificationOrigin.AUTHORED, None)
                        for i, text in enumerate(claim.qualifications))
        self.assertEqual(bound.bindings[0].qualifications, tuple(expected))
        self.assertEqual(len(expected), 6)

    def test_selection_carries_all_owner_qualifications_without_scope_inference(self):
        graph = q.QuantityGraph()
        owner = EvidenceRecord(S1, CSVLocator(1, 1, 1, 2), 'two cells', ('first cell only', 'second cell only'))
        verification = EvidenceVerification(owner, CSVExtraction(S1, owner.locator, (('2', '3'),)),
                                            TextReproduction.NOT_ASSESSED, StructuredCells.AVAILABLE, QV.UNVERIFIED)
        node = graph.add_fact(verification, cell=CELL, numeric_type=q.NumericType.INTEGER, unit=UNIT)
        bound = b.bind_content(selection_bundle(node), quantities=graph)
        self.assertEqual(tuple(x.text for x in bound.bindings[0].qualifications), owner.qualifications)
        self.assertTrue(all(x.origin is c.QualificationOrigin.EVIDENCE and x.verification is QV.UNVERIFIED
                            for x in bound.bindings[0].qualifications))

    def test_repeated_paths_deduplicate_only_owner_and_index(self):
        graph, a, d, _, root, _ = ancestry()
        bound = b.bind_content(selection_bundle(root, a), quantities=graph)
        qualifications = bound.bindings[0].qualifications
        self.assertEqual(len(qualifications), 3)
        self.assertEqual(tuple(x.text for x in qualifications), ('same',) * 3)
        self.assertEqual(len({(x.owner_id, x.qualification_index) for x in qualifications}), 3)

    def test_no_qualifications(self):
        owner = record()
        bound = b.bind_content(c.ContentBundle((c.Claim('x', (owner.evidence_id,)),)), evidence=(owner,))
        self.assertEqual(bound.bindings[0].qualifications, ())

    def test_qualification_model_validation(self):
        valid = b.QualificationBinding(MISSING_EV, 0, 'text', c.QualificationOrigin.EVIDENCE, QV.UNVERIFIED)
        for kwargs in ({'qualification_index': True}, {'qualification_index': -1}, {'qualification_index': 0.0},
                       {'text': ''}, {'text': 1}, {'origin': 'evidence'}, {'verification': None},
                       {'owner_id': 'cl1:' + 'a' * 64}):
            with self.assertRaises(ValueError):
                replace(valid, **kwargs)
        authored = b.QualificationBinding('cl1:' + 'a' * 64, 0, 'text', c.QualificationOrigin.AUTHORED, None)
        with self.assertRaises(ValueError):
            replace(authored, verification=QV.UNVERIFIED)
        self.assertEqual(list(QV), [QV.UNVERIFIED])


class CitationTests(unittest.TestCase):
    def setUp(self):
        self.graph, _, _, _, root, _ = ancestry()
        self.bound = b.bind_content(selection_bundle(root), quantities=self.graph)

    def test_binding_needs_no_metadata(self):
        self.assertEqual(self.bound.bindings[0].snapshot_ids, (S1, S2))

    def test_missing(self):
        result = b.assess_citations(self.bound)
        self.assertEqual(result.referenced_snapshot_ids, (S1, S2))
        self.assertEqual(result.missing_snapshot_ids, (S1, S2))
        self.assertEqual(result.incomplete_snapshot_ids, ())
        self.assertFalse(result.is_complete)

    def test_each_missing_field_and_both_missing(self):
        for metadata in (c.SnapshotCitationMetadata(S1), c.SnapshotCitationMetadata(S1, 'title'),
                         c.SnapshotCitationMetadata(S1, bibliographic_detail='detail')):
            result = b.assess_citations(self.bound, (metadata,))
            self.assertEqual(result.missing_snapshot_ids, (S2,))
            self.assertEqual(result.incomplete_snapshot_ids, (S1,))
            self.assertFalse(result.is_complete)

    def test_complete_sorted_retained_metadata_and_unused_incomplete(self):
        metadata = (c.SnapshotCitationMetadata(S3), c.SnapshotCitationMetadata(S2, 't', 'd'),
                    c.SnapshotCitationMetadata(S1, 't', 'd'))
        result = b.assess_citations(self.bound, metadata)
        self.assertTrue(result.is_complete)
        self.assertEqual(result.metadata, tuple(sorted(metadata, key=lambda x: x.snapshot_id)))
        self.assertEqual(result.unused_snapshot_ids, (S3,))
        self.assertEqual(result.incomplete_snapshot_ids, ())
        self.assertEqual(result, b.assess_citations(self.bound, metadata[::-1]))

    def test_empty_bound_complete_with_unused_metadata(self):
        bound = b.bind_content(c.ContentBundle())
        self.assertTrue(b.assess_citations(bound).is_complete)
        result = b.assess_citations(bound, (c.SnapshotCitationMetadata(S3),))
        self.assertTrue(result.is_complete)
        self.assertEqual(result.unused_snapshot_ids, (S3,))

    def test_duplicate_metadata_even_unused(self):
        metadata = c.SnapshotCitationMetadata(S3)
        with self.assertRaises(ValueError):
            b.assess_citations(self.bound, (metadata, replace(metadata, title='different')))

    def test_malformed_metadata_and_unused_entries_validated(self):
        class SubMetadata(c.SnapshotCitationMetadata):
            pass
        for bad in (None, {}, SubMetadata(S3)):
            with self.assertRaises(ValueError):
                b.assess_citations(self.bound, (bad,))
        for name, bad in [('snapshot_id', 'bad'), ('title', ''), ('title', 1),
                          ('bibliographic_detail', '\t'), ('bibliographic_detail', False)]:
            metadata = c.SnapshotCitationMetadata(S3)
            object.__setattr__(metadata, name, bad)
            with self.assertRaises(ValueError):
                b.assess_citations(self.bound, (metadata,))

    def test_exact_argument_types_and_limits(self):
        class SubBound(b.BoundContent):
            pass
        class SubLimits(c.ContentLimits):
            pass
        for bad in (None, {}, SubBound(c.ContentBundle(), (), (), ())):
            with self.assertRaises(ValueError):
                b.assess_citations(bad)
        for bad in ([], None, c.SnapshotCitationMetadata(S1)):
            with self.assertRaises(ValueError):
                b.assess_citations(self.bound, bad)
        for bad in (None, {}, SubLimits()):
            with self.assertRaises(ValueError):
                b.assess_citations(self.bound, limits=bad)

    def test_metadata_does_not_change_identity_or_upgrade_verification(self):
        before = deepcopy(self.bound)
        ids = tuple(m.selection_id for m in self.bound.bundle.quantity_selections)
        result = b.assess_citations(self.bound, (c.SnapshotCitationMetadata(S1, 'inaccurate', 'invented'),
                                                c.SnapshotCitationMetadata(S2, 'inaccurate', 'invented')))
        self.assertTrue(result.is_complete)  # Presence only, not bibliographic accuracy.
        self.assertEqual(self.bound, before)
        self.assertEqual(tuple(m.selection_id for m in self.bound.bundle.quantity_selections), ids)
        self.assertTrue(all(x.verification is QV.UNVERIFIED for x in self.bound.bindings[0].qualifications))
        owner = record()
        claim = c.Claim('false', (owner.evidence_id,))
        bound = b.bind_content(c.ContentBundle((claim,)), evidence=(owner,))
        b.assess_citations(bound, (c.SnapshotCitationMetadata(S1, 't', 'd'),))
        self.assertEqual(bound.bundle.claims[0].claim_id, claim.claim_id)
        self.assertFalse(hasattr(claim, 'verification'))


class ResourceTests(unittest.TestCase):
    def assert_budget(self, bundle, expected, *, evidence=(), graph=None):
        before = graph_state(graph) if graph is not None else None
        result = b.bind_content(bundle, evidence=evidence, quantities=graph,
                                limits=c.ContentLimits(max_binding_steps=expected))
        if expected > 1:
            with self.assertRaisesRegex(ValueError, 'step limit'):
                b.bind_content(bundle, evidence=evidence, quantities=graph,
                               limits=c.ContentLimits(max_binding_steps=expected - 1))
        if graph is not None:
            self.assertEqual(graph_state(graph), before)
        return result

    def test_explicit_indexing_only_budget(self):
        self.assert_budget(c.ContentBundle(), 2, evidence=(record('a'), record('b')))

    def test_member_direct_reference_evidence_snapshot_budget(self):
        owner = record()
        # explicit + member + reference + evidence visit + snapshot
        self.assert_budget(c.ContentBundle((c.Claim('x', (owner.evidence_id,)),)), 5, evidence=(owner,))

    def test_direct_quantity_visit_budget(self):
        graph = q.QuantityGraph()
        a = fact(graph)
        # member + reference + quantity visit + evidence visit + snapshot
        self.assert_budget(selection_bundle(a), 5, graph=graph)

    def test_repeated_operand_positions_budget(self):
        graph = q.QuantityGraph()
        a = fact(graph)
        root = graph.derive(q.Operation.ADD, left_id=a.quantity_id, right_id=a.quantity_id)
        # member + ref + two nodes + two operand positions + evidence + snapshot
        self.assert_budget(selection_bundle(root), 8, graph=graph)

    def test_repeated_paths_and_nested_edges_budget(self):
        graph, _, _, _, root, _ = ancestry(qualifications=())
        # 1 member + 1 ref + 4 nodes + 4 edges + 2 evidence + 1 qual + 2 snapshots
        self.assert_budget(selection_bundle(root), 15, graph=graph)

    def test_shared_ancestry_across_members_budget(self):
        graph = q.QuantityGraph()
        a = fact(graph)
        bundle = c.ContentBundle((c.Claim('x', quantity_ids=(a.quantity_id,)),),
                                 (c.QuantitySelection('y', (a.quantity_id,)),))
        self.assert_budget(bundle, 10, graph=graph)

    def test_explicit_and_retained_are_separate_charges(self):
        graph = q.QuantityGraph()
        a = fact(graph)
        claim = c.Claim('x', (a.evidence_id,), (a.quantity_id,))
        self.assert_budget(c.ContentBundle((claim,)), 7, evidence=(a.verification.record,), graph=graph)

    def test_repeated_qualifications_charged_per_occurrence(self):
        owner = record(qualifications=('q', 'q'))
        claim = c.Claim('x', (owner.evidence_id,), qualifications=('q', 'q', 'q'))
        self.assert_budget(c.ContentBundle((claim,)), 10, evidence=(owner,))

    def test_shared_snapshot_charged_once_per_member(self):
        a, d = record('a'), record('b')
        claim = c.Claim('x', (a.evidence_id, d.evidence_id))
        # 2 explicit + member + 2 refs + 2 evidence visits + 1 snapshot
        self.assert_budget(c.ContentBundle((claim,)), 8, evidence=(a, d))

    def test_equal_retained_evidence_memoization_does_not_change_budget(self):
        graph = q.QuantityGraph()
        a, d = fact(graph, '2'), fact(graph, '3')
        # member + 2 refs + 2 quantity visits + 1 evidence visit + 1 snapshot
        self.assert_budget(selection_bundle(a, d), 7, graph=graph)

    def test_shared_path_get_once_per_member_but_charged_for_each_member(self):
        graph = q.QuantityGraph()
        a = fact(graph)
        root = graph.derive(q.Operation.ADD, left_id=a.quantity_id, right_id=a.quantity_id)
        bundle = c.ContentBundle((c.Claim('x', quantity_ids=(root.quantity_id,)),),
                                 (c.QuantitySelection('s', (root.quantity_id,)),))
        with patch.object(graph, 'get', wraps=graph.get) as get:
            b.bind_content(bundle, quantities=graph, limits=c.ContentLimits(max_binding_steps=16))
            self.assertEqual(get.call_count, 4)
        self.assert_budget(bundle, 16, graph=graph)

    def test_cross_member_pool_budget(self):
        graph = q.QuantityGraph()
        a = fact(graph)
        bundle = c.ContentBundle((c.Claim('x', (a.evidence_id,)),),
                                 (c.QuantitySelection('s', (a.quantity_id,)),))
        self.assert_budget(bundle, 9, graph=graph)

    def test_charges_before_get_action(self):
        graph = q.QuantityGraph()
        a = fact(graph)
        with patch.object(graph, 'get', side_effect=AssertionError('not charged yet')):
            with self.assertRaisesRegex(ValueError, 'step limit'):
                b.bind_content(selection_bundle(a), quantities=graph, limits=c.ContentLimits(max_binding_steps=2))

    def test_charges_before_explicit_index_action(self):
        a, d = record('a'), record('b')
        with patch.object(b, '_validate_evidence', wraps=b._validate_evidence) as validate:
            with self.assertRaisesRegex(ValueError, 'step limit'):
                b.bind_content(c.ContentBundle(), evidence=(a, d), limits=c.ContentLimits(max_binding_steps=1))
            self.assertEqual(validate.call_count, 1)

    def test_items_boundary_and_one_over_counts_both_kinds(self):
        graph = q.QuantityGraph()
        a = fact(graph)
        bundle = c.ContentBundle((c.Claim('x', quantity_ids=(a.quantity_id,)),),
                                 (c.QuantitySelection('s', (a.quantity_id,)),))
        b.bind_content(bundle, quantities=graph, limits=c.ContentLimits(max_items=2))
        with self.assertRaisesRegex(ValueError, 'item limit'):
            b.bind_content(bundle, quantities=graph, limits=c.ContentLimits(max_items=1))

    def test_reference_boundary_counts_direct_occurrences_before_dedup(self):
        owner = record()
        bundle = c.ContentBundle((c.Claim('a', (owner.evidence_id,)), c.Claim('b', (owner.evidence_id,))))
        b.bind_content(bundle, evidence=(owner,), limits=c.ContentLimits(max_references=2))
        with self.assertRaisesRegex(ValueError, 'reference limit'):
            b.bind_content(bundle, evidence=(owner,), limits=c.ContentLimits(max_references=1))

    def test_reference_preflight_before_graph_access(self):
        graph = q.QuantityGraph()
        a, d = fact(graph), fact(graph, '3')
        with patch.object(graph, 'get', side_effect=AssertionError('preflight must happen first')):
            with self.assertRaisesRegex(ValueError, 'reference limit'):
                b.bind_content(selection_bundle(a, d), quantities=graph, limits=c.ContentLimits(max_references=1))

    def test_citation_items_only_and_no_invented_charges(self):
        graph, _, _, _, root, _ = ancestry()
        bound = b.bind_content(selection_bundle(root), quantities=graph)
        metadata = (c.SnapshotCitationMetadata(S1), c.SnapshotCitationMetadata(S2))
        result = b.assess_citations(bound, metadata, limits=c.ContentLimits(2, 1, 1))
        self.assertEqual(result.incomplete_snapshot_ids, (S1, S2))
        with self.assertRaisesRegex(ValueError, 'item limit'):
            b.assess_citations(bound, metadata, limits=c.ContentLimits(1, 1, 1))

    def test_limits_revalidated_by_both_entry_points(self):
        for name in ('max_items', 'max_references', 'max_binding_steps'):
            for bad in (True, 0, 100001):
                limits = c.ContentLimits()
                object.__setattr__(limits, name, bad)
                with self.assertRaises(ValueError):
                    b.bind_content(c.ContentBundle(), limits=limits)
                with self.assertRaises(ValueError):
                    b.assess_citations(b.BoundContent(c.ContentBundle(), (), (), ()), limits=limits)


class ArchitectureTests(unittest.TestCase):
    def test_exact_fields_frozen_output_records(self):
        owner = record(qualifications=('q',))
        claim = c.Claim('false', (owner.evidence_id,))
        bound = b.bind_content(c.ContentBundle((claim,)), evidence=(owner,))
        cases = [(bound, ['bundle', 'bindings', 'evidence', 'quantities']),
                 (bound.bindings[0], ['content_id', 'evidence_ids', 'quantity_ids', 'snapshot_ids', 'qualifications']),
                 (bound.bindings[0].qualifications[0], ['owner_id', 'qualification_index', 'text', 'origin', 'verification']),
                 (b.assess_citations(bound), ['referenced_snapshot_ids', 'metadata', 'missing_snapshot_ids',
                                            'incomplete_snapshot_ids', 'unused_snapshot_ids'])]
        for value, names in cases:
            self.assertEqual([f.name for f in fields(value)], names)
            for name in names:
                with self.assertRaises(FrozenInstanceError):
                    setattr(value, name, getattr(value, name))

    def test_output_tuple_fields_and_subclasses_rejected(self):
        bound = b.bind_content(c.ContentBundle())
        for name in ('bindings', 'evidence', 'quantities'):
            with self.assertRaises(ValueError):
                replace(bound, **{name: []})
        binding = b.ContentBinding('cl1:' + 'a' * 64, (), (), (), ())
        for name in ('evidence_ids', 'quantity_ids', 'snapshot_ids', 'qualifications'):
            with self.assertRaises(ValueError):
                replace(binding, **{name: []})
        assessment = b.assess_citations(bound)
        for field in fields(assessment):
            with self.assertRaises(ValueError):
                replace(assessment, **{field.name: []})
        class SubBinding(b.ContentBinding):
            pass
        with self.assertRaises(ValueError):
            replace(bound, bindings=(SubBinding('cl1:' + 'a' * 64, (), (), (), ()),))

    def test_deliberately_false_prose_and_numbers_bind_without_entailment(self):
        owner = record('The only reported value is 2; no recommendation is supported.')
        graph = q.QuantityGraph()
        node = fact(graph, '2')
        claims = (c.Claim('The reported value is 999999. This proves the moon is cheese.', (owner.evidence_id,)),
                  c.Claim('2 + 2 = 999. Therefore everyone should buy this.', quantity_ids=(node.quantity_id,)))
        bound = b.bind_content(c.ContentBundle(claims), evidence=(owner,), quantities=graph)
        self.assertEqual(bound.bundle.claims, c.ContentBundle(claims).claims)
        self.assertEqual(len(bound.bindings), 2)
        self.assertTrue(all(not hasattr(claim, 'verified') for claim in claims))

    def test_no_io_extraction_verification_rendering_or_arithmetic_replay(self):
        graph, _, _, _, root, _ = ancestry()
        bundle = selection_bundle(root)
        forbidden = ['builtins.open', 'io.open', 'os.open', 'socket.socket',
                     'presentation_agent.source_capture.SourceStore.read',
                     'presentation_agent.source_capture.SourceStore.capture',
                     'presentation_agent.source_extraction.extract_csv',
                     'presentation_agent.source_extraction.extract_text',
                     'presentation_agent.evidence_verification.verify_evidence',
                     'presentation_agent.quantities._calculate',
                     'presentation_agent.quantities._parse',
                     'presentation_agent.quantities.DirectQuantity.__post_init__',
                     'presentation_agent.quantities.DerivedQuantity.__post_init__',
                     'presentation_agent.quantities.QuantityGraph.__init__',
                     'presentation_agent.quantities.QuantityGraph.add_fact',
                     'presentation_agent.quantities.QuantityGraph.derive']
        with ExitStack() as stack:
            for name in forbidden:
                stack.enter_context(patch(name, side_effect=AssertionError('forbidden call: ' + name)))
            bound = b.bind_content(bundle, quantities=graph)
            result = b.assess_citations(bound)
        self.assertEqual(len(bound.quantities), 4)
        self.assertEqual(result.missing_snapshot_ids, (S1, S2))

    def test_public_graph_get_only_no_graph_internal_access(self):
        tree = ast.parse(Path(b.__file__).read_text(), feature_version=9)
        accesses = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name) and node.value.id == 'quantities'}
        self.assertEqual(accesses, {'get'})

    def test_python39_import_boundaries_and_public_api(self):
        tree = ast.parse(Path(b.__file__).read_text(), feature_version=9)
        imports = set()
        forbidden = {'verify_evidence', 'extract_csv', 'extract_text', 'derive', 'add_fact',
                     '_calculate', 'render', 'compose', 'open', 'DirectQuantity', 'DerivedQuantity'}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add('.' * node.level + node.module)
            elif isinstance(node, ast.Call):
                name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ''
                self.assertNotIn(name, forbidden)
                if name == 'dataclass':
                    self.assertEqual([k.arg for k in node.keywords], ['frozen'])
        self.assertEqual(imports, {'dataclasses', 'typing', '.content', '.evidence', '.evidence_verification', '.quantities'})
        self.assertEqual(set(b.__all__), {'QualificationBinding', 'ContentBinding', 'BoundContent',
                                         'CitationAssessment', 'bind_content', 'assess_citations'})
        for module in (b, c):
            self.assertFalse(hasattr(module, 'ClaimKind'))
            for name in ('encode', 'decode', 'load', 'to_dict', 'from_dict'):
                self.assertFalse(hasattr(module, name))
        root = Path(b.__file__).parent
        self.assertNotIn('content', (root / '__init__.py').read_text())


if __name__ == '__main__':
    unittest.main()
