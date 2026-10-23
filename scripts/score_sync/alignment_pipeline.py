"""Multi-stage score-to-recording sequence refinement.

This module produces evidence-bearing candidates. Recording-specific reviewed
times belong in the project, never in this algorithm. Rendering is not involved.
"""
from pathlib import Path
from collections import Counter
from copy import deepcopy
import gzip
import hashlib
import json
import math
import numpy as np
from numba import njit
from scipy.ndimage import gaussian_filter1d, median_filter
from scipy.signal import find_peaks
from .alignment import qvalue, pitch_bounds, occupancy, descriptor, extract_features, project_notes, validate_anchors


def attacks(events):
    return [e for e in events if e.get('pitch') is not None and e.get('is_player', True)
            and not e.get('grace') and not e.get('tie_stop')]


def constraints_from_anchors(score, anchors, duration):
    """Migrate existing reviewed [q, seconds] anchors without losing exact times.

    Source binding is established from the current prepared score, not inferred
    from unrelated cached audio. The caller must supply genuinely reviewed times.
    """
    rows=[]
    for q,t in validate_anchors(anchors,qvalue(score['total_q']),duration):
        events=[dict(source_id=e['source_id'],source_measure=e['source_measure'],pitch=e['pitch'])
                for e in attacks(score['events']) if abs(qvalue(e['q'])-q)<1e-9]
        rows.append(dict(q=q,seconds=t,events=events,kind='attack' if events else 'clock',
                         exact=True,provenance='caller-supplied reviewed legacy anchor'))
    if not score.get('source_sha256'):
        raise ValueError('Migrating reviewed anchors requires a prepared source SHA')
    return {'source_sha256':score['source_sha256'],'rows':rows}


def validate_constraints(data, score, duration):
    """Bind each reviewed timing constraint to all attacking source identities at q."""
    source_bound=isinstance(data,dict) and data.get('source_sha256')==score.get('source_sha256') and bool(score.get('source_sha256'))
    if isinstance(data, dict):
        if data.get('source_sha256') and data['source_sha256'] != score.get('source_sha256'):
            raise ValueError('Constraint source hash changed')
        rows = data.get('rows', [])
    else:
        rows = data or []
    result = {}
    total = qvalue(score['total_q'])
    for original in rows:
        row = dict(original)
        q, t = float(row['q']), float(row['seconds'])
        tolerance = float(row.get('tolerance_seconds', .015))
        if not np.isfinite(q+t+tolerance) or not 0 <= q <= total or not 0 <= t <= duration or tolerance <= 0:
            raise ValueError('Invalid reviewed constraint range/tolerance')
        actual = [dict(source_id=e['source_id'], source_measure=e['source_measure'], pitch=e['pitch'])
                  for e in attacks(score['events']) if abs(qvalue(e['q'])-q) < 1e-9]
        key = lambda e: (e['source_id'], e['source_measure'], e['pitch'])
        if row.get('kind','attack') not in ('attack','clock'):
            raise ValueError('Unknown constraint kind')
        clock=row.get('kind')=='clock'
        if clock and not source_bound:
            raise ValueError('Non-attack clock constraints require the source hash')
        if (not actual and not clock) or sorted(actual, key=key) != sorted(row.get('events', []), key=key):
            raise ValueError(f'Constraint source identity changed at q={q}')
        if q in result:
            raise ValueError('Duplicate reviewed constraint q')
        result[q] = {**row, 'q':q, 'seconds':t, 'tolerance_seconds':tolerance}
    ordered = sorted(result.items())
    if any(b[1]['seconds'] <= a[1]['seconds'] for a, b in zip(ordered, ordered[1:])):
        raise ValueError('Reviewed constraint times must be strictly monotone')
    return result


