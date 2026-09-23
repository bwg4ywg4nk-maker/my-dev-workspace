import ast
from io import BytesIO
from zipfile import ZipFile
from xml.etree import ElementTree as ET
import copy
from pathlib import Path
import tempfile
import unittest
from presentation_agent.models import load_inputs, canonical, semantic_manifest
from presentation_agent.validate import validate, ValidationError
from presentation_agent.compose import compose
from presentation_agent.pptx_renderer import render, inspect_pptx
from presentation_agent.qa import structural_qa

ROOT = Path(__file__).resolve().parents[1]

class MilestoneOneTests(unittest.TestCase):
    def setUp(self):
        self.inputs = load_inputs(ROOT)

    def test_expected_calculation(self):
        validate(self.inputs)
        self.assertEqual(self.inputs['evidence']['calculations'][0]['value'],25)
        self.assertEqual((12-9)/12*100,25)

    def test_reject_incorrect_calculation(self):
        self.inputs['evidence']['calculations'][0]['value'] = 24
        with self.assertRaisesRegex(ValidationError,'Incorrect calculation'):
            validate(self.inputs)

    def test_reject_missing_citation(self):
        self.inputs['evidence']['sources'].pop(0)
        with self.assertRaisesRegex(ValidationError,'Missing citation target'):
            validate(self.inputs)

    def test_reject_duplicate_ids(self):
        self.inputs['content']['items'][0]['id'] = 'E1'
        with self.assertRaisesRegex(ValidationError,'unique'):
            validate(self.inputs)

    def test_reject_missing_claim_evidence(self):
        self.inputs['content']['items'][0]['evidence_ids'] = ['missing']
        with self.assertRaisesRegex(ValidationError,'Unresolved claim'):
            validate(self.inputs)

    def test_preserve_content_and_qualifications(self):
        before = copy.deepcopy(self.inputs)
        composition = compose(self.inputs)
        self.assertEqual(before,self.inputs)
        items = {c['id']:c for c in self.inputs['content']['items']}
        for slide in composition['slides']:
            self.assertEqual(slide['content_ids'],[e['content_id'] for e in slide['elements'] if 'content_id' in e])
            for e in slide['elements']:
                if 'content_id' in e:
                    self.assertEqual(items[e['content_id']]['text'], e['source_text'])
                    displayed = '\n'.join(part.get('text', '') for part in slide['elements'] if part['id'].startswith(e['content_id']+'-'))
                    if e['content_id'] not in ('C5', 'C6', 'C8'):
                        self.assertIn(items[e['content_id']]['text'], ' '.join(displayed.split()))
        self.assertEqual([s['id'] for s in composition['slides']],['SL1','SL2','SL3','SL4','SL5','SL6'])

    def test_communication_strategies_and_hierarchy(self):
        slides = compose(self.inputs)['slides']
        self.assertEqual([s['strategy'] for s in slides], [
            'hero_metric', 'structured_framework', 'direct_comparison',
            'quantitative_evidence', 'evidence_to_interpretation', 'references'])
        hero = {e['id']: e for e in slides[0]['elements']}
        self.assertEqual(sum(e.get('text', '').count(slides[0]['principal_message'])
                             for e in hero.values()), 1)
        self.assertGreater(hero['metric']['size'], hero['title']['size'])
        self.assertEqual(hero['metric-context']['text'], '12 → 9 min/case')
        self.assertIn('not a rollout decision', hero['C1-body']['text'])
        comparison = {e['id']: e for e in slides[2]['elements']}
        for id, value in [('C5', '12'), ('C6', '9')]:
            self.assertEqual(comparison[id+'-value']['text'], value)
            self.assertEqual(comparison[id+'-unit']['text'], 'min/case')
            self.assertEqual(comparison[id+'-sample']['text'], 'n = 30')
            self.assertGreater(comparison[id+'-value']['size'], comparison[id+'-sample']['size'])
            self.assertEqual(comparison[id+'-value']['role'], 'primary_quantity')
        qualification = next(r for r in slides[2]['relationships'] if r['type']=='qualifies')
        self.assertEqual(qualification['targets'], ['C5', 'C6'])
        self.assertGreater(comparison['C7-body']['box'][2], comparison['C5-value']['box'][2])
        criteria = next(e for e in slides[1]['elements'] if e['id']=='C4-unmeasured')
        self.assertEqual(criteria['text'], 'Quality and cost remain unmeasured.')
        self.assertEqual(criteria['role'], 'unmeasured')

    def test_concise_calculations_and_epistemic_boundaries(self):
        slides = compose(self.inputs)['slides']
        for index in (3, 4):
            finding = next(e for e in slides[index]['elements'] if e['id']=='C8-body')
            self.assertEqual(finding['text'], '3 fewer min/case • 25% lower than A')
            self.assertEqual(finding['evidence_ids'], ['E1','E2','D1','D2'])
            anchor = next(e for e in slides[index]['elements'] if e['id']=='C8')
            self.assertIn('(12 − 9) / 12 × 100 = 25%', anchor['source_text'])
        slide = slides[4]
        self.assertIn(dict(type='evidence_to_interpretation_to_limits',
                           targets=['C8','C9','C10']), slide['relationships'])
        elements = {e['id']: e for e in slide['elements']}
        self.assertEqual([elements[id]['role'] for id in ('C8','C9','C10')],
                         ['observed_finding','interpretation','limits'])
        self.assertLess(elements['C8-body']['box'][1], elements['C9-body']['box'][1])
        self.assertLess(elements['C9-body']['box'][1], elements['C10-body']['box'][1])
        self.assertIn('cannot establish causality, statistical significance', elements['C10-body']['text'])
        self.assertEqual(elements['C7-body']['text'], self.inputs['content']['items'][6]['text'])

    def test_display_fragments_keep_selected_claim_provenance(self):
        for slide in compose(self.inputs)['slides']:
            anchors = {e['content_id']: e for e in slide['elements'] if 'content_id' in e}
            for element in slide['elements']:
                if 'derived_from_content_id' in element:
                    anchor = anchors[element['derived_from_content_id']]
                    self.assertEqual(element['evidence_ids'], anchor['evidence_ids'])
                    self.assertEqual(element['source_ids'], anchor['source_ids'])
            for anchor in anchors.values():
                self.assertEqual(anchor['size'], 12)
                self.assertTrue(anchor['visible_citation_ids'])

    def test_unselected_claims_do_not_leak_into_composition(self):
        for index in range(5):
            data = copy.deepcopy(self.inputs)
            data['presentation_plan']['slides'][index]['content_ids'] = ['C10']
            slide = compose(data)['slides'][index]
            self.assertEqual({e['derived_from_content_id'] for e in slide['elements']
                              if 'derived_from_content_id' in e}, {'C10'})
            self.assertNotIn('C7', [r.get('source') for r in slide['relationships']])

    def test_semantic_equivalence(self):
        first = semantic_manifest(self.inputs,compose(self.inputs))
        again = load_inputs(ROOT)
        self.assertEqual(canonical(first),canonical(semantic_manifest(again,compose(again))))

    def test_theme_independence(self):
        original = copy.deepcopy(self.inputs)
        self.inputs['theme']['colors']['accent'] = '335577'
        compose(self.inputs)
        for key in ['evidence','content','presentation_plan']:
            self.assertEqual(original[key],self.inputs[key])

    def test_only_renderer_imports_pptx(self):
        for path in (ROOT/'src'/'presentation_agent').glob('*.py'):
            if path.name == 'pptx_renderer.py':
                continue
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node,ast.Import):
                    self.assertFalse(any(a.name.split('.')[0]=='pptx' for a in node.names))
                if isinstance(node,ast.ImportFrom):
                    self.assertNotEqual((node.module or '').split('.')[0],'pptx')

    def test_native_deck_reopen_and_rebuild(self):
        c = compose(self.inputs)
        with tempfile.TemporaryDirectory(dir=ROOT/'output'/'milestone1') as tmp:
            a,b = Path(tmp)/'a.pptx',Path(tmp)/'b.pptx'
            render(c,a)
            render(compose(load_inputs(ROOT)),b)
            report = structural_qa(self.inputs,c,a,b)
            self.assertTrue(report['passed'],report)
            self.assertEqual(report['evidence_source_relationships']['SL4']['CH1'],['S1','S2'])

    def test_qa_rejects_wrong_chart_data(self):
        c = compose(self.inputs)
        chart = next(e for e in c['slides'][3]['elements'] if e['kind']=='chart')
        chart['values'][1] = 8
        with tempfile.TemporaryDirectory(dir=ROOT/'output'/'milestone1') as tmp:
            path = Path(tmp)/'bad.pptx'
            render(c,path)
            self.assertFalse(structural_qa(self.inputs,c,path)['passed'])

    def test_independent_fixture_truth(self):
        ev = {e['id']: e for e in self.inputs['evidence']['evidence']}
        for id, value in [('E1', 12), ('E2', 9)]:
            self.assertEqual(ev[id]['value'], value)
            self.assertEqual(ev[id]['unit'], 'minutes per case')
            self.assertEqual(ev[id]['sample_size'], 30)
        calc = {c['id']: c for c in self.inputs['evidence']['calculations']}
        self.assertEqual((calc['D1']['value'], calc['D1']['unit']), (25, 'percent'))
        self.assertEqual((calc['D2']['value'], calc['D2']['unit']), (3, 'minutes per case'))
        self.assertEqual(calc['D2']['input_ids'], ['E1', 'E2'])

    def test_plan_order_and_selection_every_layout(self):
        for index in range(5):
            for selected in [list(reversed(self.inputs['presentation_plan']['slides'][index]['content_ids'])), ['C10']]:
                data = copy.deepcopy(self.inputs)
                data['presentation_plan']['slides'][index]['content_ids'] = selected
                slide = compose(data)['slides'][index]
                self.assertEqual([e['content_id'] for e in slide['elements'] if 'content_id' in e], selected)
                self.assertEqual([e['id'] for e in slide['elements'] if 'content_id' in e], selected)
        self.inputs['presentation_plan']['slides'][-1]['source_ids'] = ['S3', 'S1']
        self.assertEqual([e['reference_source_id'] for e in compose(self.inputs)['slides'][-1]['elements'] if 'reference_source_id' in e], ['S3', 'S1'])

    def test_chart_selection_and_calculation_id(self):
        chart = copy.deepcopy(self.inputs['content']['charts'][0])
        chart.update(id='CH2', categories=['Approach B', 'Approach A'], evidence_ids=['E2', 'E1'])
        self.inputs['content']['charts'].append(chart)
        self.inputs['presentation_plan']['slides'][3]['chart_id'] = 'CH2'
        self.inputs['evidence']['calculations'].reverse()
        c = compose(self.inputs)
        self.assertEqual(next(e for e in c['slides'][3]['elements'] if e['kind'] == 'chart')['values'], [9, 12])
        self.assertEqual(next(e for e in c['slides'][0]['elements'] if e['id'] == 'metric')['text'], '25%')

    def test_reject_16_12_with_stale_prose(self):
        self.inputs['evidence']['evidence'][0]['value'] = 16
        self.inputs['evidence']['evidence'][1]['value'] = 12
        with self.assertRaisesRegex(ValidationError, 'Incorrect calculation'):
            compose(self.inputs)
        self.inputs['evidence']['calculations'][1]['value'] = 4
        with self.assertRaisesRegex(ValidationError, 'Stale quantitative prose'):
            compose(self.inputs)
        # Even after updating claim values, stale source totals are rejected.
        self.inputs['content']['items'][4]['text'] = '16 minutes per case; n = 30. Synthetic pilot A log.'
        with self.assertRaisesRegex(ValidationError, 'Stale source detail'):
            compose(self.inputs)

    def test_reject_invalid_units_samples_and_values(self):
        for key, value in [('unit', 'seconds'), ('sample_size', 31), ('sample_size', True), ('value', -1), ('value', float('nan'))]:
            data = copy.deepcopy(self.inputs)
            data['evidence']['evidence'][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValidationError):
                validate(data)

    def test_quantitative_provenance(self):
        c = compose(self.inputs)
        for index, id, expected in [(0, 'title', ['E1','E2','D1']), (0, 'metric', ['D1']), (0, 'metric-label', ['D1']), (3, 'title', ['D1']), (3, 'C8', ['E1','E2','D1','D2'])]:
            element = next(e for e in c['slides'][index]['elements'] if e['id'] == id)
            self.assertEqual(element['evidence_ids'], expected)
            self.assertEqual(element['source_ids'], ['S1','S2'])
        self.assertEqual(c['units'], {'geometry': 'inches', 'font_size': 'points'})

    def test_independent_chart_contract(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'output'/'milestone1') as tmp:
            path = Path(tmp)/'deck.pptx'
            render(compose(self.inputs), path)
            chart = next(e for e in inspect_pptx(path)['slides'][3] if e['kind'] == 'chart')
            self.assertEqual(chart['values'], [12, 9])
            self.assertEqual(chart['categories'], ['Approach A', 'Approach B'])
            self.assertEqual(chart['workbook_cells'], {'B1': 'minutes per case', 'A2': 'Approach A', 'A3': 'Approach B', 'B2': 12, 'B3': 9})
            self.assertEqual(chart['series_name'], 'minutes per case')
            self.assertEqual(chart['title'], 'Mean handling time (minutes per case)')
            self.assertEqual(chart['chart_type'], 51)  # OOXML clustered column enum
            self.assertEqual(chart['axis_min'], 0)
            self.assertEqual(chart['axis_max'], 15)
            self.assertEqual(chart['label_format'], '0" min/case"')

    def test_qa_rejects_missing_extra_markers(self):
        for replacement in ['', '[S1] [S2]', '[S1] [S1]']:
            c = compose(self.inputs)
            claim = next(e for e in c['slides'][2]['elements'] if e['id'] == 'C5')
            claim['text'] = claim['text'].replace('[S1]', replacement)
            with tempfile.TemporaryDirectory(dir=ROOT/'output'/'milestone1') as tmp:
                path = Path(tmp)/'deck.pptx'
                render(c, path)
                self.assertFalse(structural_qa(self.inputs, c, path)['checks']['citation_mapping'])

    def test_semantic_drift_is_detected(self):
        c = compose(self.inputs)
        c['slides'][0]['elements'][1]['text'] = 'Unsupported conclusion'
        with tempfile.TemporaryDirectory(dir=ROOT/'output'/'milestone1') as tmp:
            path = Path(tmp)/'deck.pptx'
            render(c, path)
            report = structural_qa(self.inputs, c, path)
            self.assertFalse(report['checks']['semantic_rebuild_equivalence'])
            self.assertFalse(report['passed'])

    def test_unsupported_chart_type_rejected(self):
        c = compose(self.inputs)
        next(e for e in c['slides'][3]['elements'] if e['kind'] == 'chart')['style']['type'] = 'pie'
        with tempfile.TemporaryDirectory(dir=ROOT/'output'/'milestone1') as tmp:
            with self.assertRaisesRegex(ValueError, 'Only column'):
                render(c, Path(tmp)/'deck.pptx')

    def test_workbook_cache_mismatch_rejected(self):
        c = compose(self.inputs)
        with tempfile.TemporaryDirectory(dir=ROOT/'output'/'milestone1') as tmp:
            path = Path(tmp)/'deck.pptx'
            render(c, path)
            with ZipFile(path) as z:
                parts = {n: z.read(n) for n in z.namelist()}
            name = next(n for n in parts if n.startswith('ppt/embeddings/') and n.endswith('.xlsx'))
            with ZipFile(BytesIO(parts[name])) as z:
                workbook = {n: z.read(n) for n in z.namelist()}
            sheet = ET.fromstring(workbook['xl/worksheets/sheet1.xml'])
            ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            sheet.find(".//s:c[@r='B2']/s:v", ns).text = '16'
            workbook['xl/worksheets/sheet1.xml'] = ET.tostring(sheet)
            buffer = BytesIO()
            with ZipFile(buffer, 'w') as z:
                for n, blob in workbook.items():
                    z.writestr(n, blob)
            parts[name] = buffer.getvalue()
            with ZipFile(path, 'w') as z:
                for n, blob in parts.items():
                    z.writestr(n, blob)
            chart = next(e for e in inspect_pptx(path)['slides'][3] if e['kind'] == 'chart')
            self.assertEqual(chart['values'], [12, 9])
            self.assertEqual(chart['workbook_cells']['B2'], 16)
            self.assertFalse(structural_qa(self.inputs, c, path)['checks']['native_editable_chart_matches_validated_data'])

    def test_reject_stale_headline_takeaway_and_source(self):
        mutations = [('content', 'items', 7, 'text', 'B recorded 4 fewer minutes per case.'),
                     ('evidence', 'sources', 0, 'detail', 'Invented fixture; 30 cases; total handling time 480 minutes.'),
                     ('presentation_plan', 'slides', 3, 'principal_message', 'B recorded 30% lower mean handling time')]
        for group, collection, index, field, value in mutations:
            data = copy.deepcopy(self.inputs)
            data[group][collection][index][field] = value
            with self.subTest(field=field), self.assertRaises(ValidationError):
                validate(data)

    def test_metric_selection_is_authoritative(self):
        self.inputs['content']['metrics'].append(dict(id='M2', calculation_id='D2', label='lower mean handling time\nB versus A', evidence_ids=['D2']))
        self.inputs['presentation_plan']['slides'][0]['metric_id'] = 'M2'
        metric = next(e for e in compose(self.inputs)['slides'][0]['elements'] if e['id'] == 'metric')
        self.assertEqual(metric['text'], '3 minutes per case')
        self.assertEqual(metric['evidence_ids'], ['D2'])

    def test_reject_missing_quantitative_provenance(self):
        for collection, index in [('items', 7), ('items', 4)]:
            data = copy.deepcopy(self.inputs)
            data['content'][collection][index]['evidence_ids'] = ['E3']
            with self.assertRaises(ValidationError):
                validate(data)
        self.inputs['presentation_plan']['slides'][3]['evidence_ids'] = []
        with self.assertRaises(ValidationError):
            validate(self.inputs)

if __name__ == '__main__':
    unittest.main()
