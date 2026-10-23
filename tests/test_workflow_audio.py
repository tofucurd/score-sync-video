"""Actual FFmpeg encode/decode, using constructed PCM fixtures (not music accuracy)."""
import json
import subprocess
import numpy as np
import pytest
import soundfile as sf
from score_sync.workflow import master_audio

@pytest.mark.parametrize('bits,subtype,codec',[(16,'PCM_16','alac'),(24,'PCM_24','alac'),(32,'PCM_32','pcm_s32le')])
def test_master_audio_exact_concatenation_without_movement_padding(tmp_path,bits,subtype,codec):
    rate=44100
    cfg={'_root':str(tmp_path),'movements':[{'id':'first'},{'id':'second'}]}
    # Unequal prime lengths cannot both align with a60fps frame boundary.
    # Entire signal nonzero; distinct channels expose silent padding/downmix.
    originals=[]
    shift=32-bits
    for mid,count,sign in [('first',1009,1),('second',701,-1)]:
        d=tmp_path/'.score-sync'/mid;d.mkdir(parents=True)
        ramp=np.arange(1,count+1,dtype=np.int64)
        data=np.stack((sign*(ramp+31),sign*(2*ramp+97)),axis=1)
        data=(data*(1<<shift)).astype(np.int32)
        sf.write(d/'audio.wav',data,rate,subtype=subtype)
        (d/'audio.json').write_text(json.dumps({'sample_rate':rate,'bits':bits,'channels':2,'samples':count}))
        originals.append(data)
    output=tmp_path/'assembled';output.mkdir()
    result=master_audio(cfg,output)
    raw=subprocess.check_output(['ffmpeg','-v','error','-nostdin','-i',str(result),'-map','0:a:0','-c:a','pcm_s32le','-f','s32le','pipe:1'])
    actual=np.frombuffer(raw,dtype='<i4').reshape(-1,2)
    expected=np.concatenate(originals,axis=0)
    assert actual.shape==(1710,2)
    np.testing.assert_array_equal(actual,expected)
    np.testing.assert_array_equal(actual[1008:1011],expected[1008:1011])
    metadata=json.loads((output/'audio-manifest.json').read_text())
    assert metadata['samples']==1710 and metadata['codec']==codec
    assert metadata['sample_rate']==rate and metadata['no_added_gap'] is True

    assert [c['start_sample'] for c in metadata['chapters']]==[0,1009]
    assert [c['end_sample'] for c in metadata['chapters']]==[1009,1710]