def correct_guide(qgrid, tgrid, constraints):
    qgrid, tgrid = np.asarray(qgrid, float), np.asarray(tgrid, float)
    if len(qgrid) < 2 or np.any(np.diff(qgrid) <= 0):
        raise ValueError('Guide score grid must increase')
    points = sorted((q, a['seconds']) for q, a in constraints.items() if qgrid[0] <= q <= qgrid[-1])
    qq = [qgrid[0]] + [q for q,t in points if qgrid[0] < q < qgrid[-1]] + [qgrid[-1]]
    residual = [constraints.get(float(qgrid[0]), {}).get('seconds', tgrid[0])-tgrid[0]]
    residual += [t-float(np.interp(q, qgrid, tgrid)) for q,t in points if qgrid[0] < q < qgrid[-1]]
    residual += [constraints.get(float(qgrid[-1]), {}).get('seconds', tgrid[-1])-tgrid[-1]]
    result = tgrid + np.interp(qgrid, qq, residual)
    if not np.all(np.isfinite(result)) or np.any(np.diff(result) <= 0):
        raise ValueError('Reviewed guide is not strictly monotone; inspect boundary evidence')
    return result


def initial_attack_candidate(score, features, lo, search_seconds=10.):
    """Suggest the first notated attack from RMS plus compatible pitch rise.

    This seeds a search corridor only. A reviewed constraint takes precedence.
    Immediate music and a silent lead-in both work; an ambiguous entrance remains
    explicitly review-required rather than becoming an asserted hard anchor.
    """
    if not np.isfinite(search_seconds) or not 0<search_seconds<=120:
        raise ValueError('initial_search_seconds must be between 0 and 120')
    events=attacks(score['events']);first_q=min(qvalue(e['q']) for e in events)
    pitches=sorted({int(e['pitch']) for e in events if qvalue(e['q'])==first_q})
    ts,rms=features['ts'],features['rms'];roi=(ts<=min(ts[-1],search_seconds))
    local_peak=float(np.max(rms[roi]));initial=rms[ts<=min(ts[-1],.5)]
    noise=min(float(np.percentile(initial,5)),local_peak*.01)
    threshold=max(noise*5,local_peak*.001,1e-8)
    active=np.flatnonzero(roi & (rms>threshold))
    if not len(active):
        return None
    first=float(ts[active[0]]);ii=np.flatnonzero((ts>=max(0,first-.03))&(ts<=first+.20))
    if not len(ii):
        return None
    evidence=np.log1p(features['rise'][ii][:,np.array(pitches)-lo]).mean(1)
    peaks=find_peaks(evidence)[0]
    index=int(max(peaks,key=lambda k:evidence[k])) if len(peaks) else int(np.argmax(evidence))
    candidate=float(ts[ii[index]]) if float(evidence[index])>0 else first
    return dict(q=first_q,seconds=candidate,pitches=pitches,rms_gate_seconds=first,
        rms_threshold=threshold,pitch_rise_evidence=float(evidence[index]),reviewed=False,
        physical_attack_measured=False,basis='RMS entrance plus first expected pitch-rise candidate')


def register_coarse_guide(score, features, pitch_low, pitch_high, max_axis=2000):
    """48D register-aware constrained DTW, with an explicitly bounded cost matrix."""
    import librosa
    if not 16 <= max_axis <= 8000:
        raise ValueError('coarse_max_axis must be between 16 and 8000')
    total = qvalue(score['total_q'])
    step = max(.5, total/max(2, max_axis-1))
    x = descriptor(occupancy(score['events'], total, pitch_low, pitch_high, step), pitch_low)
    sq = np.arange(len(x))*step
    stride = max(19, math.ceil(len(features['ct'])/max_axis))
    y = descriptor(features['cqt'][::stride], pitch_low)
    times = features['ct'][::stride]
    ts, rms = features['ts'], features['rms']
    floor = float(np.median(rms[ts > ts[-1]-.5]))
    active = ts[rms > max(floor*5, float(rms.max())*.005)]
    if len(active):
        keep = times <= min(times[-1], active[-1]+1)
        times, y = times[keep], y[keep]
    if len(times) < 2 or len(x) < 2:
        raise ValueError('Insufficient score/audio extent for coarse sequence alignment')
    steps = np.array([[1,1], [1,2], [1,3], [1,4], [2,1], [3,1], [4,1]])
    _, path = librosa.sequence.dtw(C=np.clip(1-x@y.T, 0, 2), step_sizes_sigma=steps,
        weights_add=np.array([0,.05,.10,.15,.05,.10,.15]))
    path = path[::-1]
    q, t = sq[path[:,0]], times[path[:,1]]
    return q, t, dict(method='48D register-aware constrained DTW', score_step_q=step,
        audio_stride=stride, cost_shape=[len(x), len(y)], reviewed=False)


