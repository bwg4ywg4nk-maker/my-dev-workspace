"""Phase-1 local/model and controlled metric tests; no real-provider acceptance."""
import ast
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import MISSING, FrozenInstanceError, fields, replace
from fractions import Fraction as Q
from hashlib import sha256
import inspect
from pathlib import Path
from typing import Tuple, get_type_hints
import unittest
from unittest.mock import patch

from presentation_agent import layout as l
from presentation_agent import display as d
from presentation_agent.content import SnapshotCitationMetadata
from presentation_agent.evidence import canonical_bytes


FONT_BYTES = b'controlled metric double only; not a font'
TEST_DIGEST = sha256(FONT_BYTES).hexdigest()
FIXED_DIGEST = '525979822591a3447cfc49d943d6f7683508e25543407871c0ed8fed05fd2bd9'
NAME = 'ascii-lf-arial-regular-basic-720dpi-v1'


def forged(cls, **values):
    result = object.__new__(cls)
    for name, value in values.items():
        object.__setattr__(result, name, value)
    return result


def altered(value, **changes):
    return forged(type(value), **dict(vars(value), **changes))


def profile(digest=TEST_DIGEST):
    return l.LayoutProfile(NAME, 1, l.FontIdentity(digest, 0, 'Arial', 'Regular'),
                           '12.3.0', '2.14.3', 'sha256:' + 'a' * 64, 'sha256:' + 'b' * 64)


def placement(ref, rank=0, box=None, size=18000):
    return l.FieldPlacement(ref, box or l.Rect(0, rank * 10000, 100000, (rank + 1) * 10000),
                            l.Insets(0, 0, 0, 0), size, 18000,
                            l.HorizontalAlignment.LEFT, l.VerticalAlignment.TOP, rank)


def fixture(texts=('Hello',), roles=False, label=True):
    content = tuple(d.DisplayText(d.BlockRef(0, d.BlockKind.CONTENT, i), text)
                    for i, text in enumerate(texts))
    qualifications = (d.DisplayText(d.BlockRef(0, d.BlockKind.QUALIFICATION, 0), 'Hello',
                                    d.DisplayStatusLabel.UNVERIFIED if label else None),) if roles else ()
    citations = (d.DisplayCitation(d.BlockRef(0, d.BlockKind.CITATION, 0),
                                   SnapshotCitationMetadata('sha256:' + 'c' * 64, 'Hello', 'Hello')),) if roles else ()
    slide = d.SlideDisplay(0, content, qualifications, citations)
    # The layout trust boundary deliberately never reads the provenance object.
    display = forged(d.PresentationDisplay, composition=object(), slides=(slide,))
    refs = [l.FieldRef(x.source, l.FieldRole.TEXT) for x in content]
    for item in qualifications:
        refs.append(l.FieldRef(item.source, l.FieldRole.TEXT))
        if item.status_label is not None:
            refs.append(l.FieldRef(item.source, l.FieldRole.STATUS_LABEL))
    for item in citations:
        refs.extend((l.FieldRef(item.source, l.FieldRole.CITATION_TITLE),
                     l.FieldRef(item.source, l.FieldRole.CITATION_DETAIL)))
    spec = l.LayoutSpec((l.SlideLayoutSpec(0, 100000, 200000, l.Insets(0, 0, 0, 0),
                                          tuple(placement(ref, i) for i, ref in enumerate(refs))),))
    return display, spec


class DoubleFont:
    def __init__(self, provider, size):
        self.provider = provider
        self.size = size
        self.layout_engine = provider.basic_engine

    def getname(self):
        self.provider.calls.append(('name', self.size))
        return self.provider.name

    def getmetrics(self):
        self.provider.calls.append(('metrics', self.size))
        return self.provider.metrics[self.size]

    def getlength(self, text, **kwargs):
        self.provider.calls.append(('length', self.size, text, kwargs))
        self.provider.maybe_fail(text, 'length')
        return self.provider.advance

    def getbbox(self, text, **kwargs):
        self.provider.calls.append(('bbox', self.size, text, kwargs))
        self.provider.maybe_fail(text, 'bbox')
        return self.provider.bounds


class DoubleProvider:
    basic_engine = object()

    def __init__(self):
        self.calls = []
        self.metrics = {180: (8, 2), 240: (12, 3), 320: (16, 4)}
        self.advance = 5
        self.bounds = (0, -8, 5, 2)
        self.name = ('Arial', 'Regular')
        self.failure = None

    def maybe_fail(self, text, operation):
        if self.failure == (text, operation):
            raise RuntimeError('controlled failure')

    def open(self, bound_profile):
        self.calls.append(('open', bound_profile))
        if self.failure == 'open':
            raise RuntimeError('controlled open failure')
        return self

    def inspect_font(self, data, bound_profile):
        self.calls.append(('inspect', data, bound_profile))
        if self.failure == 'inspect':
            raise RuntimeError('controlled inspection failure')

    def load_font(self, data, **kwargs):
        self.calls.append(('load', data, kwargs))
        if self.failure == 'load':
            raise RuntimeError('controlled load failure')
        return DoubleFont(self, kwargs['size'])


