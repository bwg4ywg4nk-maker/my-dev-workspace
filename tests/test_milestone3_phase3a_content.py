"""Frozen Phase 3A content contract and independent literal identity vectors."""
import ast
from dataclasses import FrozenInstanceError, fields, replace
import hashlib
from pathlib import Path
import unittest
from unittest.mock import patch

from presentation_agent import content as c
from presentation_agent.evidence import MAX_TEXT_CHARS, MAX_RECORDS, canonical_bytes


EV = 'ev1:' + '0' * 64
EV2 = 'ev1:' + '2' * 64
QF = 'qf1:' + '1' * 64
QD = 'qd1:' + '2' * 64
SNAP = 'sha256:' + '3' * 64
# Generated independently from hand-written canonical JSON, without importing
# production content or its identity implementation. Expected digests are literals.
CLAIM_ID = 'cl1:8803721e198c2539fdddeac0c64040dde7b3411bea1410664c7df2e6a9bfc1dd'
SELECTION_ID = 'qs1:87e57fa0a4c0dc41da6d1d0722fffd767adaad448d9660790b2b43b3227f8c60'
CLAIM_JSON = ('{"evidence_ids":["' + EV + '"],"qualifications":[" caveat ","caveat"],'
              '"quantity_ids":["' + QF + '"],"schema_version":1,"text":" Δ claim "}').encode('utf-8')
SELECTION_JSON = ('{"label":" Measure ","quantity_ids":["' + QF +
                  '"],"schema_version":1}').encode('utf-8')


class StringSubclass(str):
    pass


class TupleSubclass(tuple):
    pass


class IntegerSubclass(int):
    pass


