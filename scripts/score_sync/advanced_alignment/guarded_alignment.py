"""Isolated hypothesis/diagnostic experiment; never writes production or imports repo code.

Caller supplies source/audio and candidate guides. No work-specific timestamps
or observed holdout times live here. Output is eligible for independent review,
never a claim of transcription or automatic ground truth.
"""
from pathlib import Path
import ast,copy,hashlib,inspect,sys
import numpy as np
from scipy.ndimage import gaussian_filter1d,median_filter

from score_sync import alignment_pipeline as legacy
from score_sync.alignment import qvalue,occupancy,descriptor

def imported_provenance():
    return {'module':str(Path(legacy.__file__).resolve()),
            'sha256':hashlib.sha256(Path(legacy.__file__).read_bytes()).hexdigest(),
            'step_table':step_table()}

def step_table():
    """Read the actual imported code's (code,di,dj) table, not a hardcoded floor."""
    fn=getattr(legacy.banded_sequence_path,'py_func',legacy.banded_sequence_path)
    tree=ast.parse(inspect.getsource(fn))
    for node in ast.walk(tree):
        if isinstance(node,ast.Assign) and any(isinstance(x,ast.Name)and x.id=='steps'for x in node.targets):
            return [list(x)for x in ast.literal_eval(node.value)]
    raise RuntimeError('Cannot prove imported DP step table')

def reachable_slopes(rates,step_q,audio_hop,ratio_bounds=(.4,2.5)):
    rates=np.asarray(rates,float);ratios=np.array([dj/di for _,di,dj in step_table()])
    ok=(ratios[:,None]/rates[None,:]>=ratio_bounds[0])&(ratios[:,None]/rates[None,:]<=ratio_bounds[1])
    lows=np.min(np.where(ok,ratios[:,None],np.inf),axis=0)*audio_hop/step_q
    highs=np.max(np.where(ok,ratios[:,None],-np.inf),axis=0)*audio_hop/step_q
    return lows,highs

def norm(x):return x/np.maximum(np.linalg.norm(x,axis=1,keepdims=True),1e-6)

def local_features(score,features,lo,hi,start_q,end_q,time_bounds,step_q=.03125,audio_hop=.01):
    count=round((end_q-start_q)/step_q)
    if abs(start_q+count*step_q-end_q)>1e-9:raise ValueError('Local score span must fit step grid')
    sq=np.arange(count+1)*step_q+start_q
    ts=np.arange(time_bounds[0],time_bounds[1]+audio_hop/2,audio_hop)
    events=[]
    for e in score['events']:
        q=qvalue(e['q']);d=qvalue(e['duration'])
        if q+d<=start_q or q>end_q:continue
        z=copy.copy(e);z['q']=q-start_q;events.append(z)
    occ=occupancy(events,end_q-start_q,lo,hi,step_q)
    x=descriptor(occ,lo).astype(np.float32)
    y=descriptor(np.stack([np.interp(ts,features['ct'],features['cqt'][:,p])for p in range(hi-lo+1)],axis=1),lo).astype(np.float32)
    a=np.zeros_like(occ)
    for e in legacy.attacks(events):
        i=round(qvalue(e['q'])/step_q);p=int(e['pitch'])-lo
        if 0<=i<len(a):a[i,p]=1
    a=norm(gaussian_filter1d(a,.7,axis=0)).astype(np.float32)
    b=norm(np.stack([np.interp(ts,features['ts'],np.log1p(features['rise'][:,p]))for p in range(hi-lo+1)],axis=1)).astype(np.float32)
    return {'score_q':sq,'audio_t':ts,'x':x,'y':y,'a':a,'b':b,
            'step_q':step_q,'audio_hop':audio_hop,'events':events,'pitch_low':lo}

def guide_hypothesis(sq,source_q,source_t,endpoints,kind):
    """Old shape and independent secant are hypotheses, not output interpolators."""
    if kind=='independent_secant':return np.interp(sq,[sq[0],sq[-1]],endpoints)
    if kind!='legacy_shape':raise ValueError('Unknown guide hypothesis')
    old=np.interp(sq,source_q,source_t)
    # Actual compatibility warp in time, preserving internal proportions.
    return np.interp(old,[old[0],old[-1]],endpoints)

def guide_rates(sq,guide,step_q,audio_hop,rate_kind):
    if rate_kind=='independent_secant':
        spq=(guide[-1]-guide[0])/(sq[-1]-sq[0])
        return np.full(len(sq),spq*step_q/audio_hop)
    if rate_kind!='legacy_local':raise ValueError('Unknown rate hypothesis')
    left,right=np.maximum(sq[0],sq-2),np.minimum(sq[-1],sq+2)
    tempo=(np.interp(right,sq,guide)-np.interp(left,sq,guide))/np.maximum(.01,right-left)
    return np.clip(median_filter(tempo,size=max(3,int(4/step_q))|1)*step_q/audio_hop,.4,8.)