class LayoutTests(unittest.TestCase):
    def test_line_constructor_scaled_coordinate_boundaries(self):
        m = 2**53 - 1
        for index, name in enumerate(('advance', 'left', 'top', 'right', 'bottom')):
            for sign in ((1,) if index == 0 else (-1, 1)):
                for magnitude in (m, m + 1):
                    with self.subTest(quantity=name, sign=sign, magnitude=magnitude):
                        value = Q(sign * magnitude, 100)
                        advance = value if index == 0 else Q(0)
                        bounds = [Q(0)] * 4
                        if index:
                            edge = index - 1
                            bounds[edge] = value
                            # Equal opposite edges preserve ordering where required;
                            # zero-width/height provider bounds are locally valid.
                            if edge < 2 and sign > 0:
                                bounds[edge + 2] = value
                            elif edge >= 2 and sign < 0:
                                bounds[edge - 2] = value
                        args = (0, 0, 1, 0, advance, tuple(bounds), l.Rect(0, 0, 0, 0))
                        if magnitude == m:
                            line = l.LineMeasurement(*args)
                            self.assertEqual(line.advance, advance)
                            self.assertEqual(line.provider_bounds, tuple(bounds))
                        else:
                            with self.assertRaisesRegex(ValueError, 'Rational checkpoint'):
                                l.LineMeasurement(*args)

    def test_label_aggregate_overflow_precedes_later_malformed_entry(self):
        for preceding in (False, True):
            with self.subTest(preceding_slide=preceding):
                display, spec = fixture(('A',) if preceding else ())
                index = int(preceding)
                labeled = d.DisplayText(d.BlockRef(index, d.BlockKind.QUALIFICATION, 0),
                                        'Q', d.DisplayStatusLabel.UNVERIFIED)
                slide = forged(d.SlideDisplay, slide_index=index, content=(),
                               qualifications=(labeled, None), citations=())
                slides = display.slides + (slide,) if preceding else (slide,)
                display = altered(display, slides=slides)
                limits = replace(l.LayoutLimits(), max_display_fields=2 + int(preceding),
                                 max_fields_per_slide=3)
                provider = DoubleProvider()
                with self.assertRaisesRegex(ValueError, 'Layout pass 3:.*Display fields with labels'):
                    self.call(display, spec, provider, limits=limits)
                self.assertEqual(provider.calls, [])

    def test_forged_alignment_nonmembers_local_and_pass7(self):
        display, spec = fixture()
        original = spec.slides[0].fields[0]
        for name, cls in (('horizontal_alignment', l.HorizontalAlignment),
                          ('vertical_alignment', l.VerticalAlignment)):
            with self.subTest(alignment=name):
                changes = {name: object.__new__(cls)}
                with self.assertRaisesRegex(ValueError, 'Unsupported .* alignment'):
                    replace(original, **changes)
                malformed = altered(spec, slides=(altered(spec.slides[0], fields=(
                    altered(original, **changes),)),))
                self.fail_pass(7, display, malformed)

    def call(self, display=None, spec=None, provider=None, **kwargs):
        if display is None:
            display, default_spec = fixture()
            if spec is None:
                spec = default_spec
        if spec is None:
            raise AssertionError('Test needs specification')
        provider = provider or DoubleProvider()
        kwargs.setdefault('font_bytes', FONT_BYTES)
        kwargs.setdefault('profile', profile())
        # Test-only digest stand-in lets synthetic bytes reach passes 10–14.
        # Production digest validation remains active and separately tested.
        with patch.object(l, '_FONT_SHA256', TEST_DIGEST), patch.object(l, '_open_provider', provider.open):
            return l.layout_presentation(display, spec, **kwargs)

    def fail_pass(self, number, display, spec, **kwargs):
        provider = DoubleProvider()
        with self.assertRaisesRegex(ValueError, 'Layout pass ' + str(number) + ':'):
            self.call(display, spec, provider, **kwargs)
        if number < 10:
            self.assertEqual(provider.calls, [])

    def test_surface_fields_types_defaults_and_signature(self):
        expected = {
            l.Rect: dict(left=int, top=int, right=int, bottom=int),
            l.Insets: dict(left=int, top=int, right=int, bottom=int),
            l.FieldRef: dict(source=d.BlockRef, role=l.FieldRole),
            l.FontIdentity: dict(sha256=str, face_index=int, family=str, style=str),
            l.LayoutProfile: dict(name=str, schema_version=int, font=l.FontIdentity, pillow_version=str,
                                  freetype_version=str, provider_build_id=str, runtime_id=str),
            l.FieldPlacement: dict(field=l.FieldRef, box=l.Rect, insets=l.Insets, font_size=int,
                                   size_floor=int, horizontal_alignment=l.HorizontalAlignment,
                                   vertical_alignment=l.VerticalAlignment, reading_order=int),
            l.SlideLayoutSpec: dict(slide_index=int, width=int, height=int, safe_margins=l.Insets,
                                    fields=Tuple[l.FieldPlacement, ...]),
            l.LayoutSpec: dict(slides=Tuple[l.SlideLayoutSpec, ...]),
            l.LineMeasurement: dict(line_index=int, source_start=int, source_end=int, baseline=int,
                                    advance=Q, provider_bounds=Tuple[Q, Q, Q, Q], occupancy=l.Rect),
            l.MeasuredField: dict(placement=l.FieldPlacement, text=str, ascent=Q, descent=Q,
                                  lines=Tuple[l.LineMeasurement, ...], occupancy=l.Rect),
            l.SlideLayout: dict(specification=l.SlideLayoutSpec, fields=Tuple[l.MeasuredField, ...]),
            l.PresentationLayout: dict(display=d.PresentationDisplay, specification=l.LayoutSpec,
                                       profile=l.LayoutProfile, slides=Tuple[l.SlideLayout, ...]),
            l.LayoutLimits: {name: int for name in (
                'max_slides', 'max_display_fields', 'max_fields_per_slide', 'max_total_characters',
                'max_characters_per_field', 'max_characters_per_line', 'max_lines_per_field',
                'max_total_line_slots', 'max_font_bytes', 'max_slide_width', 'max_slide_height')},
        }
        self.assertEqual(len(expected), 13)
        self.assertEqual(set(l.__all__), {x.__name__ for x in expected} |
                         {'FieldRole', 'HorizontalAlignment', 'VerticalAlignment', 'layout_presentation'})
        for cls, hints in expected.items():
            self.assertEqual(get_type_hints(cls), hints)
            self.assertEqual([f.name for f in fields(cls)], list(hints))
            self.assertTrue(cls.__dataclass_params__.frozen)
            if cls is not l.LayoutLimits:
                self.assertTrue(all(f.default is MISSING for f in fields(cls)))
        self.assertEqual([f.default for f in fields(l.LayoutLimits)],
                         [1000, 10000, 128, 2000000, 100000, 4096, 256, 100000, 8388608, 14400000, 14400000])
        sig = inspect.signature(l.layout_presentation)
        self.assertEqual(list(sig.parameters), ['display', 'specification', 'font_bytes', 'profile', 'limits'])
        for name in ('font_bytes', 'profile', 'limits'):
            self.assertEqual(sig.parameters[name].kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertEqual(sig.parameters['limits'].default, l.LayoutLimits())
        self.assertEqual([(v.name, v.value) for v in l.FieldRole],
                         [('TEXT', 'text'), ('STATUS_LABEL', 'status_label'),
                          ('CITATION_TITLE', 'citation_title'), ('CITATION_DETAIL', 'citation_detail')])
        self.assertEqual([(v.name, v.value) for v in l.HorizontalAlignment], [('LEFT', 'left')])
        self.assertEqual([(v.name, v.value) for v in l.VerticalAlignment], [('TOP', 'top')])

    def test_frozen_and_concrete_leaf_shapes(self):
        class Int(int):
            pass
        class Str(str):
            pass
        class Tup(tuple):
            pass
        class Rat(Q):
            pass
        class Rectangle(l.Rect):
            pass
        for bad in (True, Int(1), 1.0, '1', None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                l.Rect(bad, 0, 1, 1)
        for make in (lambda: Rectangle(0, 0, 1, 1), lambda: l.Rect(2, 0, 1, 1),
                     lambda: l.Insets(-1, 0, 0, 0), lambda: l.Rect(0, 0, l._M + 1, 1),
                     lambda: l.LayoutSpec(Tup()), lambda: l.FontIdentity(Str('a' * 64), 0, 'A', 'B'),
                     lambda: l.LineMeasurement(0, 0, 1, 1, Rat(1), (Q(0),) * 4, l.Rect(0, 0, 1, 1))):
            with self.assertRaises(ValueError):
                make()
        r = l.Rect(-l._M, -l._M, l._M, l._M)
        with self.assertRaises(FrozenInstanceError):
            r.left = 0
        self.assertEqual(l.Rect(0, 0, 0, 0).right, 0)
        with self.assertRaises(AttributeError):
            profile().profile_id = 'fake'

    def test_font_identity_and_local_profile_policy(self):
        for face in (0, l._M):
            for n in (1, 100):
                font = l.FontIdentity('a' * 64, face, 'é' * n, 'B' * n)
                canonical_bytes(l._descriptor(replace(profile(), font=font)))
        for face in (-1, l._M + 1, True, 0.0, type('I', (int,), {})(0)):
            with self.assertRaises(ValueError):
                l.FontIdentity('a' * 64, face, 'Arial', 'Regular')
        for changes in ({'sha256': 'A' * 64}, {'family': ' '}, {'family': '\ud800'},
                        {'style': 'a' * 101}, {'face_index': None}):
            with self.assertRaises(ValueError):
                replace(profile().font, **changes)
        for changes in ({'name': 'other'}, {'schema_version': True}, {'schema_version': 2},
                        {'pillow_version': '\n'}, {'freetype_version': 'é'},
                        {'runtime_id': 'sha256:' + 'A' * 64}, {'provider_build_id': 'x'}):
            with self.assertRaises(ValueError):
                replace(profile(), **changes)
        # Versions/bindings and font family mismatches are locally representable.
        replace(profile(), pillow_version='other', font=replace(profile().font, family='Other'))
        display, spec = fixture()
        self.fail_pass(9, display, spec, profile=replace(profile(), font=replace(profile().font, face_index=1)))

    def test_field_roles_and_reference_local_rules(self):
        legal = {d.BlockKind.CONTENT: [l.FieldRole.TEXT],
                 d.BlockKind.QUALIFICATION: [l.FieldRole.TEXT, l.FieldRole.STATUS_LABEL],
                 d.BlockKind.CITATION: [l.FieldRole.CITATION_TITLE, l.FieldRole.CITATION_DETAIL]}
        for kind in d.BlockKind:
            for role in l.FieldRole:
                source = d.BlockRef(0, kind, 0)
                if role in legal[kind]:
                    self.assertIs(l.FieldRef(source, role).source, source)
                else:
                    with self.assertRaises(ValueError):
                        l.FieldRef(source, role)
        for source in (forged(d.BlockRef), d.BlockRef(0, d.BlockKind.CONTENT, 0)):
            with self.assertRaises(ValueError):
                l.FieldRef(source, 'text')

    def test_enumeration_all_roles_equal_text_and_identity(self):
        for label in (False, True):
            display, spec = fixture(roles=True, label=label)
            p = profile()
            result = self.call(display, spec, profile=p)
            self.assertIs(result.display, display)
            self.assertIs(result.specification, spec)
            self.assertIs(result.profile, p)
            self.assertIs(result.slides[0].specification, spec.slides[0])
            expected = ['Hello', 'Hello'] + (['Unverified'] if label else []) + ['Hello', 'Hello']
            self.assertEqual([f.text for f in result.slides[0].fields], expected)
            self.assertEqual(len(set(f.placement.field for f in result.slides[0].fields)), len(expected))
            for field, allocated in zip(result.slides[0].fields, spec.slides[0].fields):
                self.assertIs(field.placement, allocated)
        reordered_ranks = tuple(replace(p, reading_order=4-i) for i, p in enumerate(spec.slides[0].fields))
        self.call(display, l.LayoutSpec((replace(spec.slides[0], fields=reordered_ranks),)))

    def test_empty_slide_and_presentation_still_load_all_sizes(self):
        for empty_presentation in (False, True):
            display, spec = fixture(())
            if empty_presentation:
                display = altered(display, slides=())
                spec = l.LayoutSpec(())
            provider = DoubleProvider()
            result = self.call(display, spec, provider)
            self.assertEqual(len(result.slides), 0 if empty_presentation else 1)
            self.assertEqual([c[0] for c in provider.calls],
                             ['open', 'inspect', 'load', 'name', 'load', 'name', 'load', 'name',
                              'metrics', 'metrics', 'metrics'])

    def test_deterministic_provider_calls_kwargs_sizes_metrics(self):
        display, spec = fixture(('A\n\nB\n', 'C', 'D'))
        placements = tuple(replace(p, font_size=size) for p, size in zip(spec.slides[0].fields, l._SIZES))
        spec = l.LayoutSpec((replace(spec.slides[0], fields=placements),))
        provider = DoubleProvider()
        first = self.call(display, spec, provider)
        names = [c[0] for c in provider.calls]
        self.assertEqual(names, ['open', 'inspect', 'load', 'name', 'load', 'name', 'load', 'name'] +
                         ['metrics'] * 3 + ['length', 'bbox'] * 4)
        self.assertEqual([c[1] for c in provider.calls if c[0] == 'metrics'], [180, 240, 320])
        for call, size in zip((c for c in provider.calls if c[0] == 'load'), (180, 240, 320)):
            self.assertIs(call[1], FONT_BYTES)
            self.assertEqual(call[2], dict(size=size, index=0, encoding='unic', layout_engine=provider.basic_engine))
        for call in provider.calls:
            if call[0] in ('length', 'bbox'):
                expected = dict(mode='L', direction=None, features=None, language=None)
                if call[0] == 'bbox':
                    expected.update(stroke_width=0, anchor='ls')
                self.assertEqual(call[3], expected)
        self.assertEqual([(f.ascent, f.descent) for f in first.slides[0].fields],
                         [(Q(8), Q(2)), (Q(12), Q(3)), (Q(16), Q(4))])
        second_provider = DoubleProvider()
        second = self.call(display, spec, second_provider)
        self.assertEqual(first, second)
        self.assertEqual(provider.calls, second_provider.calls)

    def test_lines_ranges_blank_slots_internal_spaces_and_ascii(self):
        text = '\nA  B\n\nC\n\n'
        display, spec = fixture((text,))
        measured = self.call(display, spec).slides[0].fields[0]
        self.assertEqual([(x.source_start, x.source_end) for x in measured.lines],
                         [(0, 0), (1, 5), (6, 6), (7, 8), (9, 9), (10, 10)])
        self.assertEqual([measured.text[x.source_start:x.source_end] for x in measured.lines],
                         ['', 'A  B', '', 'C', '', ''])
        self.assertEqual(measured.occupancy.bottom, 6000)
        for i, line in enumerate(measured.lines):
            self.assertEqual(line.baseline, 800 + i * 1000)
            if line.source_start == line.source_end:
                self.assertEqual(line.advance, 0)
                self.assertEqual(line.provider_bounds, (Q(0),) * 4)
        legal = 'X' + ''.join(chr(i) for i in range(32, 127)) + 'X'
        self.call(*fixture((legal,)))
        self.assertEqual(l._scan_text('', l.LayoutLimits(), 0, complete=False), 1)
        self.assertEqual(l._spans(''), ((0, 0),))
        self.assertEqual(l._line_geometry(Q(8), Q(2), 0, Q(0), (Q(0),)*4),
                         (800, (0, 0, 0, 1000)))

    def test_text_domain_and_complete_blank_rejections(self):
        invalid = [chr(i) for i in range(32) if i != 10] + ['\x7f', 'é', 'ا', '\u0301',
                    '\ud800', '\u00a0', '\u202e', '\u200b', '\r\n']
        for char in invalid:
            with self.subTest(char=repr(char)):
                display, spec = fixture()
                item = altered(display.slides[0].content[0], text='A' + char + 'B')
                display = altered(display, slides=(altered(display.slides[0], content=(item,)),))
                self.fail_pass(8, display, spec)
        for text in ('', '\n', '\n\n', ' ', ' A', 'A ', 'A\n B', 'A\n ', ' \nA'):
            display, spec = fixture()
            item = altered(display.slides[0].content[0], text=text)
            self.fail_pass(8, altered(display, slides=(altered(display.slides[0], content=(item,)),)), spec)

    def test_geometry_safe_insets_overlap_shared_edges(self):
        display, spec = fixture(('A', 'B'))
        first, second = spec.slides[0].fields
        self.call(display, spec)  # Shared horizontal edge.
        for box in (l.Rect(0, 9999, 100000, 20000), l.Rect(-1, 10000, 100000, 20000),
                    l.Rect(0, 10000, 100001, 20000), l.Rect(0, 10000, 100000, 200001)):
            bad = altered(spec.slides[0], fields=(first, altered(second, box=box)))
            self.fail_pass(7, display, altered(spec, slides=(bad,)))
        for changes in ({'width': 0}, {'height': -1}, {'width': True},
                        {'safe_margins': l.Insets(100000, 0, 0, 0)},
                        {'safe_margins': l.Insets(1, 0, 0, 0)}):
            self.fail_pass(7, display, altered(spec, slides=(altered(spec.slides[0], **changes),)))
        for changes in ({'box': l.Rect(0, 0, 0, 10000)}, {'insets': l.Insets(100000, 0, 0, 0)},
                        {'font_size': 18001}, {'font_size': True}, {'size_floor': 24000},
                        {'horizontal_alignment': 'left'}, {'vertical_alignment': 'top'}):
            with self.assertRaises(ValueError):
                replace(first, **changes)
            bad = altered(spec.slides[0], fields=(altered(first, **changes), second))
            self.fail_pass(7, display, altered(spec, slides=(bad,)))
        for size in l._SIZES:
            for floor in l._SIZES:
                if floor <= size:
                    replace(first, font_size=size, size_floor=floor)
                else:
                    with self.assertRaises(ValueError):
                        replace(first, font_size=size, size_floor=floor)
        # A corner is also legal; insets place the origin strictly inside the box.
        first = replace(first, box=l.Rect(10, 10, 5010, 5010), insets=l.Insets(100, 100, 100, 100))
        second = replace(second, box=l.Rect(5010, 5010, 10010, 10010))
        safe_spec = replace(spec.slides[0], safe_margins=l.Insets(10, 10, 10, 10), fields=(first, second))
        self.call(display, l.LayoutSpec((safe_spec,)))

    def test_default_provider_fail_closed_and_digest_gate(self):
        display, spec = fixture()
        with patch.object(l, '_FONT_SHA256', TEST_DIGEST):
            with self.assertRaisesRegex(ValueError, 'pass 10:.*Controlled fresh-process'):
                l.layout_presentation(display, spec, font_bytes=FONT_BYTES, profile=profile())
        with patch.object(l, '_open_provider', side_effect=AssertionError('must not access')) as opened:
            with self.assertRaisesRegex(ValueError, 'pass 9: Font digest'):
                l.layout_presentation(display, spec, font_bytes=FONT_BYTES, profile=profile(FIXED_DIGEST))
            opened.assert_not_called()
        self.fail_pass(9, display, spec, font_bytes=b'')

    def test_provider_stage_failures_and_atomicity(self):
        display, spec = fixture(('A', 'Z'))
        for failure, stage in (('open', 10), ('inspect', 11), ('load', 11), (('Z', 'bbox'), 12)):
            provider = DoubleProvider()
            provider.failure = failure
            provider.bounds = (-1, -8, 5, 2)  # Earlier field already cannot fit.
            with patch.object(l, '_construct', side_effect=AssertionError('atomicity')) as construction:
                with self.assertRaisesRegex(ValueError, 'pass ' + str(stage) + ':'):
                    self.call(display, spec, provider)
                construction.assert_not_called()
        provider = DoubleProvider()
        provider.bounds = (-1, -8, 5, 2)
        with patch.object(l, '_construct') as construction:
            with self.assertRaisesRegex(ValueError, 'pass 13: Containment left'):
                self.call(display, spec, provider)
            construction.assert_not_called()
        self.assertEqual([c[2] for c in provider.calls if c[0] == 'bbox'], ['A', 'Z'])

    def test_provider_protocol_rejects_malformed_results(self):
        class Int(int):
            pass
        class Float(float):
            pass
        for metrics in ([8, 2], (8,), (8, 2, 1), (True, 2), (8.0, 2), (Int(8), 2),
                        (0, 2), (-8, 2), (8, -2)):
            provider = DoubleProvider()
            provider.metrics[320] = metrics
            with self.subTest(metrics=metrics), self.assertRaisesRegex(ValueError, 'pass 12:'):
                self.call(provider=provider)
            self.assertFalse(any(c[0] == 'length' for c in provider.calls))
        for advance in (True, Int(1), Float(1), Q(1), -1, float('nan'), float('inf'), None):
            provider = DoubleProvider()
            provider.advance = advance
            with self.subTest(advance=advance), self.assertRaisesRegex(ValueError, 'pass 12:'):
                self.call(provider=provider)
            self.assertFalse(any(c[0] == 'bbox' for c in provider.calls))
        for bounds in ([0, -8, 5, 2], (0, 1), (0, -8, 5, 2, 3), (True, -8, 5, 2),
                       (0, -8, Int(5), 2), (0, -8, float('nan'), 2), (5, -8, 0, 2), (0, 2, 5, -8)):
            provider = DoubleProvider()
            provider.bounds = bounds
            with self.subTest(bounds=bounds), self.assertRaisesRegex(ValueError, 'pass 12:'):
                self.call(provider=provider)
        for name in (['Arial', 'Regular'], ('Arial',), ('Other', 'Regular'), ('Arial', 1)):
            provider = DoubleProvider()
            provider.name = name
            with self.assertRaisesRegex(ValueError, 'pass 11:'):
                self.call(provider=provider)

    def test_exact_observations_rounding_envelope_and_boundary_fit(self):
        for number in (0, 1, -1, 0.5, -0.125, 1.25):
            self.assertEqual(l._observation(number), Q(number))
        for number, rounded in ((Q(3, 2), 2), (Q(-3, 2), -1), (Q(-1, 2), 0),
                                (Q(1, 2), 1), (Q(149, 100), 1)):
            self.assertEqual(l._nearest(number), rounded)
        self.assertEqual(l._floor(Q(-1, 3)), -1)
        self.assertEqual(l._ceil(Q(-1, 3)), 0)
        display, spec = fixture()
        provider = DoubleProvider()
        provider.advance = 5.125
        provider.bounds = (0, -8, 4.5, 2)
        measured = self.call(display, spec, provider).slides[0].fields[0]
        self.assertEqual(measured.lines[0].advance, Q(41, 8))
        self.assertEqual(measured.occupancy.right, 513)
        provider.advance = 4
        provider.bounds = (0, -8, 5.125, 2)
        self.assertEqual(self.call(display, spec, provider).slides[0].fields[0].occupancy.right, 513)
        p = replace(spec.slides[0].fields[0], box=l.Rect(50, 50, 550, 1050))
        exact = l.LayoutSpec((replace(spec.slides[0], fields=(p,)),))
        self.call(display, exact)
        cases = [((-0.0078125, -8, 5, 2), 'left'), ((0, -8.0078125, 5, 2), 'top'),
                 ((0, -8, 5.0078125, 2), 'right'), ((0, -8, 5, 2.0078125), 'bottom')]
        for bounds, edge in cases:
            provider = DoubleProvider()
            provider.bounds = bounds
            with self.assertRaisesRegex(ValueError, 'pass 13: Containment ' + edge):
                self.call(display, exact, provider)
        # Width alone fits (500), but translated left bearing fails.
        provider = DoubleProvider()
        provider.advance = 4
        provider.bounds = (-1, -8, 4, 2)
        with self.assertRaisesRegex(ValueError, 'pass 13: Containment left'):
            self.call(display, exact, provider)
        self.assertEqual(l._line_geometry(Q(8), Q(2), 0, Q(4), tuple(map(Q, provider.bounds)))[1],
                         (-100, 0, 400, 1000))

    def test_arithmetic_semantic_checkpoints_and_equivalent_algebra(self):
        m = l._M
        for value in (m, -m):
            self.assertEqual(l._integer(value), value)
            self.assertEqual(l._rational(Q(value)), value)
        for value in (m+1, -m-1):
            with self.assertRaises(ValueError):
                l._integer(value)
            with self.assertRaises(ValueError):
                l._rational(Q(value))
        self.assertEqual(l._rational(Q(1, m)), Q(1, m))
        with self.assertRaises(ValueError):
            l._rational(Q(1, m+1))
        self.assertEqual(l._rational(Q(2*m, 2)), m)
        self.assertEqual(l._rational(Q(m*m, m)), m)
        for sign in (-1, 1):
            self.assertEqual(l._scaled(Q(sign*m, 100)), Q(sign*m, 100))
            with self.assertRaises(ValueError):
                l._scaled(Q(sign*(m+1), 100))
        # H can exceed its rational bound despite bounded components.
        with self.assertRaises(ValueError):
            l._metrics(Q(m), Q(1))
        with self.assertRaises(ValueError):
            l._metrics(Q(m // 100 + 1), Q(0))
        # Fully reduced semantic sums are checked, never cross products.
        a, h = Q(m - 1, 100), Q(1, 100)
        self.assertEqual(l._scaled(a + h), l._scaled(Q((m - 1)*100 + 100, 10000)))
        self.assertEqual(l._nearest(Q(m)), m)  # Adding 1/2 is not bounded independently.
        for q in (Q(m+1), Q(-m-1)):
            with self.assertRaises(ValueError):
                l._nearest(q)
        with self.assertRaises(ValueError):
            l._line_geometry(Q(1), Q(0), m // 100, Q(0), (Q(0),)*4)
        for bounds in ((Q(0), Q(-m), Q(0), Q(0)), (Q(0), Q(0), Q(m), Q(0))):
            with self.assertRaises(ValueError):
                l._line_geometry(Q(1), Q(0), 0, Q(0), bounds)
        with self.assertRaises(ValueError):
            l._line_geometry(Q(1), Q(0), 0, Q(m), (Q(0),)*4)
        with self.assertRaises(ValueError):
            l._line_geometry(Q(m, 100), Q(0), 0, Q(0), (Q(0), Q(0), Q(0), Q(1, 100)))
        # Check cancellation and signed outward rounding without float arithmetic.
        self.assertEqual(l._line_geometry(Q(3, 200), Q(1, 200), 0, Q(1, 200),
                                         (Q(-1, 200), Q(-1, 50), Q(1, 200), Q(0))),
                         (2, (-1, -1, 1, 2)))

    def test_constructor_trust_boundary_and_forged_measurements(self):
        display, spec = fixture()
        result = self.call(display, spec)
        with patch.object(l, '_open_provider', side_effect=AssertionError('constructors must be pure')):
            unrelated, _ = fixture(('Different',))
            local = replace(result, display=unrelated)
            self.assertIs(local.display, unrelated)
            self.assertEqual(local.slides[0].fields[0].text, 'Hello')
            # Recreate observations without any origin token/provider call.
            measured = result.slides[0].fields[0]
            self.assertEqual(replace(measured), measured)
            for changes in ({'ascent': Q(9)}, {'descent': Q(-1)}, {'text': ' Hello'},
                            {'occupancy': l.Rect(0, 0, 501, 1000)}, {'lines': ()},
                            {'lines': (altered(measured.lines[0], source_start=1),)},
                            {'lines': (altered(measured.lines[0], baseline=801),)}):
                with self.assertRaises(ValueError):
                    replace(measured, **changes)
            with self.assertRaises(ValueError):
                replace(result, slides=(altered(result.slides[0], fields=(forged(l.MeasuredField),)),))
            with self.assertRaises(ValueError):
                replace(result, profile=forged(l.LayoutProfile))
        self.assertFalse(any(name in vars(result) for name in ('fits', 'origin', 'certified', 'result_hash')))

    def test_no_mutation(self):
        display, spec = fixture(roles=True)
        before_display = deepcopy(display.slides)
        before_spec = deepcopy(spec)
        self.call(display, spec)
        self.assertEqual(display.slides, before_display)
        self.assertEqual(spec, before_spec)
        provider = DoubleProvider()
        provider.failure = ('Hello', 'bbox')
        with self.assertRaises(ValueError):
            self.call(display, spec, provider)
        self.assertEqual(display.slides, before_display)
        self.assertEqual(spec, before_spec)

    def test_every_limit_strict_lower_only_and_isolated_equality(self):
        class Int(int):
            pass
        defaults = l.LayoutLimits()
        for field in fields(defaults):
            for value in (0, -1, True, Int(1), 1.0, field.default + 1):
                with self.subTest(limit=field.name, value=value), self.assertRaises(ValueError):
                    replace(defaults, **{field.name: value})
            for ceiling in (field.default, 1):
                limits = replace(defaults, **{field.name: ceiling})
                l._ceiling(ceiling, getattr(limits, field.name), field.name)
                with self.assertRaises(ValueError):
                    l._ceiling(ceiling + 1, getattr(limits, field.name), field.name)
            display, spec = fixture()
            self.fail_pass(2, display, spec, limits=altered(defaults, **{field.name: True}))

    def test_resource_slide_count_and_population_preflight(self):
        display, spec = fixture()
        for ceiling in (2, 1000):
            limits = replace(l.LayoutLimits(), max_slides=ceiling)
            # Equality reaches entry shape, not the ceiling; no proportional construction.
            for count, message in ((ceiling, 'Expected concrete'), (ceiling+1, 'slides limit')):
                bad_display = altered(display, slides=(None,) * count)
                with self.assertRaisesRegex(ValueError, message):
                    self.call(bad_display, spec, limits=limits)
                bad_spec = altered(spec, slides=(None,) * count)
                with self.assertRaisesRegex(ValueError, message):
                    self.call(display, bad_spec, limits=limits)
        slide = display.slides[0]
        for ceiling in (2, 128):
            limits = replace(l.LayoutLimits(), max_fields_per_slide=ceiling)
            for container in ('content', 'qualifications', 'citations'):
                # Citation minimum cost is twice the tuple length.
                count = ceiling // 2 if container == 'citations' else ceiling
                changes = dict(content=(), qualifications=(), citations=())
                changes[container] = (None,) * count
                with self.assertRaisesRegex(ValueError, 'Expected concrete'):
                    self.call(altered(display, slides=(altered(slide, **changes),)), spec, limits=limits)
                changes[container] = (None,) * (count+1)
                with self.assertRaisesRegex(ValueError, 'limit exceeded'):
                    self.call(altered(display, slides=(altered(slide, **changes),)), spec, limits=limits)
            for count, message in ((ceiling, 'pass 4:'), (ceiling+1, 'pass 3:')):
                bad = altered(spec, slides=(altered(spec.slides[0], fields=(None,) * count),))
                with self.assertRaisesRegex(ValueError, message):
                    self.call(display, bad, limits=limits)
        # Both slide lengths precede malformed entries in either population.
        bad_display = altered(display, slides=(None,))
        self.fail_pass(3, bad_display, altered(spec, slides=(None,) * 1001))
        # Aggregate minimum counts precede entry shape in both populations.
        many_display = altered(display, slides=tuple(altered(slide, content=(None,)*100) for _ in range(101)))
        many_spec = altered(spec, slides=tuple(altered(spec.slides[0], fields=(None,)*100) for _ in range(101)))
        for disp, allocated in ((many_display, spec), (display, many_spec)):
            with self.assertRaisesRegex(ValueError, 'fields limit'):
                self.call(disp, allocated)
        for count, stage in ((10000, 4), (10001, 3)):
            populations = tuple(altered(spec.slides[0], fields=(None,)*min(100, count-i))
                                for i in range(0, count, 100))
            self.fail_pass(stage, display, altered(spec, slides=populations))
        # No enumeration/span/measurement result construction on structural failure.
        with ExitStack() as stack:
            for name in ('_enumerate_fields', '_spans', '_measure', '_construct'):
                stack.enter_context(patch.object(l, name, side_effect=AssertionError(name)))
            with self.assertRaisesRegex(ValueError, 'pass 3:'):
                self.call(display, many_spec)

    def test_resource_characters_and_lines_actual_gates(self):
        for ceiling in (7, 100000):
            limits = replace(l.LayoutLimits(), max_characters_per_field=ceiling)
            self.assertEqual(l._text_length('X' * ceiling, limits, 0), ceiling)
            with self.assertRaisesRegex(ValueError, 'Field characters'):
                l._text_length('X' * (ceiling+1), limits, 0)
        for ceiling in (7, 2000000):
            limits = replace(l.LayoutLimits(), max_total_characters=ceiling)
            self.assertEqual(l._text_length('X', limits, ceiling-1), ceiling)
            with self.assertRaisesRegex(ValueError, 'Total characters'):
                l._text_length('X', limits, ceiling)
        for ceiling in (7, 4096):
            limits = replace(l.LayoutLimits(), max_characters_per_line=ceiling)
            self.assertEqual(l._scan_text('X'*ceiling, limits, 0), 1)
            with self.assertRaisesRegex(ValueError, 'Line characters'):
                l._scan_text('X'*(ceiling+1), limits, 0)
        for ceiling in (2, 256):
            limits = replace(l.LayoutLimits(), max_lines_per_field=ceiling)
            self.assertEqual(l._scan_text('X'+'\n'*(ceiling-1), limits, 0), ceiling)
            with self.assertRaisesRegex(ValueError, 'Field line slots'):
                l._scan_text('X'+'\n'*ceiling, limits, 0)
        for ceiling in (2, 100000):
            limits = replace(l.LayoutLimits(), max_total_line_slots=ceiling)
            self.assertEqual(l._scan_text('X', limits, ceiling-1), ceiling)
            with self.assertRaisesRegex(ValueError, 'Total line slots'):
                l._scan_text('X', limits, ceiling)
        display, spec = fixture(('A\n',))
        self.call(display, spec, limits=replace(l.LayoutLimits(), max_characters_per_field=2,
                                               max_total_characters=2, max_lines_per_field=2,
                                               max_total_line_slots=2, max_characters_per_line=1))
        for name, maximum, stage in (('max_characters_per_field', 1, 3),
                                     ('max_total_characters', 1, 3),
                                     ('max_lines_per_field', 1, 8), ('max_total_line_slots', 1, 8)):
            self.fail_pass(stage, display, spec, limits=replace(l.LayoutLimits(), **{name: maximum}))
        # All scans, across all fields, must pass before any span allocation.
        display, spec = fixture(('A', 'B\nC'))
        with patch.object(l, '_spans', side_effect=AssertionError('too early')):
            self.fail_pass(8, display, spec, limits=replace(l.LayoutLimits(), max_total_line_slots=2))
        # Full domain scan precedes any line checks for that field.
        display, spec = fixture((' A\t',))
        with self.assertRaisesRegex(ValueError, 'Text domain'):
            self.call(display, spec, limits=replace(l.LayoutLimits(), max_characters_per_line=1))
        # At a line end: length, edge spaces, field slots, total slots.
        with self.assertRaisesRegex(ValueError, 'Line characters'):
            l._scan_text(' A', replace(l.LayoutLimits(), max_characters_per_line=1), 100000)
        with self.assertRaisesRegex(ValueError, 'Line edge'):
            l._scan_text(' A', l.LayoutLimits(), 100000)
        with self.assertRaisesRegex(ValueError, 'Field line slots'):
            l._scan_text('A\n', replace(l.LayoutLimits(), max_lines_per_field=1,
                                       max_total_line_slots=1), 0)

    def test_font_size_and_dimension_resource_equalities(self):
        display, spec = fixture(())
        for name in ('max_slide_width', 'max_slide_height'):
            for maximum in (1, 14400000):
                limits = replace(l.LayoutLimits(), **{name: maximum})
                dimension = 'width' if name.endswith('width') else 'height'
                good = altered(spec, slides=(altered(spec.slides[0], **{dimension: maximum}),))
                self.call(display, good, limits=limits)
                bad = altered(spec, slides=(altered(spec.slides[0], **{dimension: maximum+1}),))
                self.fail_pass(7, display, bad, limits=limits)
        for maximum in (4, 8388608):
            limits = replace(l.LayoutLimits(), max_font_bytes=maximum)
            with self.assertRaisesRegex(ValueError, 'Font digest mismatch'):
                l._profile_preflight(profile(), b'X'*maximum, limits)
            with self.assertRaisesRegex(ValueError, 'Font bytes limit'):
                l._profile_preflight(profile(), b'X'*(maximum+1), limits)
        self.call(*fixture(), limits=replace(l.LayoutLimits(), max_font_bytes=len(FONT_BYTES)))
        self.fail_pass(9, *fixture(), limits=replace(l.LayoutLimits(), max_font_bytes=len(FONT_BYTES)-1))

    def test_default_constructor_counts_before_malformed_entries(self):
        display, spec = fixture()
        measured = self.call(display, spec).slides[0].fields[0]
        for constructor in (
            lambda: l.LayoutSpec((None,)*1001),
            lambda: l.SlideLayoutSpec(0, 1, 1, l.Insets(0,0,0,0), (None,)*129),
            lambda: replace(measured, lines=(None,)*257),
            lambda: l.SlideLayout(spec.slides[0], (None,)*129),
            lambda: l.PresentationLayout(display, spec, profile(), (None,)*1001),
        ):
            with self.assertRaisesRegex(ValueError, 'limit exceeded'):
                constructor()
        slides = tuple(forged(l.SlideLayout, specification=spec.slides[0], fields=(None,)*100)
                       for _ in range(101))
        with self.assertRaisesRegex(ValueError, 'Output fields limit'):
            l.PresentationLayout(display, spec, profile(), slides)
        oversized = altered(measured, text='X'*100001, lines=(None,))
        with self.assertRaisesRegex(ValueError, 'Field characters'):
            l.SlideLayout(spec.slides[0], (oversized,))
        line_overflow = altered(measured, text='X'+'\n'*256, lines=(None,))
        with patch.object(l, '_spans', side_effect=AssertionError('premature')):
            with self.assertRaisesRegex(ValueError, 'Field line slots'):
                l.SlideLayout(spec.slides[0], (line_overflow,))

    def test_ordered_shallow_limits_payload_refs_coverage_geometry_text(self):
        display, spec = fixture(roles=True)
        slide = display.slides[0]
        bad_label = altered(slide.qualifications[0], status_label=object())
        labeled = altered(display, slides=(altered(slide, qualifications=(bad_label,)),))
        # Passes 1 and 2 precede payloads.
        self.fail_pass(1, labeled, spec, font_bytes=bytearray(FONT_BYTES))
        self.fail_pass(2, labeled, spec, limits=altered(l.LayoutLimits(), max_slides=False))
        self.fail_pass(3, labeled, spec, limits=replace(l.LayoutLimits(), max_fields_per_slide=4))
        for limit in ('max_lines_per_field', 'max_font_bytes'):
            self.fail_pass(3, labeled, spec, limits=replace(l.LayoutLimits(), **{limit: 1}))
        # Text length precedes the same item's label; label precedes later field's text.
        labeled_long = altered(display, slides=(altered(slide, qualifications=(altered(bad_label, text='X'*10),)),))
        with self.assertRaisesRegex(ValueError, 'Field characters'):
            self.call(labeled_long, spec, limits=replace(l.LayoutLimits(), max_characters_per_field=9))
        citation_long = altered(slide.citations[0], metadata=altered(slide.citations[0].metadata, title='X'*10))
        labeled_later = altered(labeled, slides=(altered(labeled.slides[0], citations=(citation_long,)),))
        with self.assertRaisesRegex(ValueError, 'Expected concrete DisplayStatusLabel'):
            self.call(labeled_later, spec, limits=replace(l.LayoutLimits(), max_characters_per_field=9))
        # Citation validity precedes index/count correspondence, but count preflight precedes citation.
        for metadata in (object(), forged(SnapshotCitationMetadata),
                         altered(slide.citations[0].metadata, snapshot_id='x'),
                         altered(slide.citations[0].metadata, title=None),
                         altered(slide.citations[0].metadata, bibliographic_detail=None),
                         altered(slide.citations[0].metadata, title=' ')):
            bad = altered(display, slides=(altered(slide, slide_index=12, citations=(
                altered(slide.citations[0], metadata=metadata),)),))
            self.fail_pass(3, bad, l.LayoutSpec(()))
        # Reference shapes precede coverage (and are not replayed in geometry).
        bad_ref = altered(spec.slides[0].fields[0], field=forged(l.FieldRef))
        malformed = altered(spec, slides=(altered(spec.slides[0], fields=(bad_ref,)),))
        self.fail_pass(4, display, malformed)
        bad_source = altered(slide.content[0], source=forged(d.BlockRef))
        self.fail_pass(4, altered(display, slides=(altered(slide, content=(bad_source,)),)), spec)
        self.fail_pass(6, display, altered(spec, slides=(altered(spec.slides[0], fields=()),)))
        malformed = altered(spec, slides=(altered(spec.slides[0], width=0),))
        self.fail_pass(7, display, malformed, profile=forged(l.LayoutProfile))
        text_bad = altered(slide.content[0], text='Hello\t')
        self.fail_pass(8, altered(display, slides=(altered(slide, content=(text_bad,)),)), spec,
                       profile=forged(l.LayoutProfile))
        # Missing geometry isn't dereferenced before coverage; missing profile fields wait until 9.
        outer_only = forged(l.FieldPlacement, field=spec.slides[0].fields[0].field)
        malformed = altered(spec, slides=(altered(spec.slides[0], fields=(outer_only,)),))
        self.fail_pass(6, display, malformed, profile=forged(l.LayoutProfile))

    def test_coverage_order_duplicates_cross_slide_and_ranks(self):
        display, spec = fixture(('A', 'B'))
        first, second = spec.slides[0].fields
        for placements in ((first,), (second, first), (first, first), (first, second, second),
                           (altered(first, field=l.FieldRef(d.BlockRef(1, d.BlockKind.CONTENT, 0), l.FieldRole.TEXT)), second),
                           (altered(first, reading_order=True), second),
                           (altered(first, reading_order=2), second),
                           (altered(first, reading_order=1), second)):
            self.fail_pass(6, display, altered(spec, slides=(altered(spec.slides[0], fields=placements),)))
            if len(placements) != 1:  # An omission is locally valid; presence belongs to the factory.
                with self.assertRaises(ValueError):
                    l.SlideLayoutSpec(0, 100000, 200000, l.Insets(0,0,0,0), placements)
        for bad_source in (altered(display.slides[0].content[0].source, slide_index=1),
                           altered(display.slides[0].content[0].source, kind=d.BlockKind.QUALIFICATION),
                           altered(display.slides[0].content[0].source, block_index=1)):
            items = (altered(display.slides[0].content[0], source=bad_source), display.slides[0].content[1])
            self.fail_pass(4, altered(display, slides=(altered(display.slides[0], content=items),)), spec)
        for index in (True, -1, 1):
            self.fail_pass(4, altered(display, slides=(altered(display.slides[0], slide_index=index),)), spec)
        self.fail_pass(4, display, l.LayoutSpec(()))
        display, spec = fixture(roles=True)
        citation = display.slides[0].citations[0]
        duplicate = altered(citation, source=d.BlockRef(0, d.BlockKind.CITATION, 1))
        self.fail_pass(4, altered(display, slides=(altered(display.slides[0], citations=(citation, duplicate)),)), spec)

    def test_imports_python39_grammar_no_provider_dependency(self):
        source = Path(l.__file__).read_text()
        tree = ast.parse(source, feature_version=(3, 9))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module)
        self.assertFalse(any(name.startswith(('PIL', 'pptx')) for name in imports if name))
        self.assertNotIn('_pillow_basic', source)
        self.assertNotIn('open(', source)

    def test_literal_profile_preimage_and_digest(self):
        expected_preimage = (
            b'presentation-agent:layout-profile:v1\x00{"arithmetic":{"checkpoints":"semantic-checkpoints-v1","max_int'
            b'eger_magnitude":9007199254740991,"max_rational_denominator":9007199254740991,"max_rational_numerator'
            b'_magnitude":9007199254740991},"emu_owner":"future-renderer","font":{"face_index":0,"family":"Arial",'
            b'"sha256":"525979822591a3447cfc49d943d6f7683508e25543407871c0ed8fed05fd2bd9","static":true,"style":"R'
            b'egular"},"font_sizes":[18000,24000,32000],"guarantee":"level-2-provider-measured-fit","layout":{"ali'
            b'gnment":["left","top"],"allocation":"complete-exactly-once-same-slide","autofit":"forbid","clipping_'
            b'success":"forbid","containment":"inclusive-four-edges","dimensions":"explicit-per-slide","fallback":'
            b'"forbid","field_order":"source-canonical-v1","origin":"content-left-top","overlap":"field-box-interi'
            b'ors-forbidden","pagination":"forbid","reading_order":"explicit-per-slide-permutation","repair":"forb'
            b'id","safe_margins":"explicit","shared_edges":"allow","shrink":"forbid","size_floor":"supported-size-'
            b'not-above-size","substitution":"forbid","wrap":"forbid"},"measurement":{"baseline":"ascent-plus-inde'
            b'x-times-line-height","bounds":"provider-relative-left-baseline","empty_line":"zero-advance-zero-boun'
            b'ds","envelope":["translated-provider-box","advance-segment","complete-vertical-slot"],"leading":0,"l'
            b'ine_height":"ascent-plus-positive-descent","metrics":"independent-all-supported-sizes","negative_bea'
            b'rings":"preserve","observations":"exact-binary-rational"},"name":"ascii-lf-arial-regular-basic-720dp'
            b'i-v1","provider":{"bbox_anchor":"ls","build_id":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
            b'aaaaaaaaaaaaaaaaaaaa","direction":null,"engine":"BASIC","features":null,"font_encoding":"unic","font'
            b'_inspection":"sfnt-unicode-ascii-agreement-v1","freetype_version":"2.14.3","language":null,"measurem'
            b'ent_mode":"L","name":"Pillow","return_protocol":"pillow-basic-exact-shapes-v1","runtime_configuratio'
            b'n":"controlled-fresh-process-no-overrides-v1","runtime_id":"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
            b'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","stroke_width":0,"version":"12.3.0"},"resource_policy":"layout-limi'
            b'ts-v1-lower-only","rounding":{"epsilon":0,"maxima":"ceiling","minima":"floor","scalar":"nearest-ties'
            b'-positive-infinity"},"schema_version":1,"text":{"blank_lines":"preserve","codepoint_max":126,"codepo'
            b'int_min":32,"complete_blank_fields":"reject","direction":"ltr","edge_spaces":"reject","empty_primiti'
            b've_lines":1,"internal_spaces":"preserve","lf_semantics":"authored-line-boundary","line_separator":10'
            b',"spaces_only_lines":"reject","trailing_lf":"preserve"},"units":{"model_units_per_pixel":100,"model_'
            b'units_per_point":1000,"pixels_per_point":10}}'
        )
        p = profile(FIXED_DIGEST)
        self.assertEqual(l._NAMESPACE + canonical_bytes(l._descriptor(p)), expected_preimage)
        self.assertEqual(p.profile_id, 'lp1:5248983f88271cd3900fbb46a1b452cd246df421d4271a7d36739b3024a697c2')
        self.assertEqual(p.profile_id, 'lp1:' + sha256(expected_preimage).hexdigest())
        for changes in ({'pillow_version': 'other'}, {'freetype_version': 'other'},
                        {'provider_build_id': 'sha256:'+'c'*64}, {'runtime_id': 'sha256:'+'c'*64},
                        {'font': replace(p.font, family='Other')}, {'font': replace(p.font, style='Other')},
                        {'font': replace(p.font, sha256='c'*64)}, {'font': replace(p.font, face_index=l._M)}):
            self.assertNotEqual(replace(p, **changes).profile_id, p.profile_id)
        self.assertNotIn('limits', l._descriptor(p))

    def test_forged_fraction_and_missing_local_attributes(self):
        for numerator, denominator in ((2, 2), (1, 0), (1, -1), (True, 1), (1, True)):
            raw = object.__new__(Q)
            object.__setattr__(raw, '_numerator', numerator)
            object.__setattr__(raw, '_denominator', denominator)
            with self.assertRaises(ValueError):
                l._rational(raw)
        for cls in (l.Rect, l.Insets, l.FieldRef, l.FontIdentity, l.LayoutProfile,
                    l.FieldPlacement, l.SlideLayoutSpec, l.LayoutSpec, l.LineMeasurement,
                    l.MeasuredField, l.SlideLayout, l.PresentationLayout):
            with self.subTest(cls=cls.__name__), self.assertRaises(ValueError):
                forged(cls).__post_init__()
        # Dataclass defaults remain valid accessible values on an empty instance.
        forged(l.LayoutLimits).__post_init__()

    def test_pass_ownership_sentinels_and_earlier_later_character_precedence(self):
        display, spec = fixture(('A', 'B'), roles=True)
        slide = display.slides[0]
        bad_label = altered(slide.qualifications[0], status_label=object())
        for earlier in (True, False):
            if earlier:
                content = (altered(slide.content[0], text='X'*101), slide.content[1])
                bad_slide = altered(slide, content=content, qualifications=(bad_label,))
                message = 'Field characters'
            else:
                citation = altered(slide.citations[0], metadata=altered(slide.citations[0].metadata, title='X'*101))
                bad_slide = altered(slide, qualifications=(bad_label,), citations=(citation,))
                message = 'Expected concrete DisplayStatusLabel'
            with self.assertRaisesRegex(ValueError, message):
                self.call(altered(display, slides=(bad_slide,)), spec,
                          limits=replace(l.LayoutLimits(), max_characters_per_field=100))
        # No premature upstream post-init/provenance replay, including citations.
        with ExitStack() as stack:
            for cls in (d.PresentationDisplay, d.SlideDisplay, d.DisplayText, d.DisplayCitation,
                        d.BlockRef, SnapshotCitationMetadata):
                stack.enter_context(patch.object(cls, '__post_init__', side_effect=AssertionError('upstream replay')))
            self.call(display, spec)
        # Mapping pass never revalidates citation metadata, labels or reference shapes.
        with ExitStack() as stack:
            for name in ('_digest', '_block_ref', '_text_length'):
                stack.enter_context(patch.object(l, name, side_effect=AssertionError('wrong owner')))
            l._enumerate_fields(display)
        # Provider stage gate is before import/open even when empty.
        import sys
        with patch.object(sys, 'version_info', (3, 9, 99)):
            with self.assertRaisesRegex(ValueError, 'pass 10:.*Python >= 3.10'):
                self.call(display, spec)

    def test_measured_records_bounds_ranges_and_parent_correspondence(self):
        result = self.call(*fixture(('A\n',)))
        measured = result.slides[0].fields[0]
        line = measured.lines[0]
        for changes in ({'line_index': True}, {'source_start': -1}, {'source_start': 2},
                        {'source_end': True}, {'baseline': -1}, {'baseline': l._M+1},
                        {'advance': 1}, {'advance': Q(-1)}, {'provider_bounds': (Q(0),)*3},
                        {'provider_bounds': (Q(1), Q(0), Q(0), Q(0))}, {'occupancy': None}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(line, **changes)
        for changes in ({'source_end': 0}, {'line_index': 1}, {'baseline': line.baseline+1}):
            fabricated = replace(line, **changes)  # Local line consistency is deliberately weaker.
            with self.assertRaises(ValueError):
                replace(measured, lines=(fabricated, measured.lines[1]))
        blank = replace(measured.lines[1], advance=Q(1))
        with self.assertRaisesRegex(ValueError, 'Empty line'):
            replace(measured, lines=(line, blank))
        shifted = replace(measured.placement, box=l.Rect(1, 0, 100000, 10000))
        changed = replace(measured, placement=shifted)
        with self.assertRaisesRegex(ValueError, 'placement correspondence'):
            replace(result.slides[0], fields=(changed,))
        wrong_slide = replace(result.slides[0].specification, slide_index=1,
                              fields=(replace(measured.placement, field=l.FieldRef(
                                  d.BlockRef(1, d.BlockKind.CONTENT, 0), l.FieldRole.TEXT)),))
        with self.assertRaisesRegex(ValueError, 'Noncontiguous'):
            l.LayoutSpec((wrong_slide,))

    def test_output_aggregate_limits_before_children_and_ranges(self):
        display, spec = fixture()
        measured = self.call(display, spec).slides[0].fields[0]
        slide_spec = spec.slides[0]
        # Exactly 100000 declared line slots advance to text scanning; one more
        # rejects before line entry access. Payload remains within char ceilings.
        for count in (100000, 100001):
            measured_fields = tuple(altered(measured, lines=(None,)*min(250, count-i))
                                    for i in range(0, count, 250))
            slides = tuple(forged(l.SlideLayout, specification=slide_spec, fields=measured_fields[i:i+100])
                           for i in range(0, len(measured_fields), 100))
            if count == 100000:
                l._output_counts(slides, l.LayoutLimits())
            else:
                with self.assertRaisesRegex(ValueError, 'Output line tuples'):
                    l._output_counts(slides, l.LayoutLimits())
        # Character and text-derived slot aggregates are independent of supplied lines.
        for count in (2000000, 2000001):
            fs = tuple(altered(measured, text='X'*min(100000, count-i), lines=())
                       for i in range(0, count, 100000))
            slides = (forged(l.SlideLayout, specification=slide_spec, fields=fs),)
            message = 'Line characters' if count == 2000000 else 'Total characters'
            with self.assertRaisesRegex(ValueError, message):
                l._output_counts(slides, l.LayoutLimits())
        bad_specs = tuple(forged(l.SlideLayout, specification=altered(slide_spec, fields=(None,)*100), fields=())
                          for _ in range(101))
        with self.assertRaisesRegex(ValueError, 'Output specification fields'):
            l._output_counts(bad_specs, l.LayoutLimits())

    def test_multiple_slide_identity_contiguity_and_no_cross_slide_overlap(self):
        display, spec = fixture(('A',))
        second_ref = d.BlockRef(1, d.BlockKind.CONTENT, 0)
        second_display = d.SlideDisplay(1, (d.DisplayText(second_ref, 'B'),), (), ())
        second_spec = l.SlideLayoutSpec(1, 100000, 200000, l.Insets(0,0,0,0),
                                       (placement(l.FieldRef(second_ref, l.FieldRole.TEXT)),))
        display = altered(display, slides=display.slides+(second_display,))
        spec = l.LayoutSpec(spec.slides+(second_spec,))
        result = self.call(display, spec)
        self.assertEqual([s.fields[0].text for s in result.slides], ['A', 'B'])
        self.assertIs(result.slides[1].specification, second_spec)
        self.call(display, spec, limits=replace(l.LayoutLimits(), max_slides=2, max_display_fields=2,
                                               max_fields_per_slide=1))
        self.fail_pass(3, display, spec, limits=replace(l.LayoutLimits(), max_display_fields=1))

    def test_independent_unused_metrics_and_provider_exceptions(self):
        display, spec = fixture(())
        provider = DoubleProvider()
        provider.metrics[320] = (0, 0)
        with self.assertRaisesRegex(ValueError, 'pass 12:'):
            self.call(display, spec, provider)
        # A wrong loaded engine fails before any metrics, even on an unused size.
        provider = DoubleProvider()
        original = provider.load_font
        def bad_engine(*args, **kwargs):
            font = original(*args, **kwargs)
            font.layout_engine = object()
            return font
        with patch.object(provider, 'load_font', side_effect=bad_engine):
            with self.assertRaisesRegex(ValueError, 'pass 11: Font engine'):
                self.call(display, spec, provider)
        self.assertFalse(any(call[0] == 'metrics' for call in provider.calls))
        # Operational exceptions are not disguised as validation failures.
        with patch.object(l, '_FONT_SHA256', TEST_DIGEST), patch.object(l, '_open_provider', side_effect=MemoryError):
            with self.assertRaises(MemoryError):
                l.layout_presentation(display, spec, font_bytes=FONT_BYTES, profile=profile())

    def test_arithmetic_named_quantity_limits_and_translated_bounds(self):
        m = l._M
        # These isolated semantic checkpoints cover unreachable integrated edges:
        # all exact metric/slot/bbox/envelope quantities use the same checker.
        names = ('A', 'D', 'H', 'B', 'S', 'E', 'advance', 'left', 'top', 'right', 'bottom',
                 'B+top', 'B+bottom', 'envelope-left', 'envelope-top', 'envelope-right', 'envelope-bottom')
        for name in names:
            with self.subTest(quantity=name):
                for sign in (-1, 1):
                    self.assertEqual(l._rational(Q(sign*m)), sign*m)
                    self.assertEqual(l._scaled(Q(sign*m, 100))*100, sign*m)
                    with self.assertRaises(ValueError):
                        l._rational(Q(sign*(m+1)))
                    with self.assertRaises(ValueError):
                        l._scaled(Q(sign*(m+1), 100))
                self.assertEqual(l._rational(Q(1, m)), Q(1, m))
                with self.assertRaises(ValueError):
                    l._rational(Q(1, m+1))
        # Slot multiplication is checked after evaluation, with exact equality.
        h = Q(m, 200)
        self.assertEqual(l._scaled(2*h), Q(m, 100))
        with self.assertRaises(ValueError):
            l._scaled(3*h)
        # Nonfinite and tiny binary observations exceed their exact bounds.
        for value in (float('nan'), float('-inf'), float('inf'), 2.0**-54, float(m+1)):
            with self.assertRaises(ValueError):
                l._observation(value)
        self.assertEqual(l._observation(m), m)
        # Rounded union and translated field edges use inclusive integer bounds.
        self.assertEqual(l._union(((-m, -m, m, m), (0,0,0,0))), (-m,-m,m,m))
        with self.assertRaises(ValueError):
            l._union(((0,0,m+1,m),))
        ref = l.FieldRef(d.BlockRef(0, d.BlockKind.CONTENT, 0), l.FieldRole.TEXT)
        p = placement(ref, box=l.Rect(m-10, m-10, m, m))
        l._translated_fit(p, (0,0,10,10))
        for occupancy in ((0,0,11,10), (0,0,10,11)):
            with self.assertRaisesRegex(ValueError, 'Integer geometry bound'):
                l._translated_fit(p, occupancy)
        # Local content edges must not overflow, even before containment.
        with self.assertRaisesRegex(ValueError, 'Integer geometry bound'):
            replace(p, insets=l.Insets(11,0,0,0))
