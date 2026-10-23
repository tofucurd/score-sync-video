import json
import hashlib
from xml.etree import ElementTree as ET

import numpy as np
import pytest

from score_sync.alignment_pipeline import (
    validate_constraints, correct_guide, refine_attack_chain, audit_alignment,
    apply_local_clock_patch, export_clock, banded_sequence_path,
    constraints_from_anchors, apply_exact_constraints,
    initial_attack_candidate,
)
from score_sync.refinement_graces import source_metadata, build_grace_groups, match_grace_groups


def event(i, q, pitch=60, **extra):
    return dict(id=i, source_id=i, source_measure=1, staff='P1:1', voice='1',
                q=[q, 1], duration=[1, 1], pitch=pitch, **extra)


def test_constraints_are_bound_to_exact_attacking_source_identities():
    score={'events':[event('a',0)],'source_sha256':'source','total_q':[2,1]}
    row={'q':0,'seconds':.3,'events':[{'source_id':'a','source_measure':1,'pitch':60}]}
    assert validate_constraints([row],score,4)[0]['seconds']==.3
    with pytest.raises(ValueError,match='identity'):
        validate_constraints([{**row,'events':[{'source_id':'changed','source_measure':1,'pitch':60}]}],score,4)
    with pytest.raises(ValueError,match='source'):
        validate_constraints({'source_sha256':'other','rows':[row]},score,4)


def test_legacy_anchor_migration_preserves_non_attack_and_terminal_knots():
    score={'events':[event('a',0),event('b',2)],'source_sha256':'source','total_q':[3,1]}
    migrated=constraints_from_anchors(score,[[0,.3],[1,1.1],[3,3.5]],4.)
    constraints=validate_constraints(migrated,score,4.)
    assert constraints[1]['kind']=='clock'
    alignment={'points':[[0,0],[200,0],[1000,1],[2000,2],[3000,3],[4000,3]],'sample_rate':1000,'samples':4000}
    applied=apply_exact_constraints(alignment,score,constraints)
    assert [300,0.] in applied['points'] and [1100,1.] in applied['points']
    assert applied['points'][-2:]==[[3500,3.],[4000,3]]


def test_exact_attack_constraints_cannot_slide_to_nearby_peak():
    events=[event('a',0,60),event('b',1,64)]
    ts=np.arange(0,2,.01);rise=np.zeros((len(ts),12))
    rise[31,0]=10;rise[121,4]=10
    c={0:{'seconds':.303,'tolerance_seconds':.02,'exact':True},1:{'seconds':1.203,'tolerance_seconds':.02,'exact':True}}
    _,times,_=refine_attack_chain(events,ts,rise,60,np.array([0.,1.]),np.array([.303,1.203]),c)
    assert np.array_equal(times,np.array([.303,1.203]))


def test_initial_silence_is_not_forced_to_the_dtw_zero_endpoint():
    ts=np.arange(0,3,.01);rise=np.zeros((len(ts),12))
    rise[:,0]=np.exp(-((ts-.7)/.02)**2)*4
    rms=np.where(ts<.7,0.,.01)
    score={'events':[event('a',0,60)]}
    result=initial_attack_candidate(score,{'ts':ts,'rms':rms,'rise':rise},60)
    assert abs(result['seconds']-.7)<.02
    assert result['reviewed'] is False and not result['physical_attack_measured']


def test_corrected_guide_rejects_folded_time():
    q=np.arange(4.)
    with pytest.raises(ValueError,match='monotone'):
        correct_guide(q,np.array([0.,1.,2.,3.]),{1:{'seconds':3.2}})


def test_banded_dtw_finds_connected_path_with_different_local_rates():
    x=np.eye(4,dtype=np.float32)
    y=x[[0,1,1,2,3]]
    path=banded_sequence_path(x,y,x,y,np.array([0,1,3,4]),3,np.ones(4),terminal_radius=3)
    assert path[0,0]==0 and abs(path[0,1])<=3
    assert path[-1,0]==3
    assert np.all(np.diff(path[:,0])>0) and np.all(np.diff(path[:,1])>0)


def test_attack_chain_uses_pitch_order_and_reviewed_endpoints():
    events=[event('a',0,60),event('b',1,64),event('c',2,67)]
    ts=np.arange(0,3,.01);rise=np.zeros((len(ts),12))
    for pitch,t in [(60,.3),(64,1.2),(67,2.4),(64,2.1)]:
        rise[:,pitch-60]+=np.exp(-((ts-t)/.015)**2)*4
    constraints={0:{'seconds':.3,'tolerance_seconds':.011},2:{'seconds':2.4,'tolerance_seconds':.011}}
    q,t,_=refine_attack_chain(events,ts,rise,60,np.array([0.,1.,2.]),np.array([.3,1.2,2.4]),constraints)
    assert np.allclose(q,[0,1,2])
    assert np.allclose(t,[.3,1.2,2.4],atol=.011)


