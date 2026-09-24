"""Immutable same-slide semantic obligations over a trusted presentation plan.

Direct construction checks local structure, not factory correspondence or provenance.
No display, rendering, evidence verification, or persistence is performed here.
"""
from dataclasses import dataclass, fields
from typing import Tuple, Union

from .content import Claim, ContentBundle, ContentLimits, QuantitySelection, _exact, _id
from .content_binding import BoundContent, ContentBinding, QualificationBinding, _qualification_key
from .planning import PresentationPlan, PlanningSpec, SlidePlan


__all__ = ['ContentBlock', 'CitationBlock', 'QualificationBlock', 'SlideComposition',
           'PresentationComposition', 'CompositionLimits', 'compose_presentation']


def _index(value):
    if type(value) is not int or value < 0:
        raise ValueError('Expected exact nonnegative integer')


def _indices(values):
    _exact(values, tuple)
    if not values:
        raise ValueError('Expected nonempty placement indices')
    previous = -1
    for value in values:
        _index(value)
        if value <= previous:
            raise ValueError('Placement indices must be strictly increasing')
        previous = value


def _occurrence(q):
    return q.origin, q.owner_id, q.qualification_index


@dataclass(frozen=True)
class ContentBlock:
    placement_index: int
    content_id: str
    content: Union[Claim, QuantitySelection]

    def __post_init__(self):
        _exact(self, ContentBlock)
        _index(self.placement_index)
        if type(self.content) not in (Claim, QuantitySelection):
            raise ValueError('Expected concrete content member')
        _id(self.content_id, ('cl1',) if type(self.content) is Claim else ('qs1',))


@dataclass(frozen=True)
class CitationBlock:
    snapshot_id: str
    placement_indices: Tuple[int, ...]

    def __post_init__(self):
        _exact(self, CitationBlock)
        _id(self.snapshot_id, ('sha256',))
        _indices(self.placement_indices)


@dataclass(frozen=True)
class QualificationBlock:
    qualification: QualificationBinding
    placement_indices: Tuple[int, ...]

    def __post_init__(self):
        _exact(self, QualificationBlock)
        _exact(self.qualification, QualificationBinding)
        # This validator consumes only the five local occurrence fields.
        self.qualification.__post_init__()
        _indices(self.placement_indices)


@dataclass(frozen=True)
class SlideComposition:
    slide_index: int
    content_blocks: Tuple[ContentBlock, ...]
    citation_blocks: Tuple[CitationBlock, ...]
    qualification_blocks: Tuple[QualificationBlock, ...]

    def __post_init__(self):
        _exact(self, SlideComposition)
        _index(self.slide_index)
        for values in (self.content_blocks, self.citation_blocks, self.qualification_blocks):
            _exact(values, tuple)
        identities = set()
        for index, block in enumerate(self.content_blocks):
            _exact(block, ContentBlock)
            block.__post_init__()
            if block.placement_index != index:
                raise ValueError('Noncontiguous placement indices')
            if block.content_id in identities:
                raise ValueError('Duplicate content identity')
            identities.add(block.content_id)
        for blocks, cls in ((self.citation_blocks, CitationBlock),
                            (self.qualification_blocks, QualificationBlock)):
            seen = set()
            previous = None
            for block in blocks:
                _exact(block, cls)
                block.__post_init__()
                if block.placement_indices[-1] >= len(self.content_blocks):
                    raise ValueError('Unresolved placement association')
                key = (block.snapshot_id if cls is CitationBlock
                       else _occurrence(block.qualification))
                order = (block.placement_indices[0], block.snapshot_id if cls is CitationBlock
                         else _qualification_key(block.qualification))
                if key in seen:
                    raise ValueError('Duplicate obligation key')
                if previous is not None and order <= previous:
                    raise ValueError('Noncanonical obligation ordering')
                seen.add(key)
                previous = order


@dataclass(frozen=True)
class CompositionLimits:
    max_slides: int = 1_000
    max_placements: int = 10_000
    max_obligation_associations: int = 100_000

    def __post_init__(self):
        _exact(self, CompositionLimits)
        for field in fields(CompositionLimits):
            value = getattr(self, field.name)
            if type(value) is not int or not 1 <= value <= field.default:
                raise ValueError('Invalid composition limit: ' + field.name)


@dataclass(frozen=True)
class PresentationComposition:
    plan: PresentationPlan
    slides: Tuple[SlideComposition, ...]

    def __post_init__(self):
        _exact(self, PresentationComposition)
        _exact(self.plan, PresentationPlan)
        _exact(self.slides, tuple)
        limits = CompositionLimits()
        if len(self.slides) > limits.max_slides:
            raise ValueError('Slide limit exceeded')
        placements = associations = 0
        for index, slide in enumerate(self.slides):
            _exact(slide, SlideComposition)
            for values in (slide.content_blocks, slide.citation_blocks, slide.qualification_blocks):
                _exact(values, tuple)
            placements += len(slide.content_blocks)
            if placements > limits.max_placements:
                raise ValueError('Placement limit exceeded')
            for blocks, cls in ((slide.citation_blocks, CitationBlock),
                                (slide.qualification_blocks, QualificationBlock)):
                for block in blocks:
                    _exact(block, cls)
                    _exact(block.placement_indices, tuple)
                    associations += len(block.placement_indices)
                    if associations > limits.max_obligation_associations:
                        raise ValueError('Obligation association limit exceeded')
            if slide.slide_index != index:
                raise ValueError('Noncontiguous slide indices')
        for slide in self.slides:
            slide.__post_init__()


