"""Frozen 3B placement, correspondence, and authority boundaries."""
import ast
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import FrozenInstanceError, fields, replace
import inspect
from pathlib import Path
from typing import Tuple, get_type_hints
import unittest
from unittest.mock import PropertyMock, patch

from presentation_agent import content as c, content_binding as b, planning as p
from presentation_agent.evidence import EvidenceRecord, TextLocator


EV = 'ev1:' + 'a' * 64
Q = 'qf1:' + 'b' * 64
UNKNOWN = 'cl1:' + 'f' * 64


def forged(cls, **values):
    """Bypass constructors only to probe the reduced structural boundary."""
    result = object.__new__(cls)
    for name, value in values.items():
        object.__setattr__(result, name, value)
    return result


def altered(value, **changes):
    return forged(type(value), **dict(vars(value), **changes))


def fixture():
    owner = EvidenceRecord('sha256:' + '1' * 64, TextLocator(1, 1),
                           'reported', ('same', 'same'))
    claims = tuple(c.Claim(label, (owner.evidence_id,), qualifications=('same', 'same'))
                   for label in ('alpha', 'beta'))
    return b.bind_content(c.ContentBundle(claims), evidence=(owner,))


def quantity_fixture():
    # Equivalent producer correspondence fixture; no ancestry is asserted here.
    selections = tuple(c.QuantitySelection(label, (Q,)) for label in ('first', 'second'))
    bundle = c.ContentBundle(quantity_selections=selections)
    bindings = tuple(b.ContentBinding(x.selection_id, (), (Q,), (), ())
                     for x in bundle.quantity_selections)
    return b.BoundContent(bundle, bindings, (), ())