@njit(cache=True)
def banded_sequence_path(x, y, a, b, centers, width, rates, terminal_radius=100):
    n, nt, w = len(x), len(y), width*2+1
    back = np.zeros((n,w), np.uint8)
    previous = np.full(w, 1e15)
    previous2 = previous.copy()
    steps = ((1,1,1), (2,1,2), (3,2,1), (5,1,3), (6,1,4), (7,1,5), (8,1,6), (9,1,7), (10,1,8))
    for i in range(n):
        current = np.full(w, 1e15)
        base = centers[i]-width
        for k in range(w):
            j = base+k
            if j < 0 or j >= nt:
                continue
            similarity, attack = 0., 0.
            for h in range(x.shape[1]):
                similarity += x[i,h]*y[j,h]
            for h in range(a.shape[1]):
                attack += a[i,h]*b[j,h]
            cost = .7*(1-similarity)+.3*(1-attack)
            best, chosen = 1e15, 0
            if i == 0:
                if abs(j-centers[0]) > 3:
                    continue
                best, chosen = abs(j-centers[0])*.04, 4
            else:
                for code, di, dj in steps:
                    if i < di:
                        continue
                    kk = j-dj-(centers[i-di]-width)
                    if kk < 0 or kk >= w:
                        continue
                    ratio = dj/di/rates[i]
                    if ratio < .4 or ratio > 2.5:
                        continue
                    value = (previous if di == 1 else previous2)[kk] + cost*(di+dj)/2 + .12*np.log(ratio)**2
                    if value < best:
                        best, chosen = value, code
            current[k], back[i,k] = best, chosen
        previous2, previous = previous, current
    for k in range(w):
        if abs(k-width) > terminal_radius:
            previous[k] = 1e15
    if np.min(previous) >= 1e14:
        raise ValueError('No connected finite DTW path to final attack region')
    j, i = centers[-1]-width+np.argmin(previous), n-1
    path = []
    while i >= 0:
        path.append((i,j))
        k = j-(centers[i]-width)
        if k < 0 or k >= w:
            raise ValueError('Disconnected DTW backtrack')
        code = back[i,k]
        if code == 4:
            break
        elif code == 1:
            i -= 1; j -= 1
        elif code == 2:
            i -= 1; j -= 2
        elif code == 3:
            i -= 2; j -= 1
        elif code >= 5:
            i -= 1; j -= code-2
        else:
            raise ValueError('Disconnected DTW backtrack')
    result = np.array(path[::-1])
    if result[0,0] != 0:
        raise ValueError('DTW path does not reach score beginning')
    return result


