"""Fixed offline normalized-evidence bridge; no work occurs on import."""
import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Tuple

from .compose import compose
from .evidence import CSVLocator, EvidenceRecord, TextLocator
from .evidence_verification import QualificationVerification, verify_evidence
from .milestone1_adapter import (
    DemoProfile, Milestone1Adaptation, Milestone1DemoMapping,
    SourcePresentation, adapt_milestone1_demo,
)
from .pptx_renderer import render
from .qa import structural_qa
from .quantities import NumericType, Operation, QuantityGraph, Unit, UnitKind
from .source_capture import SourceSnapshot, SourceStore
from .validate import validate


_STATEMENT = 'Convenience samples were not randomized; case mix may differ.'
_QUALIFICATION = 'Quality and cost remain unmeasured.'
_CRITERIA = 'Compare minutes per case, sample size, and strength of inference.'
_LABEL = 'Unverified qualification: '


@dataclass(frozen=True)
class QualificationContentBinding:
    owner_evidence_id: str
    qualification_index: int
    status: QualificationVerification
    qualification_text: str
    content_id: str
    slide_id: str
    element_id: str
    display_text: str


@dataclass(frozen=True)
class DemoBuildResult:
    deck_path: Path
    snapshots: Tuple[SourceSnapshot, ...]
    adaptation: Milestone1Adaptation
    qa_report: dict
    qualification_content_bindings: Tuple[QualificationContentBinding, ...]


def _require(condition):
    if not condition:
        raise ValueError('demo_qualification: incompatible fixed placement or provenance')


def _qualification_binding(adaptation):
    """Accept exactly the one approved authored qualification, without inference."""
    provenance = adaptation.provenance
    owner = provenance.mapping.e3_evidence_id
    captured = [(record.evidence_id, index, text)
                for record in provenance.evidence
                for index, text in enumerate(record.qualifications)]
    _require(captured == [(owner, 0, _QUALIFICATION)])
    _require(len(provenance.qualifications) == 1)
    qualification = provenance.qualifications[0]
    _require((qualification.owner_evidence_id, qualification.qualification_index,
              qualification.status) == (owner, 0, QualificationVerification.UNVERIFIED))
    record = next(record for record in provenance.evidence if record.evidence_id == owner)
    _require(record.qualification_verification is QualificationVerification.UNVERIFIED)
    text = record.qualifications[qualification.qualification_index]
    return QualificationContentBinding(owner, 0, qualification.status, text,
                                       'C4', 'SL2', 'C4-unmeasured', _LABEL + text)


def _place_qualification(inputs, binding):
    items = inputs['content']['items']
    candidates = [item for item in items if item['id'] == 'C4']
    _require(len(candidates) == 1)
    item = candidates[0]
    # Reject stale prose rather than repairing an incompatible M1 fixture.
    _require(item['text'] == _CRITERIA + ' ' + binding.qualification_text)
    _require(item['evidence_ids'] == ['E3'])
    _require(sum(c['text'].count(binding.qualification_text) for c in items) == 1)
    placements = [(slide['id'], slide['layout'])
                  for slide in inputs['presentation_plan']['slides']
                  for content_id in slide['content_ids'] if content_id == 'C4']
    _require(placements == [('SL2', 'context')])
    c7 = [c for c in items if c['id'] == 'C7']
    _require(len(c7) == 1 and c7[0]['text'] == _STATEMENT and
             c7[0]['evidence_ids'] == ['E3'])
    item['text'] = _CRITERIA + ' ' + binding.display_text


def _validate_qualification(adaptation, bindings, composition):
    expected = _qualification_binding(adaptation)
    _require(bindings == (expected,))
    matches = [(slide, element) for slide in composition['slides']
               for element in slide['elements']
               if expected.qualification_text in element.get('text', '') or
               _LABEL.strip() in element.get('text', '') or
               element['id'] == expected.element_id]
    _require(len(matches) == 1)
    slide, element = matches[0]
    _require(slide['id'] == expected.slide_id and
             element['id'] == expected.element_id and element['kind'] == 'text' and
             element.get('derived_from_content_id') == expected.content_id and
             element.get('evidence_ids') == ['E3'] and element.get('source_ids') == ['S3'] and
             element['text'] == expected.display_text)


