"""Compile source-ledger guide content into the native-score presentation layer.

All times are absolute movement seconds. The input ledger remains in the output;
loading a compiled payload repeats source, coverage and identity validation.
This module uses only the standard library and never opens a browser.
"""
from __future__ import annotations
import bisect
import copy
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import re
from statistics import median
import xml.etree.ElementTree as ET

from .guide_connections import bound_connections, attach_routing_references
from .presentation_layers import check_sources


TIMING = {'full_lead_seconds': .8, 'extend_seconds': .65,
          'retract_seconds': .35, 'post_source_hold_seconds': .2,
          'page_ready_seconds': .7, 'panel_ready_seconds': .85}


def _read(path):
    return json.loads(Path(path).read_text())


def _number(value, name):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError(name + ' must be a finite number')
    return float(value)


def _q(value):
    return float(Fraction(*value)) if isinstance(value, list) else _number(value, 'score position')


def _identities(rows, name):
    result = {}
    for row in rows:
        identity = row.get('id')
        if not isinstance(identity, str) or not identity or identity in result:
            raise ValueError('Missing or duplicate ' + name + ' identity')
        result[identity] = row
    return result


def _interval(row, first, last, name, duration=None):
    a, b = _number(row[first], name), _number(row[last], name)
    if b <= a or (duration is not None and (a < 0 or b > duration + 1e-7)):
        raise ValueError('Invalid ' + name + ' interval')
    return a, b


def _clock(alignment):
    rate = _number(alignment['sample_rate'], 'sample rate')
    if rate <= 0:
        raise ValueError('Alignment sample rate must be positive')
    duration = _number(alignment['samples'], 'sample count') / rate
    points = alignment['points']
    if rate <= 0 or duration <= 0 or len(points) < 2:
        raise ValueError('Guide requires a complete alignment clock')
    points = [(_number(t, 'sample'), _q(q)) for t, q in points]
    if any(t2 <= t1 or q2 < q1 for (t1, q1), (t2, q2) in zip(points, points[1:])):
        raise ValueError('Alignment clock must be monotone')
    # Match visual.bundle's source-position interpolation, including last
    # sample at repeated positions (holds). No score-tempo clock is introduced.
    qs, ts = [p[1] for p in points], [p[0] / rate for p in points]
    def time_at(q):
        q = _q(q)
        if q < qs[0] - 1e-7 or q > qs[-1] + 1e-7:
            raise ValueError('Guide score position outside alignment')
        i = bisect.bisect_right(qs, q) - 1
        if i < 0:
            return ts[0]
        if i == len(qs) - 1:
            return ts[-1]
        return ts[i] + (ts[i+1] - ts[i]) * (q - qs[i]) / (qs[i+1] - qs[i])
    return time_at, duration


def _corrected_slice(unit, a, b):
    text, cursor, pieces = unit['text'], a, []
    for correction in unit.get('errata', []):
        x, y = correction['start'], correction['end']
        if y <= a or x >= b:
            continue
        if x < a or y > b:
            raise ValueError('Display source range splits an erratum')
        pieces.extend([text[cursor:x], correction['replacement']])
        cursor = y
    pieces.append(text[cursor:b])
    return ''.join(pieces)