def dense_sequence(score, features, lo, hi, guide_q, guide_t, constraints, config):
    events = attacks(score['events'])
    last = max(qvalue(e['q']) for e in events)
    if last <= 0:
        raise ValueError('Dense sequence requires at least two distinct score attack positions')
    median_rate = float(np.median(np.diff(guide_t)/np.diff(guide_q)))
    suggested = 2**round(math.log2(.01/max(.01, median_rate)))
    step = float(config.get('step_q', min(.125, max(1/128, suggested))))
    hop = float(config.get('audio_step_seconds', .01))
    halfwidth = float(config.get('dense_halfwidth_seconds', 3.))
    if not 0 < step <= 1 or not .001 <= hop <= .1 or not .01 <= halfwidth <= 30:
        raise ValueError('Invalid dense-grid parameters')
    occ = occupancy(score['events'], last, lo, hi, step)
    sq = np.arange(len(occ))*step
    sq[-1] = last
    guide = correct_guide(sq, np.interp(sq, guide_q, guide_t), constraints)
    width = math.ceil(halfwidth/hop)
    if len(sq)*(2*width+1) > int(config.get('max_backtrack_cells', 100_000_000)):
        raise ValueError('Dense backtrack exceeds configured memory cap; set an explicit coarser step_q')
    ts = np.arange(0, min(features['ts'][-1], guide[-1]+halfwidth)+hop/2, hop)
    x = descriptor(occ, lo)
    y = descriptor(np.stack([np.interp(ts, features['ct'], features['cqt'][:,p])
                            for p in range(hi-lo+1)], axis=1), lo)
    a = np.zeros_like(occ)
    for event in events:
        i, p = round(qvalue(event['q'])/step), int(event['pitch'])-lo
        if i < len(a):
            a[i,p] = 1
    a = gaussian_filter1d(a, .7, axis=0)
    a /= np.maximum(np.linalg.norm(a, axis=1, keepdims=True), 1e-6)
    b = np.stack([np.interp(ts, features['ts'], np.log1p(features['rise'][:,p]))
                  for p in range(hi-lo+1)], axis=1)
    b /= np.maximum(np.linalg.norm(b, axis=1, keepdims=True), 1e-6)
    left, right = np.maximum(sq[0], sq-2), np.minimum(sq[-1], sq+2)
    tempo = (np.interp(right,sq,guide)-np.interp(left,sq,guide))/np.maximum(.01,right-left)
    tempo = median_filter(tempo, size=max(3,int(4/step))|1)
    rates = np.clip(tempo*step/hop, .4, 8.)
    path = banded_sequence_path(x.astype(np.float32), y.astype(np.float32), a.astype(np.float32),
        b.astype(np.float32), np.round(guide/hop).astype(np.int64), width, rates,
        terminal_radius=round(float(config.get('terminal_search_seconds',1.))/hop))
    return sq[path[:,0]], ts[path[:,1]], dict(step_q=step, audio_step_seconds=hop,
        halfwidth_seconds=halfwidth, backtrack_cells=len(sq)*(2*width+1))


def refine_attack_chain(events, ts, rise, lo, qgrid, tgrid, constraints=None, config=None):
    constraints, config = constraints or {}, config or {}
    groups = {}
    for event in attacks(events):
        groups.setdefault(qvalue(event['q']), Counter())[int(event['pitch'])] += 1
    qs = np.array(sorted(groups), dtype=float)
    seed = np.interp(qs,qgrid,tgrid)
    left, right = np.maximum(qgrid[0],qs-8), np.minimum(qgrid[-1],qs+8)
    rates = np.maximum(.05, (np.interp(right,qgrid,tgrid)-np.interp(left,qgrid,tgrid))/np.maximum(.01,right-left))
    halfwidth, tempo_weight = float(config.get('attack_halfwidth_seconds',2.)), float(config.get('tempo_weight',4.))
    if not 0 < halfwidth <= 30 or not 0 <= tempo_weight <= 100:
        raise ValueError('Invalid attack-chain search parameters')
    nodes, backs, costs = [], [], None
    evidence = np.log1p(rise)
    for i,q in enumerate(qs):
        ii = np.flatnonzero(abs(ts-seed[i]) < halfwidth)
        if not len(ii):
            raise ValueError(f'Empty audio candidate window at q={q}')
        ps = np.array(list(groups[q]))-lo
        weights = np.sqrt(np.array(list(groups[q].values()),dtype=float));weights /= weights.sum()
        ev = evidence[ii][:,ps]@weights
        peaks = find_peaks(ev,prominence=.01,distance=2)[0]
        candidate = np.unique(np.r_[peaks,np.arange(0,len(ii),3)])
        times, support = ts[ii[candidate]], ev[candidate]
        if q in constraints:
            target = constraints[q]['seconds']
            keep = abs(times-target) < constraints[q]['tolerance_seconds']
            times, support = times[keep], support[keep]
            if constraints[q].get('exact'):
                times,support=np.array([],float),np.array([],float)
            # An exact reviewed time remains selectable even between 10 ms bins.
            times = np.r_[times,target]
            support = np.r_[support,float(np.interp(target,ts[ii],ev))]
            order = np.argsort(times);times,support=times[order],support[order]
        elif i == len(qs)-1:
            keep = abs(times-seed[i]) < float(config.get('last_attack_halfwidth_seconds',.30))
            times, support = times[keep], support[keep]
        if not len(times):
            raise ValueError(f'No candidate within reviewed/terminal range at q={q}')
        local = -support + .02*((times-seed[i])/halfwidth)**2
        if i:
            dt = times[:,None]-nodes[-1]['times'][None,:]
            expected = (constraints[q]['seconds']-constraints[qs[i-1]]['seconds']) if q in constraints and qs[i-1] in constraints else (q-qs[i-1])*np.median(rates[max(0,i-4):i+5])
            penalty = tempo_weight*np.log(np.maximum(dt,.001)/expected)**2
            penalty[(dt < max(.008,expected*.35)) | (dt > expected*2.8+.02)] = np.inf
            mat = costs[None,:]+penalty;back=mat.argmin(1)
            costs=local+mat[np.arange(len(times)),back]
        else:
            costs,back=local,np.full(len(times),-1)
        if not np.any(np.isfinite(costs)):
            raise ValueError(f'No ordered pitch-attack path at q={q}')
        nodes.append(dict(q=float(q),times=times,support=support,seed=float(seed[i])))
        backs.append(back)
    k=int(np.argmin(costs));selected=[];rows=[]
    for i in range(len(qs)-1,-1,-1):
        selected.append(float(nodes[i]['times'][k]))
        rows.append(dict(q=float(qs[i]),seconds=selected[-1],seed=nodes[i]['seed'],
            pitch_attack_evidence=float(nodes[i]['support'][k]),pitches=sorted(groups[qs[i]]),reviewed_constraint=qs[i] in constraints))
        k=backs[i][k]
    return qs,np.array(selected[::-1]),rows[::-1]


