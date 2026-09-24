"""Atomic structural provenance binding and separate citation field assessment.

Success says nothing about truth, entailment, credibility, interpretation,
recommendations, or numbers written in authored prose.
"""
from dataclasses import dataclass
from typing import Optional, Tuple, Union

from .content import (
    Claim, ContentBundle, ContentLimits, QualificationOrigin,
    SnapshotCitationMetadata, _exact, _id, _member_id, _references, _text,
    _validate_bundle,
)
from .evidence import EvidenceRecord
from .evidence_verification import EvidenceVerification, QualificationVerification
from .quantities import DirectQuantity, DerivedQuantity, QuantityGraph


__all__ = ['QualificationBinding', 'ContentBinding', 'BoundContent',
           'CitationAssessment', 'bind_content', 'assess_citations']


def _ordered_ids(values, prefixes):
    if _references(values, prefixes) != values:
        raise ValueError('Expected lexical identities')


def _qualification_key(value):
    return (0 if value.origin is QualificationOrigin.EVIDENCE else 1,
            value.owner_id, value.qualification_index)


@dataclass(frozen=True)
class QualificationBinding:
    owner_id: str
    qualification_index: int
    text: str
    origin: QualificationOrigin
    verification: Optional[QualificationVerification]

    def __post_init__(self):
        _exact(self.origin, QualificationOrigin)
        if type(self.qualification_index) is not int or self.qualification_index < 0:
            raise ValueError('Invalid qualification index')
        _text(self.text)
        if self.origin is QualificationOrigin.EVIDENCE:
            _id(self.owner_id, ('ev1',))
            if self.verification is not QualificationVerification.UNVERIFIED:
                raise ValueError('Evidence qualification must remain unverified')
        else:
            _id(self.owner_id, ('cl1',))
            if self.verification is not None:
                raise ValueError('Authored qualification has no verification status')


@dataclass(frozen=True)
class ContentBinding:
    content_id: str
    evidence_ids: Tuple[str, ...]
    quantity_ids: Tuple[str, ...]
    snapshot_ids: Tuple[str, ...]
    qualifications: Tuple[QualificationBinding, ...]

    def __post_init__(self):
        _id(self.content_id, ('cl1', 'qs1'))
        _ordered_ids(self.evidence_ids, ('ev1',))
        _ordered_ids(self.quantity_ids, ('qf1', 'qd1'))
        _ordered_ids(self.snapshot_ids, ('sha256',))
        _exact(self.qualifications, tuple)
        for qualification in self.qualifications:
            _exact(qualification, QualificationBinding)
            qualification.__post_init__()
        keys = tuple(_qualification_key(q) for q in self.qualifications)
        if keys != tuple(sorted(set(keys))):
            raise ValueError('Invalid qualification occurrence ordering')


def _validate_evidence(record):
    _exact(record, EvidenceRecord)
    record.__post_init__()
    record.locator.__post_init__()
    identity = record.evidence_id
    _id(identity, ('ev1',))
    return identity


def _node_id(node):
    if type(node) not in (DirectQuantity, DerivedQuantity):
        raise ValueError('Expected concrete quantity node')
    # Identity access only: never run node constructors or arithmetic validators.
    try:
        identity = node.quantity_id
    except (AttributeError, TypeError, KeyError, IndexError) as exc:
        raise ValueError('Invalid quantity identity structure') from exc
    _id(identity, ('qf1',) if type(node) is DirectQuantity else ('qd1',))
    return identity


@dataclass(frozen=True)
class BoundContent:
    bundle: ContentBundle
    bindings: Tuple[ContentBinding, ...]
    evidence: Tuple[EvidenceRecord, ...]
    quantities: Tuple[Union[DirectQuantity, DerivedQuantity], ...]

    def __post_init__(self):
        _validate_bundle(self.bundle)
        _exact(self.bindings, tuple)
        _exact(self.evidence, tuple)
        _exact(self.quantities, tuple)
        for binding in self.bindings:
            _exact(binding, ContentBinding)
            binding.__post_init__()
        _ordered_ids(tuple(b.content_id for b in self.bindings), ('cl1', 'qs1'))
        _ordered_ids(tuple(_validate_evidence(e) for e in self.evidence), ('ev1',))
        _ordered_ids(tuple(_node_id(q) for q in self.quantities), ('qf1', 'qd1'))


@dataclass(frozen=True)
class CitationAssessment:
    referenced_snapshot_ids: Tuple[str, ...]
    metadata: Tuple[SnapshotCitationMetadata, ...]
    missing_snapshot_ids: Tuple[str, ...]
    incomplete_snapshot_ids: Tuple[str, ...]
    unused_snapshot_ids: Tuple[str, ...]

    def __post_init__(self):
        for values in (self.referenced_snapshot_ids, self.missing_snapshot_ids,
                       self.incomplete_snapshot_ids, self.unused_snapshot_ids):
            _ordered_ids(values, ('sha256',))
        _exact(self.metadata, tuple)
        for item in self.metadata:
            _exact(item, SnapshotCitationMetadata)
            item.__post_init__()
        _ordered_ids(tuple(m.snapshot_id for m in self.metadata), ('sha256',))

    @property
    def is_complete(self) -> bool:
        return not self.missing_snapshot_ids and not self.incomplete_snapshot_ids


class _Budget:
    def __init__(self, limit):
        self.limit = limit
        self.used = 0

    def charge(self):
        if self.used >= self.limit:
            raise ValueError('Content binding step limit exceeded')
        self.used += 1


