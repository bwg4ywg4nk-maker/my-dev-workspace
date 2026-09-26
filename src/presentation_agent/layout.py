"""Bounded ASCII/LF layout models and exact, provider-independent measurement.

The production provider remains unavailable pending controlled-runtime binding. Constructors
establish local consistency only; they do not certify provider observations.
"""
from dataclasses import dataclass, fields as _dataclass_fields
from enum import Enum
from fractions import Fraction
from hashlib import sha256 as _sha256
from math import gcd as _gcd, isfinite as _isfinite
from typing import Tuple

from .display import (BlockRef, BlockKind, DisplayStatusLabel, DisplayText,
                      DisplayCitation, SlideDisplay, PresentationDisplay)
from .content import SnapshotCitationMetadata
from .evidence import canonical_bytes

__all__ = ['FieldRole', 'HorizontalAlignment', 'VerticalAlignment', 'Rect',
           'Insets', 'FieldRef', 'FontIdentity', 'LayoutProfile', 'FieldPlacement',
           'SlideLayoutSpec', 'LayoutSpec', 'LineMeasurement', 'MeasuredField',
           'SlideLayout', 'PresentationLayout', 'LayoutLimits', 'layout_presentation']

_M = 2**53 - 1
_SIZES = (18000, 24000, 32000)
_NAME = 'ascii-lf-arial-regular-basic-720dpi-v1'
_FONT_SHA256 = '525979822591a3447cfc49d943d6f7683508e25543407871c0ed8fed05fd2bd9'
_NAMESPACE = b'presentation-agent:layout-profile:v1\0'


class FieldRole(Enum):
    TEXT = 'text'
    STATUS_LABEL = 'status_label'
    CITATION_TITLE = 'citation_title'
    CITATION_DETAIL = 'citation_detail'


class HorizontalAlignment(Enum):
    LEFT = 'left'


class VerticalAlignment(Enum):
    TOP = 'top'


def _exact(value, cls):
    if type(value) is not cls:
        raise ValueError('Expected concrete ' + cls.__name__)


def _require(condition, role):
    if not condition:
        raise ValueError(role)


def _integer(value, nonnegative=False):
    _exact(value, int)
    _require(abs(value) <= _M and (not nonnegative or value >= 0), 'Integer geometry bound')
    return value


def _index(value):
    _exact(value, int)
    _require(value >= 0, 'Nonnegative index required')


def _ceiling(value, maximum, role):
    _require(value <= maximum, role + ' limit exceeded')


def _local(value, cls, validator):
    try:
        _exact(value, cls)
        validator(value)
    except AttributeError as exc:
        raise ValueError(cls.__name__ + ': missing local attribute') from exc


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    def __post_init__(self):
        _local(self, Rect, _rect)


@dataclass(frozen=True)
class Insets:
    left: int
    top: int
    right: int
    bottom: int

    def __post_init__(self):
        _local(self, Insets, _insets)


@dataclass(frozen=True)
class FieldRef:
    source: BlockRef
    role: FieldRole

    def __post_init__(self):
        _local(self, FieldRef, _field_ref)


@dataclass(frozen=True)
class FontIdentity:
    sha256: str
    face_index: int
    family: str
    style: str

    def __post_init__(self):
        _local(self, FontIdentity, _font_identity)


@dataclass(frozen=True)
class LayoutProfile:
    name: str
    schema_version: int
    font: FontIdentity
    pillow_version: str
    freetype_version: str
    provider_build_id: str
    runtime_id: str

    def __post_init__(self):
        _local(self, LayoutProfile, _profile)

    @property
    def profile_id(self):
        _local(self, LayoutProfile, _profile)
        return 'lp1:' + _sha256(_NAMESPACE + canonical_bytes(_descriptor(self))).hexdigest()


@dataclass(frozen=True)
class FieldPlacement:
    field: FieldRef
    box: Rect
    insets: Insets
    font_size: int
    size_floor: int
    horizontal_alignment: HorizontalAlignment
    vertical_alignment: VerticalAlignment
    reading_order: int

    def __post_init__(self):
        _local(self, FieldPlacement, _placement)


@dataclass(frozen=True)
class SlideLayoutSpec:
    slide_index: int
    width: int
    height: int
    safe_margins: Insets
    fields: Tuple[FieldPlacement, ...]

    def __post_init__(self):
        _local(self, SlideLayoutSpec, _slide_spec)


@dataclass(frozen=True)
class LayoutSpec:
    slides: Tuple[SlideLayoutSpec, ...]

    def __post_init__(self):
        _local(self, LayoutSpec, _layout_spec)


