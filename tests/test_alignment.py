import numpy as np
from score_sync.alignment import ordered_path, project_notes, pitch_bounds, validate_anchors

def test_dp_rejects_loud_out_of_order_peak():
    nodes=[{'q':0,'times':[1.,2.],'scores':[1.,8.]},{'q':1,'times':[1.5,3.],'scores':[10.,1.]}]
    chosen=ordered_path(nodes, lambda q:q+1)
    assert nodes[1]['times'][chosen[1]]>nodes[0]['times'][chosen[0]]

def test_pitch_range_extends_for_real_score():
    lo,hi=pitch_bounds([{'pitch':15},{'pitch':115},{'pitch':None}])
    assert lo<=15 and hi>=115 and (hi-lo+1)%12==0

def test_dwell_onset_uses_rightmost_and_end_uses_leftmost():
    events=[{'id':'x','q':[1,1],'duration':[1,1],'grace':False}, {'id':'g','q':[1,1],'duration':[0,1],'grace':True}]
    out=project_notes(events,[[0,0],[100,1],[150,1],[250,2]],100,250)
    assert out[0]['range']==[150,250]
    assert out[1]['range']==[145,150]

def test_bad_anchors_rejected():
    import pytest
    with pytest.raises(ValueError): validate_anchors([[2,1],[1,2]],4,5)

def test_dtw_handles_nonuniform_performance_clock():
    from score_sync.alignment import coarse_dtw
    score=np.eye(3,dtype=float)
    audio=score[[0,0,1,1,1,2]]
    q,t,meta=coarse_dtw(score,audio,np.arange(3.),np.arange(6.)*.2)
    assert np.allclose(q,[0,1,2])
    assert np.allclose(t,[.1,.6,1.])
    assert meta['cost_shape']==[3,6]

def test_tie_chain_extends_first_head_but_not_next_attack():
    events=[{'id':'a','q':[0,1],'duration':[1,1],'pitch':60,'staff':'1','voice':'1','tie_start':True}, {'id':'b','q':[1,1],'duration':[1,1],'pitch':60,'staff':'1','voice':'1','tie_stop':True}, {'id':'c','q':[2,1],'duration':[1,1],'pitch':60,'staff':'1','voice':'1'}]
    out=project_notes(events,[[0,0],[100,1],[200,2],[300,3]],100,300)
    assert out[0]['range']==[0,200] and out[2]['range']==[200,300]

def test_end_to_end_acoustic_features_with_reviewed_anchors(tmp_path):
    """Generated sinusoid fixture tests DSP plumbing, not real-recording accuracy."""
    import json,soundfile as sf
    from score_sync.alignment import align_movement
    sr=24000;t=np.arange(sr*4)/sr;y=np.zeros(len(t),dtype=np.float32)
    for pitch,a,b in [(60,.3,1.1),(64,1.2,2.3),(67,2.4,3.5)]:
        mask=(t>=a)&(t<b);y[mask]=.1*np.sin(2*np.pi*(440*2**((pitch-69)/12))*t[mask])
    sf.write(tmp_path/'audio.wav',y,sr,subtype='PCM_24')
    (tmp_path/'audio.json').write_text(json.dumps({'path':'audio.wav','sample_rate':sr,'samples':len(y),'channels':1}))
    events=[{'id':str(i),'q':[i,1],'duration':[1,1],'pitch':p,'kind':'pitched'} for i,p in enumerate([60,64,67])]
    (tmp_path/'score.json').write_text(json.dumps({'total_q':[3,1],'events':events}))
    result=align_movement(tmp_path,[[0,.3],[1,1.2],[2,2.4],[3,3.5]])
    assert result['points'][1]==[7200,0.]
    assert result['notes'][1]['range']==[28800,57600]
    assert result['points'][-1]==[sr*4,3.]
    assert result['physical_attacks_measured'] is False