def export_clock(score, audio, qgrid, tgrid, ts, rms, guide_q=None, guide_t=None):
    sr,samples=audio['sample_rate'],audio['samples'];total=qvalue(score['total_q'])
    last=float(tgrid[-1]);tail=rms[ts>ts[-1]-.4];local=rms[(ts>=last)&(ts<last+2)]
    threshold=max(float(np.median(tail))*4,float(np.max(local))*.02 if len(local) else 0)
    active=ts[(ts>last)&(rms>threshold)]
    release=min(samples/sr,max(last+.15,float(active[-1])) if len(active) else last+.5)
    qnodes=sorted(set([0.,total]+[qvalue(e['q']) for e in score['events']]+[qvalue(e['q'])+qvalue(e['duration']) for e in score['events']]))
    times=np.interp(qnodes,qgrid,tgrid);after=np.array(qnodes)>qgrid[-1]
    before=np.array(qnodes)<qgrid[0]
    if np.any(before):
        if guide_q is None or guide_t is None:
            raise ValueError('An opening rest needs a guide before the first physical attack')
        times[before]=np.interp(np.array(qnodes)[before],guide_q,guide_t)
    times[after]=np.interp(np.array(qnodes)[after],[qgrid[-1],total],[last,release])
    points=[[round(t*sr),q] for q,t in zip(qnodes,times)]
    if points[0][0]>0:
        points.insert(0,[0,0.])
    if points[-1][0]<samples:
        points.append([samples,total])
    if any(b[0]<=a[0] or b[1]<a[1] for a,b in zip(points,points[1:])):
        raise ValueError('Refined clock is not monotone at sample precision')
    return dict(schema=1,points=points,notes=project_notes(score['events'],points,sr,samples),
        sample_rate=sr,samples=samples,source_sha256=score.get('source_sha256'),flags=[],
        method='register-aware coarse DTW + dense state/attack sequence + ordered pitch-attack chain + source-ordered ornaments',
        review_required=True,accuracy_claim=None,physical_attacks_measured=False,
        revision_evidence={'release':{'seconds':release,'threshold':threshold,'criterion':'RMS decay display projection'},
                           'all_physical_attacks_measured':False})


