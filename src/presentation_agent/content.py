"""Immutable authored content identities; no semantic verification or persistence."""
from dataclasses import dataclass, fields
from enum import Enum
import hashlib
import re
from typing import Optional, Tuple

from .evidence import MAX_TEXT_CHARS, canonical_bytes


__all__ = ['ContentLimits', 'Claim', 'QuantitySelection', 'ContentBundle',
           'SnapshotCitationMetadata', 'QualificationOrigin']


def _exact(value, cls):
    if type(value) is not cls:
        raise ValueError('Expected exact ' + cls.__name__)


def _text(value):
    _exact(value, str)
    if not value.strip() or len(value) > MAX_TEXT_CHARS:
        raise ValueError('Invalid or oversized text')
    value.encode('utf-8', errors='strict')


def _id(value, prefixes):
    _exact(value, str)
    if not re.fullmatch('(?:' + '|'.join(prefixes) + r'):[0-9a-f]{64}', value):
        raise ValueError('Invalid identity')


def _references(values, prefixes):
    _exact(values, tuple)
    for value in values:
        _id(value, prefixes)
    if len(set(values)) != len(values):
        raise ValueError('Duplicate reference')
    return tuple(sorted(values))


@dataclass(frozen=True)
class ContentLimits:
    max_items: int = 10_000
    max_references: int = 10_000
    max_binding_steps: int = 100_000

    def __post_init__(self):
        for field in fields(ContentLimits):
            value = getattr(self, field.name)
            if type(value) is not int or not 1 <= value <= field.default:
                raise ValueError('Invalid content limit: ' + field.name)


@dataclass(frozen=True)
class Claim:
    text: str
    evidence_ids: Tuple[str, ...] = ()
    quantity_ids: Tuple[str, ...] = ()
    qualifications: Tuple[str, ...] = ()

    def __post_init__(self):
        _text(self.text)
        evidence = _references(self.evidence_ids, ('ev1',))
        quantities = _references(self.quantity_ids, ('qf1', 'qd1'))
        if not evidence and not quantities:
            raise ValueError('Claim requires a reference')
        _exact(self.qualifications, tuple)
        for text in self.qualifications:
            _text(text)
        object.__setattr__(self, 'evidence_ids', evidence)
        object.__setattr__(self, 'quantity_ids', quantities)
        canonical_bytes(self.identity_payload())

    @property
    def claim_id(self) -> str:
        return 'cl1:' + hashlib.sha256(
            b'presentation-agent:claim:v1\0' +
            canonical_bytes(self.identity_payload())).hexdigest()

    def identity_payload(self) -> dict:
        return {'schema_version': 1, 'text': self.text,
                'evidence_ids': list(self.evidence_ids),
                'quantity_ids': list(self.quantity_ids),
                'qualifications': list(self.qualifications)}


@dataclass(frozen=True)
class QuantitySelection:
    label: str
    quantity_ids: Tuple[str, ...]

    def __post_init__(self):
        _text(self.label)
        quantities = _references(self.quantity_ids, ('qf1', 'qd1'))
        if not quantities:
            raise ValueError('Selection requires a quantity reference')
        object.__setattr__(self, 'quantity_ids', quantities)
        canonical_bytes(self.identity_payload())

    @property
    def selection_id(self) -> str:
        return 'qs1:' + hashlib.sha256(
            b'presentation-agent:quantity-selection:v1\0' +
            canonical_bytes(self.identity_payload())).hexdigest()

    def identity_payload(self) -> dict:
        return {'schema_version': 1, 'label': self.label,
                'quantity_ids': list(self.quantity_ids)}


def _member_id(member):
    return member.claim_id if type(member) is Claim else member.selection_id


def _validate_member(member, cls):
    _exact(member, cls)
    # Validate without re-running a canonicalizing initializer on the input.
    if cls is Claim:
        copy = Claim(member.text, member.evidence_ids, member.quantity_ids,
                     member.qualifications)
    else:
        copy = QuantitySelection(member.label, member.quantity_ids)
    if copy != member:
        raise ValueError('Noncanonical content member')


def _members(values, cls):
    _exact(values, tuple)
    for value in values:
        _validate_member(value, cls)
    ordered = tuple(sorted(values, key=_member_id))
    identities = tuple(_member_id(value) for value in ordered)
    if len(set(identities)) != len(identities):
        raise ValueError('Duplicate content identity')
    return ordered


@dataclass(frozen=True)
class ContentBundle:
    claims: Tuple[Claim, ...] = ()
    quantity_selections: Tuple[QuantitySelection, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, 'claims', _members(self.claims, Claim))
        object.__setattr__(self, 'quantity_selections',
                           _members(self.quantity_selections, QuantitySelection))


def _validate_bundle(bundle):
    _exact(bundle, ContentBundle)
    if (_members(bundle.claims, Claim) != bundle.claims or
            _members(bundle.quantity_selections, QuantitySelection) != bundle.quantity_selections):
        raise ValueError('Noncanonical bundle')


@dataclass(frozen=True)
class SnapshotCitationMetadata:
    snapshot_id: str
    title: Optional[str] = None
    bibliographic_detail: Optional[str] = None

    def __post_init__(self):
        _id(self.snapshot_id, ('sha256',))
        for text in (self.title, self.bibliographic_detail):
            if text is not None:
                _text(text)


class QualificationOrigin(Enum):
    EVIDENCE = 'evidence'
    AUTHORED = 'authored'
