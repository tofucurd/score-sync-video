from score_sync.audio import pcm_spec

def test_pcm_preserves_44100_24_stereo():
    assert pcm_spec({'codec_name':'pcm_s24le','sample_rate':'44100','channels':2,'bits_per_raw_sample':'24'})==(44100,2,24,'pcm_s24le')

def test_dsd_converts_to_96k24_without_downmix():
    assert pcm_spec({'codec_name':'dsd_lsbf_planar','sample_rate':'352800','channels':6})==(96000,6,24,'pcm_s24le')

def test_float_conversion_is_explicit():
    assert pcm_spec({'codec_name':'pcm_f32le','sample_rate':'48000','channels':1})==(48000,1,24,'pcm_s24le')

def test_prepare_keeps_pcm_samples_and_channels(tmp_path):
    import numpy as np,soundfile as sf
    from score_sync.audio import prepare_audio
    src=tmp_path/'source.wav';out=tmp_path/'prepared'
    data=(np.arange(2400,dtype=np.int32).reshape(-1,2)-1200)*256
    sf.write(src,data,44100,subtype='PCM_24')
    metadata=prepare_audio({'audio':str(src)},out)
    restored,rate=sf.read(out/'audio.wav',dtype='int32',always_2d=True)
    assert rate==44100 and np.array_equal(data,restored)
    assert metadata['samples']==1200 and metadata['bits']==24
    assert len(metadata['prepared_sha256'])==64