def _compile_content(p):
    units = _identities(p.get('units', []), 'source unit')
    if not units:
        raise ValueError('Guide requires its complete source content units')
    coverage = {k: {'covered_ranges': [], 'display_occurrences': 0, 'provenance': u.get('provenance')}
                for k, u in units.items()}
    for unit in units.values():
        if not isinstance(unit.get('provenance'), dict) or not unit['provenance']:
            raise ValueError('Every source unit requires provenance')
        unit.setdefault('kind', 'text')
        unit.setdefault('text', '')
        if not isinstance(unit['text'], str) or (not unit['text'] and unit['kind'] != 'figure'):
            raise ValueError('Source text must be nonempty; use figure units for diagrams')
        previous = 0
        for correction in unit.get('errata', []):
            a, b = correction['start'], correction['end']
            if (not isinstance(a, int) or not isinstance(b, int) or a < previous or
                    not a < b <= len(unit['text']) or unit['text'][a:b] != correction['original'] or
                    not isinstance(correction.get('replacement'), str) or not correction.get('reason')):
                raise ValueError('Errata require exact original ranges, replacement and evidence reason')
            previous = b
    for i, block in enumerate(p['blocks']):
        if 'index' in block and block['index'] != i:
            raise ValueError('block.index must match its stable list index')
        block['index'] = i
        block.setdefault('id', 'block-' + str(i))
        block.setdefault('kind', 'text')
        if block['kind'] == 'image':
            raise ValueError('Guide figures must be translated to native notation, not PDF images')
        unit = units.get(block.get('unit_id'))
        if unit is None:
            raise ValueError('Every block must reference a known source unit')
        block['provenance'] = copy.deepcopy(unit['provenance'])
        block['errata'] = copy.deepcopy(unit.get('errata', []))
        ranges = block.get('display_ranges', [])
        if unit['kind'] == 'figure':
            if block['kind'] not in ('native_score', 'native_table', 'score_figure_reference'):
                raise ValueError('Figure unit requires a native figure translation')
            block.setdefault('text', unit['text'])
        else:
            if not ranges:
                raise ValueError('Text block requires exact display_ranges')
            pieces, previous = [], -1
            for pair in ranges:
                if not isinstance(pair, list) or len(pair) != 2:
                    raise ValueError('Display ranges must be [start,end] character offsets')
                a, b = pair
                if (not isinstance(a, int) or not isinstance(b, int) or a < previous or
                        not 0 <= a < b <= len(unit['text'])):
                    raise ValueError('Invalid display source interval')
                previous = b
                pieces.append(_corrected_slice(unit, a, b))
                coverage[unit['id']]['covered_ranges'].append([a, b])
            expected = ''.join(pieces)
            if 'text' in block and block['text'] != expected:
                raise ValueError('Displayed source text differs from exact source ranges and errata')
            block['text'] = expected
        coverage[unit['id']]['display_occurrences'] += 1
    _identities(p['blocks'], 'block')
    represented_figures = {b['unit_id'] for b in p['blocks'] if b['kind'] in ('native_score', 'native_table')}
    represented_figures.update(c.get('source_unit_id') for c in p.get('native_comparisons', []))
    represented_figures.update(u for span in p.get('spans', []) for u in span.get('source_unit_ids', []))
    uncovered = []
    for identity, unit in units.items():
        entry = coverage[identity]
        if unit['kind'] == 'figure':
            if identity not in represented_figures:
                uncovered.append({'unit_id': identity, 'kind': 'untranslated-figure'})
            continue
        cursor = 0
        for a, b in sorted(entry['covered_ranges']):
            if a > cursor:
                uncovered.append({'unit_id': identity, 'range': [cursor, a]})
            cursor = max(cursor, b)
        if cursor < len(unit['text']):
            uncovered.append({'unit_id': identity, 'range': [cursor, len(unit['text'])]})
    if uncovered:
        raise ValueError('Incomplete source coverage: ' + json.dumps(uncovered, ensure_ascii=False))
    p['coverage'] = {'complete': True, 'units': coverage, 'uncovered': []}
    return units


def _native_svg(text):
    if not isinstance(text, str) or re.search(r'<!DOCTYPE|<!ENTITY', text, re.I):
        raise ValueError('Native SVG cannot load XML entities')
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise ValueError('Invalid native SVG') from e
    allowed = {'svg', 'g', 'defs', 'path', 'use', 'symbol', 'text', 'tspan', 'line', 'polyline',
               'polygon', 'rect', 'circle', 'ellipse', 'clipPath', 'mask', 'title', 'desc',
               'linearGradient', 'radialGradient', 'stop'}
    ids, references = set(), []
    if root.tag.split('}')[-1] != 'svg':
        raise ValueError('Native figure requires an SVG root')
    for node in root.iter():
        if node.tag.split('}')[-1] not in allowed:
            raise ValueError('Unsafe or unsupported native SVG element')
        if node.get('id'):
            if node.get('id') in ids:
                raise ValueError('Duplicate native SVG identity')
            ids.add(node.get('id'))
        for key, value in node.attrib.items():
            key = key.split('}')[-1].lower()
            if key.startswith('on') or key in ('src', 'base') or re.search(r'@import|expression\s*\(|javascript:|data:', value, re.I):
                raise ValueError('Unsafe native SVG attribute')
            if key == 'href':
                if not value.startswith('#'):
                    raise ValueError('External native SVG reference')
                references.append(value[1:])
            for match in re.finditer(r'url\s*\(([^)]*)\)', value, re.I):
                ref = match.group(1).strip(' \t\r\n\"\'')
                if not ref.startswith('#'):
                    raise ValueError('External native SVG paint reference')
                references.append(ref[1:])
    if set(references) - ids:
        raise ValueError('Native SVG has unresolved local references')
    return ids, ''.join(root.itertext())


