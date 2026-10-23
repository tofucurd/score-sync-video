"""Preserve the listening master; decode a separate analysis signal."""
from pathlib import Path
import hashlib,json,subprocess

def probe(path):
    return json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','a:0','-show_streams','-show_format','-of','json',str(path)]))

def pcm_spec(stream):
    codec=stream.get('codec_name',''); rate=int(stream['sample_rate']); channels=int(stream['channels'])
    if codec.startswith('dsd'): return 96000,channels,24,'pcm_s24le'
    raw=stream.get('bits_per_raw_sample') or stream.get('bits_per_sample') or 0
    bits=int(raw) if str(raw).isdigit() else 0
    if 'f32' in codec or 'f64' in codec: bits=24
    if not bits: bits=24 if codec not in ('pcm_s16le','pcm_s16be') else 16
    bits=16 if bits<=16 else 24 if bits<=24 else 32
    return rate,channels,bits,f'pcm_s{bits}le'

def prepare_audio(movement,out_dir):
    out=Path(out_dir);out.mkdir(parents=True,exist_ok=True)
    src=Path(movement['audio']); info=probe(src); streams=info.get('streams',[])
    if not streams: raise ValueError(f'No audio stream: {src}')
    rate,channels,bits,codec=pcm_spec(streams[0]); dst=out/'audio.wav'
    cmd=['ffmpeg','-v','error','-nostdin','-y','-i',str(src),'-map','0:a:0','-vn']
    span=movement.get('audio_range')
    if span:
        a,b=map(float,span)
        if a<0 or b<=a: raise ValueError('audio_range must be increasing nonnegative seconds')
        # Sample-domain trim after decode avoids inaccurate compressed-input seeks.
        cmd+=['-af',f'atrim=start={a}:end={b},asetpts=PTS-STARTPTS']
    cmd+=['-ar',str(rate),'-ac',str(channels),'-c:a',codec,'-rf64','auto',str(dst)]
    subprocess.run(cmd,check=True)
    p=probe(dst)['streams'][0]
    # PCM WAV duration_ts uses the native sample time base; fall back only if absent.
    from fractions import Fraction
    samples=round(int(p['duration_ts'])*Fraction(p['time_base'])*rate) if 'duration_ts' in p else round(float(p['duration'])*rate)
    sha=hashlib.sha256()
    with src.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): sha.update(block)
    prepared=hashlib.sha256()
    with dst.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):prepared.update(block)
    data={'prepared_sha256':prepared.hexdigest(),'path':'audio.wav','sample_rate':rate,'channels':channels,'bits':bits,'samples':samples,'source_sha256':sha.hexdigest(),'audio_range':span or None,'recipe':{'argv':cmd,'source_codec':streams[0].get('codec_name'),'float_quantization_to_24bit':'f32' in streams[0].get('codec_name','') or 'f64' in streams[0].get('codec_name',''),'processing':'decode only; optional requested range; no normalization/downmix/time stretch','lossless_relative_to':'decoded PCM master, not DSD bitstream or lossy original encoding'}}
    (out/'audio.json').write_text(json.dumps(data,ensure_ascii=False,indent=2))
    return data
