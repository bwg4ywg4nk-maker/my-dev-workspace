"""Frozen 3C.1 semantic composition and deliberately local trust boundaries."""
import ast
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import FrozenInstanceError, fields, replace
import inspect
from pathlib import Path
from typing import Tuple, Union, get_type_hints
import unittest
from unittest.mock import PropertyMock, patch

from presentation_agent import composition as m, content as c, content_binding as b, planning as p
from presentation_agent.evidence import EvidenceRecord, TextLocator
from presentation_agent.evidence_verification import QualificationVerification


SNAP = 'sha256:' + '1' * 64
OTHER = 'sha256:' + '2' * 64
EV = 'ev1:' + 'a' * 64
QID = 'qf1:' + 'b' * 64
CID = 'cl1:' + 'f' * 64


def altered(value, **changes):
    """Tampering is used only for explicit rejection/trust-boundary probes."""
    result = object.__new__(type(value))
    for name, field in dict(vars(value), **changes).items():
        object.__setattr__(result, name, field)
    return result


def fixture():
    evidence = EvidenceRecord(SNAP, TextLocator(1, 1), 'reported', ('same', 'same'))
    claims = tuple(c.Claim(text, (evidence.evidence_id,), qualifications=('same',))
                   for text in ('  α\n\tمرحبا e\u0301  ', 'second'))
    return b.bind_content(c.ContentBundle(claims), evidence=(evidence,))


def plan_for(bound, slides=None, omitted=()):
    if slides is None:
        slides = (tuple(x.content_id for x in bound.bindings),)
    return p.plan_presentation(bound, p.PlanningSpec(tuple(p.SlidePlan(x) for x in slides), omitted))