def _compile_comparisons(p, directory, notes, staffs, units, duration):
    text = []
    comparisons = _identities(p['native_comparisons'], 'native comparison')
    for c in comparisons.values():
        check_sources(c, directory)
        if c.get('source_unit_id') not in units:
            raise ValueError('Native comparison requires source-unit provenance')
        if not c.get('source_note_ids') or set(c['source_note_ids']) - notes.keys():
            raise ValueError('Native comparison requires current source_note_ids')
        refs, svg_text = _native_svg(c['svg'])
        text.extend([svg_text, c.get('caption', ''), *c.get('caption_lines', [])])
        _interval(c, 'from', 'to', 'native comparison', duration)
        if c.get('anchor_staff') not in staffs:
            raise ValueError('Unknown comparison anchor staff')
        c.setdefault('placement', 'score')
        c.setdefault('correspondences', copy.deepcopy(c.get('pairs', [])))
        c.setdefault('pairs', copy.deepcopy(c['correspondences']))
        if c.get('native_controls'):
            raise ValueError('Native comparisons require prearranged source SVG, not work-specific controls')
        c.setdefault('height', 100)
        c.setdefault('color', p['palette'].get(c.get('theme'), '#38443E'))
        c.setdefault('native_x', min(notes[n].get('x', 0) for n in c['source_note_ids']))
        for pair in c['correspondences']:
            if pair.get('ref_id') not in refs or pair.get('score_id') not in notes:
                raise ValueError('Native comparison pair references missing source/target notes')
        for group in c.get('pair_groups', []):
            if set(group.get('ref_ids', [])) - refs or set(group.get('score_ids', [])) - notes.keys():
                raise ValueError('Native comparison group has missing source/target notes')
        for highlight in c.get('reference_highlights', []) + c.get('source_note_colors', []):
            if set(highlight.get('ids', [])) - refs:
                raise ValueError('Native comparison color references missing native nodes')
        if c['placement'] == 'sidebar':
            block = c.get('host_block')
            if not isinstance(block, int) or not 0 <= block < len(p['blocks']):
                raise ValueError('Sidebar native comparison requires a valid host_block')
            host = p['blocks'][block]
            if host['kind'] != 'native_score' or host.get('figure_id') != c['id']:
                raise ValueError('Sidebar native comparison and host figure differ')
    for block in p['blocks']:
        if block['kind'] == 'native_table':
            _, svg_text = _native_svg(block['svg'])
            text.append(svg_text)
        if block['kind'] == 'native_score' and block.get('figure_id') not in comparisons:
            raise ValueError('Native score block has no compiled comparison')
    return ''.join(text)


