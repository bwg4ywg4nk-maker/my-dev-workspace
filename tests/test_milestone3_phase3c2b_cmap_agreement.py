"""Phase-4 synthetic agreement checks; no production qualification."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from presentation_agent import _pillow_basic as p
from presentation_agent import layout as l
from test_milestone3_phase3c2b_layout import profile
from test_milestone3_phase3c2b_pillow import fake_pillow, sfnt, tables, cmap_table, format4, format12

GLYPHS = tuple(range(1, 96))


def audit(glyphs=GLYPHS):
    return (2, ((0, 0, 3, 0x756e6963, 4, glyphs),
                (1, 3, 10, 0x756e6963, 12, glyphs)), 1, glyphs, 1, glyphs)


def font(value):
    return SimpleNamespace(font=SimpleNamespace(_pa_cmap_audit=Mock(return_value=value)))


class CmapAgreementTests(unittest.TestCase):
    def setUp(self):
        self.data = bytes(sfnt())
        self.inspection = p._inspect_sfnt(self.data)

    def test_agreement_and_nonzero_selected_map(self):
        face = font(audit())
        p._audit_font(face, self.inspection)
        face.font._pa_cmap_audit.assert_called_once_with()

    def test_missing_extra_reordered_and_changed_candidates(self):
        first, second = audit()[1]
        cases = ((first,), (first, second, (2,) + second[1:]),
                 ((0,) + second[1:], (1,) + first[1:]),
                 (first, second[:2] + (1,) + second[3:]))
        for maps in cases:
            with self.subTest(maps=maps), self.assertRaises(ValueError):
                p._audit_font(font((len(maps), maps, 0, GLYPHS, 0, GLYPHS)), self.inspection)

    def test_each_of_95_glyphs_compared_even_when_native_maps_agree(self):
        for index in range(95):
            changed = list(GLYPHS)
            changed[index] += 1
            with self.subTest(codepoint=index + 32), self.assertRaisesRegex(ValueError, 'glyph mismatch'):
                p._audit_font(font(audit(tuple(changed))), self.inspection)

    def test_selected_restoration_and_shape_mismatches(self):
        for slot, replacement in ((2, 0), (3, GLYPHS[:-1] + (100,)),
                                  (4, 0), (5, GLYPHS[:-1] + (100,)),
                                  (3, GLYPHS[:-1]), (0, True)):
            value = list(audit())
            value[slot] = replacement
            with self.subTest(slot=slot), self.assertRaises(ValueError):
                p._audit_font(font(tuple(value)), self.inspection)

    def test_ineligible_maps_do_not_change_candidate_order(self):
        first, second = audit()[1]
        maps = (first, (1, 1, 0, 0, 0, ()), (2,) + second[1:])
        p._audit_font(font((3, maps, 2, GLYPHS, 2, GLYPHS)), self.inspection)
        with self.assertRaises(ValueError):
            p._audit_font(font((3, maps, 1, GLYPHS, 1, GLYPHS)), self.inspection)

    def test_native_failure_has_no_retry(self):
        for error in (RuntimeError('restore failed'), MemoryError()):
            face = font(None)
            face.font._pa_cmap_audit.side_effect = error
            with self.assertRaises(MemoryError if isinstance(error, MemoryError) else ValueError):
                p._audit_font(face, self.inspection)
            face.font._pa_cmap_audit.assert_called_once_with()

    def test_pass11_audits_each_measurement_face_and_stops_on_failure(self):
        for failing in (None, 0, 1, 2):
            with self.subTest(failing=failing), fake_pillow() as (_, image_font):
                core = p._PillowBasicCore()
                faces = [font(audit()) for _ in range(3)]
                for face in faces:
                    face.layout_engine = core.basic_engine
                    face.getname = lambda: ('Arial', 'Regular')
                if failing is not None:
                    faces[failing].font._pa_cmap_audit.return_value = audit(tuple(range(2, 97)))
                image_font.FreeTypeFont.side_effect = faces
                if failing is None:
                    result = l._load_fonts(core, self.data, profile())
                    self.assertEqual(list(result.values()), faces)
                else:
                    with self.assertRaises(ValueError):
                        l._load_fonts(core, self.data, profile())
                count = 3 if failing is None else failing + 1
                self.assertEqual(image_font.FreeTypeFont.call_count, count)
                self.assertEqual([f.font._pa_cmap_audit.call_count for f in faces],
                                 [int(i < count) for i in range(3)])

    def test_parser_rejects_before_any_native_load(self):
        items = tables()
        items[b'cmap'] = cmap_table(((0, 3, format4()), (3, 10, format12(((32, 126, 2),)))))
        with fake_pillow() as (_, image_font):
            with self.assertRaisesRegex(ValueError, 'candidate disagreement'):
                l._load_fonts(p._PillowBasicCore(), bytes(sfnt(items.items())), profile())
            image_font.FreeTypeFont.assert_not_called()
