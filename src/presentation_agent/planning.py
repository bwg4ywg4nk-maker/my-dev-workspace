"""Immutable slide placements over trusted 3A bindings; no composition or I/O."""
from dataclasses import dataclass, fields
from typing import Tuple

from .content import Claim, ContentBundle, ContentLimits, QuantitySelection, _exact, _id
from .content_binding import BoundContent, ContentBinding


__all__ = ['SlidePlan', 'PlanningSpec', 'PresentationPlan', 'PlanningLimits',
           'plan_presentation']


def _content_ids(values):
    _exact(values, tuple)
    seen = set()
    for identity in values:
        _id(identity, ('cl1', 'qs1'))
        if identity in seen:
            raise ValueError('Duplicate content identity')
        seen.add(identity)


@dataclass(frozen=True)
class SlidePlan:
    content_ids: Tuple[str, ...]

    def __post_init__(self):
        _exact(self, SlidePlan)
        _content_ids(self.content_ids)


@dataclass(frozen=True)
class PlanningSpec:
    slides: Tuple[SlidePlan, ...] = ()
    omitted_content_ids: Tuple[str, ...] = ()

    def __post_init__(self):
        _exact(self, PlanningSpec)
        _spec_structure(self)
        object.__setattr__(self, 'omitted_content_ids',
                           tuple(sorted(self.omitted_content_ids)))


def _spec_structure(specification):
    _exact(specification, PlanningSpec)
    _exact(specification.slides, tuple)
    for slide in specification.slides:
        _exact(slide, SlidePlan)
        _content_ids(slide.content_ids)
    _content_ids(specification.omitted_content_ids)


@dataclass(frozen=True)
class PlanningLimits:
    max_slides: int = 1_000
    max_placements: int = 10_000

    def __post_init__(self):
        _exact(self, PlanningLimits)
        for field in fields(PlanningLimits):
            value = getattr(self, field.name)
            if type(value) is not int or not 1 <= value <= field.default:
                raise ValueError('Invalid planning limit: ' + field.name)


def _preflight(specification, limits):
    _exact(limits, PlanningLimits)
    limits.__post_init__()
    _exact(specification, PlanningSpec)
    _exact(specification.slides, tuple)
    if len(specification.slides) > limits.max_slides:
        raise ValueError('Slide limit exceeded')
    placements = 0
    for slide in specification.slides:
        _exact(slide, SlidePlan)
        _exact(slide.content_ids, tuple)
        placements += len(slide.content_ids)
        if placements > limits.max_placements:
            raise ValueError('Placement limit exceeded')


def _member_ids(bound):
    # Deliberately do not invoke 3A validators or inspect provenance fields.
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
    identities = set()
    for members, cls, attribute in (
            (bound.bundle.claims, Claim, 'claim_id'),
            (bound.bundle.quantity_selections, QuantitySelection, 'selection_id')):
        for member in members:
            _exact(member, cls)
            identity = getattr(member, attribute)
            if identity in identities:
                raise ValueError('Duplicate bundle member identity')
            identities.add(identity)
    binding_ids = set()
    previous = None
    for binding in bound.bindings:
        _exact(binding, ContentBinding)
        identity = binding.content_id
        _id(identity, ('cl1', 'qs1'))
        if previous is not None and identity <= previous:
            raise ValueError('Binding identities must be strictly lexical')
        previous = identity
        binding_ids.add(identity)
    if binding_ids != identities:
        raise ValueError('Binding identities must exactly match bundle members')
    return identities


@dataclass(frozen=True)
class PresentationPlan:
    bound_content: BoundContent
    specification: PlanningSpec

    def __post_init__(self):
        _exact(self, PresentationPlan)
        _preflight(self.specification, PlanningLimits())
        identities = _member_ids(self.bound_content)
        _spec_structure(self.specification)
        omitted = self.specification.omitted_content_ids
        if omitted != tuple(sorted(omitted)):
            raise ValueError('Omission identities must be lexical')
        placed = {identity for slide in self.specification.slides
                  for identity in slide.content_ids}
        omissions = set(omitted)
        if placed & omissions:
            raise ValueError('Content cannot be both placed and omitted')
        if (placed | omissions) - identities:
            raise ValueError('Unknown content reference')
        if placed | omissions != identities:
            raise ValueError('Incomplete content coverage')

    def bindings_for_slide(self, slide_index: int) -> Tuple[ContentBinding, ...]:
        """Return authoritative same-slide citation/qualification obligations."""
        if type(slide_index) is not int:
            raise ValueError('Slide index must be an exact integer')
        if slide_index < 0 or slide_index >= len(self.specification.slides):
            raise IndexError('Slide index out of range')
        bindings = {binding.content_id: binding for binding in self.bound_content.bindings}
        return tuple(bindings[identity]
                     for identity in self.specification.slides[slide_index].content_ids)


def plan_presentation(
    bound_content: BoundContent,
    specification: PlanningSpec,
    *,
    limits: PlanningLimits = PlanningLimits(),
) -> PresentationPlan:
    """Check coverage atomically without reconstructing 3A provenance."""
    _preflight(specification, limits)
    return PresentationPlan(bound_content, specification)
