"""Source-tempo hypothesis and diagnostic refinement; isolated development v2.

Phase-A module is immutable. XML tempo metadata supplies alternative relative
priors, never exact performance times. No implicit automatic acceptance exists.
"""
from pathlib import Path
from fractions import Fraction
import copy,hashlib,json,xml.etree.ElementTree as ET
import numpy as np
from . import guarded_alignment as v1
from .guarded_alignment import local_features,guide_rates,candidate_disagreement
from score_sync.alignment import qvalue

def imported_provenance(dependency_paths=()):
    result=v1.imported_provenance()
    base=Path(v1.legacy.__file__).parent
    files=[base/'alignment.py',base/'refinement_graces.py',Path(v1.__file__),Path(__file__),*map(Path,dependency_paths)]
    result['dependencies']={str(p.resolve()):hashlib.sha256(p.read_bytes()).hexdigest()for p in files}
    return result

def source_tempo_events(score,source_xml):
    """Map first-part source tempo metadata through actual performance route."""
    root=ET.parse(source_xml).getroot();part=root.find('part')
    if part is None:raise ValueError('No canonical partwise source')
    source={};div=1;active=None
    for mi,m in enumerate(part.findall('measure'),1):
        div=int(m.findtext('attributes/divisions',str(div)));cursor=Fraction(0);rows=[]
        inherited=active
        for node in m:
            if node.tag=='backup':cursor-=Fraction(node.findtext('duration','0'))/div
            elif node.tag=='forward':cursor+=Fraction(node.findtext('duration','0'))/div
            elif node.tag=='note'and node.find('chord')is None and node.find('grace')is None:
                cursor+=Fraction(node.findtext('duration','0'))/div
            elif node.tag in ('direction','sound'):
                snd=[node]if node.tag=='sound'else node.findall('sound')
                for s in snd:
                    if 'tempo'not in s.attrib:continue
                    bpm=float(s.attrib['tempo'])
                    if not np.isfinite(bpm)or bpm<=0:continue
                    at=cursor+Fraction(node.findtext('offset','0'))/div
                    words=' '.join((w.text or '').strip()for w in node.findall('.//words'))
                    rows.append({'source_index':mi,'offset_q':float(at),'tempo_metadata':bpm,'words':words})
                    active=bpm
        source[mi]={'inherited_tempo':inherited,'events':rows}
    out=[];previous=None
    for m in score['measures']:
        i=int(m['source_index']);q=qvalue(m['q']);entry=source[i]
        # Restore source tempo on route jumps rather than retaining a later tempo.
        if previous is not None and i!=previous+1 and entry['inherited_tempo']:
            out.append({'q':q,'source_index':i,'tempo_metadata':entry['inherited_tempo'],'words':'source tempo restored at route jump'})
        for row in entry['events']:
            out.append({**row,'q':q+row['offset_q']})
        previous=i
    return sorted(out,key=lambda r:r['q'])

def source_tempo_hypothesis(sq,endpoints,tempo_events,exponent):
    """Integrate tempo^-gamma, normalize only total duration to outer evidence."""
    if exponent<0 or exponent>1:raise ValueError('Exploratory tempo exponent must be in[0,1]')
    start,end=float(sq[0]),float(sq[-1]);events=[r for r in tempo_events if r['q']<=end]
    breaks=sorted({start,end}|{float(r['q'])for r in events if start<r['q']<end})
    factors=[];used=[]
    for a,b in zip(breaks,breaks[1:]):
        previous=[r for r in events if r['q']<=a+1e-9]
        row=previous[-1]if previous else None
        # Unknown metadata yields a flat hypothesis; uncertainty remains explicit.
        bpm=row['tempo_metadata']if row else 1.
        factors.append(bpm**(-exponent));used.append({'q':[a,b],'metadata':row})
    lengths=np.diff(breaks);raw=lengths*np.asarray(factors);duration=endpoints[1]-endpoints[0]
    scale=duration/raw.sum();times=np.r_[endpoints[0],endpoints[0]+np.cumsum(raw)*scale]
    guide=np.interp(sq,breaks,times)
    ids=np.clip(np.searchsorted(breaks,sq,side='right')-1,0,len(factors)-1)
    seconds_per_q=np.asarray(factors)[ids]*scale
    return guide,seconds_per_q,{'exponent':exponent,'source_breaks_q':breaks,
       'guide_breaks_seconds':times.tolist(),'sections':used,
       'purpose':'relative source-tempo prior; normalized duration only; not metronomic output'}

def run_hypothesis(data,guide,rates,halfwidth_seconds,terminal_radius_seconds=0.,source_boundaries=()):
    r=v1.run_hypothesis(data,guide,rates,halfwidth_seconds,terminal_radius_seconds)
    if not r.get('path'):return r
    q=np.asarray(r['path']['q']);t=np.asarray(r['path']['seconds']);mid=(q[1:]+q[:-1])/2
    slopes=np.diff(t)/np.diff(q);lo,_=v1.reachable_slopes(rates,data['step_q'],data['audio_hop'])
    minrate=np.interp(q[1:],data['score_q'],lo);sat=np.isclose(slopes,minrate,atol=1e-6)
    windows=[]
    for length in (8.,16.,32.):
        for a in np.arange(q[0],q[-1]-length+1e-8,length/2):
            b=a+length;m=(a+b)/2;times=np.interp([a,m,b],q,t);dur=np.diff(times)
            ratio=float(dur.max()/max(1e-9,dur.min()));mask=(mid>=a)&(mid<b)
            saturation=float(sat[mask].mean())if mask.any()else 0.
            confounded=any(a<z<b for z in source_boundaries)
            if ratio>2.5 or saturation>.25:
                windows.append({'q':[float(a),float(b)],'half_duration_ratio':ratio,
                 'fastest_reachable_step_fraction':saturation,'crosses_source_tempo_boundary':confounded,
                 'requires_shape_review':bool(ratio>2.5 and saturation>.25 and not confounded)})
    reasons=list(r.get('reasons',[]))
    if source_boundaries and 'phrase_compression_and_step_saturation'in reasons:
        reasons.remove('phrase_compression_and_step_saturation')
    if any(w['requires_shape_review']for w in windows):reasons.append('local_phrase_compression_and_step_saturation')
    r['reasons']=reasons;r['status']='rejected_for_independent_review'if reasons else 'eligible_for_independent_review'
    r['automatic_application_allowed']=False
    r['diagnostics']['sliding_source_score_windows']=windows
    r['diagnostics']['source_tempo_boundaries_q']=list(source_boundaries)
    return r

def grace_confidence_gate(rows,reviewed_windows=None):
    out=v1.grace_confidence_gate(rows,reviewed_windows)
    for r in out:
        r['feature_consistency_without_detected_conflict']=r.pop('may_auto_apply')
        r['automatic_application_allowed']=False
        r['status']='requires_identity_review'if r['review_reasons']else 'eligible_for_independent_review'
    return out
