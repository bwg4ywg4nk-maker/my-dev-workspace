"""Frozen display resolution, local constructors, and bounded trust boundary."""
import ast
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import FrozenInstanceError, fields, replace
import inspect
from pathlib import Path
from typing import Optional, Tuple, get_type_hints
import unittest
from unittest.mock import patch, PropertyMock

import presentation_agent
from presentation_agent import display as d, composition as m, content as c
from presentation_agent import content_binding as b, planning as p
from presentation_agent.evidence import EvidenceRecord, TextLocator


SNAP = 'sha256:' + '1' * 64
OTHER = 'sha256:' + '2' * 64
EV = 'ev1:' + 'a' * 64
QID = 'qf1:' + 'b' * 64


def altered(value, **changes):
    result = object.__new__(type(value))
    for name, item in dict(vars(value), **changes).items():
        object.__setattr__(result, name, item)
    return result


def plan_for(bound, slides=None, omitted=()):
    if slides is None:
        slides = (tuple(x.content_id for x in bound.bindings),)
    return p.plan_presentation(bound, p.PlanningSpec(tuple(p.SlidePlan(x) for x in slides), omitted))


def fixture():
    evidence = EvidenceRecord(SNAP, TextLocator(1, 1), 'reported', (' same\n', ' same\n'))
    claims = tuple(c.Claim(text, (evidence.evidence_id,), qualifications=('Unverified authored\t',))
                   for text in ('  α\n\tمرحبا e\u0301  ', 'second'))
    bound = b.bind_content(c.ContentBundle(claims), evidence=(evidence,))
    return m.compose_presentation(plan_for(bound))


def cost(result):
    return sum(sum(len(x.text) + (len(x.status_label.value) if x.status_label else 0)
                   for x in s.content + s.qualifications)
               + sum(len(x.metadata.title) + len(x.metadata.bibliographic_detail) for x in s.citations)
               for s in result.slides)


