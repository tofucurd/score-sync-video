"""Suppress Verovio beam ink whose source notes are all explicitly hidden.

MusicXML print-object=no can hide the note groups while leaving their parent
beam polygon visible. Preserve every source event and all native geometry.
"""
import re
from fractions import Fraction
from xml.etree import ElementTree as ET


def suppress_hidden_beams(svg, events):
    hidden = {e['id'] for e in events if e.get('visible') is False}
    root = ET.fromstring(svg)
    changes = []
    for beam in root.iter():
        if beam.get('class') != 'beam' or beam.get('visibility') == 'hidden':
            continue
        members = [n for n in beam.iter() if n.get('class') in ('note', 'rest')]
        if not members or not all(n.get('id') in hidden and n.get('visibility') == 'hidden' for n in members):
            continue
        # Do not hide an unrelated control or a separately visible shared group.
        if any(n.get('visibility') == 'visible' for n in beam.iter()):
            continue
        beam_id = beam.get('id')
        if not beam_id:
            continue
        pattern = r'<g\b(?=[^>]*\bid="' + re.escape(beam_id) + r'")[^>]*>'
        def hide(match):
            tag = match.group(0)
            if re.search(r'\bvisibility=', tag):
                raise ValueError(f'Unexpected beam visibility on {beam_id}')
            return tag[:-1] + ' visibility="hidden">'
        svg, count = re.subn(pattern, hide, svg)
        if count != 1:
            raise ValueError(f'Ambiguous native beam identity: {beam_id}')
        changes.append({'beam_id': beam_id, 'member_ids': [n.get('id') for n in members],
                        'reason': 'All source events and native note/rest groups explicitly hidden'})
    return svg, changes


def suppress_hidden_spanners(svg, events, mei):
    """Hide slurs/ties belonging wholly to hidden events of one staff/voice.

Hidden endpoints alone are insufficient: retain any span containing a visible
event, unresolved reference, chord-level reference or mixed voice/staff.
"""
    by_id = {e['id']: e for e in events}
    native = {n.get('id'): n for n in ET.fromstring(svg).iter() if n.get('id')}
    mei_root = ET.fromstring(mei)
    xmlid = '{http://www.w3.org/XML/1998/namespace}id'
    changes = []
    for control in mei_root.iter():
        kind = control.tag.rsplit('}', 1)[-1]
        if kind not in ('slur', 'tie'):
            continue
        endpoints = [control.get(k, '').removeprefix('#') for k in ('startid', 'endid')]
        if not all(i in by_id and i in native and by_id[i].get('visible') is False
                   and native[i].get('visibility') == 'hidden' for i in endpoints):
            continue
        first, last = (by_id[i] for i in endpoints)
        if (first['staff'], first['voice']) != (last['staff'], last['voice']):
            continue
        a, b = Fraction(*first['q']), Fraction(*last['q'])
        if b < a or any(e.get('visible', True) for e in events
                        if (e['staff'], e['voice']) == (first['staff'], first['voice'])
                        and a <= Fraction(*e['q']) <= b):
            continue
        control_id = control.get(xmlid)
        node = native.get(control_id)
        if node is None or node.get('class') != kind or node.get('visibility') == 'hidden':
            continue
        if any(n.get('visibility') == 'visible' for n in node.iter()):
            continue
        pattern = r'<g\b(?=[^>]*\bid="' + re.escape(control_id) + r'")[^>]*>'
        def hide(match):
            tag = match.group(0)
            if re.search(r'\bvisibility=', tag):
                raise ValueError(f'Unexpected spanner visibility on {control_id}')
            return tag[:-1] + ' visibility="hidden">'
        svg, count = re.subn(pattern, hide, svg)
        if count != 1:
            raise ValueError(f'Ambiguous native spanner identity: {control_id}')
        changes.append({'control_id': control_id, 'kind': kind, 'endpoints': endpoints,
                        'reason': 'Same staff/voice span wholly hidden in source and native SVG'})
    return svg, changes
