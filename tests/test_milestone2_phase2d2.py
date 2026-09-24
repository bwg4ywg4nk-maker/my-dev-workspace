"""Real offline bridge integration in isolated repository-shaped roots."""
import ast
import builtins
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import FrozenInstanceError, fields, replace
from decimal import Decimal
import importlib
import io
import json
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from presentation_agent import milestone2_demo as demo
from presentation_agent.evidence import CSVLocator, TextLocator, snapshot_identity
from presentation_agent.evidence_verification import (
    QualificationVerification as QV, StructuredCells as SC, TextReproduction as TR,
)
from presentation_agent.pptx_renderer import inspect_pptx
from presentation_agent.quantities import NumericType, Operation, Unit, UnitKind

ROOT = Path(__file__).resolve().parents[1]
STATEMENT = 'Convenience samples were not randomized; case mix may differ.'
QUALIFICATION = 'Quality and cost remain unmeasured.'
DISPLAY = 'Unverified qualification: ' + QUALIFICATION
SOURCE_BYTES = {
    'pilot_a.csv': b'mean_minutes_per_case,sample_size,total_minutes\n12,30,360\n',
    'pilot_b.csv': b'mean_minutes_per_case,sample_size,total_minutes\n9,30,270\n',
    'protocol.txt': b'Convenience samples were not randomized; case mix may differ.\n',
}
# Independent primary oracle: deliberately not loaded or generated from M1 fixtures.
EXPECTED = {
    'synthetic': True,
    'sources': [
        {'id': 'S1', 'title': 'Synthetic pilot A log',
         'detail': 'Invented fixture; 30 cases; total handling time 360 minutes.'},
        {'id': 'S2', 'title': 'Synthetic pilot B log',
         'detail': 'Invented fixture; 30 cases; total handling time 270 minutes.'},
        {'id': 'S3', 'title': 'Synthetic evaluation protocol',
         'detail': 'Invented fixture; convenience samples, no random assignment; timing only.'},
    ],
    'evidence': [
        {'id': 'E1', 'source_id': 'S1', 'value': 12, 'unit': 'minutes per case', 'sample_size': 30},
        {'id': 'E2', 'source_id': 'S2', 'value': 9, 'unit': 'minutes per case', 'sample_size': 30},
        {'id': 'E3', 'source_id': 'S3',
         'text': 'Convenience samples were not randomized; case mix may differ.'},
    ],
    'calculations': [
        {'id': 'D1', 'operation': 'relative_reduction_percent', 'input_ids': ['E1', 'E2'],
         'value': 25, 'unit': 'percent'},
        {'id': 'D2', 'operation': 'absolute_difference', 'input_ids': ['E1', 'E2'],
         'value': 3, 'unit': 'minutes per case'},
    ],
}


class DemoTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.sources = self.root / 'fixtures' / 'milestone2_phase2d2'
        self.sources.mkdir(parents=True)
        for name in SOURCE_BYTES:
            shutil.copyfile(ROOT / 'fixtures' / 'milestone2_phase2d2' / name, self.sources / name)
        for name in ('content', 'presentation_plan', 'theme'):
            shutil.copyfile(ROOT / 'fixtures' / (name + '.json'),
                            self.root / 'fixtures' / (name + '.json'))
        self.final = self.root / 'output' / 'milestone2_phase2d2' / 'deck.pptx'

    def test_source_bytes(self):
        for name, expected in SOURCE_BYTES.items():
            actual = (ROOT / 'fixtures' / 'milestone2_phase2d2' / name).read_bytes()
            self.assertEqual(actual, expected)
            self.assertEqual(actual.decode('utf-8').encode('utf-8'), actual)
            self.assertNotIn(b'\r', actual)
            self.assertTrue(actual.endswith(b'\n'))
        self.assertNotIn(QUALIFICATION.encode(), SOURCE_BYTES['protocol.txt'])

    def test_real_pipeline_authority_provenance_and_pptx(self):
        events, verifications, facts, derivations, compositions = [], [], [], [], []
        capture, verify = demo.SourceStore.capture, demo.verify_evidence
        add_fact, derive = demo.QuantityGraph.add_fact, demo.QuantityGraph.derive
        compose, render, qa, replace_file = demo.compose, demo.render, demo.structural_qa, demo.os.replace
        original_content = (self.root / 'fixtures/content.json').read_bytes()

        def capture_spy(store, path):
            events.append('capture')
            return capture(store, path)

        def verify_spy(*args, **kwargs):
            events.append('verify')
            result = verify(*args, **kwargs)
            verifications.append(result)
            return result

        def fact_spy(graph, *args, **kwargs):
            events.append('fact')
            result = add_fact(graph, *args, **kwargs)
            facts.append(result)
            return result

        def derive_spy(graph, *args, **kwargs):
            events.append('derive')
            result = derive(graph, *args, **kwargs)
            derivations.append(result)
            return result

        def compose_spy(inputs):
            self.assertEqual(inputs['evidence'], EXPECTED)
            # Equal copies are valid: the handoff does not depend on identity.
            copied = deepcopy(inputs)
            result = compose(copied)
            compositions.append(result)
            return result

        def render_spy(composition, path):
            events.append(path.name)
            return render(composition, path)

        def qa_spy(inputs, composition, primary, rebuilt):
            self.assertEqual(inputs['evidence'], EXPECTED)
            self.assertTrue(primary.exists() and rebuilt.exists())
            report = qa(inputs, composition, primary, rebuilt)
            self.assertIs(report['passed'], True)
            events.append('QA PASS')
            return report

        def replace_spy(source, target):
            events.append('replace')
            self.assertEqual(target, self.final)
            return replace_file(source, target)

        def guarded_open(original):
            def guard(file, *args, **kwargs):
                if isinstance(file, (str, Path)) and Path(file).name == 'evidence.json':
                    self.fail('Runtime attempted historical evidence read')
                return original(file, *args, **kwargs)
            return guard

        with ExitStack() as stack:
            for target, replacement in (
                ('SourceStore.capture', capture_spy), ('verify_evidence', verify_spy),
                ('QuantityGraph.add_fact', fact_spy), ('QuantityGraph.derive', derive_spy),
                ('compose', compose_spy), ('render', render_spy),
                ('structural_qa', qa_spy), ('os.replace', replace_spy),
            ):
                stack.enter_context(patch('presentation_agent.milestone2_demo.' + target, replacement))
            adaptation_spy = stack.enter_context(patch.object(demo, 'adapt_milestone1_demo', wraps=demo.adapt_milestone1_demo))
            validation_spy = stack.enter_context(patch.object(demo, 'validate', wraps=demo.validate))
            stack.enter_context(patch('presentation_agent.models.load_inputs', side_effect=AssertionError('load_inputs')))
            stack.enter_context(patch('presentation_agent.build.build', side_effect=AssertionError('M1 build')))
            stack.enter_context(patch('builtins.open', guarded_open(builtins.open)))
            stack.enter_context(patch('io.open', guarded_open(io.open)))
            result = demo.build_demo(self.root)
        self.assertEqual(events[:18], ['capture'] * 3 + ['verify'] * 7 + ['fact'] * 6 + ['derive'] * 2)
        self.assertEqual(events[18:], ['primary.pptx', 'rebuilt.pptx', 'QA PASS', 'replace'])
        self.assertEqual(adaptation_spy.call_count, 1)
        self.assertEqual(validation_spy.call_count, 1)
        self.assertEqual(len(compositions), 2)
        self.assertEqual(compositions[0], compositions[1])
        self.assertEqual(result.adaptation.legacy_evidence, EXPECTED)
        for item in result.adaptation.legacy_evidence['evidence'][:2]:
            self.assertIs(type(item['value']), int)
            self.assertIs(type(item['sample_size']), int)
        for item in result.adaptation.legacy_evidence['calculations']:
            self.assertIs(type(item['value']), int)
        for index, (verification, fact, raw) in enumerate(zip(verifications, facts, ('12', '30', '360', '9', '30', '270'))):
            col = index % 3 + 1
            cell = CSVLocator(2, 2, col, col)
            snapshot = result.snapshots[index // 3]
            self.assertEqual(snapshot.snapshot_id, snapshot_identity(SOURCE_BYTES[Path(snapshot.source_path).name]))
            self.assertEqual(verification.extraction.rows, ((raw,),))
            self.assertEqual(verification.record.locator, cell)
            self.assertEqual((verification.text_reproduction, verification.structured_cells,
                              verification.qualification_verification), (TR.NOT_ASSESSED, SC.AVAILABLE, QV.UNVERIFIED))
            self.assertEqual(verification.record.qualifications, ())
            self.assertEqual((fact.snapshot_id, fact.cell, fact.raw_text, fact.value),
                             (snapshot.snapshot_id, cell, raw, Decimal(raw)))
            self.assertEqual(fact.numeric_type, NumericType.INTEGER if col == 2 else NumericType.DECIMAL)
            self.assertEqual(fact.unit, Unit(UnitKind.NAMED, ('minutes_per_case', 'cases', 'minutes')[col - 1]))
        e3 = verifications[-1]
        self.assertEqual(e3.record.locator, TextLocator(1, 1))
        self.assertEqual(e3.extraction.text, STATEMENT)
        self.assertEqual((e3.text_reproduction, e3.structured_cells, e3.qualification_verification),
                         (TR.EXACT_MATCH, SC.NOT_APPLICABLE, QV.UNVERIFIED))
        self.assertEqual(e3.record.qualifications, (QUALIFICATION,))
        self.assertEqual((derivations[0].operation, derivations[0].input_ids, derivations[0].value),
                         (Operation.SUBTRACT, (facts[0].quantity_id, facts[3].quantity_id), Decimal('3')))
        self.assertEqual((derivations[1].operation, derivations[1].input_ids, derivations[1].value),
                         (Operation.RATIO, (derivations[0].quantity_id, facts[0].quantity_id), Decimal('0.25')))
        self.assertEqual(result.qualification_content_bindings, (demo.QualificationContentBinding(
            e3.record.evidence_id, 0, QV.UNVERIFIED, QUALIFICATION, 'C4', 'SL2', 'C4-unmeasured', DISPLAY),))
        observed = inspect_pptx(result.deck_path)
        self.assertEqual(len(observed['slides']), 6)
        elements = [e for slide in observed['slides'] for e in slide]
        texts = [e.get('text') for e in elements]
        self.assertEqual(texts.count(DISPLAY), 1)
        self.assertNotIn(QUALIFICATION, texts)
        for text in ('12', '9', '25%', '3 fewer min/case • 25% lower than A'):
            self.assertIn(text, texts)
        self.assertEqual(texts.count('n = 30'), 2)
        chart = next(e for e in elements if e['kind'] == 'chart')
        self.assertEqual(chart['values'], [12, 9])
        self.assertEqual(chart['workbook_cells'], {'B1': 'minutes per case', 'A2': 'Approach A', 'A3': 'Approach B', 'B2': 12, 'B3': 9})
        self.assertTrue(all(result.qa_report['checks'].values()))
        self.assertIn('rendered_rebuild_equivalence', result.qa_report['checks'])
        self.assertEqual((self.root / 'fixtures/content.json').read_bytes(), original_content)
        self.assertEqual(list(self.final.parent.iterdir()), [self.final])

    def test_repeatability_and_public_api(self):
        first = demo.build_demo(self.root)
        observed = inspect_pptx(first.deck_path)
        second = demo.build_demo(self.root)
        self.assertEqual(first, second)
        self.assertEqual(observed, inspect_pptx(second.deck_path))
        self.assertEqual([f.name for f in fields(first)], ['deck_path', 'snapshots', 'adaptation', 'qa_report', 'qualification_content_bindings'])
        for value, field in ((first, 'deck_path'), (first.qualification_content_bindings[0], 'content_id')):
            with self.assertRaises(FrozenInstanceError):
                setattr(value, field, None)

    def test_compatibility_failures(self):
        cases = (
            ('missing', 'pilot_a.csv', None),
            ('malformed', 'pilot_a.csv', b'header\n"unterminated\n'),
            ('mismatch', 'protocol.txt', b'Other statement.\n'),
            ('numeric', 'pilot_a.csv', SOURCE_BYTES['pilot_a.csv'].replace(b'12,', b'NaN,')),
            ('total', 'pilot_a.csv', SOURCE_BYTES['pilot_a.csv'].replace(b'360', b'361')),
            ('sample', 'pilot_a.csv', SOURCE_BYTES['pilot_a.csv'].replace(b'12,30,360', b'12,31,372')),
            ('profile', 'pilot_b.csv', SOURCE_BYTES['pilot_b.csv'].replace(b'9,30,270', b'15,30,450')),
        )
        for label, name, data in cases:
            with self.subTest(label=label):
                path = self.sources / name
                if data is None:
                    path.rename(path.with_suffix('.missing'))
                else:
                    path.write_bytes(data)
                with patch.object(demo, 'render') as renderer:
                    with self.assertRaises((ValueError, FileNotFoundError)):
                        demo.build_demo(self.root)
                    renderer.assert_not_called()
                self.assertFalse(self.final.exists())
                path.write_bytes(SOURCE_BYTES[name])
        path = self.root / 'fixtures/content.json'
        content = json.loads(path.read_text())
        next(c for c in content['items'] if c['id'] == 'C5')['text'] = 'Stale prose.'
        path.write_text(json.dumps(content))
        with self.assertRaisesRegex(ValueError, 'Stale quantitative prose'):
            demo.build_demo(self.root)

    def test_publication_failures_preserve_final_and_snapshots(self):
        real_render = demo.render
        for existing in (False, True):
            for stage in ('primary', 'rebuild', 'qa_exception', 'qa_false', 'replace'):
                with self.subTest(existing=existing, stage=stage), TemporaryDirectory() as directory:
                    root = Path(directory)
                    shutil.copytree(self.root / 'fixtures', root / 'fixtures')
                    final = root / 'output/milestone2_phase2d2/deck.pptx'
                    if existing:
                        final.parent.mkdir(parents=True)
                        final.write_bytes(b'previous deck sentinel')
                    def render(composition, path):
                        if path.stem == stage or (stage == 'rebuild' and path.stem == 'rebuilt'):
                            raise RuntimeError('injected render failure')
                        return real_render(composition, path)
                    with ExitStack() as stack:
                        stack.enter_context(patch.object(demo, 'render', render))
                        if stage == 'qa_exception':
                            stack.enter_context(patch.object(demo, 'structural_qa', side_effect=RuntimeError('injected QA failure')))
                        elif stage == 'qa_false':
                            stack.enter_context(patch.object(demo, 'structural_qa', return_value={'passed': False, 'checks': {}}))
                        if stage == 'replace':
                            stack.enter_context(patch.object(demo.os, 'replace', side_effect=OSError('injected replacement failure')))
                        with self.assertRaises((RuntimeError, OSError)):
                            demo.build_demo(root)
                    self.assertEqual(final.read_bytes() if existing else final.exists(), b'previous deck sentinel' if existing else False)
                    self.assertEqual(len(list((root / '.runtime/snapshots').iterdir())), 3)
                    self.assertEqual(list(final.parent.iterdir()), [final] if existing else [])

    def test_reject_qualification_provenance_mutations(self):
        real_adapt = demo.adapt_milestone1_demo
        for mutation in ('missing', 'duplicate', 'owner', 'index', 'text', 'additional'):
            with self.subTest(mutation=mutation):
                def adapt(**kwargs):
                    result = real_adapt(**kwargs)
                    p = result.provenance
                    records, bindings = list(p.evidence), list(p.qualifications)
                    if mutation == 'missing':
                        records[-1] = replace(records[-1], qualifications=())
                    elif mutation == 'duplicate':
                        bindings *= 2
                    elif mutation == 'owner':
                        bindings[0] = replace(bindings[0], owner_evidence_id=records[0].evidence_id)
                    elif mutation == 'index':
                        bindings[0] = replace(bindings[0], qualification_index=1)
                    elif mutation == 'text':
                        records[-1] = replace(records[-1], qualifications=('Wrong text.',))
                    else:
                        records[0] = replace(records[0], qualifications=('Additional qualification.',))
                    return replace(result, provenance=replace(p, evidence=tuple(records), qualifications=tuple(bindings)))
                with patch.object(demo, 'adapt_milestone1_demo', adapt), patch.object(demo, 'render') as renderer:
                    with self.assertRaisesRegex(ValueError, 'demo_qualification'):
                        demo.build_demo(self.root)
                    renderer.assert_not_called()
                self.assertFalse(self.final.exists())

    def test_reject_composed_qualification_mutations(self):
        real_compose = demo.compose
        for mutation in ('missing', 'duplicate', 'unlabeled', 'text', 'slide', 'content', 'element', 'evidence'):
            with self.subTest(mutation=mutation):
                def compose(inputs):
                    result = real_compose(inputs)
                    slide = result['slides'][1]
                    element = next(e for e in slide['elements'] if e['id'] == 'C4-unmeasured')
                    if mutation == 'missing':
                        slide['elements'].remove(element)
                    elif mutation == 'duplicate':
                        slide['elements'].append(deepcopy(element))
                    elif mutation == 'unlabeled':
                        element['text'] = QUALIFICATION
                    elif mutation == 'text':
                        element['text'] = 'Unverified qualification: Wrong text.'
                    elif mutation == 'slide':
                        slide['elements'].remove(element)
                        result['slides'][0]['elements'].append(element)
                    else:
                        key = {'content': 'derived_from_content_id', 'element': 'id', 'evidence': 'evidence_ids'}[mutation]
                        element[key] = ['E1'] if mutation == 'evidence' else 'wrong'
                    return result
                with patch.object(demo, 'compose', compose), patch.object(demo, 'render') as renderer:
                    with self.assertRaisesRegex(ValueError, 'demo_qualification'):
                        demo.build_demo(self.root)
                    renderer.assert_not_called()
                self.assertFalse(self.final.exists())

    def test_reject_stale_or_misbound_content(self):
        path = self.root / 'fixtures/content.json'
        original = json.loads(path.read_text())
        for mutation in ('missing', 'duplicate', 'owner', 'c7'):
            with self.subTest(mutation=mutation):
                content = deepcopy(original)
                c4 = next(c for c in content['items'] if c['id'] == 'C4')
                if mutation == 'missing':
                    c4['text'] = 'Missing qualification.'
                elif mutation == 'duplicate':
                    c4['text'] += ' ' + QUALIFICATION
                elif mutation == 'owner':
                    c4['evidence_ids'] = ['E1']
                else:
                    next(c for c in content['items'] if c['id'] == 'C7')['text'] = 'Stale qualification.'
                path.write_text(json.dumps(content))
                with self.assertRaisesRegex(ValueError, 'demo_qualification'):
                    demo.build_demo(self.root)
        path.write_text(json.dumps(original))
        plan_path = self.root / 'fixtures/presentation_plan.json'
        plan = json.loads(plan_path.read_text())
        plan['slides'][1]['id'] = 'wrong'
        plan_path.write_text(json.dumps(plan))
        with self.assertRaisesRegex(ValueError, 'demo_qualification'):
            demo.build_demo(self.root)

    def test_reject_content_binding_mutations(self):
        result = demo.build_demo(self.root)
        binding = result.qualification_content_bindings[0]
        inputs = {name: json.loads((self.root / 'fixtures' / (name + '.json')).read_text())
                  for name in ('content', 'presentation_plan', 'theme')}
        inputs['evidence'] = deepcopy(result.adaptation.legacy_evidence)
        demo._place_qualification(inputs, binding)
        composition = demo.compose(inputs)
        mutations = {
            'owner_evidence_id': result.adaptation.provenance.evidence[0].evidence_id,
            'qualification_index': 1, 'status': None, 'qualification_text': 'Wrong.',
            'content_id': 'C7', 'slide_id': 'SL1', 'element_id': 'C4-body',
            'display_text': QUALIFICATION,
        }
        for field, value in mutations.items():
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'demo_qualification'):
                demo._validate_qualification(result.adaptation,
                                             (replace(binding, **{field: value}),), composition)
        for bindings in ((), (binding, binding)):
            with self.assertRaisesRegex(ValueError, 'demo_qualification'):
                demo._validate_qualification(result.adaptation, bindings, composition)

    def test_architecture_import_and_git_hygiene(self):
        source = (ROOT / 'src/presentation_agent/milestone2_demo.py').read_text()
        tree = ast.parse(source)
        imports = [n.module or '' for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        self.assertNotIn('models', imports)
        self.assertNotIn('build', imports)
        self.assertNotIn('evidence.json', source)
        # Reviewable import allowlist excludes network, model and inference SDKs.
        self.assertEqual(set(imports), {
            'dataclasses', 'pathlib', 'tempfile', 'typing', 'compose', 'evidence',
            'evidence_verification', 'milestone1_adapter', 'pptx_renderer', 'qa',
            'quantities', 'source_capture', 'validate',
        })
        self.assertEqual({alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
                          for alias in node.names}, {'argparse', 'json', 'os'})
        for name in ('evidence', 'source_capture', 'source_extraction', 'evidence_verification', 'quantities'):
            text = (ROOT / 'src/presentation_agent' / (name + '.py')).read_text()
            self.assertNotIn('milestone1_adapter', text)
            self.assertNotIn('milestone2_demo', text)
        for path in (ROOT / 'src/presentation_agent').glob('*.py'):
            if path.name == 'pptx_renderer.py':
                continue
            parsed = ast.parse(path.read_text())
            for node in ast.walk(parsed):
                if isinstance(node, ast.ImportFrom):
                    self.assertFalse(node.level == 0 and
                                     (node.module or '').split('.')[0] == 'pptx')
                elif isinstance(node, ast.Import):
                    self.assertFalse(any(n.name.split('.')[0] == 'pptx' for n in node.names))
        # Reload restores imports after the guard; otherwise the module retains
        # the mocked renderer and contaminates subsequent integration tests.
        self.addCleanup(importlib.reload, demo)
        with patch.object(demo.SourceStore, 'capture', side_effect=AssertionError('capture on import')), \
                patch('presentation_agent.pptx_renderer.render', side_effect=AssertionError('render on import')), \
                patch.object(Path, 'read_text', side_effect=AssertionError('read on import')), \
                patch('builtins.open', side_effect=AssertionError('open on import')):
            importlib.reload(demo)
        result = subprocess.run(['git', 'check-ignore', '.runtime/snapshots/example',
                                 'output/milestone2_phase2d2/deck.pptx'], cwd=ROOT,
                                capture_output=True, text=True, check=True)
        self.assertEqual(len(result.stdout.splitlines()), 2)
        tracked = subprocess.run(['git', 'ls-files', '.runtime', 'output'], cwd=ROOT,
                                 capture_output=True, text=True, check=True)
        self.assertEqual(tracked.stdout, '')


if __name__ == '__main__':
    unittest.main()
