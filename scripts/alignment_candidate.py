"""Opt-in wide-corridor candidate from prepared source/feature data; no rendering."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from score_sync.alignment import qvalue
from score_sync import alignment_pipeline as base
from score_sync.advanced_alignment import full_alignment_core as core
from score_sync.advanced_alignment.state_refinement_v2 import refine
from score_sync.advanced_alignment.source_tempo_boundary_policy import complete_source_tempo_boundaries
from score_sync.advanced_alignment.export_full_clock import export_clock as terminal_export


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for key in ('score', 'audio', 'pcm', 'features', 'source', 'fit', 'output'):
        ap.add_argument('--' + key, type=Path, required=True)
    args = ap.parse_args()
    read = lambda p: json.loads(p.read_text())
    fit, score, audio = read(args.fit), read(args.score), read(args.audio)
    for key, path in [('score_sha256',args.score), ('audio_metadata_sha256',args.audio),
                      ('prepared_audio_sha256',args.pcm), ('features_sha256',args.features),
                      ('source_sha256',args.source)]:
        if fit.get(key) != sha(path):
            raise ValueError('Missing/mismatched input binding: ' + key)
    if score.get('source_sha256') != sha(args.source):
        raise ValueError('Original source does not match prepared score')
    if args.output.exists():
        raise ValueError('Use a fresh candidate output directory')
    anchors = fit['fit_anchors']
    if len(anchors) < 2:
        raise ValueError('Provide at least two independently reviewed boundary windows')
    source_attacks=base.attacks(score['events'])
    if not source_attacks or anchors[0]['q'] > min(qvalue(e['q']) for e in source_attacks) or anchors[-1]['q'] < max(qvalue(e['q']) for e in source_attacks):
        raise ValueError('Full-route boundaries must include every regular source attack')
    duration = audio['samples']/audio['sample_rate']
    for i, row in enumerate(anchors):
        q, target, (a,b) = row['q'], row['target'], row['window']
        if not all(np.isfinite([q,target,a,b])) or not 0 <= a <= target <= b <= duration:
            raise ValueError('Invalid reviewed boundary')
        if not 0 <= q <= qvalue(score['total_q']):
            raise ValueError('Fit outside source route')
        if i and not (anchors[i-1]['q'] < q and anchors[i-1]['target'] < target):
            raise ValueError('Fit boundaries must be ordered')
    lo, hi = fit['pitch_low'], fit['pitch_high']
    keyfile=args.features.with_name('alignment-features-key.json')
    if read(keyfile).get('key') != f'{sha(args.pcm)}:{lo}:{hi}:feature-v2':
        raise ValueError('Prepared PCM/pitch range does not match feature cache identity')
    end = float(fit['music_search_end_seconds'])
    if not anchors[-1]['window'][1] <= end <= duration:
        raise ValueError('Search boundary outside original recording')
    with np.load(args.features) as z:
        features = {k:z[k] for k in ('ct','cqt','ts','rise','rms')}
    if features['cqt'].shape[1] != hi-lo+1 or features['rise'].shape[1] != hi-lo+1:
        raise ValueError('Feature pitch range mismatch')
    features = {k:v[v0 <= end] for k,v,v0 in
                ((k,v,features['ct'] if k in ('ct','cqt') else features['ts']) for k,v in features.items())}
    step = float(fit.get('step_q',1/32)); hop = float(fit.get('audio_hop',.01))
    width = float(fit.get('corridor_halfwidth_seconds',16))
    if not step > 0 or not hop > 0 or not width > 0:
        raise ValueError('Grid parameters must be positive')
    rows = round((anchors[-1]['q']-anchors[0]['q'])/step)+1
    if rows*(2*round(width/hop)+1) > int(fit.get('max_backtrack_cells',100_000_000)):
        raise ValueError('Backtrace exceeds explicit memory limit')
    args.output.mkdir(parents=True)
    write = lambda name,v: (args.output/name).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
    blocks = [core.coarse_block(score,features,a,b,lo,hi,int(fit.get('coarse_max_axis',4000)))
              for a,b in zip(anchors,anchors[1:])]
    gq = np.concatenate([np.array(b['q'])[int(i>0):] for i,b in enumerate(blocks)])
    gt = np.concatenate([np.array(b['seconds'])[int(i>0):] for i,b in enumerate(blocks)])
    data = core.local_features(score,features,lo,hi,anchors[0]['q'],anchors[-1]['q'],[0,end],step,hop)
    sq,ts = data['score_q'],data['audio_t'];guide=np.interp(sq,gq,gt)
    tempos=core.source_tempo_events(score,args.source); rates=np.zeros(len(sq));profiles=[]
    for a,b in zip(anchors,anchors[1:]):
        mask=(sq>=a['q'])&(sq<=b['q'])
        _,rates[mask],meta=core.source_tempo_hypothesis(sq[mask],[a['target'],b['target']],tempos,1.)
        profiles.append(meta)
    cuts,boundary_evidence=complete_source_tempo_boundaries(float(sq[0]),float(sq[-1]),tempos,profiles)
    lower,upper=core.fit_grid_limits(sq,ts,anchors)
    raw,cost=core.global_banded_path(data['x'],data['y'],data['a'],data['b'],
        np.round((guide-ts[0])/hop).astype(np.int64),round(width/hop),rates*step/hop,lower,upper,core.STEPS)
    dq,dt=sq[raw[:,0]],ts[raw[:,1]]
    constraints={r['q']:{'seconds':r['target'],'tolerance_seconds':(r['window'][1]-r['window'][0])/2} for r in anchors}
    events=[e for e in score['events'] if dq[0] <= qvalue(e['q']) <= dq[-1]]
    q,t,chain=refine(events,features['ts'],features['rise'],lo,dq,dt,data,constraints,sorted(cuts),source_aware_rate=True,retain_state=False)
    policy=fit.get('terminal_rest_policy')
    if policy:
        result=terminal_export(score,audio,q,t,features['ts'],features['rms'],gq,gt,policy)
    else:
        result=base.export_clock(score,audio,q,t,features['ts'],features['rms'],gq,gt)
    result.update(review_required=True,accuracy_claim=None,physical_attacks_measured=False,
                  method='opt-in wide source-tempo candidate; ornaments require separate source-owned refinement')
    write('alignment-candidate.json',result)
    write('candidate-evidence.json',{'fit_sha256':sha(args.fit),'source_tempo_events':tempos,
        'fit_q_excluded_from_independent_validation':[r['q'] for r in anchors],
        'dense_objective':cost,'chain':chain,'coarse':blocks,'tempo_boundary_policy':boundary_evidence,
        'diagnostics':core.diagnostics(sq,ts,guide,raw,width),'old_clock_used':False,
        'automatic_application_allowed':False,'ornaments_refined':False})


if __name__ == '__main__':
    main()