@dataclass(frozen=True)
class LineMeasurement:
    line_index: int
    source_start: int
    source_end: int
    baseline: int
    advance: Fraction
    provider_bounds: Tuple[Fraction, Fraction, Fraction, Fraction]
    occupancy: Rect

    def __post_init__(self):
        _local(self, LineMeasurement, _line_record)


@dataclass(frozen=True)
class MeasuredField:
    placement: FieldPlacement
    text: str
    ascent: Fraction
    descent: Fraction
    lines: Tuple[LineMeasurement, ...]
    occupancy: Rect

    def __post_init__(self):
        _local(self, MeasuredField, _measured_field)


@dataclass(frozen=True)
class SlideLayout:
    specification: SlideLayoutSpec
    fields: Tuple[MeasuredField, ...]

    def __post_init__(self):
        _local(self, SlideLayout, _slide_layout)


@dataclass(frozen=True)
class PresentationLayout:
    display: PresentationDisplay
    specification: LayoutSpec
    profile: LayoutProfile
    slides: Tuple[SlideLayout, ...]

    def __post_init__(self):
        _local(self, PresentationLayout, _presentation_layout)


@dataclass(frozen=True)
class LayoutLimits:
    max_slides: int = 1000
    max_display_fields: int = 10000
    max_fields_per_slide: int = 128
    max_total_characters: int = 2000000
    max_characters_per_field: int = 100000
    max_characters_per_line: int = 4096
    max_lines_per_field: int = 256
    max_total_line_slots: int = 100000
    max_font_bytes: int = 8388608
    max_slide_width: int = 14400000
    max_slide_height: int = 14400000

    def __post_init__(self):
        _local(self, LayoutLimits, _limits)


def _limits(value):
    for field in _dataclass_fields(LayoutLimits):
        item = getattr(value, field.name)
        _exact(item, int)
        _require(1 <= item <= field.default, 'Invalid limit: ' + field.name)


def _edges(value):
    return value.left, value.top, value.right, value.bottom


def _rect(value):
    _exact(value, Rect)
    for name in ('left', 'top', 'right', 'bottom'):
        _integer(getattr(value, name))
    _require(value.left <= value.right and value.top <= value.bottom, 'Unordered rectangle')


def _insets(value):
    _exact(value, Insets)
    for name in ('left', 'top', 'right', 'bottom'):
        _integer(getattr(value, name), True)


def _positive(edges):
    _require(edges[0] < edges[2] and edges[1] < edges[3], 'Positive extent required')


def _contains(outer, inner):
    for valid, edge in zip((outer[0] <= inner[0], outer[1] <= inner[1],
                            inner[2] <= outer[2], inner[3] <= outer[3]),
                           ('left', 'top', 'right', 'bottom')):
        _require(valid, 'Containment ' + edge)


def _block_ref(value):
    _exact(value, BlockRef)
    _index(value.slide_index)
    _exact(value.kind, BlockKind)
    _index(value.block_index)


def _field_ref(value):
    _exact(value, FieldRef)
    _block_ref(value.source)
    _exact(value.role, FieldRole)
    legal = {BlockKind.CONTENT: (FieldRole.TEXT,),
             BlockKind.QUALIFICATION: (FieldRole.TEXT, FieldRole.STATUS_LABEL),
             BlockKind.CITATION: (FieldRole.CITATION_TITLE, FieldRole.CITATION_DETAIL)}
    _require(value.role in legal[value.source.kind], 'Illegal field role/kind')


def _key(ref):
    return (ref.source.slide_index,
            (BlockKind.CONTENT, BlockKind.QUALIFICATION, BlockKind.CITATION).index(ref.source.kind),
            ref.source.block_index,
            1 if ref.role in (FieldRole.STATUS_LABEL, FieldRole.CITATION_DETAIL) else 0)


def _digest(value, prefix=''):
    _exact(value, str)
    _require(len(value) == len(prefix) + 64 and value.startswith(prefix)
             and all(c in '0123456789abcdef' for c in value[len(prefix):]), 'Invalid digest')


def _short_string(value, ascii_only=False):
    _exact(value, str)
    _require(0 < len(value) <= 100, 'Invalid string length')
    _require(bool(value.strip()), 'Blank string')
    try:
        value.encode('utf-8', errors='strict')
    except UnicodeError as exc:
        raise ValueError('Invalid UTF-8 string') from exc
    if ascii_only:
        _require(all(32 <= ord(c) <= 126 for c in value), 'Printable ASCII required')