class PlanningTests(unittest.TestCase):
    def setUp(self):
        self.bound = fixture()
        self.ids = tuple(x.content_id for x in self.bound.bindings)
        self.spec = p.PlanningSpec((p.SlidePlan(self.ids[::-1]),))

    def test_fields_types_frozen_and_api(self):
        plan = p.plan_presentation(self.bound, self.spec)
        cases = [(p.SlidePlan, {'content_ids': Tuple[str, ...]}),
                 (p.PlanningSpec, {'slides': Tuple[p.SlidePlan, ...],
                                  'omitted_content_ids': Tuple[str, ...]}),
                 (p.PresentationPlan, {'bound_content': b.BoundContent, 'specification': p.PlanningSpec}),
                 (p.PlanningLimits, {'max_slides': int, 'max_placements': int})]
        for cls, expected in cases:
            self.assertEqual(get_type_hints(cls), expected)
            self.assertEqual([f.name for f in fields(cls)], list(expected))
            self.assertTrue(cls.__dataclass_params__.frozen)
        for value in (self.spec.slides[0], self.spec, plan, p.PlanningLimits()):
            for field in fields(value):
                with self.assertRaises(FrozenInstanceError):
                    setattr(value, field.name, None)
            subclass = type('Subclass', (type(value),), {})
            with self.assertRaises(ValueError):
                subclass(**vars(value))
        self.assertEqual(set(p.__all__), {cls.__name__ for cls, _ in cases} | {'plan_presentation'})
        self.assertFalse(hasattr(p, 'validate_plan'))
        signature = inspect.signature(p.plan_presentation)
        self.assertEqual(list(signature.parameters), ['bound_content', 'specification', 'limits'])
        self.assertEqual(signature.parameters['limits'].kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertEqual(signature.parameters['limits'].default, p.PlanningLimits(1000, 10000))

    def test_invalid_containers_ids_and_concrete_types(self):
        for construct in (p.plan_presentation, p.PresentationPlan):
            with self.subTest(construct=construct):
                class TupleSubclass(tuple):
                    pass
                class StringSubclass(str):
                    pass
                for bad in ([], None, set(), iter(()), TupleSubclass()):
                    for make in (p.SlidePlan, lambda x: p.PlanningSpec(x),
                                 lambda x: p.PlanningSpec(omitted_content_ids=x)):
                        with self.assertRaises(ValueError):
                            make(bad)
                for bad in (None, 1, EV, 'cl1:A' + 'a' * 63, StringSubclass(self.ids[0])):
                    with self.assertRaises(ValueError):
                        p.SlidePlan((bad,))
                    with self.assertRaises(ValueError):
                        p.PlanningSpec(omitted_content_ids=(bad,))
                for bad in (None, {}, self.spec.slides[0], forged(type('SubSpec', (p.PlanningSpec,), {}), **vars(self.spec))):
                    with self.assertRaises(ValueError):
                        construct(self.bound, bad)
                with self.assertRaises(ValueError):
                    p.PlanningSpec((None,))
                invalid_specs = (
                    altered(self.spec, slides=[]),
                    altered(self.spec, slides=(None,)),
                    altered(self.spec, slides=(forged(type('SubSlide', (p.SlidePlan,), {}),
                                                     content_ids=self.ids),)),
                    altered(self.spec, slides=(forged(p.SlidePlan, content_ids=[]),)),
                    altered(self.spec, slides=(forged(p.SlidePlan, content_ids=('bad',)),)),
                    altered(self.spec, omitted_content_ids=[]),
                    altered(self.spec, omitted_content_ids=('bad',)),
                )
                for bad in invalid_specs:
                    with self.assertRaises(ValueError):
                        construct(self.bound, bad)
                for bad in (None, {}, forged(type('SubBound', (b.BoundContent,), {}), **vars(self.bound))):
                    with self.assertRaises(ValueError):
                        construct(bad, self.spec)

    def test_same_slide_duplicates_both_kinds_and_tampering(self):
        for bound in (self.bound, quantity_fixture()):
            identity, other = (binding.content_id for binding in bound.bindings)
            for ids in ((identity, identity), (identity, other, identity)):
                with self.assertRaisesRegex(ValueError, 'Duplicate'):
                    p.SlidePlan(ids)
                slide = forged(p.SlidePlan, content_ids=ids)
                spec = forged(p.PlanningSpec, slides=(slide,), omitted_content_ids=())
                for construct in (p.plan_presentation, p.PresentationPlan):
                    with self.subTest(kind=identity[:3], ids=ids, construct=construct):
                        with self.assertRaisesRegex(ValueError, 'Duplicate'):
                            construct(bound, spec)

    def test_order_repetition_identity_and_obligations(self):
        spec = p.PlanningSpec((p.SlidePlan(self.ids[::-1]), p.SlidePlan(()), p.SlidePlan(self.ids)))
        plan = p.plan_presentation(self.bound, spec)
        self.assertIs(plan.specification, spec)
        self.assertIs(plan.bound_content, self.bound)
        self.assertEqual(plan.bindings_for_slide(1), ())
        for index, expected in ((0, self.bound.bindings[::-1]), (2, self.bound.bindings)):
            for actual, binding in zip(plan.bindings_for_slide(index), expected):
                self.assertIs(actual, binding)
                self.assertIs(actual.snapshot_ids, binding.snapshot_ids)
                self.assertIs(actual.qualifications, binding.qualifications)
                self.assertEqual(len(actual.snapshot_ids), 1)
                self.assertEqual(len(actual.qualifications), 4)
        self.assertIs(plan.bindings_for_slide(0)[0], plan.bindings_for_slide(2)[1])

    def test_quantity_selection_placement(self):
        selection = c.QuantitySelection('selection', (Q,))
        # Equivalent producer correspondence fixture; no ancestry is asserted here.
        binding = b.ContentBinding(selection.selection_id, (), (Q,), (), ())
        bound = b.BoundContent(c.ContentBundle(quantity_selections=(selection,)), (binding,), (), ())
        slide = p.SlidePlan((selection.selection_id,))
        plan = p.plan_presentation(bound, p.PlanningSpec((slide, slide)))
        self.assertIs(plan.bindings_for_slide(1)[0], binding)

    def test_coverage_omissions_and_unknowns(self):
        for construct in (p.plan_presentation, p.PresentationPlan):
            with self.subTest(construct=construct):
                spec = p.PlanningSpec(omitted_content_ids=self.ids[::-1])
                self.assertEqual(spec.omitted_content_ids, self.ids)
                self.assertEqual(construct(self.bound, spec).specification.slides, ())
                construct(self.bound, p.PlanningSpec((p.SlidePlan(self.ids[:1]),), self.ids[1:]))
                for spec in (p.PlanningSpec(), p.PlanningSpec((p.SlidePlan(self.ids[:1]),)),
                             p.PlanningSpec(self.spec.slides, self.ids[:1]),
                             p.PlanningSpec(self.spec.slides, (UNKNOWN,)),
                             p.PlanningSpec((p.SlidePlan(self.ids + (UNKNOWN,)),))):
                    with self.assertRaises(ValueError):
                        construct(self.bound, spec)
                with self.assertRaisesRegex(ValueError, 'Duplicate'):
                    p.PlanningSpec(omitted_content_ids=(self.ids[0], self.ids[0]))
                for omitted in (self.ids[::-1], self.ids + self.ids):
                    with self.assertRaises(ValueError):
                        construct(self.bound, forged(p.PlanningSpec, slides=(), omitted_content_ids=omitted))

    def test_empty_cases(self):
        bound = b.bind_content(c.ContentBundle())
        for spec in (p.PlanningSpec(), p.PlanningSpec((p.SlidePlan(()),))):
            self.assertEqual(p.plan_presentation(bound, spec), p.PresentationPlan(bound, spec))
        p.plan_presentation(self.bound, p.PlanningSpec((p.SlidePlan(()),), self.ids))

    def test_lookup_errors(self):
        class IntSubclass(int):
            pass
        plan = p.plan_presentation(self.bound, self.spec)
        for bad in (True, False, 0.0, '0', None, IntSubclass(0)):
            with self.assertRaises(ValueError):
                plan.bindings_for_slide(bad)
        for bad in (-1, 1, 10**30):
            with self.assertRaises(IndexError):
                plan.bindings_for_slide(bad)
        with self.assertRaises(IndexError):
            p.plan_presentation(b.bind_content(c.ContentBundle()), p.PlanningSpec()).bindings_for_slide(0)

    def test_correspondence_failures(self):
        for construct in (p.plan_presentation, p.PresentationPlan):
            with self.subTest(construct=construct):
                bundle = self.bound.bundle
                bindings = self.bound.bindings
                subbundle = forged(type('SubBundle', (c.ContentBundle,), {}), **vars(bundle))
                subclaim = forged(type('SubClaim', (c.Claim,), {}), **vars(bundle.claims[0]))
                subbinding = forged(type('SubBinding', (b.ContentBinding,), {}), **vars(bindings[0]))
                bad_bundles = (None, subbundle, altered(bundle, claims=[]),
                               altered(bundle, quantity_selections=[]), altered(bundle, claims=(None, bundle.claims[1])),
                               altered(bundle, claims=(subclaim, bundle.claims[1])),
                               altered(bundle, claims=(bundle.claims[0],) * 2),
                               altered(bundle, claims=bundle.claims[:1], quantity_selections=(bundle.claims[1],)))
                bad_bindings = ([], bindings[:1], bindings + bindings[:1], bindings[::-1],
                                (bindings[0], bindings[0]), (None, bindings[1]), (subbinding, bindings[1]),
                                (altered(bindings[0], content_id='bad'), bindings[1]),
                                (bindings[0], altered(bindings[1], content_id=UNKNOWN)))
                for bad in bad_bundles:
                    with self.assertRaises(ValueError):
                        construct(altered(self.bound, bundle=bad), self.spec)
                for bad in bad_bindings:
                    with self.assertRaises(ValueError):
                        construct(altered(self.bound, bindings=bad), self.spec)

    def test_preflight_before_member_identity_and_compute_once(self):
        with patch.object(c.Claim, 'claim_id', new_callable=PropertyMock, side_effect=AssertionError('identity read')):
            with self.assertRaisesRegex(ValueError, 'count'):
                p.plan_presentation(altered(self.bound, bindings=()), self.spec)
            oversized = altered(self.bound.bundle, claims=(self.bound.bundle.claims[0],) * 10001)
            with self.assertRaisesRegex(ValueError, 'item limit'):
                p.plan_presentation(altered(self.bound, bundle=oversized), self.spec)
        getter = c.Claim.claim_id.fget
        calls = []
        def counted(member):
            calls.append(member)
            return getter(member)
        with patch.object(c.Claim, 'claim_id', property(counted)):
            p.plan_presentation(self.bound, self.spec)
        self.assertEqual(len(calls), 2)

    def test_quantity_correspondence_strictness_and_identity_counting(self):
        bound = quantity_fixture()
        spec = p.PlanningSpec((p.SlidePlan(tuple(x.content_id for x in bound.bindings)),))
        members = bound.bundle.quantity_selections
        subclass = forged(type('SubSelection', (c.QuantitySelection,), {}), **vars(members[0]))
        for construct in (p.plan_presentation, p.PresentationPlan):
            with self.subTest(construct=construct):
                for invalid in ((subclass, members[1]), (None, members[1]),
                                (self.bound.bundle.claims[0], members[1])):
                    with patch.object(c.QuantitySelection, 'selection_id', new_callable=PropertyMock,
                                      side_effect=AssertionError('identity read before type check')):
                        with self.assertRaises(ValueError):
                            construct(altered(bound, bundle=altered(bound.bundle,
                                      quantity_selections=invalid)), spec)
                with self.assertRaisesRegex(ValueError, 'Duplicate bundle member'):
                    construct(altered(bound, bundle=altered(bound.bundle,
                              quantity_selections=(members[0],) * 2)), spec)
                with patch.object(c.QuantitySelection, 'selection_id', new_callable=PropertyMock,
                                  side_effect=AssertionError('identity read before count check')):
                    with self.assertRaisesRegex(ValueError, 'count'):
                        construct(altered(bound, bindings=()), spec)
                    oversized = altered(bound.bundle, quantity_selections=(members[0],) * 10001)
                    with self.assertRaisesRegex(ValueError, 'item limit'):
                        construct(altered(bound, bundle=oversized), spec)
                getter = c.QuantitySelection.selection_id.fget
                calls = []
                def counted(member):
                    calls.append(member)
                    return getter(member)
                with patch.object(c.QuantitySelection, 'selection_id', property(counted)):
                    construct(bound, spec)
                self.assertEqual(len(calls), len(members))
                for actual, expected in zip(calls, members):
                    self.assertIs(actual, expected)

    def test_placement_limit_precedes_content_correspondence(self):
        slide = self.spec.slides[0]
        cases = ((p.plan_presentation, p.PlanningSpec((slide, slide)),
                  {'limits': p.PlanningLimits(max_placements=3)}),
                 (p.PresentationPlan, p.PlanningSpec((p.SlidePlan(tuple('cl1:' + format(i, '064x')
                   for i in range(10001))),)), {}))
        for construct, spec, kwargs in cases:
            with self.subTest(construct=construct):
                with patch.object(p, '_member_ids', side_effect=AssertionError('correspondence visited')):
                    with self.assertRaisesRegex(ValueError, 'Placement limit'):
                        construct(self.bound, spec, **kwargs)

    def test_limits_and_revalidation(self):
        class IntSubclass(int):
            pass
        for name, maximum in (('max_slides', 1000), ('max_placements', 10000)):
            for bad in (True, False, 0, -1, 1.0, '1', IntSubclass(1), maximum + 1):
                with self.assertRaises(ValueError):
                    p.PlanningLimits(**{name: bad})
                with self.assertRaises(ValueError):
                    p.plan_presentation(self.bound, self.spec, limits=altered(p.PlanningLimits(), **{name: bad}))
        for bad in (None, {}, forged(type('SubLimits', (p.PlanningLimits,), {}), **vars(p.PlanningLimits()))):
            with self.assertRaises(ValueError):
                p.plan_presentation(self.bound, self.spec, limits=bad)
        spec = p.PlanningSpec(self.spec.slides * 2)
        p.plan_presentation(self.bound, spec, limits=p.PlanningLimits(2, 4))
        for limits in (p.PlanningLimits(1, 4), p.PlanningLimits(2, 3)):
            with self.assertRaises(ValueError):
                p.plan_presentation(self.bound, spec, limits=limits)

    def test_default_exact_boundaries(self):
        for construct in (p.plan_presentation, p.PresentationPlan):
            with self.subTest(construct=construct):
                empty = b.bind_content(c.ContentBundle())
                construct(empty, p.PlanningSpec((p.SlidePlan(()),) * 1000))
                with self.assertRaises(ValueError):
                    construct(empty, p.PlanningSpec((p.SlidePlan(()),) * 1001))
                claims = tuple(c.Claim(str(i), (EV,)) for i in range(10000))
                bundle = c.ContentBundle(claims)
                bindings = tuple(b.ContentBinding(x.claim_id, (), (), (), ()) for x in bundle.claims)
                bound = b.BoundContent(bundle, bindings, (), ())
                slide = p.SlidePlan(tuple(x.content_id for x in bindings))
                construct(bound, p.PlanningSpec((slide,)))
                with self.assertRaisesRegex(ValueError, 'Placement limit'):
                    construct(bound, p.PlanningSpec((slide, p.SlidePlan(slide.content_ids[:1]))))

    def test_determinism_and_atomicity(self):
        before = deepcopy((self.bound, self.spec))
        first = p.plan_presentation(self.bound, self.spec)
        self.assertEqual(first, p.plan_presentation(self.bound, self.spec))
        invalid = p.PlanningSpec(self.spec.slides, self.ids)
        invalid_before = deepcopy(invalid)
        with self.assertRaises(ValueError):
            p.plan_presentation(self.bound, invalid)
        self.assertEqual((self.bound, self.spec), before)
        self.assertEqual(invalid, invalid_before)

    def test_no_semantic_reconstruction_or_side_effects(self):
        forbidden = ['builtins.open', 'io.open', 'os.open', 'socket.socket',
                     'presentation_agent.content_binding.bind_content',
                     'presentation_agent.content_binding.BoundContent.__post_init__',
                     'presentation_agent.content_binding.ContentBinding.__post_init__',
                     'presentation_agent.content._validate_bundle',
                     'presentation_agent.content.Claim.__post_init__',
                     'presentation_agent.content.QuantitySelection.__post_init__',
                     'presentation_agent.quantities.QuantityGraph.get',
                     'presentation_agent.quantities._calculate',
                     'presentation_agent.quantities._parse',
                     'presentation_agent.evidence_verification.verify_evidence',
                     'presentation_agent.source_extraction.extract_csv',
                     'presentation_agent.source_extraction.extract_text']
        with ExitStack() as stack:
            for target in forbidden:
                stack.enter_context(patch(target, side_effect=AssertionError(target)))
            plan = p.plan_presentation(self.bound, self.spec)
            self.assertIs(plan.bindings_for_slide(0)[0], self.bound.bindings[-1])
        # These intentionally tampered fields demonstrate the *limited* guarantee,
        # not supported provenance-producing inputs.
        opaque = altered(self.bound, evidence=object(), quantities=object())
        p.plan_presentation(opaque, self.spec)

    def test_python39_and_static_architecture(self):
        tree = ast.parse(Path(p.__file__).read_text(), feature_version=9)
        imports = set()
        forbidden = {'evidence', 'quantities', 'snapshot_ids', 'qualifications',
                     'quantity_ids', 'evidence_ids', 'identity_payload', 'get',
                     'render', 'compose', 'verify_evidence', '_calculate', 'bind_content',
                     'CitationRequirement', 'QualificationRequirement', 'open'}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add('.' * node.level + node.module)
            elif isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, forbidden)
            elif isinstance(node, ast.Name):
                self.assertNotIn(node.id, forbidden)
        self.assertEqual(imports, {'dataclasses', 'typing', '.content', '.content_binding'})
        ast.parse(Path(__file__).read_text(), feature_version=9)


if __name__ == '__main__':
    unittest.main()