class ContentModelTests(unittest.TestCase):
    def test_exact_fields_and_frozen_records(self):
        cases = [
            (c.ContentLimits(), ['max_items', 'max_references', 'max_binding_steps']),
            (c.Claim('claim', (EV,)), ['text', 'evidence_ids', 'quantity_ids', 'qualifications']),
            (c.QuantitySelection('label', (QF,)), ['label', 'quantity_ids']),
            (c.ContentBundle(), ['claims', 'quantity_selections']),
            (c.SnapshotCitationMetadata(SNAP), ['snapshot_id', 'title', 'bibliographic_detail']),
        ]
        for value, names in cases:
            self.assertEqual([f.name for f in fields(value)], names)
            self.assertTrue(value.__dataclass_params__.frozen)
            for name in names:
                with self.assertRaises(FrozenInstanceError):
                    setattr(value, name, getattr(value, name))

    def test_text_strict_and_nonblank(self):
        for text in [None, True, 1, b'x', '', ' \t\n', StringSubclass('x'), '\ud800']:
            makers = [lambda: c.Claim(text, (EV,)),
                      lambda: c.QuantitySelection(text, (QF,)),
                      lambda: c.Claim('x', (EV,), qualifications=(text,))]
            if text is not None:
                makers.extend([lambda: c.SnapshotCitationMetadata(SNAP, text),
                               lambda: c.SnapshotCitationMetadata(SNAP, bibliographic_detail=text)])
            for make in makers:
                with self.subTest(text=repr(text)), self.assertRaises(ValueError):
                    make()

    def test_existing_text_ceiling(self):
        text = '🙂' * MAX_TEXT_CHARS
        self.assertEqual(c.Claim(text, (EV,)).text, text)
        self.assertEqual(c.QuantitySelection(text, (QF,)).label, text)
        self.assertEqual(c.SnapshotCitationMetadata(SNAP, text).title, text)
        self.assertEqual(c.Claim('x', (EV,), qualifications=(text,)).qualifications, (text,))
        for make in [lambda: c.Claim(text + 'x', (EV,)),
                     lambda: c.QuantitySelection(text + 'x', (QF,)),
                     lambda: c.SnapshotCitationMetadata(SNAP, text + 'x'),
                     lambda: c.Claim('x', (EV,), qualifications=(text + 'x',))]:
            with self.assertRaises(ValueError):
                make()

    def test_canonical_collection_ceiling_without_new_qualification_limit(self):
        self.assertEqual(len(c.Claim('x', (EV,), qualifications=('q',) * MAX_RECORDS).qualifications), MAX_RECORDS)
        with self.assertRaises(ValueError):
            c.Claim('x', (EV,), qualifications=('q',) * (MAX_RECORDS + 1))

    def test_canonical_byte_ceiling(self):
        with self.assertRaisesRegex(ValueError, 'Canonical byte limit'):
            c.Claim('x', (EV,), qualifications=('🙂' * MAX_TEXT_CHARS,) * 42)

    def test_tuple_fields_reject_lists_and_subclasses(self):
        for bad in [[], [EV], TupleSubclass((EV,)), None, 'x']:
            for make in [lambda: c.Claim('x', bad),
                         lambda: c.Claim('x', (EV,), bad),
                         lambda: c.Claim('x', (EV,), qualifications=bad),
                         lambda: c.QuantitySelection('x', bad),
                         lambda: c.ContentBundle(bad),
                         lambda: c.ContentBundle(quantity_selections=bad)]:
                with self.assertRaises(ValueError):
                    make()

    def test_reference_required(self):
        with self.assertRaises(ValueError):
            c.Claim('x')
        with self.assertRaises(ValueError):
            c.QuantitySelection('x', ())
        self.assertEqual(c.Claim('x', quantity_ids=(QF,)).quantity_ids, (QF,))

    def test_bad_ids_and_prefix_separation(self):
        for prefix, make in [('ev1', lambda x: c.Claim('x', (x,))),
                             ('qf1', lambda x: c.QuantitySelection('x', (x,))),
                             ('qd1', lambda x: c.Claim('x', quantity_ids=(x,))),
                             ('sha256', lambda x: c.SnapshotCitationMetadata(x))]:
            for bad in [None, True, 1, prefix + ':' + 'a' * 63,
                        prefix + ':' + 'a' * 65, prefix + ':' + 'A' * 64,
                        prefix + ':' + 'g' * 64, ' ' + prefix + ':' + 'a' * 64,
                        prefix + ':' + 'a' * 64 + '\n', StringSubclass(prefix + ':' + 'a' * 64)]:
                with self.subTest(prefix=prefix, bad=bad), self.assertRaises(ValueError):
                    make(bad)
        for bad in (QF, QD, SNAP, CLAIM_ID, SELECTION_ID):
            with self.assertRaises(ValueError):
                c.Claim('x', (bad,))
        for bad in (EV, SNAP, CLAIM_ID, SELECTION_ID):
            with self.assertRaises(ValueError):
                c.QuantitySelection('x', (bad,))

    def test_duplicate_references_rejected(self):
        for make in [lambda: c.Claim('x', (EV, EV)),
                     lambda: c.Claim('x', quantity_ids=(QF, QF)),
                     lambda: c.QuantitySelection('x', (QD, QD))]:
            with self.assertRaisesRegex(ValueError, 'Duplicate'):
                make()

    def test_reference_sorting_and_permutations(self):
        a = c.Claim('x', (EV2, EV), (QF, QD))
        b = c.Claim('x', (EV, EV2), (QD, QF))
        self.assertEqual(a, b)
        self.assertEqual(a.claim_id, b.claim_id)
        self.assertEqual(a.evidence_ids, tuple(sorted((EV2, EV))))
        self.assertEqual(a.quantity_ids, tuple(sorted((QF, QD))))
        self.assertEqual(c.QuantitySelection('x', (QF, QD)), c.QuantitySelection('x', (QD, QF)))

    def test_empty_bundle(self):
        self.assertEqual(c.ContentBundle().claims, ())
        self.assertEqual(c.ContentBundle().quantity_selections, ())

    def test_bundle_is_identity_sorted_semantic_pool(self):
        claims = (c.Claim('a', (EV,)), c.Claim('b', (EV,)))
        selections = (c.QuantitySelection('a', (QF,)), c.QuantitySelection('b', (QF,)))
        a = c.ContentBundle(claims, selections)
        self.assertEqual(a, c.ContentBundle(claims[::-1], selections[::-1]))
        self.assertEqual(a.claims, tuple(sorted(claims, key=lambda x: x.claim_id)))
        self.assertEqual(a.quantity_selections, tuple(sorted(selections, key=lambda x: x.selection_id)))

    def test_duplicate_member_identity(self):
        claim = c.Claim('x', (EV,))
        selection = c.QuantitySelection('x', (QF,))
        with self.assertRaises(ValueError):
            c.ContentBundle((claim, replace(claim)))
        with self.assertRaises(ValueError):
            c.ContentBundle(quantity_selections=(selection, replace(selection)))

    def test_bundle_rejects_wrong_and_subclass_members(self):
        class SubClaim(c.Claim):
            pass
        class SubSelection(c.QuantitySelection):
            pass
        for bad in (None, {}, SubClaim('x', (EV,)), c.QuantitySelection('x', (QF,))):
            with self.assertRaises(ValueError):
                c.ContentBundle((bad,))
        for bad in (None, {}, SubSelection('x', (QF,)), c.Claim('x', (EV,))):
            with self.assertRaises(ValueError):
                c.ContentBundle(quantity_selections=(bad,))

    def test_metadata_optional_and_exact_preservation(self):
        self.assertIsNone(c.SnapshotCitationMetadata(SNAP).title)
        value = c.SnapshotCitationMetadata(SNAP, ' title\n', '\tdetail ')
        self.assertEqual((value.title, value.bibliographic_detail), (' title\n', '\tdetail '))

    def test_limits_defaults_and_lowering(self):
        self.assertEqual(c.ContentLimits(), c.ContentLimits(10000, 10000, 100000))
        self.assertEqual(c.ContentLimits(1, 1, 1).max_items, 1)
        for field in fields(c.ContentLimits):
            for bad in (True, False, 0, -1, 1.0, '1', None, IntegerSubclass(1), field.default + 1):
                with self.subTest(field=field.name, bad=bad), self.assertRaises(ValueError):
                    c.ContentLimits(**{field.name: bad})


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.claim = c.Claim(' Δ claim ', (EV,), (QF,), (' caveat ', 'caveat'))
        self.selection = c.QuantitySelection(' Measure ', (QF,))

    def test_literal_claim_vector_and_exact_payload(self):
        self.assertEqual(self.claim.claim_id, CLAIM_ID)
        self.assertEqual(self.claim.identity_payload(), {'schema_version': 1, 'text': ' Δ claim ',
                         'evidence_ids': [EV], 'quantity_ids': [QF],
                         'qualifications': [' caveat ', 'caveat']})
        self.assertEqual(canonical_bytes(self.claim.identity_payload()), CLAIM_JSON)

    def test_literal_selection_vector_and_exact_payload(self):
        self.assertEqual(self.selection.selection_id, SELECTION_ID)
        self.assertEqual(self.selection.identity_payload(), {'schema_version': 1,
                         'label': ' Measure ', 'quantity_ids': [QF]})
        self.assertEqual(canonical_bytes(self.selection.identity_payload()), SELECTION_JSON)

    def test_additional_literal_unicode_and_derived_reference_vectors(self):
        # Independently hashed hand-written canonical JSON, as above.
        self.assertEqual(c.Claim('e\u0301', quantity_ids=(QD,)).claim_id,
                         'cl1:58354221ddbe0e46cef81a50c4385536389261bb24a22eb9c5f6840a131aa366')
        self.assertEqual(c.QuantitySelection('é', (QD,)).selection_id,
                         'qs1:db98e01a4a2c7c52aac4ba164fa8b3d7e22a2050319df92e5a87aaf9227725b3')

    def test_exact_domains_and_terminal_nul_preimages(self):
        for value, attr, expected in [
            (self.claim, 'claim_id', b'presentation-agent:claim:v1\0' + CLAIM_JSON),
            (self.selection, 'selection_id', b'presentation-agent:quantity-selection:v1\0' + SELECTION_JSON)]:
            with patch.object(c.hashlib, 'sha256', wraps=hashlib.sha256) as digest:
                getattr(value, attr)
                digest.assert_called_once_with(expected)

    def test_each_identity_component_matters(self):
        for kwargs in [{'text': 'different'}, {'evidence_ids': (EV2,)},
                       {'quantity_ids': (QD,)}, {'qualifications': ('changed',)},
                       {'qualifications': self.claim.qualifications[::-1]}]:
            self.assertNotEqual(replace(self.claim, **kwargs).claim_id, CLAIM_ID)
        self.assertNotEqual(replace(self.selection, label='different').selection_id, SELECTION_ID)
        self.assertNotEqual(replace(self.selection, quantity_ids=(QD,)).selection_id, SELECTION_ID)

    def test_repeated_authored_occurrences_preserved(self):
        value = replace(self.claim, qualifications=('same', 'same'))
        self.assertEqual(value.qualifications, ('same', 'same'))
        self.assertNotEqual(value.claim_id, replace(value, qualifications=('same',)).claim_id)

    def test_whitespace_and_unicode_are_not_normalized(self):
        for a, b in [(' x ', 'x'), ('x\ny', 'x y'), ('é', 'e\u0301')]:
            self.assertNotEqual(c.Claim(a, (EV,)).claim_id, c.Claim(b, (EV,)).claim_id)
            self.assertNotEqual(c.QuantitySelection(a, (QF,)).selection_id,
                                c.QuantitySelection(b, (QF,)).selection_id)
            self.assertEqual(c.Claim(a, (EV,)).text, a)
            self.assertEqual(c.QuantitySelection(a, (QF,)).label, a)

    def test_payload_is_detached_identity_facility(self):
        payload = self.claim.identity_payload()
        payload['evidence_ids'].clear()
        self.assertEqual(self.claim.claim_id, CLAIM_ID)
        payload = self.selection.identity_payload()
        payload['quantity_ids'].clear()
        self.assertEqual(self.selection.selection_id, SELECTION_ID)

    def test_no_extra_identity_or_persistence_api(self):
        self.assertFalse(hasattr(c, 'ClaimKind'))
        for value in (self.claim, self.selection, c.ContentBundle(), c.SnapshotCitationMetadata(SNAP)):
            for name in ('to_dict', 'from_dict', 'encode', 'decode', 'load', 'schema',
                         'bundle_id', 'citation_id', 'verification', 'kind'):
                self.assertFalse(hasattr(value, name), name)
        self.assertEqual(set(c.__all__), {'Claim', 'QuantitySelection', 'ContentBundle',
                                         'ContentLimits', 'SnapshotCitationMetadata', 'QualificationOrigin'})

    def test_python39_syntax_and_no_new_dependencies(self):
        tree = ast.parse(Path(c.__file__).read_text(), feature_version=9)
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add('.' * node.level + node.module)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'dataclass':
                self.assertEqual([k.arg for k in node.keywords], ['frozen'])
        self.assertEqual(imports, {'dataclasses', 'enum', 'hashlib', 're', 'typing', '.evidence'})


if __name__ == '__main__':
    unittest.main()