def _font_identity(value):
    _exact(value, FontIdentity)
    _digest(value.sha256)
    _integer(value.face_index, True)
    _short_string(value.family)
    _short_string(value.style)


def _profile(value):
    _exact(value, LayoutProfile)
    _exact(value.name, str)
    _require(value.name == _NAME, 'Unsupported profile name')
    _exact(value.schema_version, int)
    _require(value.schema_version == 1, 'Unsupported profile schema')
    _font_identity(value.font)
    _short_string(value.pillow_version, True)
    _short_string(value.freetype_version, True)
    _digest(value.provider_build_id, 'sha256:')
    _digest(value.runtime_id, 'sha256:')


def _content_edges(placement):
    b, i = placement.box, placement.insets
    return (b.left + i.left, b.top + i.top, b.right - i.right, b.bottom - i.bottom)


def _content_box(placement):
    result = _content_edges(placement)
    for edge in result:
        _integer(edge)
    _positive(result)
    _contains(_edges(placement.box), result)
    return result


def _placement_geometry(value):
    _rect(value.box)
    _positive(_edges(value.box))
    _insets(value.insets)
    _content_box(value)
    for name in ('font_size', 'size_floor'):
        size = getattr(value, name)
        _integer(size)
        _require(size in _SIZES, 'Unsupported font size/floor')
    _require(value.font_size >= value.size_floor, 'Size below floor')
    _exact(value.horizontal_alignment, HorizontalAlignment)
    _require(value.horizontal_alignment is HorizontalAlignment.LEFT, 'Unsupported horizontal alignment')
    _exact(value.vertical_alignment, VerticalAlignment)
    _require(value.vertical_alignment is VerticalAlignment.TOP, 'Unsupported vertical alignment')


def _placement(value):
    _field_ref(value.field)
    _placement_geometry(value)
    _index(value.reading_order)


def _spec_counts(slides, limits):
    _exact(slides, tuple)
    _ceiling(len(slides), limits.max_slides, 'Slides')
    total = 0
    for slide in slides:
        _exact(slide, SlideLayoutSpec)
        _exact(slide.fields, tuple)
        _ceiling(len(slide.fields), limits.max_fields_per_slide, 'Slide fields')
        total += len(slide.fields)
        _ceiling(total, limits.max_display_fields, 'Specification fields')


def _ranks_and_order(slide):
    previous = None
    ranks = set()
    for placement in slide.fields:
        key = _key(placement.field)
        _require(key[0] == slide.slide_index, 'Cross-slide allocation')
        _require(previous is None or previous < key, 'Duplicate or noncanonical allocation')
        previous = key
        _index(placement.reading_order)
        _require(placement.reading_order < len(slide.fields) and
                 placement.reading_order not in ranks, 'Reading order permutation')
        ranks.add(placement.reading_order)


def _slide_geometry(slide, limits):
    for name, maximum in (('width', limits.max_slide_width),
                          ('height', limits.max_slide_height)):
        dimension = getattr(slide, name)
        _integer(dimension)
        _require(dimension > 0, 'Positive slide dimension required')
        _ceiling(dimension, maximum, 'Slide dimension')
    _insets(slide.safe_margins)
    m = slide.safe_margins
    safe = (m.left, m.top, slide.width - m.right, slide.height - m.bottom)
    for edge in safe:
        _integer(edge)
    _positive(safe)
    _contains((0, 0, slide.width, slide.height), safe)
    for placement in slide.fields:
        _placement_geometry(placement)
        _contains(safe, _edges(placement.box))
    for i, first in enumerate(slide.fields):
        for j in range(i + 1, len(slide.fields)):
            a, b = first.box, slide.fields[j].box
            _require(not (max(a.left, b.left) < min(a.right, b.right) and
                          max(a.top, b.top) < min(a.bottom, b.bottom)), 'Field box overlap')


def _slide_spec(value):
    limits = LayoutLimits()
    _spec_counts((value,), limits)
    _index(value.slide_index)
    for placement in value.fields:
        _exact(placement, FieldPlacement)
        _field_ref(placement.field)
    _ranks_and_order(value)
    _slide_geometry(value, limits)


def _layout_spec(value):
    _spec_counts(value.slides, LayoutLimits())
    for i, slide in enumerate(value.slides):
        _slide_spec(slide)
        _require(slide.slide_index == i, 'Noncontiguous slide indices')


