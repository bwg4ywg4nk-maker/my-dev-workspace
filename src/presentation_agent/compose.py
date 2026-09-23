"""Six fixture-scoped communication strategies, resolved to renderer-neutral geometry."""
from .validate import validate, citation_sources

STRATEGIES = dict(hero='hero_metric', context='structured_framework',
                  comparison='direct_comparison', chart='quantitative_evidence',
                  interpretation='evidence_to_interpretation', references='references')
ROLES = dict(C1='decision_qualification', C2='decision', C3='scope', C4='criteria',
             C5='comparison', C6='comparison', C7='sampling_qualification',
             C8='observed_finding', C9='interpretation', C10='limits')


def compose(data):
    validate(data)
    theme = data['theme']
    items = {x['id']: x for x in data['content']['items']}
    evidence = {x['id']: x for x in data['evidence']['evidence']}
    calculations = {x['id']: x for x in data['evidence']['calculations']}
    result = dict(schema_version=3, units=dict(geometry='inches', font_size='points'),
                  width=theme['width'], height=theme['height'], theme=theme, slides=[])
    for number, plan in enumerate(data['presentation_plan']['slides'], 1):
        layout = plan['layout']
        # Intent and hierarchy are semantic; no renderer objects enter this boundary.
        hierarchy = [dict(content_id=id, role=ROLES.get(id, 'support'),
                          level=1 if id in ('C2', 'C5', 'C6', 'C8') else 2)
                     for id in plan['content_ids']]
        slide = dict(id=plan['id'], layout=layout, principal_message=plan['principal_message'],
                     content_ids=plan['content_ids'], visual_intent=plan['purpose'],
                     strategy=STRATEGIES[layout], hierarchy=[dict(element_id='title', role='principal_message', level=0)]+hierarchy, relationships=[], elements=[])

        def provenance(ids, visible=False):
            sources = citation_sources(data, ids)
            return dict(evidence_ids=ids, source_ids=sources, visible_citation_ids=sources if visible else [])

        def text(id, value, box, size=18, color='ink', **extra):
            slide['elements'].append(dict(id=id, kind='text', text=value, box=box,
                font=theme['font'], size=size, color=theme['colors'][color],
                paragraph_space_after=0, bold_first_paragraph=False, **extra))

        def rule(id, box):
            slide['elements'].append(dict(id=id, kind='rule', box=box, color='CBD4DE'))

        text('label', 'SYNTHETIC EVIDENCE • OFFLINE DEMONSTRATION', [.6,.25,12.1,.25], 12, 'accent')
        text('title', plan['principal_message'], [.6,.82,12.1,1.0], 28,
             bold=True, role='principal_message', **provenance(plan['evidence_ids']))

        # Roles choose slots, while the plan remains authoritative for selection/order.
        slots = {
            'hero': {'C1': [.6,4.55,11.9,1.0], 'C7': [.6,6.0,11.9,.65]},
            'context': {'C2': [.6,2.05,11.9,1.0], 'C3': [.6,3.65,4.7,2.2], 'C4': [6.2,3.65,6.0,2.3]},
            'comparison': {'C5': [.9,2.1,5.3,2.9], 'C6': [7.0,2.1,5.3,2.9], 'C7': [.9,5.7,11.4,.9]},
            'chart': {'C8': [8.6,2.1,4.0,1.8], 'C7': [8.6,4.5,4.0,1.8]},
            'interpretation': {'C8': [1.2,1.95,11.1,1.0], 'C9': [1.2,3.35,11.1,1.0],
                               'C10': [1.2,4.75,11.1,1.25], 'C7': [1.2,6.15,11.1,.55]},
            'references': {},
        }[layout]
        for index, id in enumerate(plan['content_ids']):
            c = items[id]
            x,y,w,h = slots.get(id, [.6,2+index*1.15,11.9,1.05])
            role = ROLES.get(id, 'support')
            links = dict(derived_from_content_id=id, **provenance(c['evidence_ids']))
            markers = ' '.join('['+s+']' for s in links['source_ids'])
            # The content anchor preserves verbatim source wording, even where the
            # display is a validated quantitative projection into separate elements.
            text(id, markers, [x,y+h-.2,w,.22], 12, 'muted', content_id=id,
                 source_text=c['text'], role=role, **provenance(c['evidence_ids'], True))
            heading = {'C8':'OBSERVED FINDING', 'C10':'WHAT THE EVIDENCE DOES NOT ESTABLISH'}.get(id, c['title'].upper())
            if id == 'C1' and layout == 'hero':
                text(id+'-body', c['text'], [x,y,w,.8], 24, **links)
            elif id == 'C7':
                text(id+'-body', c['text'], [x,y,w,h-.23], 16, **links)
                slide['relationships'].append(dict(type='qualifies', source=id,
                    targets=[i for i in plan['content_ids'] if i != id], scope='slide'))
            elif id in ('C5','C6') and layout == 'comparison':
                ev = evidence[c['evidence_ids'][0]]
                text(id+'-heading', c['title'].upper(), [x,y,w,.3], 16, bold=True, **links)
                text(id+'-value', f'{ev["value"]:g}', [x,y+.5,2.2,1.0], 64, 'accent', role='primary_quantity', **links)
                text(id+'-unit', 'min/case', [x+2.25,y+1.0,2.8,.4], 22, **links)
                text(id+'-sample', f'n = {ev["sample_size"]}', [x,y+1.85,w,.4], 22, **links)
                text(id+'-detail', c['text'].split('. ',1)[1], [x,y+2.35,w,.3], 14, 'muted', **links)
            else:
                text(id+'-heading', heading, [x,y,w,.28], 13, 'accent', bold=True, **links)
                body = c['text']
                size = 20 if id == 'C2' else 18
                if id == 'C8':
                    body = f'{calculations["D2"]["value"]:g} fewer min/case • {calculations["D1"]["value"]:g}% lower than A'
                    size = 26 if layout == 'interpretation' else 28
                if id == 'C4' and layout == 'context' and '. ' in body:
                    measured, unmeasured = body.split('. ',1)
                    text(id+'-body', measured+'.', [x,y+.45,w,.9], size, **links)
                    text(id+'-unmeasured', unmeasured, [x,y+1.5,w,.6], 18, 'muted', bold=True, role='unmeasured', **links)
                else:
                    text(id+'-body', body, [x,y+.38,w,h-.6], size,
                         role='primary_quantity' if id == 'C8' else role, **links)

        if layout == 'hero':
            metric = next(m for m in data['content']['metrics'] if m['id'] == plan['metric_id'])
            calc = calculations[metric['calculation_id']]
            slide['hierarchy'].append(dict(element_id='metric', role='primary_quantity', level=1))
            suffix = '%' if calc['unit'] == 'percent' else ' '+calc['unit']
            text('metric', f'{calc["value"]:g}'+suffix, [.6,2.0,5.6,1.4],
                 88 if calc['unit']=='percent' else 32, 'accent', role='primary_quantity',
                 metric_id=metric['id'], unit=calc['unit'], **provenance(metric['evidence_ids']))
            markers = ' '.join('['+s+']' for s in citation_sources(data,metric['evidence_ids']))
            text('metric-label', metric['label']+' '+markers, [.65,3.5,5.6,.8], 18, **provenance(metric['evidence_ids'],True))
            a,b = [evidence[i] for i in calc['input_ids']]
            text('metric-context', f'{a["value"]:g} → {b["value"]:g} min/case', [7,2.45,5.2,.7], 32,
                 role='metric_context', **provenance(calc['input_ids']))
            text('metric-context-label', 'APPROACH A → APPROACH B', [7,3.25,5.2,.3], 13, 'muted', **provenance(calc['input_ids']))
            rule('decision-rule', [.6,4.3,12,.015])
            slide['relationships'].append(dict(type='metric_to_context', source='metric', targets=['metric-context']))
        elif layout == 'context':
            rule('decision-rule', [.6,3.3,12,.015])
            rule('scope-criteria-rule', [5.65,3.65,.015,2.5])
            slide['relationships'].append(dict(type='decision_scope_criteria', targets=plan['content_ids']))
        elif layout == 'comparison':
            rule('comparison-rule', [6.55,2.1,.015,2.95])
            rule('shared-qualification-rule', [.9,5.4,11.4,.015])
        elif layout == 'chart':
            c = next(c for c in data['content']['charts'] if c['id'] == plan['chart_id'])
            values = [evidence[i]['value'] for i in c['evidence_ids']]
            slide['elements'].append(dict(id=c['id'], kind='chart', box=[.6,2,7.5,4.55],
                title=c['title'], unit=c['unit'], series_name=c['unit'], categories=c['categories'],
                values=values, sample_sizes=[evidence[i]['sample_size'] for i in c['evidence_ids']],
                **provenance(c['evidence_ids']), font=theme['font'], style=dict(type='column',
                    axis_min=0, axis_max=max(15,max(values)*1.25), axis_step=3, axis_size=14,
                    title_size=16, label_size=22, label_format='0" min/case"',
                    grid_color='DDE3EA', axis_color='A9B5C4', gap_width=140,
                    point_colors=[theme['colors']['muted'], theme['colors']['accent']])))
            text('chart-citations', ' '.join('['+s+']' for s in citation_sources(data,c['evidence_ids'])),
                 [.9,6.55,6,.25],12,'muted', **provenance(c['evidence_ids'],True))
            rule('evidence-rail', [8.3,2,.015,4.5])
        elif layout == 'interpretation':
            chain = [i for i in ('C8','C9','C10') if i in plan['content_ids']]
            slide['relationships'].append(dict(type='evidence_to_interpretation_to_limits', targets=chain))
            for i,(first,second) in enumerate(zip(chain,chain[1:])):
                text('flow-'+str(i), '↓', [.63,slots[first][1]+1.05,.4,.35], 20, 'muted',
                     relationship=dict(source=first,target=second))
        elif layout == 'references':
            sources = {s['id']:s for s in data['evidence']['sources']}
            for i,id in enumerate(plan['source_ids']):
                s = sources[id]
                y = 2.1+i*1.4
                text(id, '['+id+']', [.6,y,1,.4], 22, 'accent', bold=True,
                     reference_source_id=id,visible_citation_ids=[id])
                text(id+'-title', s['title'], [2,y,10.5,.4], 22, bold=True)
                text(id+'-detail', s['detail'], [2,y+.53,10.5,.55], 17, 'muted')
                rule(id+'-rule', [.6,y+1.16,12,.012])
        text('footer', f'Synthetic fixture • Not real-world evidence                                      {number} / 6', [.6,7,12.1,.25],12,'muted')
        result['slides'].append(slide)
    return result