def test_local_patch_preserves_unreviewed_regions_and_checks_boundaries():
    score={'events':[event('a',0),event('b',1),event('c',2)],'total_q':[3,1],'source_sha256':'src'}
    base={'sample_rate':100,'samples':400,'source_sha256':'src','points':[[10,0],[100,1],[210,2],[300,3],[400,3]],'notes':[]}
    candidate={**base,'points':[[15,0],[110,1],[220,2],[300,3],[400,3]]}
    patched=apply_local_clock_patch(base,candidate,score,0,2)
    assert patched['points']==[[10,0],[110,1],[210,2],[300,3],[400,3]]
    with pytest.raises(ValueError,match='source'):
        apply_local_clock_patch(base,{**candidate,'source_sha256':'wrong'},score,0,2)


def test_tail_and_recording_duration_have_separate_roles():
    score={'events':[event('a',0),event('b',1)],'total_q':[2,1],'source_sha256':'src'}
    ts=np.arange(0,4,.01);rms=np.where(ts<2.2,.2,.00001)
    result=export_clock(score,{'sample_rate':1000,'samples':4000},np.array([0.,1.]),np.array([.2,1.2]),ts,rms)
    assert result['points'][-1]==[4000,2.]
    assert result['points'][-2][0]<3000
    assert result['physical_attacks_measured'] is False


def test_full_attack_audit_handles_silence_without_fake_accuracy():
    score={'events':[event('a',0),event('b',1)]}
    clock={'points':[[20,0],[100,1],[200,2]],'sample_rate':100}
    rows,summary=audit_alignment(score,clock,np.arange(0,2,.01),np.zeros((200,12)),60)
    assert len(rows)==2 and summary['no_local_peak']==2
    assert summary['local_flux_signed_residual_quantiles'] is None


def test_grace_tail_keeps_chord_clusters_and_same_voice_ownership():
    root=ET.fromstring('<score-partwise><part id="P1"><measure><attributes><divisions>1</divisions></attributes><note><duration>3</duration><voice>1</voice><notations><ornaments><trill-mark/></ornaments></notations></note><note><grace/><voice>1</voice></note><note><chord/><grace/><voice>1</voice></note><backup><duration>3</duration></backup><note><duration>3</duration><voice>2</voice></note></measure></part></score-partwise>')
    meta=source_metadata(root)
    assert meta['s-p1-m1-n2']['ownership']=='after_previous'
    assert meta['s-p1-m1-n3']['chord'] is True
    events=[event('a',0,60),event('g1',3,62,grace=True),event('g2',3,65,grace=True)]
    events[1]['source_id']='s-p1-m1-n2';events[2]['source_id']='s-p1-m1-n3'
    for e in events:e['measure']=1
    groups=build_grace_groups({'events':events},meta)
    assert groups[0]['ordered_attack_clusters']==[['g1','g2']]


def test_unresolved_grace_is_not_assigned_fixed_fifty_ms():
    group={'group_id':'g','ownership':'unresolved','q':1,'members':[],'ordered_attack_clusters':[]}
    rows=match_grace_groups([group],np.arange(0,2,.01),np.zeros((200,12)),60,np.array([0.,1.]),np.array([.3,1.2]))
    assert rows[0]['status']=='unresolved_notation_ownership'
    assert rows[0]['clusters']==[]


@pytest.mark.parametrize('change',['audio_source','route','range','prepared_pcm','missing_binding'])
def test_existing_guide_rejects_changed_inputs_before_audio_analysis(tmp_path,monkeypatch,change):
    import score_sync.alignment_pipeline as module
    score={'source_sha256':'src','source_route':[1,2], 'total_q':[2,1],
           'events':[event('a',0,60),event('b',1,64)]}
    audio={'path':'audio.wav','source_sha256':'recording-a','sample_rate':24000,
           'samples':96000,'channels':1,'bits':24,'audio_range':None}
    (tmp_path/'score.json').write_text(json.dumps(score));(tmp_path/'audio.json').write_text(json.dumps(audio))
    (tmp_path/'audio.wav').write_bytes(b'original prepared PCM fixture')
    binding={'schema':1,'score_json_sha256':hashlib.sha256((tmp_path/'score.json').read_bytes()).hexdigest(),
             'source_score_sha256':'src','source_route':[1,2],
             'audio':{'source_sha256':'recording-a','prepared_sha256':hashlib.sha256((tmp_path/'audio.wav').read_bytes()).hexdigest(),
                      'sample_rate':24000,'samples':96000,'channels':1,'bits':24,'audio_range':None}}
    old={'source_sha256':'src','sample_rate':24000,'samples':96000,
         'points':[[0,0],[7200,0],[28800,1],[84000,2],[96000,2]],'input_binding':binding}
    if change=='audio_source':audio['source_sha256']='different-recording-same-duration'
    elif change=='route':score['source_route']=[2,1]
    elif change=='range':audio['audio_range']=[10,14]
    elif change=='prepared_pcm':(tmp_path/'audio.wav').write_bytes(b'different prepared PCM fixture')
    elif change=='missing_binding':old.pop('input_binding')
    (tmp_path/'score.json').write_text(json.dumps(score));(tmp_path/'audio.json').write_text(json.dumps(audio))
    (tmp_path/'alignment.json').write_text(json.dumps(old))
    def must_not_analyze(*args,**kwargs):
        raise AssertionError('Stale guide must be rejected before feature extraction')
    monkeypatch.setattr(module,'extract_features',must_not_analyze)
    with pytest.raises(ValueError,match='Existing guide'):
        module.refine_movement(tmp_path,config={'use_existing_guide':True})


