"""Source-ordered ornament matching with explicit acoustic evidence.

Written ownership and acoustic confidence are separate. A shared pitch-flux peak
never proves an isolated instrument attack. No recording-specific times live here.
"""
from collections import defaultdict
from fractions import Fraction
import numpy as np
from scipy.signal import find_peaks
from .alignment import qvalue


def classify(attrs, previous, following):
    if attrs.get('steal-time-previous') is not None:
        return 'after_previous', 'explicit steal-time-previous'
    if attrs.get('steal-time-following') is not None:
        return 'before_following', 'explicit steal-time-following'
    if previous and previous.get('trill') and not following:
        return 'after_previous', 'source-order trill termination after sustained note'
    if following:
        return 'before_following', 'same-voice following principal in source measure'
    return 'unresolved', 'ownership requires score/audio review'


def source_metadata(root):
    """Return source ordinal metadata matching parse_musicxml's stable source IDs."""
    result = {}
    for pi, part in enumerate(root.findall('part'), 1):
        div = 1
        measures = part.findall('measure')
        for mi, measure in enumerate(measures, 1):
            div = int(measure.findtext('attributes/divisions', str(div)))
            cursor = last = Fraction(0)
            records = []
            notes = measure.findall('note')
            for node in measure:
                duration = Fraction(node.findtext('duration', '0')) / div
                if node.tag == 'backup':
                    cursor -= duration
                elif node.tag == 'forward':
                    cursor += duration
                elif node.tag == 'note':
                    grace = node.find('grace') is not None
                    duration = Fraction(0) if grace else duration
                    chord = node.find('chord') is not None
                    at = last if chord else cursor
                    if not chord:
                        last = cursor
                        cursor += duration
                    records.append(dict(q=float(at), duration=float(duration),
                        voice=node.findtext('voice', '1'), staff=node.findtext('staff', '1'),
                        trill=node.find('notations/ornaments/trill-mark') is not None,
                        chord=chord, rest=node.find('rest') is not None, grace=grace))
            for ni, (note, record) in enumerate(zip(notes, records), 1):
                if not record['grace']:
                    continue
                def same(other):
                    return not other['grace'] and other['voice'] == record['voice'] and other['staff'] == record['staff']
                previous = next((r for r in reversed(records[:ni-1]) if same(r)), None)
                following = next((r for r in records[ni:] if same(r)), None)
                if previous and previous['chord']:
                    previous = dict(previous)
                    previous['trill'] = any(r['trill'] for r in records[:ni-1]
                        if r['voice'] == record['voice'] and r['staff'] == record['staff'] and r['q'] == previous['q'])
                attrs = dict(note.find('grace').attrib)
                kind, reason = classify(attrs, previous, following)
                # A bar-end grace after a rest can belong to the next principal.
                # This is source evidence only, not a claim of independent review.
                if kind == 'unresolved' and previous and previous['rest'] and mi < len(measures):
                    target = next((n for n in measures[mi].findall('note')
                        if n.find('grace') is None and n.findtext('voice', '1') == record['voice']
                        and n.findtext('staff', '1') == record['staff']), None)
                    if target is not None and target.find('rest') is None:
                        kind, reason = 'before_following', 'bar-end grace after rest before next-measure same-voice principal'
                result[f's-p{pi}-m{mi}-n{ni}'] = dict(source_note_ordinal=ni,
                    chord=record['chord'], grace_attributes=attrs, written_type=note.findtext('type'),
                    ownership=kind, ownership_evidence=reason,
                    previous_source_note=previous, following_source_note=following)
    return result


def build_grace_groups(score, metadata):
    grouped = defaultdict(list)
    for event in score['events']:
        if not event.get('grace') or not event.get('is_player', True):
            continue
        if event['source_id'] not in metadata:
            raise ValueError(f"Grace source identity missing: {event['source_id']}")
        owner = metadata[event['source_id']]['ownership']
        grouped[(event['staff'], event['voice'], qvalue(event['q']), event['measure'], owner)].append(event)
    out = []
    for (staff, voice, at, measure, owner), events in grouped.items():
        events.sort(key=lambda e: metadata[e['source_id']]['source_note_ordinal'])
        clusters, members = [], []
        for event in events:
            item = metadata[event['source_id']]
            if not item['chord'] or not clusters:
                clusters.append([])
            clusters[-1].append(event['id'])
            members.append({**event, **item})
        others = [e for e in score['events'] if e['staff'] == staff and e['voice'] == voice
                  and not e.get('grace') and e.get('pitch') is not None and e.get('is_player', True)]
        previous_q = max((qvalue(e['q']) for e in others if qvalue(e['q']) < at), default=at-1)
        previous = [dict(id=e['id'], pitch=e['pitch'], q=qvalue(e['q']), duration=e['duration'])
                    for e in others if qvalue(e['q']) == previous_q]
        out.append(dict(group_id=f'{staff}:{voice}:q{at}:o{measure}:{owner}', staff=staff,
            voice=voice, q=at, performance_measure=measure, source_measure=events[0]['source_measure'],
            ownership=owner, members=members, ordered_attack_clusters=clusters, previous_events=previous))
    return out


