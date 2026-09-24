"""Exact audience-facing payloads over trusted semantic compositions; no layout."""
from dataclasses import dataclass, fields
from enum import Enum
from typing import Optional, Tuple

from .composition import (PresentationComposition, SlideComposition, CitationBlock,
                          QualificationBlock, _index)
from .content import (Claim, QualificationOrigin, SnapshotCitationMetadata,
                      _exact, _text)


__all__ = ['BlockKind', 'DisplayStatusLabel', 'BlockRef', 'DisplayText',
           'DisplayCitation', 'SlideDisplay', 'DisplayLimits',
           'PresentationDisplay', 'resolve_display']


class BlockKind(Enum):
    CONTENT = 'content'
    QUALIFICATION = 'qualification'
    CITATION = 'citation'


class DisplayStatusLabel(Enum):
    UNVERIFIED = 'Unverified'


@dataclass(frozen=True)
class BlockRef:
    slide_index: int
    kind: BlockKind
    block_index: int

    def __post_init__(self):
        _exact(self, BlockRef)
        _index(self.slide_index)
        _exact(self.kind, BlockKind)
        _index(self.block_index)


def _source(source, kinds):
    _exact(source, BlockRef)
    source.__post_init__()
    if source.kind not in kinds:
        raise ValueError('Incorrect source block kind')


def _metadata(metadata, complete=False):
    _exact(metadata, SnapshotCitationMetadata)
    metadata.__post_init__()
    if complete and (metadata.title is None or metadata.bibliographic_detail is None):
        raise ValueError('Incomplete required citation metadata')


@dataclass(frozen=True)
class DisplayText:
    source: BlockRef
    text: str
    status_label: Optional[DisplayStatusLabel] = None

    def __post_init__(self):
        _exact(self, DisplayText)
        _source(self.source, (BlockKind.CONTENT, BlockKind.QUALIFICATION))
        _text(self.text)
        if self.status_label is not None:
            _exact(self.status_label, DisplayStatusLabel)
            if self.source.kind is BlockKind.CONTENT:
                raise ValueError('Content forbids status label')


@dataclass(frozen=True)
class DisplayCitation:
    source: BlockRef
    metadata: SnapshotCitationMetadata

    def __post_init__(self):
        _exact(self, DisplayCitation)
        _source(self.source, (BlockKind.CITATION,))
        _metadata(self.metadata, complete=True)


@dataclass(frozen=True)
class SlideDisplay:
    slide_index: int
    content: Tuple[DisplayText, ...]
    qualifications: Tuple[DisplayText, ...]
    citations: Tuple[DisplayCitation, ...]

    def __post_init__(self):
        _exact(self, SlideDisplay)
        _index(self.slide_index)
        for values, cls, kind in ((self.content, DisplayText, BlockKind.CONTENT),
                                 (self.qualifications, DisplayText, BlockKind.QUALIFICATION),
                                 (self.citations, DisplayCitation, BlockKind.CITATION)):
            _exact(values, tuple)
            seen = set()
            for index, item in enumerate(values):
                _exact(item, cls)
                item.__post_init__()
                if (item.source.slide_index != self.slide_index or
                        item.source.kind is not kind or item.source.block_index != index):
                    raise ValueError('Noncontiguous or mismatched block reference')
                if kind is BlockKind.CITATION:
                    if item.metadata.snapshot_id in seen:
                        raise ValueError('Duplicate slide citation snapshot')
                    seen.add(item.metadata.snapshot_id)


@dataclass(frozen=True)
class DisplayLimits:
    max_slides: int = 1_000
    max_placements: int = 10_000
    max_obligation_associations: int = 100_000
    max_metadata_records: int = 100_000
    max_text_chars: int = 2_000_000

    def __post_init__(self):
        _exact(self, DisplayLimits)
        for field in fields(DisplayLimits):
            value = getattr(self, field.name)
            if type(value) is not int or not 1 <= value <= field.default:
                raise ValueError('Invalid display limit: ' + field.name)


def _ceiling(count, maximum, role):
    if count > maximum:
        raise ValueError(role + ' limit exceeded')


def _composition_counts(composition, limits):
    """Shallow counts before canonical block inspection, without reading the plan."""
    _exact(composition, PresentationComposition)
    _exact(composition.slides, tuple)
    _ceiling(len(composition.slides), limits.max_slides, 'Slide')
    placements = associations = 0
    for slide in composition.slides:
        _exact(slide, SlideComposition)
        for values in (slide.content_blocks, slide.qualification_blocks, slide.citation_blocks):
            _exact(values, tuple)
        placements += len(slide.content_blocks)
        _ceiling(placements, limits.max_placements, 'Placement')
        for blocks, cls in ((slide.qualification_blocks, QualificationBlock),
                            (slide.citation_blocks, CitationBlock)):
            for block in blocks:
                _exact(block, cls)
                _exact(block.placement_indices, tuple)
                associations += len(block.placement_indices)
                _ceiling(associations, limits.max_obligation_associations, 'Obligation association')