def _descriptor(profile):
    return {
      "schema_version": profile.schema_version,
      "name": profile.name,
      "font": {"sha256": profile.font.sha256, "face_index": profile.font.face_index,
               "family": profile.font.family, "style": profile.font.style, "static": True},
      "provider": {"name": "Pillow", "version": profile.pillow_version,
                   "freetype_version": profile.freetype_version, "engine": "BASIC",
                   "build_id": profile.provider_build_id, "runtime_id": profile.runtime_id,
                   "runtime_configuration": "controlled-fresh-process-no-overrides-v1",
                   "font_inspection": "sfnt-unicode-ascii-agreement-v1",
                   "font_encoding": "unic", "measurement_mode": "L",
                   "return_protocol": "pillow-basic-exact-shapes-v1",
                   "bbox_anchor": "ls", "stroke_width": 0,
                   "features": None, "language": None, "direction": None},
      "units": {"model_units_per_point": 1000, "pixels_per_point": 10,
                "model_units_per_pixel": 100},
      "font_sizes": [18000, 24000, 32000],
      "text": {"codepoint_min": 32, "codepoint_max": 126, "line_separator": 10,
               "direction": "ltr", "edge_spaces": "reject",
               "spaces_only_lines": "reject", "internal_spaces": "preserve",
               "blank_lines": "preserve", "trailing_lf": "preserve",
               "empty_primitive_lines": 1, "complete_blank_fields": "reject",
               "lf_semantics": "authored-line-boundary"},
      "measurement": {"observations": "exact-binary-rational",
                      "bounds": "provider-relative-left-baseline",
                      "empty_line": "zero-advance-zero-bounds",
                      "metrics": "independent-all-supported-sizes",
                      "line_height": "ascent-plus-positive-descent",
                      "baseline": "ascent-plus-index-times-line-height",
                      "leading": 0,
                      "envelope": ["translated-provider-box", "advance-segment",
                                   "complete-vertical-slot"],
                      "negative_bearings": "preserve"},
      "rounding": {"scalar": "nearest-ties-positive-infinity",
                   "minima": "floor", "maxima": "ceiling", "epsilon": 0},
      "layout": {"dimensions": "explicit-per-slide", "safe_margins": "explicit",
                 "allocation": "complete-exactly-once-same-slide",
                 "field_order": "source-canonical-v1",
                 "reading_order": "explicit-per-slide-permutation",
                 "size_floor": "supported-size-not-above-size",
                 "alignment": ["left", "top"], "origin": "content-left-top",
                 "containment": "inclusive-four-edges",
                 "overlap": "field-box-interiors-forbidden",
                 "shared_edges": "allow", "repair": "forbid",
                 "wrap": "forbid", "autofit": "forbid", "shrink": "forbid",
                 "pagination": "forbid", "fallback": "forbid",
                 "substitution": "forbid", "clipping_success": "forbid"},
      "arithmetic": {"max_integer_magnitude": 9007199254740991,
                     "max_rational_numerator_magnitude": 9007199254740991,
                     "max_rational_denominator": 9007199254740991,
                     "checkpoints": "semantic-checkpoints-v1"},
      "resource_policy": "layout-limits-v1-lower-only",
      "guarantee": "level-2-provider-measured-fit",
      "emu_owner": "future-renderer"
    }


def _rational(value):
    _exact(value, Fraction)
    _exact(value.numerator, int)
    _exact(value.denominator, int)
    _require(value.denominator > 0 and abs(value.numerator) <= _M and
             value.denominator <= _M and _gcd(value.numerator, value.denominator) == 1,
             'Rational checkpoint bound/canonical form')
    return value


def _observation(value, integer_only=False):
    if type(value) is int:
        return _rational(Fraction(value))
    if not integer_only and type(value) is float and _isfinite(value):
        return _rational(Fraction(*value.as_integer_ratio()))
    raise ValueError('Invalid provider scalar')


def _bounds(value):
    _exact(value, tuple)
    _require(len(value) == 4, 'Bounds arity')
    for coordinate in value:
        _rational(coordinate)
    _require(value[0] <= value[2] and value[1] <= value[3], 'Unordered provider bounds')


def _scaled(value):
    _rational(value)
    _rational(100 * value)
    return value


def _metrics(ascent, descent):
    _rational(ascent)
    _rational(descent)
    _require(ascent > 0 and descent >= 0, 'Invalid ascent/descent')
    height = _rational(ascent + descent)
    _require(height > 0, 'Invalid line height')
    for value in (ascent, descent, height):
        _scaled(value)
    return height


def _floor(value):
    return value.numerator // value.denominator