def match_grace_groups(groups, ts, rise, pitch_low, qgrid, tgrid):
    out = []
    for group in groups:
        base = dict(group_id=group['group_id'], q=group['q'], ownership=group['ownership'],
                    physical_instrument_isolation_claim=False)
        if group['ownership'] == 'unresolved':
            out.append({**base, 'status':'unresolved_notation_ownership', 'clusters':[]})
            continue
        end = float(np.interp(group['q'], qgrid, tgrid))
        previous_q = max((e['q'] for e in group['previous_events'] if e['q'] < group['q']), default=group['q']-1)
        previous = float(np.interp(previous_q, qgrid, tgrid))
        clusters = group['ordered_attack_clusters']
        span = min(.50, max(.10, (end-previous)*.8))
        ii = np.flatnonzero((ts > end-span) & (ts < end-.006))
        if len(ii) < max(3, 2*len(clusters)):
            out.append({**base, 'status':'insufficient_audio_window', 'clusters':[]})
            continue
        members = {e['id']:e for e in group['members']}
        nodes, backs, costs = [], [], None
        for ids in clusters:
            pitches = sorted(set(int(members[i]['pitch']) for i in ids if members[i].get('pitch') is not None))
            indices = np.array(pitches, dtype=int)-pitch_low
            if not len(indices) or np.any(indices < 0) or np.any(indices >= rise.shape[1]):
                raise ValueError(f"Grace pitch outside feature range: {group['group_id']}")
            evidence = np.log1p(rise[ii][:, indices]).mean(1)
            peaks = set(map(int, find_peaks(evidence, prominence=.01, distance=2)[0]))
            times = ts[ii]
            local = -evidence + .06*((end-times)/span)
            if costs is not None:
                dt = times[:, None]-nodes[-1]['times'][None, :]
                mat = costs[None, :] + np.where(dt >= .018, 0., np.inf)
                back = mat.argmin(1)
                costs = local + mat[np.arange(len(times)), back]
            else:
                costs, back = local, np.full(len(times), -1)
            nodes.append(dict(times=times, evidence=evidence, peaks=peaks, ids=ids, pitches=pitches))
            backs.append(back)
        if costs is None or not np.any(np.isfinite(costs)):
            out.append({**base, 'status':'no_ordered_audio_path', 'clusters':[]})
            continue
        selected, k = [], int(np.argmin(costs))
        for j in range(len(nodes)-1, -1, -1):
            node = nodes[j]
            selected.append(dict(ids=node['ids'], pitches=node['pitches'], seconds=float(node['times'][k]),
                pitch_attack_evidence=float(node['evidence'][k]), is_local_peak=k in node['peaks']))
            k = backs[j][k]
        selected.reverse()
        for j, item in enumerate(selected):
            item['end_seconds'] = selected[j+1]['seconds'] if j+1 < len(selected) else end
        distinct = all(n['is_local_peak'] and n['pitch_attack_evidence'] > .4 for n in selected)
        overlap = any(set(n['pitches']) & {int(e['pitch']) for e in group['previous_events']} for n in selected)
        out.append({**base, 'status':'audio_peak_candidate' if distinct else 'ambiguous_audio_candidate',
            'clusters':selected, 'boundary_seconds':end, 'search_interval':[end-span, end],
            'overlaps_previous_pitch':overlap})
    return out


def apply_grace_candidates(alignment, groups, candidates):
    index = {n['id']:n for n in alignment['notes']}
    group_index = {g['group_id']:g for g in groups}
    sr, samples = alignment['sample_rate'], alignment['samples']
    unresolved = []
    for row in candidates:
        if row['status'] != 'audio_peak_candidate':
            unresolved.append(dict(group_id=row['group_id'], reason=row['status']))
        group = group_index[row['group_id']]
        if row['ownership'] == 'after_previous' and row['clusters']:
            first = round(row['clusters'][0]['seconds']*sr)
            for previous in group['previous_events']:
                note = index.get(previous['id'])
                if note and note['range'][0] < first < note['range'][1]:
                    note['range'][1] = first
        for cluster in row['clusters']:
            start = max(0, min(samples, round(cluster['seconds']*sr)))
            end = min(samples, max(start+1, round(cluster['end_seconds']*sr)))
            for eid in cluster['ids']:
                index[eid].update(range=[start, end], basis='source_ordered_grace_pitch_flux_candidate',
                                 physical_attack_measured=False, grace_confidence=row['status'])
        if not row['clusters']:
            for event in group['members']:
                index[event['id']]['basis'] = 'unresolved_grace_placeholder_not_measured'
    alignment.setdefault('flags', []).extend(unresolved)
    return unresolved