def _label(qualification):
    return (DisplayStatusLabel.UNVERIFIED
            if qualification.origin is QualificationOrigin.EVIDENCE else None)


def _text_cost(text, label=None):
    return len(text) + (len(label.value) if label is not None else 0)


def _citation_cost(metadata):
    return len(metadata.title) + len(metadata.bibliographic_detail)


@dataclass(frozen=True)
class PresentationDisplay:
    composition: PresentationComposition
    slides: Tuple[SlideDisplay, ...]

    def __post_init__(self):
        _exact(self, PresentationDisplay)
        _exact(self.composition, PresentationComposition)
        _exact(self.slides, tuple)
        limits = DisplayLimits()
        _composition_counts(self.composition, limits)
        _ceiling(len(self.slides), limits.max_slides, 'Slide')
        placements = obligations = metadata_records = 0
        for slide in self.slides:
            _exact(slide, SlideDisplay)
            for values in (slide.content, slide.qualifications, slide.citations):
                _exact(values, tuple)
            placements += len(slide.content)
            obligations += len(slide.qualifications) + len(slide.citations)
            metadata_records += len(slide.citations)
            _ceiling(placements, limits.max_placements, 'Placement')
            _ceiling(obligations, limits.max_obligation_associations, 'Obligation')
            _ceiling(metadata_records, limits.max_metadata_records, 'Metadata record')
        cost = 0
        for index, slide in enumerate(self.slides):
            _index(slide.slide_index)
            if slide.slide_index != index:
                raise ValueError('Noncontiguous slide indices')
            slide.__post_init__()
            cost += sum(_text_cost(x.text, x.status_label) for x in slide.content)
            cost += sum(_text_cost(x.text, x.status_label) for x in slide.qualifications)
            cost += sum(_citation_cost(x.metadata) for x in slide.citations)
            _ceiling(cost, limits.max_text_chars, 'Visible text')


def resolve_display(
    composition: PresentationComposition,
    *,
    citation_metadata: Tuple[SnapshotCitationMetadata, ...] = (),
    limits: DisplayLimits = DisplayLimits(),
) -> PresentationDisplay:
    """Resolve exact complete display content atomically, without semantic replay."""
    _exact(limits, DisplayLimits)
    limits.__post_init__()
    _exact(composition, PresentationComposition)
    _exact(composition.slides, tuple)
    _exact(citation_metadata, tuple)
    _ceiling(len(citation_metadata), limits.max_metadata_records, 'Metadata record')
    _composition_counts(composition, limits)

    required = set()
    for index, slide in enumerate(composition.slides):
        _index(slide.slide_index)
        if slide.slide_index != index:
            raise ValueError('Noncontiguous composition slide indices')
        slide.__post_init__()
        for block in slide.content_blocks:
            if type(block.content) is not Claim:
                raise ValueError('Placed QuantitySelection is unsupported')
            _text(block.content.text)
        required.update(block.snapshot_id for block in slide.citation_blocks)

    selected = {}
    for metadata in citation_metadata:
        _metadata(metadata)
        if metadata.snapshot_id in required:
            if metadata.snapshot_id in selected:
                raise ValueError('Duplicate required citation metadata')
            _metadata(metadata, complete=True)
            selected[metadata.snapshot_id] = metadata
    if len(selected) != len(required):
        raise ValueError('Missing required citation metadata')

    cost = 0
    for slide in composition.slides:
        for block in slide.content_blocks:
            cost += len(block.content.text)
            _ceiling(cost, limits.max_text_chars, 'Visible text')
        for block in slide.qualification_blocks:
            q = block.qualification
            cost += _text_cost(q.text, _label(q))
            _ceiling(cost, limits.max_text_chars, 'Visible text')
        for block in slide.citation_blocks:
            cost += _citation_cost(selected[block.snapshot_id])
            _ceiling(cost, limits.max_text_chars, 'Visible text')

    slides = []
    for index, slide in enumerate(composition.slides):
        slides.append(SlideDisplay(
            index,
            tuple(DisplayText(BlockRef(index, BlockKind.CONTENT, i), block.content.text)
                  for i, block in enumerate(slide.content_blocks)),
            tuple(DisplayText(BlockRef(index, BlockKind.QUALIFICATION, i),
                              block.qualification.text, _label(block.qualification))
                  for i, block in enumerate(slide.qualification_blocks)),
            tuple(DisplayCitation(BlockRef(index, BlockKind.CITATION, i),
                                  selected[block.snapshot_id])
                  for i, block in enumerate(slide.citation_blocks))))
    return PresentationDisplay(composition, tuple(slides))