class CompositionTests(unittest.TestCase):
    def setUp(self):
        self.bound = fixture()
        self.plan = plan_for(self.bound)
        self.result = m.compose_presentation(self.plan)
        self.slide = self.result.slides[0]

    def test_public_fields_types_signature(self):
        cases = {
            m.ContentBlock: dict(placement_index=int, content_id=str, content=Union[c.Claim, c.QuantitySelection]),
            m.CitationBlock: dict(snapshot_id=str, placement_indices=Tuple[int, ...]),
            m.QualificationBlock: dict(qualification=b.QualificationBinding, placement_indices=Tuple[int, ...]),
            m.SlideComposition: dict(slide_index=int, content_blocks=Tuple[m.ContentBlock, ...],
                                    citation_blocks=Tuple[m.CitationBlock, ...], qualification_blocks=Tuple[m.QualificationBlock, ...]),
            m.PresentationComposition: dict(plan=p.PresentationPlan, slides=Tuple[m.SlideComposition, ...]),
            m.CompositionLimits: dict(max_slides=int, max_placements=int, max_obligation_associations=int),
        }
        self.assertEqual(set(m.__all__), {cls.__name__ for cls in cases} | {'compose_presentation'})
        for cls, expected in cases.items():
            self.assertEqual(get_type_hints(cls), expected)
            self.assertEqual([f.name for f in fields(cls)], list(expected))
            self.assertTrue(cls.__dataclass_params__.frozen)
        sig = inspect.signature(m.compose_presentation)
        self.assertEqual(list(sig.parameters), ['plan', 'limits'])
        self.assertEqual(sig.parameters['limits'].kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertEqual(sig.parameters['limits'].default, m.CompositionLimits())
        self.assertEqual(sig.return_annotation, m.PresentationComposition)

    def test_frozen_and_concrete_records(self):
        objects = (self.result, self.slide, self.slide.content_blocks[0],
                   self.slide.citation_blocks[0], self.slide.qualification_blocks[0], m.CompositionLimits())
        for obj in objects:
            for field in fields(obj):
                with self.assertRaises(FrozenInstanceError):
                    setattr(obj, field.name, None)
            subclass = type('Subclass', (type(obj),), {})
            with self.assertRaises(ValueError):
                subclass(**vars(obj))

    def test_content_local_validation(self):
        block = self.slide.content_blocks[0]
        for index in (-1, True, False, 0.0, '0', type('I', (int,), {})(0)):
            with self.assertRaises(ValueError):
                replace(block, placement_index=index)
        for identity in ('cl1:1', 'qs1:' + '1' * 64, 'cl1:' + 'A' * 64, None,
                         type('S', (str,), {})(block.content_id)):
            with self.assertRaises(ValueError):
                replace(block, content_id=identity)
        for content in (None, {}, type('C', (c.Claim,), {} )('sub', (EV,))):
            with self.assertRaises(ValueError):
                replace(block, content=content)
        with patch.object(c.Claim, 'claim_id', new_callable=PropertyMock, side_effect=AssertionError):
            self.assertEqual(replace(block, content_id=CID).content_id, CID)

    def test_association_validation(self):
        for block in (self.slide.citation_blocks[0], self.slide.qualification_blocks[0]):
            for indices in ([], (), (1, 0), (0, 0), (-1,), (True,), (0.0,),
                            type('T', (tuple,), {})((0,)), (type('I', (int,), {})(0),)):
                with self.assertRaises(ValueError):
                    replace(block, placement_indices=indices)
        for identity in ('sha256:1', CID, None, 'sha256:' + 'A' * 64):
            with self.assertRaises(ValueError):
                m.CitationBlock(identity, (0,))

    def test_qualification_local_fields(self):
        block = self.slide.qualification_blocks[0]
        for changes in (dict(owner_id=CID), dict(qualification_index=True), dict(qualification_index=-1),
                        dict(text=''), dict(text=1), dict(origin='evidence'), dict(verification=None)):
            with self.assertRaises(ValueError):
                replace(block, qualification=altered(block.qualification, **changes))
        with self.assertRaises(ValueError):
            replace(block, qualification=None)
        # A valid local owner need not resolve to any plan/evidence pool.
        q = replace(block.qualification, owner_id=EV)
        self.assertIs(m.QualificationBlock(q, (0,)).qualification, q)

    def test_slide_containers_and_children(self):
        for field in ('content_blocks', 'citation_blocks', 'qualification_blocks'):
            for value in ([], None, type('T', (tuple,), {})(), (None,)):
                with self.assertRaises(ValueError):
                    replace(self.slide, **{field: value})
        for index in (True, -1, 1.0):
            with self.assertRaises(ValueError):
                replace(self.slide, slide_index=index)
        with self.assertRaises(ValueError):
            replace(self.slide, content_blocks=self.slide.content_blocks[::-1])
        with self.assertRaises(ValueError):
            replace(self.slide, content_blocks=(self.slide.content_blocks[0],
                    replace(self.slide.content_blocks[0], placement_index=1)))
        for field in ('citation_blocks', 'qualification_blocks'):
            blocks = getattr(self.slide, field)
            with self.assertRaises(ValueError):
                replace(self.slide, **{field: blocks + blocks[:1]})
            with self.assertRaises(ValueError):
                replace(self.slide, **{field: (replace(blocks[0], placement_indices=(2,)),)})
        with self.assertRaises(ValueError):
            replace(self.slide, qualification_blocks=self.slide.qualification_blocks[::-1])
        with self.assertRaises(ValueError):
            replace(self.slide, citation_blocks=(m.CitationBlock(OTHER, (0,)), m.CitationBlock(SNAP, (0,))))

    def test_presentation_local_only(self):
        # No semantic comparison: missing slides/obligations and unrelated content
        # are structurally acceptable, but not a factory guarantee.
        self.assertEqual(m.PresentationComposition(self.plan, ()).slides, ())
        local = m.SlideComposition(0, (m.ContentBlock(0, CID, self.bound.bundle.claims[0]),), (), ())
        self.assertEqual(m.PresentationComposition(self.plan, (local,)).slides, (local,))
        for slides in ([], (None,), (replace(self.slide, slide_index=1),)):
            with self.assertRaises(ValueError):
                m.PresentationComposition(self.plan, slides)
        with self.assertRaises(ValueError):
            m.PresentationComposition(None, ())

    def test_correspondence_identity_text_and_repetition(self):
        ids = self.plan.specification.slides[0].content_ids
        plan = plan_for(self.bound, (ids[::-1], (), ids))
        result = m.compose_presentation(plan)
        self.assertIs(result.plan, plan)
        members = {x.claim_id: x for x in self.bound.bundle.claims}
        for source, slide in zip(plan.specification.slides, result.slides):
            self.assertEqual(tuple(x.content_id for x in slide.content_blocks), source.content_ids)
            for block in slide.content_blocks:
                self.assertIs(block.content, members[block.content_id])
        self.assertEqual(result.slides[1], m.SlideComposition(1, (), (), ()))
        self.assertIs(result.slides[0].content_blocks[0].content, result.slides[2].content_blocks[1].content)
        self.assertIn('  α\n\tمرحبا e\u0301  ', [x.content.text for x in self.slide.content_blocks])

    def test_quantity_retention(self):
        selection = c.QuantitySelection('  نسبة Δ  ', (QID,))
        # Equivalent trusted producer output: authoritative bindings are supplied
        # directly; composition need not require retained quantity graph nodes.
        binding = b.ContentBinding(selection.selection_id, (), (QID,), (SNAP,), ())
        bound = b.BoundContent(c.ContentBundle(quantity_selections=(selection,)), (binding,), (), ())
        result = m.compose_presentation(plan_for(bound))
        block = result.slides[0].content_blocks[0]
        self.assertIs(block.content, selection)
        self.assertEqual(block.content.label, '  نسبة Δ  ')
        self.assertIs(block.content.quantity_ids, selection.quantity_ids)
        with self.assertRaises(ValueError):
            replace(block, content_id=CID)

    def test_shared_citations_and_cross_slide_cost(self):
        ids = self.plan.specification.slides[0].content_ids
        result = m.compose_presentation(plan_for(self.bound, (ids, ids[:1])))
        self.assertEqual(result.slides[0].citation_blocks, (m.CitationBlock(SNAP, (0, 1)),))
        self.assertEqual(result.slides[1].citation_blocks, (m.CitationBlock(SNAP, (0,)),))
        self.assertEqual(self.associations(result), 12)

    @staticmethod
    def associations(result):
        return sum(len(x.placement_indices) for s in result.slides
                   for x in s.citation_blocks + s.qualification_blocks)

    def test_equivalent_occurrences_and_representatives(self):
        first, second = self.bound.bindings
        self.assertEqual(first.qualifications[0], second.qualifications[0])
        self.assertIsNot(first.qualifications[0], second.qualifications[0])
        ids = (second.content_id, first.content_id)
        result = m.compose_presentation(plan_for(self.bound, (ids, ids[::-1])))
        for slide, binding in zip(result.slides, (second, first)):
            block = slide.qualification_blocks[0]
            self.assertIs(block.qualification, binding.qualifications[0])
            self.assertEqual(block.placement_indices, (0, 1))

    def test_equal_text_distinct_occurrences_and_origins(self):
        blocks = self.slide.qualification_blocks
        self.assertEqual(len(blocks), 4)
        self.assertEqual({x.qualification.text for x in blocks}, {'same'})
        self.assertEqual([x.qualification.origin for x in blocks[:2]], [c.QualificationOrigin.EVIDENCE] * 2)
        self.assertEqual([x.qualification.origin for x in blocks[2:]], [c.QualificationOrigin.AUTHORED] * 2)
        self.assertIs(blocks[0].qualification.verification, QualificationVerification.UNVERIFIED)
        self.assertIsNone(blocks[2].qualification.verification)

    def test_conflicts_same_and_different_slides(self):
        first, second = self.bound.bindings
        for change in (dict(text='conflict'), dict(verification=None)):
            # Contradictory authoritative occurrences are rejection fixtures.
            q = altered(second.qualifications[0], **change)
            bad = altered(self.bound, bindings=(first, altered(second, qualifications=(q,) + second.qualifications[1:])))
            for slides in (((first.content_id, second.content_id),), ((first.content_id,), (second.content_id,))):
                plan = altered(self.plan, bound_content=bad,
                               specification=p.PlanningSpec(tuple(p.SlidePlan(x) for x in slides)))
                before = deepcopy(plan)
                with self.assertRaises(ValueError):
                    m.compose_presentation(plan)
                self.assertEqual(plan, before)

    def test_empty_presentations_slides_and_omissions(self):
        empty = b.bind_content(c.ContentBundle())
        self.assertEqual(m.compose_presentation(plan_for(empty, ())).slides, ())
        result = m.compose_presentation(plan_for(empty, ((), ())))
        self.assertEqual(result.slides, (m.SlideComposition(0, (), (), ()), m.SlideComposition(1, (), (), ())))
        ids = tuple(x.content_id for x in self.bound.bindings)
        for slides in ((), ((),)):
            result = m.compose_presentation(plan_for(self.bound, slides, ids))
            self.assertEqual(self.associations(result), 0)
        result = m.compose_presentation(plan_for(self.bound, (ids[:1],), ids[1:]))
        self.assertEqual(len(result.slides[0].content_blocks), 1)
        self.assertEqual(self.associations(result), 4)

    def test_omitted_obligations_not_accessed(self):
        first, second = self.bound.bindings
        plan = plan_for(self.bound, ((first.content_id,),), (second.content_id,))
        # Deliberately opaque omitted fields demonstrate the documented boundary.
        bad = altered(second, snapshot_ids=object(), qualifications=object())
        plan = altered(plan, bound_content=altered(self.bound, bindings=(first, bad)))
        self.assertEqual(self.associations(m.compose_presentation(plan)), 4)

    def test_first_encounter_not_global_lexical_order(self):
        first, second = self.bound.bindings
        # Equivalent producer output with canonical authoritative snapshot tuples.
        bound = replace(self.bound, bindings=(replace(first, snapshot_ids=(OTHER,)),
                                             replace(second, snapshot_ids=(SNAP, OTHER))))
        result = m.compose_presentation(plan_for(bound))
        self.assertEqual(result.slides[0].citation_blocks,
                         (m.CitationBlock(OTHER, (0, 1)), m.CitationBlock(SNAP, (1,))))

    def test_lower_limits_exact_and_one_over(self):
        limits = m.CompositionLimits(1, 2, 8)
        self.assertEqual(self.associations(m.compose_presentation(self.plan, limits=limits)), 8)
        for limits in (m.CompositionLimits(1, 1, 8), m.CompositionLimits(1, 2, 7)):
            with self.assertRaises(ValueError):
                m.compose_presentation(self.plan, limits=limits)
        plan = plan_for(self.bound, (self.plan.specification.slides[0].content_ids,) * 2)
        self.assertEqual(len(m.compose_presentation(plan, limits=m.CompositionLimits(2, 4, 16)).slides), 2)
        with self.assertRaises(ValueError):
            m.compose_presentation(plan, limits=m.CompositionLimits(1, 4, 16))

    def test_limit_types_and_lower_only(self):
        for field in fields(m.CompositionLimits):
            for bad in (True, False, 0, -1, 1.0, '1', type('I', (int,), {})(1), field.default + 1):
                with self.assertRaises(ValueError):
                    m.CompositionLimits(**{field.name: bad})
                with self.assertRaises(ValueError):
                    m.compose_presentation(self.plan, limits=altered(m.CompositionLimits(), **{field.name: bad}))
        for bad in (None, {}, object()):
            with self.assertRaises(ValueError):
                m.compose_presentation(self.plan, limits=bad)

    def test_preflight_before_any_obligation_work(self):
        first, second = self.bound.bindings
        # Poison the FIRST entry while a LATER placement exceeds the budget.
        bad = altered(first, qualifications=(object(),) * 3)
        plan = altered(self.plan, bound_content=altered(self.bound, bindings=(bad, second)))
        with ExitStack() as stack:
            for name in ('ContentBlock', 'CitationBlock', 'QualificationBlock', '_occurrence', '_qualification_key'):
                stack.enter_context(patch.object(m, name, side_effect=AssertionError('premature allocation/traversal')))
            with self.assertRaisesRegex(ValueError, 'association limit'):
                m.compose_presentation(plan, limits=m.CompositionLimits(max_obligation_associations=7))

    def test_shallow_limits_before_member_lookup(self):
        with patch.object(c.Claim, 'claim_id', new_callable=PropertyMock, side_effect=AssertionError):
            with self.assertRaisesRegex(ValueError, 'Placement limit'):
                m.compose_presentation(self.plan, limits=m.CompositionLimits(max_placements=1))
            oversized = altered(self.bound.bundle, claims=(self.bound.bundle.claims[0],) * 10001)
            with self.assertRaisesRegex(ValueError, 'item limit'):
                m.compose_presentation(altered(self.plan, bound_content=altered(self.bound, bundle=oversized)))
            with self.assertRaisesRegex(ValueError, 'Binding count'):
                m.compose_presentation(altered(self.plan, bound_content=altered(self.bound, bindings=())))

    def test_factory_structural_rejections(self):
        for plan in (None, altered(self.plan, specification=None),
                     altered(self.plan, specification=altered(self.plan.specification, slides=[])),
                     altered(self.plan, bound_content=None),
                     altered(self.plan, bound_content=altered(self.bound, bindings=[])),
                     altered(self.plan, bound_content=altered(self.bound, bindings=(self.bound.bindings[0],) * 2)),
                     altered(self.plan, specification=p.PlanningSpec((p.SlidePlan((CID,)),)))):
            with self.assertRaises(ValueError):
                m.compose_presentation(plan)
        for changes in (dict(snapshot_ids=[]), dict(qualifications=[]), dict(snapshot_ids=(SNAP, SNAP)),
                        dict(snapshot_ids=(OTHER, SNAP)), dict(qualifications=self.bound.bindings[0].qualifications[::-1])):
            bad = altered(self.bound.bindings[0], **changes)
            with self.assertRaises(ValueError):
                m.compose_presentation(altered(self.plan, bound_content=altered(self.bound, bindings=(bad, self.bound.bindings[1]))))

    def test_determinism_and_input_preservation(self):
        before = deepcopy(self.plan)
        self.assertEqual(m.compose_presentation(self.plan), m.compose_presentation(self.plan))
        with self.assertRaises(ValueError):
            m.compose_presentation(self.plan, limits=m.CompositionLimits(max_obligation_associations=1))
        self.assertEqual(self.plan, before)

    def test_default_slide_ceiling(self):
        empty = b.bind_content(c.ContentBundle())
        result = m.compose_presentation(plan_for(empty, ((),) * 1000))
        self.assertEqual(len(result.slides), 1000)
        with self.assertRaisesRegex(ValueError, 'Slide limit'):
            m.PresentationComposition(result.plan, result.slides + (m.SlideComposition(1000, (), (), ()),))
        bad = altered(result.plan, specification=altered(result.plan.specification, slides=(p.SlidePlan(()),) * 1001))
        with self.assertRaisesRegex(ValueError, 'Slide limit'):
            m.compose_presentation(bad)

    def test_default_placement_and_association_ceilings(self):
        # Trusted equivalent producer: ten authoritative snapshots per placement.
        claims = tuple(c.Claim(str(i), (EV,)) for i in range(10))
        bundle = c.ContentBundle(claims)
        snapshots = tuple('sha256:' + format(i, '064x') for i in range(10))
        bindings = tuple(b.ContentBinding(x.claim_id, (), (), snapshots, ()) for x in bundle.claims)
        bound = b.BoundContent(bundle, bindings, (), ())
        ids = tuple(x.content_id for x in bindings)
        plan = plan_for(bound, (ids,) * 1000)
        result = m.compose_presentation(plan)
        self.assertEqual(sum(len(s.content_blocks) for s in result.slides), 10000)
        self.assertEqual(self.associations(result), 100000)
        extra_claim = c.Claim('extra', (EV,))
        extra_binding = b.ContentBinding(extra_claim.claim_id, (), (),
                                         snapshots + ('sha256:' + 'f' * 64,), ())
        expanded = b.BoundContent(c.ContentBundle(claims + (extra_claim,)),
                                 tuple(sorted(bindings + (extra_binding,), key=lambda x: x.content_id)), (), ())
        over = plan_for(expanded, ((extra_claim.claim_id,) + ids[1:],) + (ids,) * 999)
        with self.assertRaisesRegex(ValueError, 'association limit'):
            m.compose_presentation(over)
        over_placements = altered(plan, specification=altered(plan.specification,
            slides=(p.SlidePlan(ids + (extra_claim.claim_id,)),) + plan.specification.slides[1:]))
        with self.assertRaisesRegex(ValueError, 'Placement limit'):
            m.compose_presentation(over_placements)
        with self.assertRaises(ValueError):
            m.compose_presentation(plan, limits=m.CompositionLimits(max_placements=9999))
        with self.assertRaises(ValueError):
            m.compose_presentation(plan, limits=m.CompositionLimits(max_obligation_associations=99999))
        extra = m.CitationBlock('sha256:' + 'f' * 64, (0,))
        slide = replace(result.slides[0], citation_blocks=result.slides[0].citation_blocks + (extra,))
        with self.assertRaisesRegex(ValueError, 'association limit'):
            m.PresentationComposition(plan, (slide,) + result.slides[1:])
        # Count checks reject oversized direct structures before local inspection.
        bad = altered(result.slides[0], content_blocks=result.slides[0].content_blocks + (result.slides[0].content_blocks[0],))
        with self.assertRaisesRegex(ValueError, 'Placement limit'):
            m.PresentationComposition(plan, (bad,) + result.slides[1:])

    def test_no_forbidden_calls_or_io(self):
        forbidden = ['builtins.open', 'io.open', 'os.open', 'socket.socket',
                     'presentation_agent.content_binding.bind_content',
                     'presentation_agent.content_binding.BoundContent.__post_init__',
                     'presentation_agent.content_binding.ContentBinding.__post_init__',
                     'presentation_agent.planning.PresentationPlan.__post_init__',
                     'presentation_agent.content._validate_bundle',
                     'presentation_agent.content.Claim.__post_init__',
                     'presentation_agent.content.QuantitySelection.__post_init__',
                     'presentation_agent.quantities.QuantityGraph.get',
                     'presentation_agent.quantities._calculate', 'presentation_agent.quantities._parse',
                     'presentation_agent.evidence_verification.verify_evidence',
                     'presentation_agent.source_extraction.extract_csv',
                     'presentation_agent.source_extraction.extract_text']
        with ExitStack() as stack:
            for target in forbidden:
                stack.enter_context(patch(target, side_effect=AssertionError(target)))
            self.assertEqual(m.compose_presentation(self.plan), self.result)
        opaque = altered(self.bound, evidence=object(), quantities=object())
        self.assertEqual(m.compose_presentation(altered(self.plan, bound_content=opaque)).slides, self.result.slides)

    def test_python39_and_static_architecture(self):
        source = Path(m.__file__).read_text()
        tree = ast.parse(source, feature_version=9)
        imports = set()
        forbidden = {'bind_content', 'open', 'verify_evidence', '_calculate', '_parse',
                     'QuantityGraph', 'render', 'save', 'evidence_ids', 'quantity_ids', 'quantities'}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(x.name for x in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add('.' * node.level + node.module)
            elif isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, forbidden)
            elif isinstance(node, ast.Name):
                self.assertNotIn(node.id, forbidden)
        self.assertEqual(imports, {'dataclasses', 'typing', '.content', '.content_binding', '.planning'})
        ast.parse(Path(__file__).read_text(), feature_version=9)


if __name__ == '__main__':
    unittest.main()
