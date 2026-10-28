"""Optional, source-bound full-movement vocal and material presentation inputs.

The render clock and native geometry remain authoritative. These layers never
infer lyrics, translations, themes or musical boundaries from a preview window.
"""
from pathlib import Path
import hashlib
import json
import re


def semantic_digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def check_sources(data, directory):
    bindings = data.get('source_hashes', {})
    if not bindings:
        raise ValueError('Presentation layer requires source_hashes')
    bound = set()
    for record in bindings.values():
        path = (directory / record['path']).resolve()
        path.relative_to(directory.resolve())
        if hashlib.sha256(path.read_bytes()).hexdigest() != record['sha256']:
            raise ValueError('Presentation source changed: ' + record['path'])
        bound.add(path.name)
    if not {'score.json', 'geometry.json', 'alignment.json'} <= bound:
        raise ValueError('Bind score.json, geometry.json and alignment.json')


def load_layers(directory, geometry):
    """Return optional scene payload and additional text for font subsetting."""
    d = Path(directory)
    payload, text = {}, []
    staff_ids = {s['id'] for s in geometry['staves']}
    note_ids = {n['id'] for n in geometry['notes']}
    path = d / 'staff-signatures.json'
    if path.exists():
        data = read(path)
        check_sources(data, d)
        for staff, row in data['staves'].items():
            if staff not in staff_ids:
                raise ValueError('Unknown signature staff: ' + staff)
            events = row['events']
            if any(b['q'] <= a['q'] for a, b in zip(events, events[1:])):
                raise ValueError('Signature events must follow the performed route')
            text.extend(e.get('pitch_label', '') for e in events)
        text.append('（）0123456789')
        payload['staff_signatures'] = data
    path = d / 'score-locators.json'
    if path.exists():
        data = read(path)
        check_sources(data, d)
        measures = {m['index']: m for m in geometry['measures']}
        for item in data['items']:
            native = measures.get(item['performed_index'])
            if native is None or any(native[k] != item[k] for k in ('source_index', 'occurrence', 'q')):
                raise ValueError('Locator source/route changed')
            if not native['x'] <= item['native_x'] <= native['x'] + native['width']:
                raise ValueError('Locator outside native measure')
            text.append(item['text'])
        payload['score_locators'] = data
    path = d / 'presentation.json'
    if path.exists():
        data = read(path)
        if not data['duration_seconds'] > 0 or not 0 <= data['initial_phase'] <= 1:
            raise ValueError('Invalid opening presentation policy')
        payload['presentation'] = data
    vocal = d / 'vocals'
    if vocal.exists():
        timeline, schedule, layout = [read(vocal / name) for name in
                                     ('timeline.json', 'cohort-schedule.json', 'layout-schedule.json')]
        check_sources(timeline, d)
        windows = schedule['panel_presence']['windows']
        previous_window = None
        minimum_gap = schedule['panel_presence'].get('minimum_fully_hidden_seconds', 15)
        for window in windows:
            points = [window[k] for k in ('enter_start', 'enter_end', 'exit_start', 'exit_end')]
            if not all(a < b for a, b in zip(points, points[1:])):
                raise ValueError('Panel window must have ordered entry/exit times')
            if previous_window and window['enter_start'] - previous_window['exit_end'] < minimum_gap:
                raise ValueError('Panel closes too briefly; join the full-movement windows')
            previous_window = window
        inputs = schedule['compile_inputs']
        for key, value in [('full_timeline', timeline), ('panel_entries', schedule['panel_entries']),
                           ('panel_presence', schedule['panel_presence'])]:
            if inputs[key] != semantic_digest(value):
                raise ValueError('Vocal schedule input changed: ' + key)
        for key, value in [('full_timeline', timeline), ('cohort_schedule', schedule)]:
            if layout['compile_inputs'][key] != semantic_digest(value):
                raise ValueError('Vocal layout input changed: ' + key)
        if {c['id'] for c in layout['cohorts']} != {c['id'] for c in schedule['cohorts']}:
            raise ValueError('Vocal layout/cohort identities differ')
        voice_ids = set()
        phrase_ids = set()
        for lane in timeline['lanes']:
            if lane['id'] not in staff_ids or lane['id'] in voice_ids:
                raise ValueError('Unknown or duplicate vocal staff: ' + lane['id'])
            voice_ids.add(lane['id'])
            if lane.get('family') not in ('solo', 'choir'):
                raise ValueError('Vocal family must explicitly be solo or choir')
            text.append(lane['label'])
            previous = None
            for phrase in lane['phrases']:
                if phrase['id'] in phrase_ids or not phrase['end'] > phrase['start']:
                    raise ValueError('Invalid vocal phrase identity/interval')
                phrase_ids.add(phrase['id'])
                if phrase['continuity_from_previous']:
                    if previous is None or abs(phrase['preview_at'] - previous['start']) > 1/timeline['sample_rate']:
                        raise ValueError('Continuous next phrase must preview at the previous onset')
                for segment in phrase['segments']:
                    if phrase['de'][segment['start_char']:segment['end_char']] != segment['text']:
                        raise ValueError('Vocal source character interval mismatch')
                text.extend([phrase['de'], phrase['zh']])
                previous = phrase
        for cohort in schedule['cohorts']:
            for phase in cohort['phases']:
                text.extend(group['label'] for group in phase['groups'])
        payload['vocalProgramme'] = {'timeline': timeline, 'schedule': schedule, 'layout': layout}
        payload['vocal_note_staves'] = {n['id']: n['staff'] for n in geometry['notes'] if n['staff'] in voice_ids}
    path = d / 'material-regions.json'
    if path.exists():
        data = read(path)
        check_sources(data, d)
        palette = data['palette']
        if any(not re.fullmatch(r'#[0-9A-Fa-f]{6}', c) for c in palette.values()):
            raise ValueError('Material colors must be six-digit hex')
        for region in data['regions']:
            if region['staff'] not in staff_ids or region['theme'] not in palette or not region['end_x'] > region['start_x']:
                raise ValueError('Unknown staff/theme or invalid material interval')
        for identity, theme in data['assignments'].items():
            if identity not in note_ids or theme not in palette:
                raise ValueError('Material assignment has unknown event/theme: ' + identity)
        if not set(palette) <= set(data['short_names']):
            raise ValueError('Every material needs a short name')
        payload['material_regions'] = data
        text.extend(data['short_names'].values())
    return payload, ''.join(text)