def apply_local_clock_patch(baseline, candidate, score, start_q, end_q):
    """Replace only an independently reviewed open interval; keep boundary samples."""
    if not start_q < end_q:
        raise ValueError('Local interval must have positive extent')
    if baseline.get('source_sha256') != score.get('source_sha256') or candidate.get('source_sha256') != score.get('source_sha256'):
        raise ValueError('Local patch source identity mismatch')
    if (baseline['sample_rate'],baseline['samples']) != (candidate['sample_rate'],candidate['samples']):
        raise ValueError('Local patch audio sample domain mismatch')
    qq={float(q):int(t) for t,q in candidate['points']}
    existing={float(q) for t,q in baseline['points']}
    if start_q not in existing or end_q not in existing:
        raise ValueError('Local patch boundaries must be explicit baseline points')
    result=deepcopy(baseline)
    result['points']=[[qq[float(q)] if start_q<q<end_q else t,q] for t,q in baseline['points']]
    if any(b[0]<=a[0] or b[1]<a[1] for a,b in zip(result['points'],result['points'][1:])):
        raise ValueError('Local patch folds the clock at a boundary')
    result['notes']=project_notes(score['events'],result['points'],result['sample_rate'],result['samples'])
    result['review_required']=True
    result.setdefault('revision_evidence',{})['local_interval_exclusive']=[start_q,end_q]
    result['revision_evidence']['grace_status']='reproject source-ordered grace candidates after local clock replacement'
    return result


def apply_exact_constraints(alignment, score, constraints):
    """Insert exact clock knots, preserving initial silence and final recording tail."""
    sr,samples=alignment['sample_rate'],alignment['samples'];total=qvalue(score['total_q'])
    points=alignment['points']
    for q,row in sorted(constraints.items()):
        if not row.get('exact'):
            continue
        target=round(row['seconds']*sr)
        points=[point for point in points if abs(point[1]-q)>1e-9]
        points.append([target,q])
        if q==0 and target>0:
            points.append([0,0.])
        if q==total and target<samples:
            points.append([samples,total])
    points.sort(key=lambda p:(p[1],p[0]))
    if any(b[0]<=a[0] or b[1]<a[1] for a,b in zip(points,points[1:])):
        raise ValueError('Exact reviewed clock constraint conflicts with neighboring candidate times')
    alignment['points']=points
    alignment['notes']=project_notes(score['events'],points,sr,samples)
    return alignment


def audit_alignment(score, alignment, ts, rise, lo, baseline=None):
    groups={}
    for event in attacks(score['events']):
        groups.setdefault(qvalue(event['q']),set()).add(int(event['pitch']))
    points=np.asarray(alignment['points'],float);rows=[]
    for q,pitches in sorted(groups.items()):
        time=float(np.interp(q,points[:,1],points[:,0]/alignment['sample_rate']))
        ii=np.flatnonzero(abs(ts-time)<.22)
        evidence=np.log1p(rise[ii][:,np.array(sorted(pitches))-lo]).mean(1) if len(ii) else np.array([])
        peaks=find_peaks(evidence,distance=2)[0] if len(evidence) else []
        nearest=min(peaks,key=lambda k:abs(ts[ii[k]]-time)) if len(peaks) else None
        peak=float(ts[ii[nearest]]) if nearest is not None else None
        row=dict(q=q,seconds=time,pitches=sorted(pitches),nearest_pitch_flux_peak_seconds=peak,
            signed_nearest_peak_residual_seconds=peak-time if peak is not None else None,
            peak_evidence=float(evidence[nearest]) if nearest is not None else 0,
            measurement_scope='mixture pitch-flux consistency, not isolated-instrument ground truth')
        if baseline:
            bp=np.asarray(baseline['points']);old=float(np.interp(q,bp[:,1],bp[:,0]/baseline['sample_rate']))
            row.update(baseline_seconds=old,correction_seconds=time-old)
        rows.append(row)
    residual=[r['signed_nearest_peak_residual_seconds'] for r in rows if r['signed_nearest_peak_residual_seconds'] is not None]
    summary=dict(all_nongrace_attack_nodes=len(rows),no_local_peak=len(rows)-len(residual),
        local_flux_peak_within_30ms=sum(abs(x)<=.03001 for x in residual),
        local_flux_peak_within_80ms=sum(abs(x)<=.08001 for x in residual),
        local_flux_signed_residual_quantiles=np.percentile(residual,[0,5,25,50,75,95,100]).tolist() if residual else None,
        scope='all attack nodes; feature consistency is not independent measured timing accuracy')
    return rows,summary