class DisplayTests(unittest.TestCase):
    def setUp(self):
        self.composition = fixture()
        self.metadata = (c.SnapshotCitationMetadata(SNAP, '  عنوان e\u0301\n', ' Detail\t2026 '),)
        self.result = d.resolve_display(self.composition, citation_metadata=self.metadata)

    def resolve(self, composition=None, metadata=None, **kwargs):
        return d.resolve_display(self.composition if composition is None else composition,
                                 citation_metadata=self.metadata if metadata is None else metadata, **kwargs)

    def test_exact_surface_models_signature(self):
        expected = {
            d.BlockRef: dict(slide_index=int, kind=d.BlockKind, block_index=int),
            d.DisplayText: dict(source=d.BlockRef, text=str, status_label=Optional[d.DisplayStatusLabel]),
            d.DisplayCitation: dict(source=d.BlockRef, metadata=c.SnapshotCitationMetadata),
            d.SlideDisplay: dict(slide_index=int, content=Tuple[d.DisplayText, ...],
                                qualifications=Tuple[d.DisplayText, ...], citations=Tuple[d.DisplayCitation, ...]),
            d.DisplayLimits: dict(max_slides=int, max_placements=int, max_obligation_associations=int,
                                 max_metadata_records=int, max_text_chars=int),
            d.PresentationDisplay: dict(composition=m.PresentationComposition, slides=Tuple[d.SlideDisplay, ...]),
        }
        self.assertEqual(set(d.__all__), {x.__name__ for x in expected} |
                         {'BlockKind', 'DisplayStatusLabel', 'resolve_display'})
        for cls, hints in expected.items():
            self.assertEqual(get_type_hints(cls), hints)
            self.assertEqual([f.name for f in fields(cls)], list(hints))
            self.assertTrue(cls.__dataclass_params__.frozen)
        self.assertEqual([(x.name, x.value) for x in d.BlockKind],
                         [('CONTENT', 'content'), ('QUALIFICATION', 'qualification'), ('CITATION', 'citation')])
        self.assertEqual([(x.name, x.value) for x in d.DisplayStatusLabel], [('UNVERIFIED', 'Unverified')])
        signature = inspect.signature(d.resolve_display)
        self.assertEqual(list(signature.parameters), ['composition', 'citation_metadata', 'limits'])
        self.assertEqual(signature.parameters['citation_metadata'].kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertEqual(signature.parameters['citation_metadata'].default, ())
        self.assertEqual(signature.parameters['limits'].default, d.DisplayLimits())
        with self.assertRaises(FrozenInstanceError):
            self.result.slides = ()

    def test_exact_complete_correspondence_and_traceability(self):
        self.assertIs(self.result.composition, self.composition)
        for original, slide in zip(self.composition.slides, self.result.slides):
            for blocks, output, kind in ((original.content_blocks, slide.content, d.BlockKind.CONTENT),
                                        (original.qualification_blocks, slide.qualifications, d.BlockKind.QUALIFICATION),
                                        (original.citation_blocks, slide.citations, d.BlockKind.CITATION)):
                self.assertEqual(len(blocks), len(output))
                for i, (block, item) in enumerate(zip(blocks, output)):
                    self.assertEqual(item.source, d.BlockRef(slide.slide_index, kind, i))
                    self.assertIs(blocks[item.source.block_index], block)
                    if kind is d.BlockKind.CONTENT:
                        self.assertEqual(item.text, block.content.text)
                        self.assertIsNone(item.status_label)
                    elif kind is d.BlockKind.QUALIFICATION:
                        self.assertEqual(item.text, block.qualification.text)
                        self.assertIs(item.status_label, d.DisplayStatusLabel.UNVERIFIED
                                      if block.qualification.origin is c.QualificationOrigin.EVIDENCE else None)
                    else:
                        self.assertEqual(item.metadata.snapshot_id, block.snapshot_id)
                        self.assertIs(item.metadata, self.metadata[0])
        slide = self.result.slides[0]
        self.assertIn('  α\n\tمرحبا e\u0301  ', [x.text for x in slide.content])
        self.assertEqual([x.text for x in slide.qualifications[:2]], [' same\n'] * 2)
        self.assertNotEqual(slide.qualifications[0].source, slide.qualifications[1].source)
        self.assertEqual(self.composition.slides[0].citation_blocks[0].placement_indices, (0, 1))
        self.assertEqual(slide.citations[0].metadata.title, '  عنوان e\u0301\n')
        self.assertEqual(slide.citations[0].metadata.bibliographic_detail, ' Detail\t2026 ')
        for item in slide.content + slide.qualifications:
            self.assertFalse(any(marker in item.text for marker in ('P1', 'S1', 'Q1', 'sha256:', 'cl1:', 'ev1:')))

    def test_per_role_order_repetition_and_empty_slides(self):
        bound = self.composition.plan.bound_content
        first, second = bound.bindings
        bound = replace(bound, bindings=(replace(first, snapshot_ids=(OTHER,)),
                                        replace(second, snapshot_ids=(SNAP, OTHER))))
        ids = tuple(x.content_id for x in bound.bindings)
        comp = m.compose_presentation(plan_for(bound, (ids, (), ids[::-1])))
        metadata = self.metadata + (replace(self.metadata[0], snapshot_id=OTHER),)
        result = self.resolve(comp, metadata)
        self.assertEqual(result.slides[1], d.SlideDisplay(1, (), (), ()))
        self.assertEqual([x.metadata.snapshot_id for x in result.slides[0].citations], [OTHER, SNAP])
        self.assertEqual([x.text for x in result.slides[0].content],
                         [x.text for x in result.slides[2].content][::-1])
        self.assertEqual(len(result.slides[0].citations), 2)
        self.assertNotEqual(result.slides[0].citations[0].metadata.snapshot_id,
                            result.slides[0].citations[1].metadata.snapshot_id)
        self.assertEqual(result, self.resolve(comp, metadata[::-1]))

    def test_quantity_selection_and_omission(self):
        selection = c.QuantitySelection('quantity', (QID,))
        binding = b.ContentBinding(selection.selection_id, (), (QID,), (), ())
        bound = b.BoundContent(c.ContentBundle(quantity_selections=(selection,)), (binding,), (), ())
        placed = m.compose_presentation(plan_for(bound))
        with self.assertRaisesRegex(ValueError, 'QuantitySelection'):
            self.resolve(placed, ())
        omitted = m.compose_presentation(plan_for(bound, ((),), (selection.selection_id,)))
        with patch.object(c.QuantitySelection, 'selection_id', new_callable=PropertyMock, side_effect=AssertionError):
            with patch.object(c.QuantitySelection, '__getattribute__', side_effect=AssertionError):
                self.assertEqual(self.resolve(omitted, ()).slides, (d.SlideDisplay(0, (), (), ()),))

    def test_quantity_referencing_claim_is_exact_prose(self):
        claim = c.Claim('  42 percent\n', quantity_ids=(QID,))
        binding = b.ContentBinding(claim.claim_id, (), (QID,), (), ())
        bound = b.BoundContent(c.ContentBundle((claim,)), (binding,), (), ())
        comp = m.compose_presentation(plan_for(bound))
        self.assertEqual(self.resolve(comp, ()).slides[0].content[0].text, claim.text)

    def test_metadata_superset_permutation_unused_duplicates(self):
        unused = c.SnapshotCitationMetadata(OTHER)
        for records in (self.metadata + (unused, unused), (unused,) + self.metadata,
                        (replace(unused, title='changed'), unused) + self.metadata):
            result = self.resolve(metadata=records)
            self.assertEqual(result, self.result)
            self.assertIs(result.slides[0].citations[0].metadata, self.metadata[0])
        with self.assertRaisesRegex(ValueError, 'Missing'):
            self.resolve(metadata=(unused,))
        with self.assertRaisesRegex(ValueError, 'Duplicate required'):
            self.resolve(metadata=self.metadata * 2)
        for kwargs in (dict(title=None), dict(bibliographic_detail=None), dict(title=None, bibliographic_detail=None)):
            with self.assertRaisesRegex(ValueError, 'Incomplete'):
                self.resolve(metadata=(replace(self.metadata[0], **kwargs),))
        for bad in (altered(unused, title=''), altered(unused, snapshot_id='bad'),
                    altered(unused, bibliographic_detail=1), object(),
                    type('Subclass', (c.SnapshotCitationMetadata,), {})(OTHER)):
            with self.assertRaises(ValueError):
                self.resolve(metadata=self.metadata + (bad,))
        for bad in ([], type('TupleSubclass', (tuple,), {})(self.metadata)):
            with self.assertRaises(ValueError):
                self.resolve(metadata=bad)

    def test_limits_exact_lower_only_and_numeric_types(self):
        for field in fields(d.DisplayLimits):
            for value in (True, False, 0, -1, 1.0, '1', type('IntSubclass', (int,), {})(1), field.default + 1):
                with self.subTest(field=field.name, value=value):
                    with self.assertRaises(ValueError):
                        d.DisplayLimits(**{field.name: value})
                    with self.assertRaises(ValueError):
                        self.resolve(limits=altered(d.DisplayLimits(), **{field.name: value}))
        for bad in (None, {}, type('LimitSubclass', (d.DisplayLimits,), {})):
            with self.assertRaises(ValueError):
                self.resolve(limits=bad)
        exact = d.DisplayLimits(1, 2, 8, 1, cost(self.result))
        self.assertEqual(self.resolve(limits=exact), self.result)
        for name in ('max_placements', 'max_obligation_associations', 'max_text_chars'):
            with self.assertRaises(ValueError):
                self.resolve(limits=replace(exact, **{name: getattr(exact, name) - 1}))
        comp = replace(self.composition, slides=self.composition.slides + (m.SlideComposition(1, (), (), ()),))
        with self.assertRaisesRegex(ValueError, 'Slide limit'):
            self.resolve(comp, limits=exact)
        with self.assertRaisesRegex(ValueError, 'Metadata record limit'):
            self.resolve(metadata=self.metadata + (c.SnapshotCitationMetadata(OTHER),), limits=exact)

    def test_text_budget_labels_repetition_grouping(self):
        total = cost(self.result)
        # Two evidence occurrences each require their own fixed status label.
        without_labels = total - 2 * len('Unverified')
        with self.assertRaisesRegex(ValueError, 'Visible text'):
            self.resolve(limits=d.DisplayLimits(max_text_chars=without_labels))
        self.assertEqual(self.resolve(limits=d.DisplayLimits(max_text_chars=total)), self.result)
        comp = replace(self.composition, slides=self.composition.slides +
                       (replace(self.composition.slides[0], slide_index=1),))
        repeated = self.resolve(comp)
        self.assertEqual(cost(repeated), total * 2)
        with self.assertRaises(ValueError):
            self.resolve(comp, limits=d.DisplayLimits(max_text_chars=total * 2 - 1))
        self.assertEqual(self.resolve(comp, limits=d.DisplayLimits(max_text_chars=total * 2)), repeated)
        # Eight associations, but only four qualification and one citation occurrences.
        self.assertEqual(len(self.result.slides[0].qualifications), 4)
        self.assertEqual(len(self.result.slides[0].citations), 1)
        with self.assertRaisesRegex(ValueError, 'association'):
            self.resolve(limits=d.DisplayLimits(max_obligation_associations=7))

    def test_preflight_before_output_records(self):
        for kwargs in (dict(limits=d.DisplayLimits(max_text_chars=1)),
                       dict(limits=d.DisplayLimits(max_placements=1)),
                       dict(limits=d.DisplayLimits(max_obligation_associations=7)),
                       dict(metadata=()), dict(metadata=self.metadata * 2)):
            with ExitStack() as stack:
                for name in ('BlockRef', 'DisplayText', 'DisplayCitation', 'SlideDisplay', 'PresentationDisplay'):
                    stack.enter_context(patch.object(d, name, side_effect=AssertionError('premature output')))
                with self.assertRaises(ValueError):
                    self.resolve(**kwargs)

    def test_counts_precede_consumed_validation(self):
        slide = self.composition.slides[0]
        bad = altered(slide, content_blocks=(object(), object()),
                      qualification_blocks=(altered(slide.qualification_blocks[0], qualification=object(),
                                                    placement_indices=(0,) * 9),))
        with self.assertRaisesRegex(ValueError, 'association'):
            self.resolve(altered(self.composition, slides=(bad,)),
                         limits=d.DisplayLimits(max_obligation_associations=8))
        with self.assertRaisesRegex(ValueError, 'Metadata record'):
            self.resolve(metadata=(object(),) * 2, limits=d.DisplayLimits(max_metadata_records=1))

    def test_constructor_refs_text_and_citations(self):
        for bad in (True, -1, 1.0, type('IntSubclass', (int,), {})(0)):
            for field in ('slide_index', 'block_index'):
                with self.assertRaises(ValueError):
                    replace(d.BlockRef(0, d.BlockKind.CONTENT, 0), **{field: bad})
        with self.assertRaises(ValueError):
            d.BlockRef(0, 'content', 0)
        text = self.result.slides[0].content[0]
        for changes in (dict(text=''), dict(text=1), dict(text='\ud800'), dict(source=None),
                        dict(status_label='Unverified'), dict(status_label=d.DisplayStatusLabel.UNVERIFIED),
                        dict(source=d.BlockRef(0, d.BlockKind.CITATION, 0))):
            with self.assertRaises((ValueError, UnicodeError)):
                replace(text, **changes)
        entry = self.result.slides[0].citations[0]
        for changes in (dict(source=text.source), dict(metadata=None),
                        dict(metadata=c.SnapshotCitationMetadata(SNAP)),
                        dict(metadata=altered(entry.metadata, snapshot_id='bad'))):
            with self.assertRaises(ValueError):
                replace(entry, **changes)
        with self.assertRaises(ValueError):
            type('TextSubclass', (d.DisplayText,), {})(text.source, text.text)

    def test_slide_constructor_validation(self):
        slide = self.result.slides[0]
        for field in ('content', 'qualifications', 'citations'):
            for bad in ([], (None,), type('TupleSubclass', (tuple,), {})()):
                with self.assertRaises(ValueError):
                    replace(slide, **{field: bad})
        for changes in (dict(slide_index=True), dict(slide_index=1), dict(content=slide.content[::-1]),
                        dict(content=slide.qualifications), dict(qualifications=slide.content)):
            with self.assertRaises(ValueError):
                replace(slide, **changes)
        entry = slide.citations[0]
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            replace(slide, citations=(entry, replace(entry, source=replace(entry.source, block_index=1))))

    def test_presentation_local_validation_not_correspondence(self):
        # Deliberately local-valid omissions and unrelated prose are not certified output.
        self.assertEqual(d.PresentationDisplay(self.composition, ()).slides, ())
        slide = self.result.slides[0]
        mismatch = replace(slide, content=(replace(slide.content[0], text='different'),),
                           qualifications=(), citations=())
        direct = d.PresentationDisplay(self.composition, (mismatch,))
        self.assertNotEqual(direct, self.result)
        self.assertEqual(self.resolve(), self.result)
        for comp, slides in ((None, ()), (self.composition, []), (self.composition, (None,)),
                             (self.composition, (replace(slide, slide_index=1, content=(), qualifications=(), citations=()),))):
            with self.assertRaises(ValueError):
                d.PresentationDisplay(comp, slides)

    def test_factory_consumed_structure_validation(self):
        slide = self.composition.slides[0]
        for bad in (None, altered(self.composition, slides=[]),
                    altered(self.composition, slides=(altered(slide, slide_index=True),)),
                    altered(self.composition, slides=(altered(slide, slide_index=1),)),
                    altered(self.composition, slides=(altered(slide, content_blocks=slide.content_blocks[::-1]),)),
                    altered(self.composition, slides=(altered(slide, citation_blocks=slide.citation_blocks * 2),))):
            with self.assertRaises(ValueError):
                self.resolve(bad if bad is not None else altered(self.composition, slides=(None,)))
        with self.assertRaises(ValueError):
            d.resolve_display(None)
        qblock = slide.qualification_blocks[0]
        bad = altered(qblock, qualification=altered(qblock.qualification, verification=None))
        with self.assertRaises(ValueError):
            self.resolve(altered(self.composition, slides=(altered(slide, qualification_blocks=(bad,)),)))

    def test_default_text_ceiling_and_constructor_ceiling(self):
        claim = c.Claim('x' * 100000, (EV,))
        block = m.ContentBlock(0, claim.claim_id, claim)
        slides = tuple(m.SlideComposition(i, (block,), (), ()) for i in range(20))
        comp = m.PresentationComposition(self.composition.plan, slides)
        result = self.resolve(comp, ())
        self.assertEqual(cost(result), 2000000)
        extra = c.Claim('x', (EV,))
        comp_over = replace(comp, slides=slides + (m.SlideComposition(20, (m.ContentBlock(0, extra.claim_id, extra),), (), ()),))
        with self.assertRaisesRegex(ValueError, 'Visible text'):
            self.resolve(comp_over, ())
        display_extra = d.SlideDisplay(20, (d.DisplayText(d.BlockRef(20, d.BlockKind.CONTENT, 0), 'x'),), (), ())
        with self.assertRaisesRegex(ValueError, 'Visible text'):
            d.PresentationDisplay(comp, result.slides + (display_extra,))

    def test_default_structural_ceilings(self):
        claims = tuple(c.Claim(str(i), (EV,)) for i in range(10))
        blocks = tuple(m.ContentBlock(i, x.claim_id, x) for i, x in enumerate(claims))
        snapshots = tuple('sha256:' + format(i, '064x') for i in range(10))
        citations = tuple(m.CitationBlock(s, tuple(range(10))) for s in snapshots)
        slides = tuple(m.SlideComposition(i, blocks, citations, ()) for i in range(1000))
        comp = m.PresentationComposition(self.composition.plan, slides)
        metadata = tuple(c.SnapshotCitationMetadata(s, 't', 'd') for s in snapshots)
        result = self.resolve(comp, metadata)
        self.assertEqual(len(result.slides), 1000)
        self.assertEqual(sum(len(s.content) for s in result.slides), 10000)
        for changes, pattern in ((dict(slides=slides + (m.SlideComposition(1000, (), (), ()),)), 'Slide'),
                                 (dict(slides=(altered(slides[0], content_blocks=blocks + (blocks[0],)),) + slides[1:]), 'Placement'),
                                 (dict(slides=(altered(slides[0], citation_blocks=citations + (citations[0],)),) + slides[1:]), 'association')):
            with self.assertRaisesRegex(ValueError, pattern):
                self.resolve(altered(comp, **changes), metadata)
        with self.assertRaisesRegex(ValueError, 'Slide'):
            d.PresentationDisplay(comp, result.slides + (d.SlideDisplay(1000, (), (), ()),))
        with self.assertRaisesRegex(ValueError, 'Placement'):
            d.PresentationDisplay(comp, (altered(result.slides[0], content=result.slides[0].content * 2),) + result.slides[1:])
        with self.assertRaisesRegex(ValueError, 'association'):
            d.PresentationDisplay(altered(comp, slides=(altered(slides[0], citation_blocks=citations * 2),) + slides[1:]), ())

    def test_default_metadata_ceiling(self):
        unused = c.SnapshotCitationMetadata(OTHER)
        records = self.metadata + (unused,) * 99999
        self.assertEqual(self.resolve(metadata=records), self.result)
        with self.assertRaisesRegex(ValueError, 'Metadata record'):
            self.resolve(metadata=records + (unused,))

    def test_determinism_no_mutation_or_external_operations(self):
        before = deepcopy((self.composition, self.metadata))
        forbidden = ['builtins.open', 'io.open', 'os.open', 'socket.socket',
                     'presentation_agent.content_binding.bind_content',
                     'presentation_agent.content_binding.assess_citations',
                     'presentation_agent.content_binding.BoundContent.__post_init__',
                     'presentation_agent.planning.PresentationPlan.__post_init__',
                     'presentation_agent.content.Claim.__post_init__',
                     'presentation_agent.quantities.QuantityGraph.get',
                     'presentation_agent.quantities._calculate',
                     'presentation_agent.evidence_verification.verify_evidence']
        with ExitStack() as stack:
            for target in forbidden:
                stack.enter_context(patch(target, side_effect=AssertionError(target)))
            stack.enter_context(patch.object(c.Claim, 'claim_id', new_callable=PropertyMock, side_effect=AssertionError))
            self.assertEqual(self.resolve(), self.result)
            self.assertEqual(self.resolve(), self.resolve())
            with self.assertRaises(ValueError):
                self.resolve(limits=d.DisplayLimits(max_text_chars=1))
        self.assertEqual((self.composition, self.metadata), before)
        # Neither omitted content nor any plan graph is visited.
        self.assertEqual(self.resolve(altered(self.composition, plan=object())).slides, self.result.slides)

    def test_python39_architecture_package_root(self):
        tree = ast.parse(Path(d.__file__).read_text(), feature_version=9)
        imports = set()
        forbidden = {'bind_content', 'assess_citations', 'open', 'verify_evidence', '_calculate',
                     'claim_id', 'selection_id', 'quantity_ids', 'evidence_ids', 'bound_content',
                     'render', 'save', 'hashlib', 'datetime', 'random', 'socket'}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(x.name for x in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add('.' * node.level + node.module)
            elif isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, forbidden)
            elif isinstance(node, ast.Name):
                self.assertNotIn(node.id, forbidden)
        self.assertEqual(imports, {'dataclasses', 'enum', 'typing', '.composition', '.content'})
        ast.parse(Path(__file__).read_text(), feature_version=9)
        root = Path(presentation_agent.__file__).read_text()
        self.assertNotIn('display', root)
        for name in d.__all__:
            self.assertFalse(hasattr(presentation_agent, name))


if __name__ == '__main__':
    unittest.main()
