"""Robust source-tempo contracts; v1/v2 experiment bytes remain unchanged."""
from pathlib import Path
import hashlib,xml.etree.ElementTree as ET
import numpy as np
from . import guarded_alignment_v2 as v2
from . import guarded_alignment as v1
from .guarded_alignment_v2 import local_features,guide_rates,candidate_disagreement,grace_confidence_gate
from score_sync.alignment import qvalue

def imported_provenance(dependency_paths=()):
    r=v2.imported_provenance(dependency_paths)
    r['dependencies'][str(Path(__file__).resolve())]=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return r

def source_tempo_events(score,source_xml):
    out=v2.source_tempo_events(score,source_xml)
    source=ET.parse(source_xml).getroot().find('part').findall('measure')
    inherited={};active=None
    for i,m in enumerate(source,1):
        inherited[i]=active
        for node in m.findall('.//sound'):
            if 'tempo'in node.attrib:
                value=float(node.attrib['tempo'])
                if np.isfinite(value)and value>0:active=value
    previous=None
    for m in score['measures']:
        i=int(m['source_index']);q=qvalue(m['q'])
        if previous is None or i!=previous+1:
            # No duplicate if an explicit tempo/restoration already exists at q.
            if not any(abs(r['q']-q)<1e-9 for r in out):
                out.append({'q':q,'source_index':i,'tempo_metadata':inherited[i],
                    'words':'source tempo inherited at route/fragment beginning'if inherited[i]else 'source tempo unknown at route/fragment beginning'})
        previous=i
    return sorted(out,key=lambda r:r['q'])

def source_tempo_hypothesis(sq,endpoints,tempo_events,exponent):
    if not 0<=exponent<=1:raise ValueError('Tempo exponent outside[0,1]')
    start,end=float(sq[0]),float(sq[-1]);events=[r for r in tempo_events if r['q']<=end]
    breaks=sorted({start,end}|{float(r['q'])for r in events if start<r['q']<end})
    used=[];bpms=[]
    for a,b in zip(breaks,breaks[1:]):
        previous=[r for r in events if r['q']<=a+1e-9];row=previous[-1]if previous else None
        bpm=row.get('tempo_metadata')if row else None
        known=bpm is not None and np.isfinite(bpm)and bpm>0
        bpms.append(float(bpm)if known else None);used.append({'q':[a,b],'metadata':row})
    missing=any(v is None for v in bpms);effective=0. if missing else exponent
    # Flat is dimensionless. Unknown metadata never becomes a fictitious1bpm.
    factors=np.ones(len(bpms))if effective==0 else np.asarray(bpms,float)**(-effective)
    raw=np.diff(breaks)*factors;scale=(endpoints[1]-endpoints[0])/raw.sum()
    times=np.r_[endpoints[0],endpoints[0]+np.cumsum(raw)*scale]
    guide=np.interp(sq,breaks,times);ids=np.clip(np.searchsorted(breaks,sq,side='right')-1,0,len(factors)-1)
    actual=[]
    for i in range(1,len(bpms)):
        if bpms[i]is None or bpms[i-1]is None or abs(bpms[i]-bpms[i-1])>1e-9:actual.append(breaks[i])
    return guide,factors[ids]*scale,{'exponent':exponent,'effective_exponent':effective,
      'missing_tempo_metadata':missing,'fallback':'whole_window_dimensionless_flat'if missing else None,
      'source_breaks_q':breaks,'effective_tempo_boundaries_q':actual,'guide_breaks_seconds':times.tolist(),
      'sections':used,'purpose':'relative metadata hypothesis only; performance remains audio-conditioned'}

def run_hypothesis(data,guide,rates,halfwidth_seconds,terminal_radius_seconds=0.,source_boundaries=()):
    r=v2.run_hypothesis(data,guide,rates,halfwidth_seconds,terminal_radius_seconds,source_boundaries)
    if not r.get('path'):return r
    q=np.asarray(r['path']['q']);t=np.asarray(r['path']['seconds']);mid=(q[:-1]+q[1:])/2
    low,_=v1.reachable_slopes(rates,data['step_q'],data['audio_hop'])
    saturation=np.isclose(np.diff(t)/np.diff(q),np.interp(q[1:],data['score_q'],low),atol=1e-6)
    cuts=sorted({q[0],q[-1]}|{float(v)for v in source_boundaries if q[0]<v<q[-1]});segments=[]
    for a,b in zip(cuts,cuts[1:]):
        if b-a<4:continue
        dur=np.diff(np.interp(np.linspace(a,b,4),q,t));ratio=float(dur.max()/max(1e-9,dur.min()))
        mask=(mid>=a)&(mid<b);fraction=float(saturation[mask].mean())if mask.any()else 0.
        risk=ratio>2.5 and fraction>.25
        segments.append({'q':[float(a),float(b)],'third_duration_ratio':ratio,
          'fastest_reachable_step_fraction':fraction,'requires_review':risk})
    if any(s['requires_review']for s in segments):
        r['reasons'].append('within_source_tempo_region_compression_and_saturation')
        r['status']='rejected_for_independent_review'
    r['diagnostics']['within_tempo_region_guards']=segments
    r['automatic_application_allowed']=False
    return r