def run_hypothesis(data,guide,rates,halfwidth_seconds,terminal_radius_seconds=0.):
    sq,ts=data['score_q'],data['audio_t'];hop=data['audio_hop'];step=data['step_q']
    centers=np.round((guide-ts[0])/hop).astype(np.int64)
    bounds=reachable_slopes(rates,step,hop)
    if np.any(~np.isfinite(bounds[0])):return {'status':'rejected_unreachable_rate','path':None}
    try:
        raw=legacy.banded_sequence_path(data['x'],data['y'],data['a'],data['b'],centers,
            round(halfwidth_seconds/hop),rates,terminal_radius=round(terminal_radius_seconds/hop))
    except ValueError as exc:return {'status':'rejected_no_connected_path','error':str(exc),'path':None}
    q,t=sq[raw[:,0]],ts[raw[:,1]]
    unique=np.unique(q);med=np.array([np.median(t[q==v])for v in unique])
    # Every candidate is evaluated on the same uniform score grid, preventing
    # fast step/skipped-cell paths from winning via fewer evaluated score states.
    uniform=np.interp(sq,unique,med)
    yy=np.stack([np.interp(uniform,ts,data['y'][:,k])for k in range(data['y'].shape[1])],axis=1)
    bb=np.stack([np.interp(uniform,ts,data['b'][:,k])for k in range(data['b'].shape[1])],axis=1)
    state=np.sum(data['x']*yy,axis=1);attack=np.sum(data['a']*bb,axis=1)
    indices=raw[:,0];slope=np.diff(t)/np.diff(q)
    lower=bounds[0][indices[1:]];upper=bounds[1][indices[1:]]
    at_min=np.isclose(slope,lower,atol=1e-6);at_max=np.isclose(slope,upper,atol=1e-6)
    # Broad equal-score blocks are a shape diagnostic, not an assumed uniform tempo.
    edges=np.linspace(sq[0],sq[-1],4);dur=np.diff(np.interp(edges,unique,med))
    shape_ratio=float(dur.max()/max(1e-9,dur.min()))
    reasons=[]
    if shape_ratio>2.5 and np.mean(at_min)>.25:reasons.append('phrase_compression_and_step_saturation')
    proximity=np.abs(t-guide[indices])/halfwidth_seconds
    if np.mean(proximity>.95)>.05:reasons.append('path_tracks_corridor_edge')
    return {'status':'rejected_for_independent_review'if reasons else 'eligible_for_independent_review',
       'reasons':reasons,'path':{'q':unique.tolist(),'seconds':med.tolist()},
       'diagnostics':{'state_support_mean':float(np.mean(state)),'attack_support_mean':float(np.mean(attack)),
          'uniform_score_cost':float(np.mean(.7*(1-state)+.3*(1-attack))),
          'fastest_allowed_step_fraction':float(np.mean(at_min)),
          'slowest_allowed_step_fraction':float(np.mean(at_max)),
          'reachable_seconds_per_q_minmax':[float(bounds[0].min()),float(bounds[1].max())],
          'equal_score_block_durations':dur.tolist(),'equal_score_duration_ratio':shape_ratio,
          'corridor_edge_fraction':float(np.mean(proximity>.95)),
          'max_guide_departure_seconds':float(np.max(abs(t-guide[indices]))),
          'strict_path_monotonicity':bool(np.all(np.diff(t)>0)&np.all(np.diff(q)>0)),
          'halfwidth_seconds':halfwidth_seconds,'terminal_radius_seconds':terminal_radius_seconds}}

def grace_confidence_gate(rows,reviewed_windows=None):
    """Return review diagnostics without changing ownership, lyrics or ranges."""
    reviewed_windows=reviewed_windows or {};out=[]
    for row in rows:
        reasons=[]
        if row['status']!='audio_peak_candidate':reasons.append('unresolved_acoustic_candidate')
        if row.get('overlaps_previous_pitch'):reasons.append('same_pitch_predecessor_ambiguity')
        outside=[]
        if row.get('search_interval'):
            lo,hi=row['search_interval']
            for c in row.get('clusters',[]):
                for eid in c['ids']:
                    if eid not in reviewed_windows:continue
                    a,b=reviewed_windows[eid]
                    if b<lo or a>hi:outside.append(eid)
            if outside:reasons.append('search_excludes_independent_evidence')
        out.append({'group_id':row['group_id'],'source_ownership':row['ownership'],
                    'candidate_status':row['status'],'may_auto_apply':not reasons,
                    'review_reasons':reasons,'outside_independent_evidence_ids':outside,
                    'scope':'identifiability gate, not proof that every overlapping-pitch ornament is wrong'})
    return out

def candidate_disagreement(results):
    """Keep competing paths visible; same-feature rank is not independent validation."""
    valid=[(k,v)for k,v in results.items()if v.get('path')]
    rows=[]
    for i,(a,x)in enumerate(valid):
        for b,y in valid[i+1:]:
            p,r=x['path'],y['path'];q=np.linspace(max(p['q'][0],r['q'][0]),min(p['q'][-1],r['q'][-1]),500)
            delta=np.interp(q,p['q'],p['seconds'])-np.interp(q,r['q'],r['seconds'])
            rows.append({'a':a,'b':b,'median_abs_seconds':float(np.median(abs(delta))),
                         'max_abs_seconds':float(np.max(abs(delta))),
                         'meaning':'disagreement requires independent evidence; not an error estimate'})
    return rows
