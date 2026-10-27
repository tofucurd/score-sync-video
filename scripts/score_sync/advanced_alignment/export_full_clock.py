"""Export source clock with a distinct acoustic decay and notated silent tail.

A fermata attached to a rest is not a sounding-note extension. The final silent
notation must have a display interval even when the acoustic decay ends exactly
at that rest's start. No recording samples are trimmed or stretched.
"""
from fractions import Fraction
import numpy as np
from score_sync.alignment import qvalue,project_notes

def export_clock(score,audio,qgrid,tgrid,ts,rms,guide_q,guide_t,terminal_rest_policy):
    policy=terminal_rest_policy;sr=audio['sample_rate'];samples=audio['samples'];duration=samples/sr
    total=qvalue(score['total_q']);last=float(qgrid[-1]);last_time=float(tgrid[-1]);rest=float(policy['rest_q']);fermata=float(policy['fermata_rest_q'])
    if policy.get('source_sha256')!=score.get('source_sha256')or last!=float(policy['last_attack_q'])or not last<rest<fermata<total:raise ValueError('Source-bound terminal rest policy mismatch')
    if any(qvalue(e['q'])+qvalue(e['duration'])>rest+1e-9 for e in score['events']if e.get('pitch')is not None and not e.get('grace')and e.get('is_player',True)):raise ValueError('Sounding source material extends beyond declared terminal rest')
    count=min(int(policy.get('tempo_interval_count',4)),len(qgrid)-1);rate=float(np.median(np.diff(tgrid[-count-1:])/np.diff(qgrid[-count-1:])))
    if not np.isfinite(rate)or rate<=0:raise ValueError('Invalid final contextual rate')
    rest_time=last_time+(rest-last)*rate;fermata_time=last_time+(fermata-last)*rate
    tail=rms[ts>ts[-1]-.4];local=rms[(ts>=last_time)&(ts<last_time+2)]
    threshold=max(float(np.median(tail))*4,float(np.max(local))*.02 if len(local)else 0)
    active=ts[(ts>last_time)&(rms>threshold)];decay=max(last_time+.15,float(active[-1]))if len(active)else last_time+.5
    # At least the written final silent duration at adjacent contextual tempo.
    # This is a display convention, not an independently measured release.
    context_end=last_time+(total-last)*rate;display_end=max(decay,context_end)
    if not last_time<rest_time<fermata_time<display_end<=duration:raise ValueError('Final source/rest/audio intervals cannot be ordered')
    rational=lambda x:Fraction(*x)if isinstance(x,(list,tuple))else Fraction(str(x))
    nodes=sorted({Fraction(0),rational(score['total_q'])}|{rational(e['q'])for e in score['events']}|{rational(e['q'])+rational(e['duration'])for e in score['events']}|{rational(m[k])for m in score.get('measures',[])for k in ('q','end')})
    qq=np.array([float(q)for q in nodes]);times=np.interp(qq,qgrid,tgrid);before=qq<qgrid[0];after=qq>last
    times[before]=np.interp(qq[before],guide_q,guide_t);times[after]=np.interp(qq[after],[last,rest,fermata,total],[last_time,rest_time,fermata_time,display_end])
    points=[[round(t*sr),float(q)]for q,t in zip(qq,times)]
    if points[0][0]>0:points.insert(0,[0,0.])
    if points[-1][0]<samples:points.append([samples,total])
    if any(b[0]<=a[0]or b[1]<a[1]for a,b in zip(points,points[1:])):raise ValueError('Non-monotone source-node export')
    return {'schema':1,'points':points,'notes':project_notes(score['events'],points,sr,samples),'sample_rate':sr,'samples':samples,'source_sha256':score.get('source_sha256'),'flags':[],'review_required':True,'physical_attacks_measured':False,'accuracy_claim':None,
     'revision_evidence':{'signal_decay':{'seconds':decay,'threshold':threshold,'criterion':'bounded music-only RMS decay estimate, not physical per-instrument release'},'terminal_rest_projection':{'seconds_per_quarter':rate,'last_attack_seconds':last_time,'rest_start_seconds':rest_time,'fermata_rest_start_seconds':fermata_time,'notation_display_end_seconds':display_end,'minimum_written_rest_context_end_seconds':context_end,'physical_release_measured':False,'method':'Distinct silent-notation clock; acoustic decay is not the endpoint of a notated fermata rest'},'original_audio_duration_seconds':duration,'original_audio_preserved':True,'all_physical_attacks_measured':False}}