def refine_movement(out_dir, *, source_path=None, constraints=None, config=None, output_path=None):
    """Run portable candidate generation; default output never overwrites approved alignment.

    ``constraints`` is a reviewed list or {source_sha256, rows}; ``source_path``
    must be the canonical unexpanded MusicXML/MXL used to prepare score.json.
    Pass output_path=out_dir/'alignment.json' only when intentionally rebuilding.
    """
    out=Path(out_dir);config=dict(config or {})
    score=json.loads((out/'score.json').read_text());audio=json.loads((out/'audio.json').read_text())
    if score.get('route_unresolved'):
        raise ValueError('Resolve the performed repeat/jump route before refinement')
    if not attacks(score['events']):
        raise ValueError('No pitched source attacks')
    lo,hi=pitch_bounds(score['events'])
    reviewed=validate_constraints(constraints,score,audio['samples']/audio['sample_rate'])
    master=out/audio['path'];h=hashlib.sha256()
    with master.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):
            h.update(block)
    input_binding={
        'schema':1,
        'score_json_sha256':hashlib.sha256((out/'score.json').read_bytes()).hexdigest(),
        'source_score_sha256':score.get('source_sha256'),
        'source_route':score.get('source_route'),
        'audio':{**{k:audio.get(k) for k in ['source_sha256','sample_rate','samples','channels','bits']},
                 'prepared_sha256':h.hexdigest(),'audio_range':audio.get('audio_range')},
    }
    baseline=None
    if config.get('use_existing_guide'):
        baseline=json.loads((out/'alignment.json').read_text())
        complete=(bool(input_binding['source_score_sha256']) and bool(input_binding['source_route'])
                  and all(input_binding['audio'].get(k) is not None for k in
                          ['source_sha256','sample_rate','samples','channels','bits','prepared_sha256']))
        if (not complete or baseline.get('input_binding')!=input_binding
                or baseline.get('source_sha256')!=score.get('source_sha256')
                or baseline.get('sample_rate')!=audio['sample_rate']
                or baseline.get('samples')!=audio['samples']):
            raise ValueError('Existing guide lacks matching complete score/route/recording/PCM/range binding; create a fresh candidate')
    key=f'{h.hexdigest()}:{lo}:{hi}:feature-v2'
    cache=out/'alignment-features.npz';keyfile=out/'alignment-features-key.json'
    names=['ts','rise','change','ct','cqt','rms']
    if cache.exists() and keyfile.exists() and json.loads(keyfile.read_text()).get('key')==key:
        with np.load(cache,allow_pickle=False) as z:
            features={n:z[n] for n in names}
    else:
        features=dict(zip(names,extract_features(master,out,audio['channels'],lo,hi)))
        np.savez_compressed(cache,**features)
        keyfile.write_text(json.dumps({'key':key,'rebuildable':True}))
    if config.get('use_existing_guide'):
        # Duplicate q represents initial silence/tail dwell. Keep onset-side time.
        points={float(q):float(t)/audio['sample_rate'] for t,q in baseline['points'] if q<qvalue(score['total_q'])}
        gq=np.array(sorted(points));gt=np.array([points[q] for q in gq])
        coarse={'method':'existing recording-bound clock used only as broad candidate guide','reviewed':False}
    else:
        gq,gt,coarse=register_coarse_guide(score,features,lo,hi,int(config.get('coarse_max_axis',2000)))
    guide_constraints=dict(reviewed);initial=None
    if not config.get('use_existing_guide'):
        initial=initial_attack_candidate(score,features,lo,float(config.get('initial_search_seconds',10.)))
        if initial and initial['q'] not in guide_constraints:
            guide_constraints[initial['q']]=initial
    qdense,tdense,parameters=dense_sequence(score,features,lo,hi,gq,gt,guide_constraints,config)
    corrected=correct_guide(qdense,tdense,reviewed)
    qs,tt,chain=refine_attack_chain(score['events'],features['ts'],features['rise'],lo,qdense,corrected,reviewed,config)
    result=export_clock(score,audio,qs,tt,features['ts'],features['rms'],qdense,corrected)
    result=apply_exact_constraints(result,score,reviewed)
    result['audio_source_sha256']=audio.get('source_sha256')
    result['input_binding']=input_binding
    result['parameters']={**parameters,**config,'coarse':coarse,'pitch_range':[lo,hi]}
    result['reviewed_constraints']=list(reviewed.values())
    from .refinement_graces import source_metadata,build_grace_groups,match_grace_groups,apply_grace_candidates
    grace_rows=[]
    if any(e.get('grace') and e.get('is_player',True) for e in score['events']):
        if source_path is None:
            raise ValueError('Canonical source_path is required to resolve ornament ownership')
        source=Path(source_path)
        if hashlib.sha256(source.read_bytes()).hexdigest()!=score.get('source_sha256'):
            raise ValueError('Grace source differs from prepared score')
        from .score import read_xml
        groups=build_grace_groups(score,source_metadata(read_xml(source)))
        # The complete clock extends beyond the last attack to post-trill tails.
        # q=total has a notation release followed by the complete recording tail.
        # Ornament ownership uses the release boundary, not the file-end dwell.
        grace_clock={}
        total=qvalue(score['total_q'])
        for sample,q in result['points']:
            if q<total or q not in grace_clock:
                grace_clock[q]=sample/audio['sample_rate']
        gqs=np.array(sorted(grace_clock));gts=np.array([grace_clock[q] for q in gqs])
        grace_rows=match_grace_groups(groups,features['ts'],features['rise'],lo,gqs,gts)
        apply_grace_candidates(result,groups,grace_rows)
    rows,summary=audit_alignment(score,result,features['ts'],features['rise'],lo,baseline)
    for row in rows:
        residual=row['signed_nearest_peak_residual_seconds']
        if residual is None or abs(residual)>.08001:
            result['flags'].append({'q':row['q'],'sample':round(row['seconds']*audio['sample_rate']),
                'reason':'no_local_pitch_flux_peak' if residual is None else 'pitch_flux_residual_requires_sequence_review',
                'signed_nearest_peak_residual_seconds':residual})
    result['revision_evidence']['all_attack_audit']=summary
    result['revision_evidence']['grace_groups']=len(grace_rows)
    result['revision_evidence']['initial_attack_candidate']=initial
    if initial and initial['q'] not in reviewed:
        result['flags'].append({'q':initial['q'],'reason':'initial_attack_candidate_requires_recording_review'})
    target=Path(output_path) if output_path else out/'alignment-refined.json'
    target.parent.mkdir(parents=True,exist_ok=True)
    prefix=target.with_suffix('')
    def write(path,data):
        path.write_text(json.dumps(data,ensure_ascii=False,indent=2))
    write(Path(str(prefix)+'-graces.json'),grace_rows)
    write(Path(str(prefix)+'-audit.json'),summary)
    write(Path(str(prefix)+'-chain.json'),chain)
    with gzip.open(Path(str(prefix)+'-every-attack.jsonl.gz'),'wt') as stream:
        for row in rows:
            stream.write(json.dumps(row)+'\n')
    result['evidence_files']=[p.name for p in [Path(str(prefix)+'-graces.json'),Path(str(prefix)+'-audit.json'),Path(str(prefix)+'-chain.json'),Path(str(prefix)+'-every-attack.jsonl.gz')]]
    write(target,result)
    if target.resolve()==(out/'alignment.json').resolve():
        (out/'alignment-review.json').unlink(missing_ok=True)
    return result