def _ceil(value):
    return -((-value.numerator) // value.denominator)


def _nearest(value):
    # The addition is deliberately not a semantic checkpoint.
    return _integer(_floor(value + Fraction(1, 2)))


def _line_geometry(ascent, descent, index, advance, bounds):
    height = _metrics(ascent, descent)
    _index(index)
    _rational(advance)
    _require(advance >= 0, 'Negative advance')
    _bounds(bounds)
    baseline = _rational(ascent + index * height)
    start = _rational(index * height)
    end = _rational((index + 1) * height)
    for value in (baseline, start, end):
        _rational(100 * value)
    left, top, right, bottom = bounds
    for value in (advance, left, top, right, bottom):
        _scaled(value)
    box_top = _rational(baseline + top)
    box_bottom = _rational(baseline + bottom)
    for value in (box_top, box_bottom):
        _rational(100 * value)
    envelope = (min(left, Fraction(0)), min(box_top, baseline, start),
                max(right, advance, Fraction(0)), max(box_bottom, baseline, end))
    for edge in envelope:
        _rational(edge)
    for edge in envelope:
        _rational(100 * edge)
    rounded = (_floor(100 * envelope[0]), _floor(100 * envelope[1]),
               _ceil(100 * envelope[2]), _ceil(100 * envelope[3]))
    for edge in rounded:
        _integer(edge)
    return _nearest(100 * baseline), rounded


def _union(boxes):
    # Callers establish a nonempty, bounded population before collecting boxes.
    result = (min(b[0] for b in boxes), min(b[1] for b in boxes),
              max(b[2] for b in boxes), max(b[3] for b in boxes))
    for edge in result:
        _integer(edge)
    return result


def _translated_fit(placement, occupancy):
    # Authored geometry was established in pass 7 (or the parent constructor).
    content = _content_edges(placement)
    translated = (occupancy[0] + content[0], occupancy[1] + content[1],
                  occupancy[2] + content[0], occupancy[3] + content[1])
    for edge in translated:
        _integer(edge)
    _contains(content, translated)


def _text_length(text, limits, total):
    _exact(text, str)
    _ceiling(len(text), limits.max_characters_per_field, 'Field characters')
    total += len(text)
    _ceiling(total, limits.max_total_characters, 'Total characters')
    return total


def _scan_text(text, limits, total_slots, complete=True):
    """No split or span allocation until every governed scan succeeds."""
    if complete:
        _require(bool(text.strip()), 'Complete blank field')
    for offset, character in enumerate(text):
        _require(character == '\n' or 32 <= ord(character) <= 126,
                 'Text domain at offset ' + str(offset))
    start = slots = 0
    for end in range(len(text) + 1):
        if end != len(text) and text[end] != '\n':
            continue
        _ceiling(end - start, limits.max_characters_per_line, 'Line characters')
        if end > start:
            _require(text[start] != ' ' and text[end - 1] != ' ', 'Line edge spaces')
        slots += 1
        _ceiling(slots, limits.max_lines_per_field, 'Field line slots')
        total_slots += 1
        _ceiling(total_slots, limits.max_total_line_slots, 'Total line slots')
        start = end + 1
    return total_slots


def _spans(text):
    start = 0
    result = []
    for end in range(len(text) + 1):
        if end == len(text) or text[end] == '\n':
            result.append((start, end))
            start = end + 1
    return tuple(result)


def _line_record(value):
    _exact(value, LineMeasurement)
    for name in ('line_index', 'source_start', 'source_end'):
        _index(getattr(value, name))
    _require(value.source_start <= value.source_end, 'Unordered source range')
    _integer(value.baseline, True)
    _rational(value.advance)
    _require(value.advance >= 0, 'Negative advance')
    _bounds(value.provider_bounds)
    for coordinate in (value.advance,) + value.provider_bounds:
        _scaled(coordinate)
    _rect(value.occupancy)


def _output_counts(slides, limits):
    """Preflight every output population before validating any measured child."""
    _exact(slides, tuple)
    _ceiling(len(slides), limits.max_slides, 'Output slides')
    count = spec_count = 0
    for slide in slides:
        _exact(slide, SlideLayout)
        _exact(slide.specification, SlideLayoutSpec)
        _exact(slide.specification.fields, tuple)
        _ceiling(len(slide.specification.fields), limits.max_fields_per_slide, 'Specification fields')
        spec_count += len(slide.specification.fields)
        _ceiling(spec_count, limits.max_display_fields, 'Output specification fields')
        _exact(slide.fields, tuple)
        _ceiling(len(slide.fields), limits.max_fields_per_slide, 'Output fields')
        count += len(slide.fields)
        _ceiling(count, limits.max_display_fields, 'Output fields')
    characters = slots = 0
    for slide in slides:
        for field in slide.fields:
            _exact(field, MeasuredField)
            _exact(field.lines, tuple)
            _ceiling(len(field.lines), limits.max_lines_per_field, 'Output line tuple')
            slots += len(field.lines)
            _ceiling(slots, limits.max_total_line_slots, 'Output line tuples')
            characters = _text_length(field.text, limits, characters)
    # Text-derived slot counts must independently pass, even for forged tuples.
    slots = 0
    for slide in slides:
        for field in slide.fields:
            slots = _scan_text(field.text, limits, slots)


def _measured_field(value):
    limits = LayoutLimits()
    _exact(value.lines, tuple)
    _ceiling(len(value.lines), limits.max_lines_per_field, 'Line tuple')
    _text_length(value.text, limits, 0)
    _scan_text(value.text, limits, 0)
    _exact(value.placement, FieldPlacement)
    _placement(value.placement)
    _metrics(value.ascent, value.descent)
    spans = _spans(value.text)
    _require(len(value.lines) == len(spans), 'Line/range correspondence')
    boxes = []
    for i, (line, span) in enumerate(zip(value.lines, spans)):
        _line_record(line)
        _require((line.line_index, line.source_start, line.source_end) == (i,) + span,
                 'Line source range/index')
        if span[0] == span[1]:
            _require(line.advance == 0 and line.provider_bounds == (0, 0, 0, 0),
                     'Empty line observations')
        baseline, box = _line_geometry(value.ascent, value.descent, i,
                                       line.advance, line.provider_bounds)
        _require(line.baseline == baseline and _edges(line.occupancy) == box,
                 'Line measurement equations')
        boxes.append(box)
    _rect(value.occupancy)
    _require(_edges(value.occupancy) == _union(boxes), 'Field occupancy union')
    _translated_fit(value.placement, _edges(value.occupancy))


def _slide_layout(value):
    _output_counts((value,), LayoutLimits())
    _slide_spec(value.specification)
    _require(len(value.fields) == len(value.specification.fields), 'Measured field correspondence')
    for field, placement in zip(value.fields, value.specification.fields):
        _measured_field(field)
        _require(field.placement == placement, 'Measured placement correspondence')


def _presentation_layout(value):
    _exact(value.display, PresentationDisplay)
    _exact(value.specification, LayoutSpec)
    _spec_counts(value.specification.slides, LayoutLimits())
    _output_counts(value.slides, LayoutLimits())
    _layout_spec(value.specification)
    _profile(value.profile)
    _require(len(value.slides) == len(value.specification.slides), 'Output slide correspondence')
    for slide, spec in zip(value.slides, value.specification.slides):
        _slide_layout(slide)
        _require(slide.specification == spec, 'Output specification correspondence')


def _display_containers(slide):
    for name in ('content', 'qualifications', 'citations'):
        yield getattr(slide, name)


def _payload_preflight(display, specification, limits):
    # 3(a): both lengths before either population's entries.
    _ceiling(len(display.slides), limits.max_slides, 'Display slides')
    _ceiling(len(specification.slides), limits.max_slides, 'Specification slides')
    total = 0
    # 3(b): minimum display counts, then all allocation counts.
    for slide in display.slides:
        _exact(slide, SlideDisplay)
        for values in _display_containers(slide):
            _exact(values, tuple)
            _ceiling(len(values), limits.max_fields_per_slide, 'Display container')
        count = len(slide.content) + len(slide.qualifications) + 2 * len(slide.citations)
        _ceiling(count, limits.max_fields_per_slide, 'Minimum slide fields')
        total += count
        _ceiling(total, limits.max_display_fields, 'Minimum display fields')
    _spec_counts(specification.slides, limits)
    # 3(c): count non-None occurrences without accessing label.value.
    total = 0
    for slide in display.slides:
        count = len(slide.content) + len(slide.qualifications) + 2 * len(slide.citations)
        for values, cls in ((slide.content, DisplayText), (slide.qualifications, DisplayText),
                            (slide.citations, DisplayCitation)):
            for item in values:
                _exact(item, cls)
                if cls is DisplayText and item.status_label is not None:
                    count += 1
                    _ceiling(count, limits.max_fields_per_slide, 'Slide fields with labels')
                    _ceiling(total + count, limits.max_display_fields, 'Display fields with labels')
        total += count
        _ceiling(total, limits.max_display_fields, 'Display fields with labels')
    # 3(d): canonical payload order; citation validity is owned only here.
    characters = 0
    for slide in display.slides:
        for values, content in ((slide.content, True), (slide.qualifications, False)):
            for item in values:
                characters = _text_length(item.text, limits, characters)
                if item.status_label is not None:
                    _exact(item.status_label, DisplayStatusLabel)
                    _require(item.status_label is DisplayStatusLabel.UNVERIFIED and not content,
                             'Forbidden status label')
                    characters = _text_length(item.status_label.value, limits, characters)
        for item in slide.citations:
            metadata = item.metadata
            _exact(metadata, SnapshotCitationMetadata)
            _digest(metadata.snapshot_id, 'sha256:')
            characters = _text_length(metadata.title, limits, characters)
            characters = _text_length(metadata.bibliographic_detail, limits, characters)
            _require(bool(metadata.title.strip()) and bool(metadata.bibliographic_detail.strip()),
                     'Blank citation payload')


def _references(display, specification):
    # All reference shapes precede any correspondence/key comparison.
    for slide in display.slides:
        for values in _display_containers(slide):
            for item in values:
                _block_ref(item.source)
    for slide in specification.slides:
        for placement in slide.fields:
            _exact(placement, FieldPlacement)
            _field_ref(placement.field)
    for slides in (display.slides, specification.slides):
        for index, slide in enumerate(slides):
            _index(slide.slide_index)
            _require(slide.slide_index == index, 'Noncontiguous slide indices')
    _require(len(display.slides) == len(specification.slides), 'Slide count correspondence')
    for slide in display.slides:
        for values, kind in zip(_display_containers(slide),
                                (BlockKind.CONTENT, BlockKind.QUALIFICATION, BlockKind.CITATION)):
            for index, item in enumerate(values):
                source = item.source
                _require((source.slide_index, source.kind, source.block_index) ==
                         (slide.slide_index, kind, index), 'Display source correspondence')
        seen = set()
        for item in slide.citations:
            snapshot_id = item.metadata.snapshot_id
            _require(snapshot_id not in seen, 'Duplicate citation snapshot')
            seen.add(snapshot_id)


def _enumerate_fields(display):
    # Private reference pairs avoid replaying FieldRef validation in mapping pass 5.
    # Output placements retain the original public FieldRef and BlockRef objects.
    result = []
    for slide in display.slides:
        required = []
        for item in slide.content:
            required.append(((item.source, FieldRole.TEXT), item.text, True))
        for item in slide.qualifications:
            required.append(((item.source, FieldRole.TEXT), item.text, True))
            if item.status_label is not None:
                required.append(((item.source, FieldRole.STATUS_LABEL),
                                 item.status_label.value, False))
        for item in slide.citations:
            required.append(((item.source, FieldRole.CITATION_TITLE),
                             item.metadata.title, False))
            required.append(((item.source, FieldRole.CITATION_DETAIL),
                             item.metadata.bibliographic_detail, False))
        result.append(tuple(required))
    return tuple(result)


def _coverage(required, specification):
    for items, slide in zip(required, specification.slides):
        _require(len(items) == len(slide.fields), 'Field coverage')
        for (ref, text, complete), placement in zip(items, slide.fields):
            _require(ref == (placement.field.source, placement.field.role), 'Field coverage/order')
        _ranks_and_order(slide)


def _text_preflight(required, limits):
    slots = 0
    for items in required:
        for ref, text, complete in items:
            slots = _scan_text(text, limits, slots, complete)
    return tuple(tuple(_spans(text) for ref, text, complete in items) for items in required)


def _profile_preflight(profile, font_bytes, limits):
    _profile(profile)
    _require((profile.font.family, profile.font.style, profile.font.face_index) ==
             ('Arial', 'Regular', 0), 'Unsupported v1 font identity')
    _require(len(font_bytes) > 0, 'Empty font bytes')
    _ceiling(len(font_bytes), limits.max_font_bytes, 'Font bytes')
    digest = _sha256(font_bytes).hexdigest()
    _require(digest == profile.font.sha256 and digest == _FONT_SHA256, 'Font digest mismatch')
    # No provider access or installed-version comparison at this pass.
    return 'lp1:' + _sha256(_NAMESPACE + canonical_bytes(_descriptor(profile))).hexdigest()


def _open_provider(profile):
    """Private pass-10 seam; deliberately closed until the trusted bootstrap exists.

    A controlled double supplies basic_engine, inspect_font and load_font.
    A future adapter must establish the entire compatibility/lifecycle binding
    before returning; this seam is not a public plugin or certification API.
    """
    raise ValueError('Controlled fresh-process lifecycle/build/runtime binding unavailable')


def _load_fonts(provider, font_bytes, profile):
    provider.inspect_font(font_bytes, profile)
    fonts = {}
    for size in _SIZES:
        font = provider.load_font(font_bytes, size=size // 100, index=0,
                                  encoding='unic', layout_engine=provider.basic_engine)
        _require(font.layout_engine == provider.basic_engine, 'Font engine mismatch')
        name = font.getname()
        _exact(name, tuple)
        _require(len(name) == 2, 'Font name arity')
        for item in name:
            _exact(item, str)
        _require(name == (profile.font.family, profile.font.style), 'Font name mismatch')
        fonts[size] = font
    return fonts


def _measure(fonts, required, specification, spans):
    metrics = {}
    for size in _SIZES:
        raw = fonts[size].getmetrics()
        _exact(raw, tuple)
        _require(len(raw) == 2, 'Provider metrics arity')
        ascent = _observation(raw[0], integer_only=True)
        descent = _observation(raw[1], integer_only=True)
        _metrics(ascent, descent)
        metrics[size] = (ascent, descent)
    slides = []
    for items, spec, slide_spans in zip(required, specification.slides, spans):
        measured = []
        for (ref, text, complete), placement, ranges in zip(items, spec.fields, slide_spans):
            ascent, descent = metrics[placement.font_size]
            font = fonts[placement.font_size]
            lines = []
            for i, (start, end) in enumerate(ranges):
                if start == end:
                    advance = Fraction(0)
                    bounds = (Fraction(0),) * 4
                else:
                    line = text[start:end]
                    advance = _observation(font.getlength(
                        line, mode='L', direction=None, features=None, language=None))
                    _require(advance >= 0, 'Negative provider advance')
                    raw = font.getbbox(line, mode='L', direction=None, features=None,
                                       language=None, stroke_width=0, anchor='ls')
                    _exact(raw, tuple)
                    _require(len(raw) == 4, 'Provider bbox arity')
                    bounds = tuple(_observation(v) for v in raw)
                    _bounds(bounds)
                baseline, box = _line_geometry(ascent, descent, i, advance, bounds)
                lines.append((i, start, end, baseline, advance, bounds, box))
            occupancy = _union(tuple(line[-1] for line in lines))
            measured.append((placement, text, ascent, descent, tuple(lines), occupancy))
        slides.append(tuple(measured))
    return tuple(slides)


def _construct(display, specification, profile, observations):
    slides = []
    for spec, fields in zip(specification.slides, observations):
        measured = []
        for placement, text, ascent, descent, lines, occupancy in fields:
            records = tuple(LineMeasurement(*line[:-1], Rect(*line[-1])) for line in lines)
            measured.append(MeasuredField(placement, text, ascent, descent, records, Rect(*occupancy)))
        slides.append(SlideLayout(spec, tuple(measured)))
    return PresentationLayout(display, specification, profile, tuple(slides))


def layout_presentation(
    display: PresentationDisplay,
    specification: LayoutSpec,
    *,
    font_bytes: bytes,
    profile: LayoutProfile,
    limits: LayoutLimits = LayoutLimits(),
) -> PresentationLayout:
    """Validate and measure atomically; unqualified production runtimes fail closed."""
    stage = 1
    try:
        for value, cls in ((display, PresentationDisplay), (specification, LayoutSpec),
                           (font_bytes, bytes), (profile, LayoutProfile), (limits, LayoutLimits)):
            _exact(value, cls)
        _exact(display.slides, tuple)
        _exact(specification.slides, tuple)
        stage = 2
        _limits(limits)
        stage = 3
        _payload_preflight(display, specification, limits)
        stage = 4
        _references(display, specification)
        stage = 5
        required = _enumerate_fields(display)
        stage = 6
        _coverage(required, specification)
        stage = 7
        for slide in specification.slides:
            _slide_geometry(slide, limits)
        stage = 8
        spans = _text_preflight(required, limits)
        stage = 9
        _profile_preflight(profile, font_bytes, limits)
        stage = 10
        import sys
        _require(sys.version_info >= (3, 10), 'Provider capability requires Python >= 3.10')
        provider = _open_provider(profile)
        stage = 11
        fonts = _load_fonts(provider, font_bytes, profile)
        stage = 12
        observations = _measure(fonts, required, specification, spans)
        stage = 13
        for slide in observations:
            for placement, text, ascent, descent, lines, occupancy in slide:
                _translated_fit(placement, occupancy)
        stage = 14
        return _construct(display, specification, profile, observations)
    except MemoryError:
        raise
    except Exception as exc:
        raise ValueError('Layout pass ' + str(stage) + ': ' + str(exc)) from exc