def _resolve(plan, limits):
    """Bound shallow structures and resolve members without replaying 3B."""
    _exact(plan, PresentationPlan)
    spec = plan.specification
    _exact(spec, PlanningSpec)
    _exact(spec.slides, tuple)
    if len(spec.slides) > limits.max_slides:
        raise ValueError('Slide limit exceeded')
    count = 0
    for slide in spec.slides:
        _exact(slide, SlidePlan)
        _exact(slide.content_ids, tuple)
        count += len(slide.content_ids)
        if count > limits.max_placements:
            raise ValueError('Placement limit exceeded')
    bound = plan.bound_content
    _exact(bound, BoundContent)
    _exact(bound.bundle, ContentBundle)
    _exact(bound.bundle.claims, tuple)
    _exact(bound.bundle.quantity_selections, tuple)
    _exact(bound.bindings, tuple)
    count = len(bound.bundle.claims) + len(bound.bundle.quantity_selections)
    if count > ContentLimits().max_items:
        raise ValueError('Content item limit exceeded')
    if len(bound.bindings) != count:
        raise ValueError('Binding count must equal member count')
    members = {}
    for values, cls, attr in ((bound.bundle.claims, Claim, 'claim_id'),
                              (bound.bundle.quantity_selections, QuantitySelection, 'selection_id')):
        for member in values:
            _exact(member, cls)
            identity = getattr(member, attr)
            _id(identity, ('cl1',) if cls is Claim else ('qs1',))
            if identity in members:
                raise ValueError('Duplicate member identity')
            members[identity] = member
    bindings = {}
    for binding in bound.bindings:
        _exact(binding, ContentBinding)
        _id(binding.content_id, ('cl1', 'qs1'))
        if binding.content_id in bindings:
            raise ValueError('Duplicate binding identity')
        bindings[binding.content_id] = binding
    if members.keys() != bindings.keys():
        raise ValueError('Binding/member correspondence mismatch')
    resolved = []
    for slide in spec.slides:
        placements = []
        seen = set()
        for identity in slide.content_ids:
            _id(identity, ('cl1', 'qs1'))
            if identity not in members or identity in seen:
                raise ValueError('Unknown or duplicate placement identity')
            seen.add(identity)
            placements.append((identity, members[identity], bindings[identity]))
        resolved.append(placements)
    return resolved


def compose_presentation(
    plan: PresentationPlan,
    *,
    limits: CompositionLimits = CompositionLimits(),
) -> PresentationComposition:
    """Compose trusted placements atomically; retain original semantic objects."""
    _exact(limits, CompositionLimits)
    limits.__post_init__()
    resolved = _resolve(plan, limits)
    # Count only. No obligation entry is touched and no obligation map/list or
    # output block is allocated until this complete pass has succeeded.
    associations = 0
    for placements in resolved:
        for _, _, binding in placements:
            _exact(binding.snapshot_ids, tuple)
            _exact(binding.qualifications, tuple)
            associations += len(binding.snapshot_ids) + len(binding.qualifications)
            if associations > limits.max_obligation_associations:
                raise ValueError('Obligation association limit exceeded')

    consistent = {}
    slides = []
    for slide_index, placements in enumerate(resolved):
        contents = []
        citations = {}
        qualifications = {}
        for index, (identity, member, binding) in enumerate(placements):
            contents.append(ContentBlock(index, identity, member))
            previous = None
            for snapshot in binding.snapshot_ids:
                _id(snapshot, ('sha256',))
                if previous is not None and snapshot <= previous:
                    raise ValueError('Noncanonical binding citation ordering')
                previous = snapshot
                citations.setdefault(snapshot, []).append(index)
            previous = None
            for q in binding.qualifications:
                _exact(q, QualificationBinding)
                q.__post_init__()
                key = _occurrence(q)
                order = _qualification_key(q)
                if previous is not None and order <= previous:
                    raise ValueError('Noncanonical binding qualification ordering')
                previous = order
                if key in consistent and consistent[key] != q:
                    raise ValueError('Conflicting qualification occurrence')
                consistent.setdefault(key, q)
                if key not in qualifications:
                    qualifications[key] = (q, [])
                qualifications[key][1].append(index)
        slides.append(SlideComposition(
            slide_index, tuple(contents),
            tuple(CitationBlock(key, tuple(indices)) for key, indices in citations.items()),
            tuple(QualificationBlock(q, tuple(indices)) for q, indices in qualifications.values())))
    return PresentationComposition(plan, tuple(slides))