def _compile_windows(p, time_at):
    timing = {**TIMING, **p.get('connection_timing_policy', {})}
    if any(_number(v, 'connection timing') < 0 for v in timing.values()):
        raise ValueError('Connection timing must be nonnegative')
    spans = {s['id']: s for s in p['spans']}
    windows, seen = [], {}
    for i, cue in enumerate(p['cues']):
        if cue.get('no_link'):
            continue
        for target in cue.get('link_targets') or [{}]:
            ref = {**cue, **target, 'cue_index': i}
            if ref.get('target_id') not in spans:
                raise ValueError('Connection cue requires a known target span')
            row, block = spans[ref['target_id']], p['blocks'][ref['block']]
            start = time_at(row.get('connection_q0', row['q0']))
            end = time_at(row.get('connection_q1', row['q1']))
            identity = tuple(ref.get(k) for k in ('block', 'keyword', 'keyword_occurrence', 'theme', 'target_id'))
            if identity in seen:
                seen[identity]['duplicate_cue_indices'].append(i)
                continue
            linked = 0
            for ordinal, stage in enumerate(p['reading_stages']):
                if ref['block'] not in stage['block_indices']:
                    continue
                page_ready = max(stage['from'] + (timing['page_ready_seconds'] if ordinal else 0),
                                 block.get('reveal_from', -1e9) + .7)
                a = max(start - timing['full_lead_seconds'] - timing['extend_seconds'],
                        page_ready, p['panel_in'] + timing['panel_ready_seconds'])
                z = min(end + timing['post_source_hold_seconds'] + timing['retract_seconds'],
                        block.get('persist_until', stage['to']), p['panel_out'])
                full, hold = a + timing['extend_seconds'], z - timing['retract_seconds']
                if full >= end or hold <= full:
                    continue
                w = {k: ref[k] for k in ('cue_index', 'target_id', 'theme', 'block', 'keyword',
                     'keyword_occurrence', 'role', 'semantic_event', 'retirement_priority') if k in ref}
                w.update(index=len(windows), page_id=stage['id'], **{'from': a}, full_at=full,
                         hold_until=hold, to=z, source_start=start, source_end=end,
                         source_q=[row['q0'], row['q1']], continuation=linked > 0,
                         semantic_group_q=[row.get('connection_q0', row['q0']), row.get('connection_q1', row['q1'])],
                         actual_source_start=time_at(row['q0']), actual_source_end=time_at(row['q1']),
                         focus_blocks=[n for n in ref.get('focus_blocks', [ref['block']]) if n in stage['block_indices']],
                         require_link=True, duplicate_cue_indices=[])
                windows.append(w)
                seen.setdefault(identity, w)
                linked += 1
            if not linked:
                raise ValueError('Source ended before its text could be connected: ' + row['id'])
    p['connection_timing_policy'] = timing
    return windows


