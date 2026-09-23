"""Category A only: no claims about visual rendering or communication quality."""
import re
from .compose import compose
from .models import canonical, semantic_manifest
from .pptx_renderer import inspect_pptx
from .validate import validate, citation_sources


def structural_qa(inputs, composition, path, rebuilt_path=None):
    validate(inputs)
    observed = inspect_pptx(path)
    checks = {}
    checks['six_slides'] = len(observed['slides']) == len(composition['slides']) == 6
    checks['validated_ids_references_calculations'] = True
    checks['semantic_rebuild_equivalence'] = canonical(semantic_manifest(inputs, composition)) == canonical(semantic_manifest(inputs, compose(inputs)))
    checks['successful_programmatic_reopen'] = True
    if rebuilt_path is not None:
        checks['rendered_rebuild_equivalence'] = observed == inspect_pptx(rebuilt_path)
    text_ok = chart_ok = bounds_ok = citations_ok = geometry_ok = typography_ok = ids_ok = True
    mapping = {}
    evidence = {e['id']: e for e in inputs['evidence']['evidence']}
    charts = {c['id']: c for c in inputs['content']['charts']}
    visible_mapping = {}
    references = {}
    for slide, actual in zip(composition['slides'], observed['slides']):
        ids_ok &= len(actual) == len(slide['elements']) and [e['id'] for e in actual] == [e['id'] for e in slide['elements']]
        mapping[slide['id']] = {}
        for spec, got in zip(slide['elements'], actual):
            x, y, w, h = spec['box']
            bounds_ok &= x >= 0 and y >= 0 and w > 0 and h > 0 and x+w <= composition['width'] and y+h <= composition['height']
            gx, gy, gw, gh = got['box']
            bounds_ok &= gx >= 0 and gy >= 0 and gx+gw <= observed['width']+2e-6 and gy+gh <= observed['height']+2e-6
            geometry_ok &= all(abs(a-b) < 2e-6 for a,b in zip(spec['box'],got['box']))
            if spec['kind'] == 'text':
                text_ok &= got['kind'] == 'text' and got.get('text') == spec['text']
                typography_ok &= all(f == spec['font'] for f in got.get('fonts', [])) and all(s == spec['size'] for s in got.get('sizes', []))
                typography_ok &= got['bold'] == [spec.get('bold', False) or (spec['bold_first_paragraph'] and i == 0) for i in range(len(got['bold']))]
            elif spec['kind'] == 'rule':
                geometry_ok &= got['kind'] == 'rule' and got['color'] == spec['color']
            else:
                expected_chart = charts[spec['id']]
                chart_ok &= got['kind'] == 'chart' and got['embedded_workbook'] and got['categories'] == spec['categories'] == expected_chart['categories'] and got['values'] == spec['values'] == [evidence[i]['value'] for i in expected_chart['evidence_ids']]
                cells = got['workbook_cells']
                chart_ok &= cells == {'B1': spec['series_name'], 'A2': spec['categories'][0], 'A3': spec['categories'][1], 'B2': spec['values'][0], 'B3': spec['values'][1]}
                chart_ok &= got['series_name'] == spec['series_name'] == spec['unit']
                chart_ok &= got['title'] == spec['title'] + ' (' + spec['unit'] + ')'
                chart_ok &= got['chart_type'] == 51 and spec['style']['type'] == 'column'
                chart_ok &= got['axis_min'] == spec['style']['axis_min'] == 0
                chart_ok &= got['axis_max'] == spec['style']['axis_max'] and got['axis_step'] == spec['style']['axis_step']
                chart_ok &= got['label_format'] == spec['style']['label_format'] == '0" min/case"'
                typography_ok &= got['font'] == spec['font']
            if 'evidence_ids' in spec:
                expected = citation_sources(inputs, spec['evidence_ids'])
                citations_ok &= spec['source_ids'] == expected
                mapping[slide['id']][spec['id']] = expected
            expected_visible = spec.get('visible_citation_ids', [])
            actual_visible = re.findall(r'\[([^]\n]+)\]', got.get('text', ''))
            citations_ok &= actual_visible == expected_visible
            visible_mapping.setdefault(slide['id'], {})[spec['id']] = actual_visible
            if 'reference_source_id' in spec:
                references[spec['id']] = spec['reference_source_id']
    cited = {source for entries in mapping.values() for sources in entries.values() for source in sources}
    citations_ok &= cited <= set(references.values())
    checks.update(editable_text_matches_composition=text_ok, native_editable_chart_matches_validated_data=chart_ok, geometry_within_bounds=bounds_ok, rendered_geometry_matches=geometry_ok, typography_matches=typography_ok, element_ids_match=ids_ok, citation_mapping=citations_ok)
    return {'category':'A — structural correctness', 'passed':all(checks.values()), 'checks':checks, 'evidence_source_relationships':mapping, 'visible_citation_markers':visible_mapping, 'reference_entries':references, 'human_rendering_review':'PENDING — Microsoft PowerPoint for macOS', 'human_communication_review':'PENDING'}