def build_demo(root) -> DemoBuildResult:
    """Build the fixed demo and atomically replace its deck only after QA passes."""
    root = Path(root)
    store = SourceStore(root)
    snapshots = tuple(store.capture('fixtures/milestone2_phase2d2/' + name)
                      for name in ('pilot_a.csv', 'pilot_b.csv', 'protocol.txt'))
    roles = (('mean handling time', NumericType.DECIMAL, 'minutes_per_case'),
             ('sample size', NumericType.INTEGER, 'cases'),
             ('supplied total handling time', NumericType.DECIMAL, 'minutes'))
    records = tuple(EvidenceRecord(snapshot.snapshot_id, CSVLocator(2, 2, col, col),
                                   f'Pilot {letter} {role}.')
                    for snapshot, letter in zip(snapshots[:2], ('A', 'B'))
                    for col, (role, _, _) in enumerate(roles, 1)) + (
        EvidenceRecord(snapshots[2].snapshot_id, TextLocator(1, 1),
                       _STATEMENT, (_QUALIFICATION,)),)
    verifications = tuple(verify_evidence(store, record) for record in records)
    graph = QuantityGraph()
    facts = tuple(graph.add_fact(verification, cell=verification.record.locator,
                                 numeric_type=roles[index % 3][1],
                                 unit=Unit(UnitKind.NAMED, roles[index % 3][2]))
                  for index, verification in enumerate(verifications[:6]))
    difference = graph.derive(Operation.SUBTRACT, left_id=facts[0].quantity_id,
                              right_id=facts[3].quantity_id)
    ratio = graph.derive(Operation.RATIO, left_id=difference.quantity_id,
                         right_id=facts[0].quantity_id)
    mapping = Milestone1DemoMapping(
        DemoProfile.SYNTHETIC_HANDLING_TIME_V1, True,
        SourcePresentation(snapshots[0].snapshot_id, 'Synthetic pilot A log',
                           'Invented fixture; 30 cases; total handling time 360 minutes.'),
        SourcePresentation(snapshots[1].snapshot_id, 'Synthetic pilot B log',
                           'Invented fixture; 30 cases; total handling time 270 minutes.'),
        SourcePresentation(snapshots[2].snapshot_id, 'Synthetic evaluation protocol',
                           'Invented fixture; convenience samples, no random assignment; timing only.'),
        *(fact.quantity_id for fact in facts), difference.quantity_id, ratio.quantity_id,
        records[6].evidence_id)
    adaptation = adapt_milestone1_demo(graph=graph, qualitative_verification=verifications[6],
                                     mapping=mapping)
    inputs = {name: json.loads((root / 'fixtures' / (name + '.json')).read_text(encoding='utf-8'))
              for name in ('content', 'presentation_plan', 'theme')}
    inputs['evidence'] = adaptation.legacy_evidence
    bindings = (_qualification_binding(adaptation),)
    _place_qualification(inputs, bindings[0])
    validate(inputs)
    composition = compose(inputs)
    _validate_qualification(adaptation, bindings, composition)
    output = root / 'output' / 'milestone2_phase2d2'
    output.mkdir(parents=True, exist_ok=True)
    final = output / 'deck.pptx'
    with TemporaryDirectory(dir=output) as temporary:
        primary = Path(temporary) / 'primary.pptx'
        rebuilt = Path(temporary) / 'rebuilt.pptx'
        render(composition, primary)
        rebuild = compose(inputs)
        _validate_qualification(adaptation, bindings, rebuild)
        render(rebuild, rebuilt)
        report = structural_qa(inputs, composition, primary, rebuilt)
        if report['passed'] is not True:
            raise RuntimeError('Structural QA failed: ' + str(report['checks']))
        os.replace(primary, final)
    return DemoBuildResult(final, snapshots, adaptation, report, bindings)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    result = build_demo(parser.parse_args().root)
    print(result.deck_path)


if __name__ == '__main__':
    main()