def _apply_display_lifetimes(p, directory):
    """Apply coupled label/line extensions only across continuously proven frames.

    This ports the source workflow's safe-prefix and extension-first capacity
    policies. The caller supplies real renderer probe results; absent, hidden
    or unsafe frames terminate a tail and reject an early prefix. Source and
    layout windows are retained separately, and original entrances never move
    to make room for a tail extension.
    """
    evidence = p.get('display_lifetimes')
    if not evidence:
        return
    check_sources(evidence, directory)
    fps = _number(evidence.get('fps', 30), 'display probe fps')
    if fps <= 0:
        raise ValueError('Display probe fps must be positive')
    base = {'connection_windows': copy.deepcopy(p['connection_windows']),
            'label_representatives': copy.deepcopy(p['label_representatives'])}
    p['display_lifetime_base'] = base
    windows = p['connection_windows']
    stages = {s['id']: s for s in p['reading_stages']}
    spans = {s['id']: s for s in p['spans']}
    samples = {}
    for sample in evidence.get('samples', []):
        t = _number(sample['seconds'], 'display probe time')
        ordinal = round(t * fps)
        if abs(ordinal / fps - t) > 1e-6 or sample.get('target_id') not in spans:
            raise ValueError('Display probe must identify a target and exact output frame')
        key = (sample['target_id'], ordinal)
        if key in samples:
            raise ValueError('Duplicate display probe frame')
        samples[key] = all(sample.get(k) is True for k in ('label_safe', 'route_safe', 'source_visible'))
    audit, requested_ends = [], {w['index']: w['to'] for w in windows}
    requests = evidence.get('requests', [])
    seen = set()
    for request in requests:
        target = request['target_id']
        if target in seen or target not in spans:
            raise ValueError('Display requests require distinct known targets')
        seen.add(target)
        refs = [r for r in p['label_representatives'] if r['target_id'] == target]
        links = [w for w in windows if w['target_id'] == target]
        if len(refs) != 1 or not links:
            raise ValueError('Coupled display request requires one explicit label and its connector windows')
        ref = refs[0]
        requested_from, requested_to = _interval(request, 'from', 'to', 'display request', p['panel_out'])
        old_from = min(ref['from'], *(w['from'] for w in links))
        old_to = max(ref['to'], *(w['to'] for w in links))
        if requested_from > old_from or requested_to < old_to:
            raise ValueError('Display requests extend original lifetimes; they cannot truncate original content')
        first = math.ceil((requested_from - .2) * fps - 1e-8)
        last = math.ceil((max(ref['from'], *(w['from'] for w in links)) + .2) * fps - 1e-8)
        early_safe = all(samples.get((target, n), False) for n in range(first, last))
        if requested_from < old_from and early_safe:
            ref['display_from'] = requested_from
            for w in links:
                w['routing_layout_from'] = w['from']
                duration = w['full_at'] - w['from']
                w['from'], w['full_at'] = requested_from, requested_from + duration
        horizon = min(requested_to, p['panel_out'], *(p['blocks'][w['block']].get('persist_until', stages[w['page_id']]['to']) for w in links))
        successor = min((r.get('display_from', r['from']) for r in p['label_representatives']
                         if r is not ref and spans[r['target_id']]['theme'] == spans[target]['theme']
                         and r['from'] >= ref['to']), default=horizon)
        horizon = max(old_to, min(horizon, successor))
        # Include the original retraction: missing original tail geometry is
        # not permission to carry the settled route into a new time interval.
        probe_from = min(ref['to'] - .2, *(w['hold_until'] for w in links))
        boundary, reason = horizon, 'text-or-semantic-boundary'
        for n in range(math.ceil(probe_from * fps - 1e-8), math.ceil(horizon * fps - 1e-8)):
            if not samples.get((target, n), False):
                boundary = max(old_to, n / fps)
                reason = 'missing-or-unsafe-geometry'
                break
        for w in links:
            requested_ends[w['index']] = max(w['to'], boundary)
        audit.append({'target_id': target, 'early_safe': early_safe,
                      'requested': [requested_from, requested_to], 'boundary': boundary, 'reason': reason})
    # Retire extensions before any new entrance. This is the source
    # capacity_ends algorithm with configurable points and branches.
    groups = {}
    for w in windows:
        groups.setdefault(w['semantic_group'], []).append(w)
    policy = p['connection_capacity_policy']
    for t in sorted({w['from'] for w in windows}):
        active = [g for g in groups.values() if g[0]['from'] <= t and any(requested_ends[w['index']] > t + 1e-8 for w in g)]
        while len(active) > policy['maximum_points'] or sum(sum(requested_ends[w['index']] > t + 1e-8 for w in g) for g in active) > policy['maximum_branches']:
            victims = [g for g in active if all(w['to'] <= t + 1e-8 for w in g)]
            if not victims:
                raise ValueError('Display advance exceeds connection capacity; original entrances are preserved')
            victim = min(victims, key=lambda g: (g[0]['from'], g[0]['index']))
            for w in victim:
                requested_ends[w['index']] = t
            active.remove(victim)
    for w in windows:
        end = requested_ends[w['index']]
        if end > w['to']:
            w['routing_layout_to'] = w['to']
            w['to'], w['hold_until'] = end, end - policy['retract_seconds']
    for request in requests:
        target = request['target_id']
        ref = next(r for r in p['label_representatives'] if r['target_id'] == target)
        end = min(w['to'] for w in windows if w['target_id'] == target)
        if end > ref['to']:
            ref['display_to'] = end
    p['connection_windows'], report = bound_connections(windows, policy=policy)
    p['connection_capacity'] = report
    p['display_lifetime_audit'] = {'fps': fps, 'coupled': True, 'decisions': audit,
                                   'policy': 'continuous actual-frame evidence; retain source/layout windows; retire extensions first'}