def _limits(limits):
    _exact(limits, ContentLimits)
    limits.__post_init__()


def bind_content(
    bundle: ContentBundle,
    *,
    evidence: Tuple[EvidenceRecord, ...] = (),
    quantities: Optional[QuantityGraph] = None,
    limits: ContentLimits = ContentLimits(),
) -> BoundContent:
    """Resolve only supplied references, retaining nodes without replaying them."""
    _limits(limits)
    _exact(bundle, ContentBundle)
    _exact(bundle.claims, tuple)
    _exact(bundle.quantity_selections, tuple)
    _exact(evidence, tuple)
    if quantities is not None:
        _exact(quantities, QuantityGraph)
    if len(bundle.claims) + len(bundle.quantity_selections) > limits.max_items:
        raise ValueError('Content item limit exceeded')
    _validate_bundle(bundle)
    members = sorted(bundle.claims + bundle.quantity_selections, key=_member_id)
    reference_count = sum(len(m.quantity_ids) +
                          (len(m.evidence_ids) if type(m) is Claim else 0)
                          for m in members)
    if reference_count > limits.max_references:
        raise ValueError('Content reference limit exceeded')
    if quantities is None and any(m.quantity_ids for m in members):
        raise ValueError('Quantity references require QuantityGraph')
    budget = _Budget(limits.max_binding_steps)
    pool = {}

    def retain(record, explicit=False):
        identity = _validate_evidence(record)
        if identity in pool:
            if explicit or pool[identity] != record:
                raise ValueError('Duplicate or conflicting evidence identity')
        else:
            pool[identity] = record
        return identity

    for record in evidence:
        budget.charge()
        retain(record, explicit=True)

    reachable = {}
    pending = []
    # First collect reachable retained evidence across the entire semantic pool.
    for member in members:
        budget.charge()
        evidence_ids = set()
        if type(member) is Claim:
            for identity in member.evidence_ids:
                budget.charge()
                evidence_ids.add(identity)
        visited = set()

        def visit(identity):
            if identity in visited:
                return
            budget.charge()
            try:
                node = quantities.get(identity)
            except KeyError as exc:
                raise ValueError('Missing quantity reference') from exc
            if _node_id(node) != identity:
                raise ValueError('Quantity identity mismatch')
            visited.add(identity)
            if identity in reachable and reachable[identity] != node:
                raise ValueError('Conflicting quantity identity')
            reachable[identity] = node
            if type(node) is DirectQuantity:
                _exact(node.verification, EvidenceVerification)
                evidence_ids.add(retain(node.verification.record))
            else:
                _exact(node.input_ids, tuple)
                if len(node.input_ids) != 2:
                    raise ValueError('Expected two ordered operands')
                for operand in node.input_ids:
                    budget.charge()
                    _id(operand, ('qf1', 'qd1'))
                    visit(operand)

        for identity in member.quantity_ids:
            budget.charge()
            visit(identity)
        pending.append((member, evidence_ids, visited))

    bindings = []
    bound_evidence = {}
    # Resolve direct ev1 references only after the combined pool is complete.
    for member, evidence_ids, quantity_ids in pending:
        snapshots = set()
        qualifications = []
        for identity in sorted(evidence_ids):
            budget.charge()
            if identity not in pool:
                raise ValueError('Missing evidence reference')
            record = pool[identity]
            bound_evidence[identity] = record
            for index, text in enumerate(record.qualifications):
                budget.charge()
                qualifications.append(QualificationBinding(
                    identity, index, text, QualificationOrigin.EVIDENCE,
                    QualificationVerification.UNVERIFIED))
            if record.snapshot_id not in snapshots:
                budget.charge()
                snapshots.add(record.snapshot_id)
        if type(member) is Claim:
            for index, text in enumerate(member.qualifications):
                budget.charge()
                qualifications.append(QualificationBinding(
                    member.claim_id, index, text, QualificationOrigin.AUTHORED, None))
        bindings.append(ContentBinding(
            _member_id(member), tuple(sorted(evidence_ids)),
            tuple(sorted(quantity_ids)), tuple(sorted(snapshots)),
            tuple(sorted(qualifications, key=_qualification_key))))
    return BoundContent(bundle, tuple(bindings),
                        tuple(bound_evidence[k] for k in sorted(bound_evidence)),
                        tuple(reachable[k] for k in sorted(reachable)))


def assess_citations(
    bound: BoundContent,
    metadata: Tuple[SnapshotCitationMetadata, ...] = (),
    *,
    limits: ContentLimits = ContentLimits(),
) -> CitationAssessment:
    """Assess field presence only; neither accuracy nor verification is upgraded."""
    _limits(limits)
    _exact(bound, BoundContent)
    _exact(metadata, tuple)
    if len(metadata) > limits.max_items:
        raise ValueError('Citation metadata item limit exceeded')
    bound.__post_init__()
    supplied = {}
    for item in metadata:
        _exact(item, SnapshotCitationMetadata)
        item.__post_init__()
        if item.snapshot_id in supplied:
            raise ValueError('Duplicate citation snapshot identity')
        supplied[item.snapshot_id] = item
    referenced = {s for binding in bound.bindings for s in binding.snapshot_ids}
    return CitationAssessment(
        tuple(sorted(referenced)), tuple(supplied[k] for k in sorted(supplied)),
        tuple(sorted(referenced - supplied.keys())),
        tuple(sorted(s for s in referenced & supplied.keys()
                     if supplied[s].title is None or supplied[s].bibliographic_detail is None)),
        tuple(sorted(supplied.keys() - referenced)))