def test_refined_pipeline_runs_on_short_audio_without_overwriting_reviewed_clock(tmp_path):
    """DSP/plumbing fixture only: generated tones cannot establish concert accuracy."""
    import soundfile as sf
    from score_sync.alignment_pipeline import refine_movement
    sr=24000;ts=np.arange(sr*4)/sr;y=np.zeros(len(ts),dtype=np.float32)
    for pitch,a,b in [(60,.3,1.1),(64,1.2,2.3),(67,2.4,3.5)]:
        mask=(ts>=a)&(ts<b)
        y[mask]=.1*np.sin(2*np.pi*440*2**((pitch-69)/12)*ts[mask])
    sf.write(tmp_path/'audio.wav',y,sr,subtype='PCM_24')
    score={'source_sha256':'src','source_route':[1,2,3],'total_q':[3,1],'events':[event('a',0,60),event('b',1,64),event('c',2,67)]}
    audio={'path':'audio.wav','sample_rate':sr,'samples':len(y),'channels':1,'bits':24,'source_sha256':'audio','audio_range':None}
    (tmp_path/'score.json').write_text(json.dumps(score));(tmp_path/'audio.json').write_text(json.dumps(audio))
    (tmp_path/'alignment.json').write_text('existing reviewed clock')
    rows=[{'q':q,'seconds':t,'events':[{'source_id':eid,'source_measure':1,'pitch':pitch}]} for q,t,eid,pitch in [(0,.3,'a',60),(1,1.2,'b',64),(2,2.4,'c',67)]]
    result=refine_movement(tmp_path,constraints=rows)
    assert (tmp_path/'alignment.json').read_text()=='existing reviewed clock'
    assert (tmp_path/'alignment-refined.json').exists()
    assert result['review_required'] and not result['physical_attacks_measured']
    assert result['revision_evidence']['all_attack_audit']['all_nongrace_attack_nodes']==3
    note={n['id']:n for n in result['notes']}
    assert abs(note['b']['range'][0]/sr-1.2)<.016
    unanchored=refine_movement(tmp_path)
    first=next(n for n in unanchored['notes'] if n['id']=='a')['range'][0]/sr
    assert .2<first<.4
    assert any(f['reason']=='initial_attack_candidate_requires_recording_review' for f in unanchored['flags'])
    (tmp_path/'alignment.json').write_text(json.dumps(unanchored))
    reused=refine_movement(tmp_path,config={'use_existing_guide':True})
    assert reused['input_binding']==unanchored['input_binding']


def test_neighbor_fundamentals_are_fitted_jointly_with_antiphase_channels():
    from score_sync.refinement_diagnostics import joint_neighbor_envelopes
    sr=24000;t=np.arange(sr)/sr
    f=lambda p:440*2**((p-69)/12)
    mono=.5*np.cos(2*np.pi*f(60)*t)+.2*np.cos(2*np.pi*f(61)*t)
    times,amps,meta=joint_neighbor_envelopes(np.column_stack([mono,-mono]),sr,[60,61])
    assert len(times)>100 and np.all(np.isfinite(amps))
    assert np.allclose(np.median(amps[:,0]/amps[:,1]),2.5,atol=.01)
    assert meta['pitches']==[60,61]


def test_raw_pitch_diagnostic_observes_sequence_without_changing_clock():
    from score_sync.refinement_diagnostics import raw_pitch_rise,sequence_shift_evidence
    sr=24000;t=np.arange(sr*2)/sr;y=np.zeros(len(t))
    rows=[]
    for q,p,a,b in [(0,60,.4,.8),(1,64,1.,1.4)]:
        mask=(t>=a)&(t<b);y[mask]=.2*np.sin(2*np.pi*440*2**((p-69)/12)*t[mask])
        rows.append({'q':q,'seconds':a,'pitches':[p]})
    times,rise=raw_pitch_rise(np.column_stack([y,-y]),sr,[60,64])
    result=sequence_shift_evidence(rows,times,rise)
    assert result['attack_count']==2
    assert abs(result['best_shift_seconds'])<.08
    assert result['automatic_clock_change'] is False