def compile_guide(source, movement_dir, output_path=None):
    """Compile a mapping or JSON path; write only when output_path is supplied.

    Text units store original text; block display_ranges use original Python
    Unicode character offsets. Unit errata are exact replacements with reasons.
    Existing compiled payloads are accepted and all validation runs again.
    """
    directory = Path(movement_dir).resolve()
    data = _read(source) if isinstance(source, (str, Path)) else source
    p = copy.deepcopy(data.get('guide_payload', data))
    if 'source_hashes' not in p and 'source_hashes' in data:
        p['source_hashes'] = copy.deepcopy(data['source_hashes'])
    check_sources(p, directory)
    score, geometry, alignment = [_read(directory / (n + '.json')) for n in ('score', 'geometry', 'alignment')]
    time_at, duration = _clock(alignment)
    notes = _identities(geometry['notes'], 'native note')
    staffs = _identities(geometry['staves'], 'staff')
    events = _identities(score['events'], 'source note')
    p.setdefault('id', directory.name)
    if not isinstance(p['id'], str) or not p['id']:
        raise ValueError('Guide id must be nonempty')
    for key in ('blocks', 'spans', 'cues', 'native_comparisons', 'label_representatives',
                'label_bands', 'label_space_decisions', 'label_display_windows', 'harmony_anchors'):
        p.setdefault(key, [])
    p.setdefault('labels', {})
    p.setdefault('palette', {})
    p.setdefault('panel_in', 0)
    p.setdefault('panel_out', duration)
    _interval(p, 'panel_in', 'panel_out', 'guide panel', duration)
    p.setdefault('incremental_sidebar', True)
    p.setdefault('stable_reading_blocks', True)
    p.setdefault('label_typography', {'sizes': {}})
    if p.get('display_lifetimes') and p.get('display_lifetime_base'):
        p['connection_windows'] = copy.deepcopy(p['display_lifetime_base']['connection_windows'])
        p['label_representatives'] = copy.deepcopy(p['display_lifetime_base']['label_representatives'])
    palette = p.get('palette', {})
    if not isinstance(palette, dict) or any(not re.fullmatch(r'#[0-9a-fA-F]{6}', c) for c in palette.values()):
        raise ValueError('Palette must map every material to a six-digit color')
    for theme in p['labels']:
        if theme not in palette:
            raise ValueError('Material label is missing from palette')
    for theme in palette:
        p['labels'].setdefault(theme, theme)
    units = _compile_content(p)
    blocks = {b['id']: b['index'] for b in p['blocks']}
    def block_index(value):
        value = blocks.get(value, value) if isinstance(value, str) else value
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < len(p['blocks']):
            raise ValueError('Unknown guide block')
        return value
    stages = p.pop('stages', p.get('reading_stages', None))
    if stages is None:
        stages = [{'id': 'movement', 'from': p['panel_in'], 'to': p['panel_out'],
                   'block_indices': list(range(len(p['blocks'])))}]
    if not stages:
        raise ValueError('Guide requires at least one reading stage')
    _identities(stages, 'reading stage')
    shown = set()
    for i, stage in enumerate(stages):
        _interval(stage, 'from', 'to', 'reading stage', duration)
        if stage['from'] < p['panel_in'] or stage['to'] > p['panel_out']:
            raise ValueError('Reading stage outside panel lifetime')
        if i and abs(stages[i-1]['to'] - stage['from']) > 1e-7:
            raise ValueError('Reading stages must form an ordered contiguous track')
        stage['block_indices'] = [block_index(v) for v in stage.pop('blocks', stage.get('block_indices', []))]
        if len(set(stage['block_indices'])) != len(stage['block_indices']):
            raise ValueError('Duplicate block in reading stage')
        shown.update(stage['block_indices'])
    if shown != set(range(len(p['blocks']))):
        raise ValueError('Source coverage includes blocks never displayed')
    p['reading_stages'] = stages
    spans = _identities(p['spans'], 'score span')
    columns = {}
    for note in notes.values():
        event = events.get(note['id'])
        if event and not event.get('grace'):
            columns.setdefault(_q(event['q']), []).append(note['x'])
    axis = {q: float(median(xs)) for q, xs in columns.items()}
    for measure in geometry.get('measures', []):
        axis.setdefault(_q(measure['q']), measure['x'])
    if geometry.get('measures'):
        last_measure = geometry['measures'][-1]
        axis[_q(last_measure['end'])] = last_measure['x'] + last_measure['width']
    axis = sorted(axis.items())
    def native_x(q):
        i = bisect.bisect_right([v[0] for v in axis], q) - 1
        if i < 0:
            return axis[0][1]
        if i == len(axis) - 1:
            return axis[-1][1]
        a, b = axis[i], axis[i+1]
        return a[1] + (b[1]-a[1])*(q-a[0])/(b[0]-a[0])
    assignments, regions = {}, []
    for span in spans.values():
        span['ids'] = span.pop('note_ids', span.get('ids', []))
        if (not span['ids'] or set(span['ids']) - notes.keys() or set(span['ids']) - events.keys() or span.get('staff') not in staffs or
                any(notes[n]['staff'] != span['staff'] for n in span['ids'])):
            raise ValueError('Span requires existing note identities in its declared staff')
        theme = span.get('theme')
        if theme not in palette:
            raise ValueError('Span material missing from palette')
        span.setdefault('q0', min(_q(events[n]['q']) for n in span['ids']))
        span.setdefault('q1', max(_q(events[n]['q']) + _q(events[n].get('duration', events[n].get('dur', 0))) for n in span['ids']))
        span['q0'], span['q1'] = _q(span['q0']), _q(span['q1'])
        if span['q1'] <= span['q0']:
            raise ValueError('Span has no positive source duration')
        time_at(span['q0']); time_at(span['q1'])
        span.setdefault('label', p['labels'].get(theme, ''))
        p['labels'].setdefault(theme, span['label'] or theme)
        for n in span['ids']:
            if n in assignments and assignments[n] != theme:
                raise ValueError('Conflicting material assignments for note ' + n)
            assignments[n] = theme
        x0 = span.get('start_x', native_x(span['q0']))
        x1 = span.get('end_x', native_x(span['q1']))
        if x1 <= x0:
            raise ValueError('Invalid native span geometry')
        regions.append({'staff': span['staff'], 'start_x': x0, 'end_x': x1, 'theme': theme})
    keyword_themes = dict(p.get('keyword_themes', {}))
    def register(word, theme):
        if not word or theme not in palette:
            raise ValueError('Keyword requires a known material color')
        if word in keyword_themes and keyword_themes[word] != theme:
            raise ValueError('Keyword color conflicts with its material identity: ' + word)
        keyword_themes[word] = theme
    for theme, label in p['labels'].items():
        if label:
            register(label, theme)
    for cue in p['cues']:
        cue.setdefault('no_link', not bool(cue.get('target_id') or cue.get('link_targets')))
        cue['at'] = _number(cue['at'], 'cue time')
        if not p['panel_in'] <= cue['at'] <= p['panel_out']:
            raise ValueError('Cue time outside guide panel')
        cue['block'] = block_index(cue['block'])
        for target in cue.get('link_targets') or [{}]:
            ref = {**cue, **target}
            if not ref.get('no_link'):
                span = spans.get(ref.get('target_id'))
                if span is None:
                    raise ValueError('Unknown connection target')
                theme = ref.get('theme', span['theme'])
                if theme != span['theme']:
                    raise ValueError('Keyword color conflicts with target material')
                target['theme'] = theme
                cue.setdefault('theme', theme)
                word = ref.get('keyword')
                if not isinstance(word, str) or not word or word not in p['blocks'][cue['block']]['text']:
                    raise ValueError('Connection keyword absent from source text')
                occurrence = ref.get('keyword_occurrence', 0)
                if not isinstance(occurrence, int) or not 0 <= occurrence < p['blocks'][cue['block']]['text'].count(word):
                    raise ValueError('Invalid connection keyword occurrence')
                register(word, theme)
        cue.setdefault('no_link', not bool(cue.get('target_id') or cue.get('link_targets')))
        cue.setdefault('theme', p['blocks'][cue['block']].get('theme', next(iter(palette), '')))
    if any(b['at'] < a['at'] for a, b in zip(p['cues'], p['cues'][1:])):
        raise ValueError('Cues must be ordered in absolute movement time')
    for block in p['blocks']:
        if block.get('theme') is not None and block['theme'] not in palette:
            raise ValueError('Block material missing from palette')
        for word in block.get('keywords', []):
            register(word, block.get('keyword_themes', {}).get(word, block.get('theme', keyword_themes.get(word))))
        for word, theme in block.get('keyword_themes', {}).items():
            register(word, theme)
    for block in p['blocks']:
        mapping = {word: theme for word, theme in keyword_themes.items() if word in block['text']}
        for word, color in block.get('keyword_colors', {}).items():
            if word not in mapping or color.lower() != palette[mapping[word]].lower():
                raise ValueError('Keyword color differs from complete material palette')
        block['keywords'] = sorted(mapping, key=lambda word: (-len(word), word))
        block['keyword_themes'] = mapping
        block['keyword_colors'] = {word: palette[theme] for word, theme in mapping.items()}
    p['keyword_themes'] = keyword_themes
    for ref in p['label_representatives']:
        if not isinstance(ref, dict) or ref.get('target_id') not in spans:
            raise ValueError('Label representatives require explicit target_id/from/to objects')
        _interval(ref, 'from', 'to', 'label representative', duration)
        a, b = ref.get('display_from', ref['from']), ref.get('display_to', ref['to'])
        _interval({'from': a, 'to': b}, 'from', 'to', 'label display', duration)
    for c in p['native_comparisons']:
        if 'host_block' in c:
            c['host_block'] = block_index(c['host_block'])
    extra_text = _compile_comparisons(p, directory, notes, staffs, units, duration)
    windows = p.get('connection_windows')
    if windows is None:
        windows = _compile_windows(p, time_at)
    stages_by_id = {s['id']: s for s in stages}
    indices = set()
    for i, w in enumerate(windows):
        index = w.get('index', i)
        if not isinstance(index, int) or index < 0 or index in indices or w.get('page_id') not in stages_by_id:
            raise ValueError('Connection window index/page identity mismatch')
        indices.add(index)
        w['index'] = index
        if w.get('target_id') not in spans or not 0 <= w.get('cue_index', -1) < len(p['cues']):
            raise ValueError('Connection window has unknown target/cue')
        w['block'] = block_index(w['block'])
        if w['block'] not in stages_by_id[w['page_id']]['block_indices']:
            raise ValueError('Connection source text is not displayed on its page')
        span = spans[w['target_id']]
        if w['theme'] != span['theme'] or keyword_themes.get(w['keyword']) != w['theme']:
            raise ValueError('Connection window material color mismatch')
        if abs(w['source_start'] - time_at(span.get('connection_q0', span['q0']))) > 1e-5 or abs(w['source_end'] - time_at(span.get('connection_q1', span['q1']))) > 1e-5:
            raise ValueError('Connection window source time differs from bound alignment')
    bounded, capacity = bound_connections(windows, p.get('connection_routing_conflicts', []),
                                         p.get('connection_capacity_policy', {}))
    p['connection_windows'], p['connection_capacity'] = bounded, capacity
    p['connection_capacity_policy'] = capacity['policy']
    _apply_display_lifetimes(p, directory)
    p.setdefault('routing_reference_frames', [])
    p['schema'] = 'score-sync-guide-1'
    p['material_regions'] = {'source_hashes': copy.deepcopy(p['source_hashes']), 'x_shift': 0,
                             'palette': copy.deepcopy(palette), 'short_names': copy.deepcopy(p['labels']),
                             'regions': regions, 'assignments': assignments,
                             'shared_staff_neutral_intervals': [], 'vocal_phrase_themes': []}
    p['font_text'] = ''.join(b['text'] for b in p['blocks']) + ''.join(p['labels'].values()) + extra_text
    p['font_text'] += ''.join(s.get('section_text', '') for s in stages)
    p['font_text'] += ''.join(v.get('text', '') for v in p.get('tempo_labels', []))
    if output_path is not None:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(p, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    return p


def load_guide(directory, geometry):
    """Load optional guide.json, revalidate it, and return scene fields/font text."""
    directory = Path(directory)
    path = directory / 'guide.json'
    if not path.exists():
        return {}, ''
    current = _read(directory / 'geometry.json')
    # Staff display labels may already have been localized by visual.bundle.
    def identity(g):
        return ({n['id']: n.get('svg_id') for n in g['notes']}, {s['id'] for s in g['staves']})
    if identity(current) != identity(geometry):
        raise ValueError('Guide received different native geometry identities')
    p = compile_guide(path, directory)
    fields = {'guide_payload': p}
    if p['material_regions']['assignments']:
        fields['material_regions'] = p['material_regions']
    return fields, p['font_text']
