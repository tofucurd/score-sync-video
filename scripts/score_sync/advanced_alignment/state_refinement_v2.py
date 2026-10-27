"""Version 2 final-chain research experiment, including cross-tempo edges.

No work-specific q/t values. The baseline branch preserves the installed
ordered pitch-flux objective. State context is a hypothesis, not vocal isolation.
For edges straddling a source tempo boundary, use the integral of the dense
audio-conditioned clock derivative, exactly its endpoint difference. One
midpoint region's rate cannot represent both parts of a straddling edge.
State weighting remains an unsuccessful hypothesis, not a recommended default.
"""
from collections import Counter
import numpy as np
from scipy.signal import find_peaks
from .guarded_alignment import legacy
from score_sync.alignment import qvalue

def refine(events,ts,rise,lo,qgrid,tgrid,state_data,constraints=None,
           source_boundaries=(),source_aware_rate=False,retain_state=False,
           halfwidth=2.,tempo_weight=4.,sustain_timescale=.25,state_strength=.75):
    constraints=constraints or {};groups={}
    for e in legacy.attacks(events):groups.setdefault(qvalue(e['q']),Counter())[int(e['pitch'])]+=1
    qs=np.array(sorted(groups),float);seed=np.interp(qs,qgrid,tgrid)
    left,right=np.maximum(qgrid[0],qs-8),np.minimum(qgrid[-1],qs+8)
    cuts=np.array(sorted({float(qgrid[0]),float(qgrid[-1])}|{float(q)for q in source_boundaries if qgrid[0]<q<qgrid[-1]}))
    regions=np.clip(np.searchsorted(cuts,qs,side='right')-1,0,len(cuts)-2)
    if source_aware_rate:
        left=np.maximum(left,cuts[regions]);right=np.minimum(right,cuts[regions+1])
    rates=np.maximum(.05,(np.interp(right,qgrid,tgrid)-np.interp(left,qgrid,tgrid))/np.maximum(.01,right-left))
    evidence=np.log1p(rise);nodes=[];backs=[];costs=None
    sx,sy=state_data['x'],state_data['y'];sq,st=state_data['score_q'],state_data['audio_t']
    for i,q in enumerate(qs):
        ii=np.flatnonzero(abs(ts-seed[i])<halfwidth)
        if not len(ii):raise ValueError('Empty candidate corridor')
        ps=np.array(list(groups[q]))-lo;weights=np.sqrt(np.array(list(groups[q].values()),float));weights/=weights.sum()
        ev=evidence[ii][:,ps]@weights;peaks=find_peaks(ev,prominence=.01,distance=2)[0]
        candidate=np.unique(np.r_[peaks,np.arange(0,len(ii),3)]);times=ts[ii[candidate]];support=ev[candidate]
        if q in constraints:
            target=constraints[q]['seconds'];tol=constraints[q].get('tolerance_seconds',.015)
            keep=abs(times-target)<tol;times,support=times[keep],support[keep]
            if constraints[q].get('exact'):times,support=np.array([],float),np.array([],float)
            times=np.r_[times,target];support=np.r_[support,float(np.interp(target,ts[ii],ev))]
            order=np.argsort(times);times,support=times[order],support[order]
        elif i==len(qs)-1:
            keep=abs(times-seed[i])<.30;times,support=times[keep],support[keep]
        if not len(times):raise ValueError('No endpoint/constraint candidate')
        next_q=qs[i+1]if i+1<len(qs)else q
        hold=max(0.,float(np.interp(next_q,qgrid,tgrid)-np.interp(q,qgrid,tgrid)))
        blend=hold/(hold+sustain_timescale)if hold else 0.
        state=np.zeros(len(times))
        if retain_state and hold>0:
            for frac in (.2,.5,.8):
                qctx=q+frac*(next_q-q)
                xctx=np.array([np.interp(qctx,sq,sx[:,k])for k in range(sx.shape[1])])
                yctx=np.stack([np.interp(times+frac*hold,st,sy[:,k])for k in range(sy.shape[1])],axis=1)
                state+=yctx@xctx/3
            local=-(1-.65*blend)*support+state_strength*blend*(1-state)+.02*((times-seed[i])/halfwidth)**2
        else:local=-support+.02*((times-seed[i])/halfwidth)**2
        expected=None
        if i:
            dt=times[:,None]-nodes[-1]['times'][None,:]
            if q in constraints and qs[i-1]in constraints:
                expected=constraints[q]['seconds']-constraints[qs[i-1]]['seconds']
            elif source_aware_rate and np.any((cuts>qs[i-1])&(cuts<q)):
                expected=float(np.interp(q,qgrid,tgrid)-np.interp(qs[i-1],qgrid,tgrid))
            else:
                ids=np.arange(max(0,i-4),min(len(qs),i+5))
                if source_aware_rate:
                    mid=(q+qs[i-1])/2;region=int(np.clip(np.searchsorted(cuts,mid,side='right')-1,0,len(cuts)-2))
                    ids=ids[regions[ids]==region]
                    if not len(ids):ids=np.array([i-1])
                expected=(q-qs[i-1])*np.median(rates[ids])
            penalty=tempo_weight*np.log(np.maximum(dt,.001)/expected)**2
            penalty[(dt<max(.008,expected*.35))|(dt>expected*2.8+.02)]=np.inf
            mat=costs[None,:]+penalty;back=mat.argmin(1);costs=local+mat[np.arange(len(times)),back]
        else:costs,back=local,np.full(len(times),-1)
        if not np.any(np.isfinite(costs)):raise ValueError(f'No ordered candidate path at q={q}')
        nodes.append({'q':q,'times':times,'support':support,'state':state,'seed':seed[i],
          'sustain_blend':blend,'expected_hold_seconds':hold,'expected_previous_gap_seconds':expected})
        backs.append(back)
    k=int(np.argmin(costs));selected=[];rows=[]
    for i in range(len(qs)-1,-1,-1):
        n=nodes[i];selected.append(float(n['times'][k]));rows.append({
          'q':float(n['q']),'seconds':selected[-1],'seed':float(n['seed']),
          'pitch_flux_support':float(n['support'][k]),'post_attack_state_support':float(n['state'][k]),
          'sustain_blend':float(n['sustain_blend']),'expected_hold_seconds':float(n['expected_hold_seconds']),
          'expected_previous_gap_seconds':None if n['expected_previous_gap_seconds']is None else float(n['expected_previous_gap_seconds']),
          'automatic_application_allowed':False})
        k=backs[i][k]
    return qs,np.array(selected[::-1]),rows[::-1]
