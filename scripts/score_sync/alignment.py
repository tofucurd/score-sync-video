"""Score-informed recording alignment. Estimates notation display times, not isolated instrument onsets."""
from pathlib import Path
from fractions import Fraction
import json,gzip,subprocess,hashlib
import numpy as np
from scipy.ndimage import gaussian_filter1d,uniform_filter1d
from scipy.signal import find_peaks

def qvalue(v): return float(Fraction(*v)) if isinstance(v,(list,tuple)) else float(v)

def pitch_bounds(events):
    ps=[float(e['pitch']) for e in events if e.get('pitch') is not None and e.get('is_player',True)]
    if not ps: raise ValueError('No pitched events: audio matching requires pitched score or reviewed anchors')
    if any(abs(p-round(p))>1e-6 for p in ps):raise ValueError('Microtonal score requires a finer pitch grid; semitone alignment must not silently round pitches')
    lo=int(np.floor(min(ps)/12)*12); hi=int(np.ceil((max(ps)+1-lo)/12)*12+lo-1)
    return lo,hi

def validate_anchors(anchors,total,duration):
    a=[[float(q),float(t)] for q,t in (anchors or [])]
    if any(not np.isfinite(q+t) or q<0 or q>total or t<0 or t>duration for q,t in a):raise ValueError('Anchor outside score/audio')
    if any(q2<=q1 or t2<=t1 for (q1,t1),(q2,t2) in zip(a,a[1:])):raise ValueError('Anchors must increase in both score and recording time')
    return a

def descriptor(x,lo):
    """48 dimensions: complete chroma plus three register-specific chromas."""
    x=np.asarray(x,dtype=np.float32); n=x.shape[1]; octaves=n//12
    folded=np.roll(x.reshape(-1,octaves,12).mean(1),lo%12,axis=1)
    parts=[folded]
    for indices in np.array_split(np.arange(octaves),3):
        z=x.reshape(-1,octaves,12)[:,indices,:].mean(1) if len(indices) else np.zeros_like(folded)
        parts.append(.65*np.roll(z,lo%12,axis=1))
    y=np.concatenate([p-p.mean(1,keepdims=True) for p in parts],axis=1)
    return y/np.maximum(np.linalg.norm(y,axis=1,keepdims=True),1e-8)

def occupancy(events,total,lo,hi,step):
    x=np.zeros((int(np.ceil(total/step))+1,hi-lo+1),np.float32)
    for e in events:
        if e.get('pitch') is None or e.get('grace') or not e.get('is_player',True):continue
        q=qvalue(e['q']);d=qvalue(e['duration']); p=int(round(e['pitch']))-lo
        if d>0 and 0<=p<x.shape[1]:x[max(0,int(q/step)):min(len(x),int(np.ceil((q+d)/step))),p]=1
    return x

def coarse_dtw(score_features,audio_features,score_q,audio_t,max_axis=2000):
    """Bound RAM explicitly to at most max_axis² cost cells; preserve endpoints."""
    import librosa
    si=np.unique(np.r_[np.arange(0,len(score_q),max(1,int(np.ceil(len(score_q)/max_axis)))),len(score_q)-1])
    ai=np.unique(np.r_[np.arange(0,len(audio_t),max(1,int(np.ceil(len(audio_t)/max_axis)))),len(audio_t)-1])
    sf=np.sqrt(np.maximum(score_features[si],0));af=np.sqrt(np.maximum(audio_features[ai],0))
    sf=sf/np.maximum(np.linalg.norm(sf,axis=1,keepdims=True),1e-8)
    af=af/np.maximum(np.linalg.norm(af,axis=1,keepdims=True),1e-8)
    cost=np.clip(1-sf@af.T,0,1).astype(np.float32)
    _,path=librosa.sequence.dtw(C=cost,backtrack=True)
    path=path[::-1];qs=[];ts=[]
    for i in np.unique(path[:,0]):
        qs.append(float(score_q[si[i]]));ts.append(float(np.median(audio_t[ai[path[path[:,0]==i,1]]])))
    return np.array(qs),np.array(ts),{'cost_shape':list(cost.shape),'score_stride':int(max(1,np.ceil(len(score_q)/max_axis))),'audio_stride':int(max(1,np.ceil(len(audio_t)/max_axis))),'coarsening_is_not_accuracy_claim':True}

def ordered_path(nodes,guide):
    """Minimize negative local evidence plus 1.8 log tempo-ratio squared."""
    if not nodes:return []
    prev=None;backs=[]
    for i,node in enumerate(nodes):
        ts=np.asarray(node['times']);cost=-np.asarray(node['scores'],float)
        if i:
            dt=ts[:,None]-np.asarray(nodes[i-1]['times'])[None,:]
            rate=max(.08,(guide(node['q']+1)-guide(node['q']-1))/2)
            expected=max(.01,(node['q']-nodes[i-1]['q'])*rate)
            penalty=1.8*np.log(np.maximum(dt,.001)/expected)**2
            penalty[dt<.009]=np.inf
            candidates=penalty+prev[None,:]; ptr=np.argmin(candidates,axis=1)
            cost+=candidates[np.arange(len(ts)),ptr]
        else:ptr=np.full(len(ts),-1)
        if not np.any(np.isfinite(cost)):raise ValueError(f'No ordered candidate path at q={node["q"]}; add reviewed anchors')
        prev=cost;backs.append(ptr)
    selected=[0]*len(nodes);selected[-1]=int(np.argmin(prev))
    for i in range(len(nodes)-1,0,-1):selected[i-1]=int(backs[i][selected[i]])
    return selected

def project_notes(events,points,rate,samples):
    arr=np.asarray(points,float);ss=arr[:,0];qq=arr[:,1]
    def at(q,onset):
        exact=np.flatnonzero(np.abs(qq-q)<1e-9)
        if len(exact):return int(ss[exact[-1] if onset else exact[0]])
        return int(round(np.interp(q,qq,ss)))
    out=[]
    for e in events:
        q=qvalue(e['q']);a=at(q,True);b=at(q+qvalue(e['duration']),False)
        if e.get('grace'):a,b=max(0,a-round(rate*.05)),a
        out.append({'id':e['id'],'range':[max(0,min(samples,a)),max(0,min(samples,max(a,b)))],'basis':'score_duration_projected_through_recording_clock','physical_attack_measured':False})
    # Share one exact, contiguous chain resolver with visual color inheritance.
    from .ties import tie_chains
    by_id={n['id']:n for n in out}
    for chain in tie_chains(events):
        end=max(by_id[eid]['range'][1] for eid in chain)
        for eid in chain:by_id[eid]['range'][1]=end
    return out

def extract_features(master,out,channels,lo,hi):
    """Analysis-only 24 kHz float copy, channel-power combination, bounded FFT blocks."""
    import librosa
    raw=out/'analysis-24k.f32';sr=24000;hop=240
    subprocess.run(['ffmpeg','-v','error','-nostdin','-y','-i',str(master),'-af',f'aresample=osr={sr}:filter_size=128:phase_shift=10:linear_interp=0:exact_rational=1:cutoff=0.97:filter_type=kaiser:kaiser_beta=9:dither_method=none','-c:a','pcm_f32le','-f','f32le',str(raw)],check=True)
    y=np.memmap(raw,dtype='<f4',mode='r').reshape(-1,channels)
    count=len(y);centers=np.arange(0,count,hop); pitches=np.arange(lo,hi+1);freq=440*2**((pitches-69)/12)
    if freq[-1]>=12000*.9:raise ValueError('Pitch exceeds analysis Nyquist; raise analysis rate before aligning this score')
    cqt_power=None
    for ch in range(channels):
        # Average magnitude-power, never waveform-average cancelling antiphase channels.
        z=librosa.cqt(np.asarray(y[:,ch]),sr=sr,hop_length=256,fmin=float(freq[0]),n_bins=len(pitches),bins_per_octave=12)
        p=np.abs(z.T)**2
        cqt_power=p if cqt_power is None else cqt_power+p
    cqt_power/=channels
    med=np.maximum(np.median(cqt_power,axis=0),1e-12);cqt=np.log1p(cqt_power/med)
    ct=np.arange(len(cqt))*256/sr
    dbs=[];rms=None
    for window in (1024,4096):
        result=np.zeros((len(centers),len(pitches)),np.float32);rms=np.zeros(len(centers),np.float32)
        hann=np.hanning(window).astype(np.float32);offset=np.arange(window)-window//2
        fractional_bins=freq[:,None]*np.arange(1,5)[None,:]*window/sr
        bins=np.floor(fractional_bins).astype(int);alpha=fractional_bins-bins
        valid=bins<window//2;bins=np.minimum(bins,window//2-1);weights=np.array([.35,.30,.20,.15])[None,:]*valid;weights/=np.maximum(weights.sum(1,keepdims=True),1e-8)
        for start in range(0,len(centers),128):
            cc=centers[start:start+128];idx=cc[:,None]+offset[None,:];mask=(idx>=0)&(idx<count);idx=np.clip(idx,0,count-1)
            power=None;energy=np.zeros(len(cc))
            for ch in range(channels):
                block=np.asarray(y[idx,ch])*mask;energy+=(block*block).mean(1)
                z=np.abs(np.fft.rfft(block*hann,axis=1))**2
                power=z if power is None else power+z
            power/=channels
            interpolated=power[:,bins]*(1-alpha)[None,:,:]+power[:,bins+1]*alpha[None,:,:]
            values=10*np.log10(np.maximum(interpolated,1e-18))
            result[start:start+len(cc)]=(values*weights[None,:,:]).sum(2)
            rms[start:start+len(cc)]=np.sqrt(energy/channels)
        dbs.append(gaussian_filter1d(result,1,axis=0,mode='nearest'))
    sh,lg=dbs;rise=np.zeros_like(sh);rise[3:-3]=.65*np.maximum(sh[6:]-sh[:-6],0)+.35*np.maximum(lg[6:]-lg[:-6],0)
    rise=np.clip(rise/np.maximum(np.percentile(rise,94,axis=0),.5),0,5)
    body=uniform_filter1d(lg,9,axis=0,mode='nearest');change=np.zeros_like(body);change[8:-8]=np.clip((body[16:]-body[:-16])/8,0,3)
    return centers/sr,rise,change,ct,cqt,rms

def align_movement(out_dir,anchors=None):
    out=Path(out_dir);score=json.loads((out/'score.json').read_text());audio=json.loads((out/'audio.json').read_text())
    events=score['events'];total=qvalue(score['total_q']);rate=audio['sample_rate'];samples=audio['samples'];duration=samples/rate
    if total<=0 or duration<=0:raise ValueError('Empty score or recording')
    if score.get('route_unresolved'):raise ValueError('Unresolved repeat/jump route: review actual recording route before alignment')
    anchors=validate_anchors(anchors,total,duration);lo,hi=pitch_bounds(events)
    master=out/audio['path'];digest=hashlib.sha256()
    with master.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    cache_key=f'{digest.hexdigest()}:{lo}:{hi}:feature-v2'
    cache=out/'alignment-features.npz';cache_info=out/'alignment-features-key.json'
    if cache.exists() and cache_info.exists() and json.loads(cache_info.read_text()).get('key')==cache_key:
        with np.load(cache,allow_pickle=False) as z:ts,rise,change,ct,cqt,rms=[z[k] for k in ['ts','rise','change','ct','cqt','rms']]
    else:
        ts,rise,change,ct,cqt,rms=extract_features(master,out,audio['channels'],lo,hi)
        np.savez_compressed(cache,ts=ts,rise=rise,change=change,ct=ct,cqt=cqt,rms=rms)
        cache_info.write_text(json.dumps({'key':cache_key,'rebuildable':True}))
    step=.125;sx=occupancy(events,total,lo,hi,step);sq=np.arange(len(sx))*step
    sf=descriptor(sx,lo);af=descriptor(cqt,lo)
    # Coarse chroma uses full-register 12 dimensions; the fine state uses all 48.
    score_chroma=sx.reshape(len(sx),-1,12).mean(1)
    audio_chroma=cqt.reshape(len(cqt),-1,12).mean(1)
    groups9=[slice(i,min(i+9,len(ct))) for i in range(0,len(ct),9)]
    grouped=np.array([audio_chroma[g].mean(0) for g in groups9])
    grouped_t=np.array([ct[g].mean() for g in groups9])
    gq,gt,meta=coarse_dtw(score_chroma[::4],grouped,sq[::4],grouped_t)
    if anchors:
        aq=np.array([x[0] for x in anchors]);at=np.array([x[1] for x in anchors]); residual=at-np.interp(aq,gq,gt)
        gt=gt+np.interp(gq,aq,residual)
        # Exact anchors included; monotonicity enforced by piecewise linear guides.
        for q,t in anchors:
            k=np.searchsorted(gq,q);gq=np.insert(gq,k,q);gt=np.insert(gt,k,t)
        order=np.argsort(gq,kind='stable');gq=gq[order];gt=gt[order]
    guide=lambda q:float(np.interp(q,gq,gt))
    groups={}
    for e in events:
        if e.get('pitch') is not None and e.get('is_player',True) and not e.get('grace') and not e.get('tie_stop'):
            groups.setdefault(qvalue(e['q']),set()).add(int(round(e['pitch']))-lo)
    for q,t in anchors:groups.setdefault(q,set())
    nodes=[];anchor_dict=dict(anchors)
    for q,pi in sorted(groups.items()):
        if q>=total:continue
        seed=guide(q);width=5.0 # bounded local search; requires anchors where DTW ambiguity exceeds this
        ii=np.flatnonzero((ts>=max(0,seed-width))&(ts<=min(duration,seed+width)))
        if not len(ii):raise ValueError(f'Empty search at q={q}; review anchors')
        pitches=sorted(pi)
        family=.55*rise[ii][:,pitches].mean(1)+.45*rise[ii][:,pitches].max(1)+.18*change[ii][:,pitches].mean(1) if pitches else np.zeros(len(ii))
        st=sf[min(len(sf)-1,int(q/step))];ia=np.clip(np.searchsorted(ct,ts[ii]+.06),0,len(ct)-1);ib=np.clip(np.searchsorted(ct,ts[ii]-.06),0,len(ct)-1)
        state=af[ia]@st;delta=state-af[ib]@st
        objective=1.35*family+.75*state+.35*delta-.10*((ts[ii]-seed)/max(.5,.65*width))**2
        peaks=find_peaks(objective,distance=3)[0];best=sorted(peaks,key=lambda k:-objective[k])[:14]
        idx=sorted(set(best+list(range(0,len(ii),max(2,len(ii)//70)))+[int(objective.argmax()),int(np.argmin(abs(ts[ii]-seed)))]))
        node={'q':q,'times':ts[ii[idx]].tolist(),'scores':objective[idx].tolist(),'family':family[idx].tolist(),'state':state[idx].tolist(),'seed':seed,'pitch_hypotheses':[lo+p for p in pitches]}
        if q in anchor_dict:node.update(times=[anchor_dict[q]],scores=[0.],family=[None],state=[None],reviewed_anchor=True)
        nodes.append(node)
    if not nodes:raise ValueError('No attack hypotheses; provide a pitched score')
    choices=ordered_path(nodes,guide);points=[];flags=[]
    for node,k in zip(nodes,choices):
        sample=round(node['times'][k]*rate);points.append([sample,node['q']]);node['selected']=k
        local=[]
        if not node.get('reviewed_anchor'):
            if node['family'][k]<.65:local.append('weak_family_change')
            if node['state'][k]<.12:local.append('weak_state_support')
            if abs(node['times'][k]-node['seed'])>1.5:local.append('far_from_coarse_guide')
        if local:flags.append({'q':node['q'],'sample':sample,'reasons':local})
    if points[0][0]>0:points.insert(0,[0,0.])
    elif points[0][1]>0:points.insert(0,[0,0.])
    # Notation terminal uses measured decay; preserve full recording tail separately.
    db=20*np.log10(np.maximum(rms,1e-15)); floor=float(np.median(db[ts>max(0,duration-.5)]));active=np.flatnonzero((ts>points[-1][0]/rate)&(db>floor+6))
    terminal=min(samples,max(points[-1][0]+1,round((ts[active[-1]]+.1)*rate) if len(active) else samples))
    if total in anchor_dict:terminal=round(anchor_dict[total]*rate)
    if terminal<=points[-1][0]:raise ValueError('Terminal anchor precedes final event')
    points.append([terminal,total])
    if terminal<samples:points.append([samples,total])
    if any(b[0]<=a[0] or b[1]<a[1] for a,b in zip(points,points[1:])):raise ValueError('Nonmonotone final map; review source route/anchors')
    notes=project_notes(events,points,rate,samples)
    result={'schema':1,'points':points,'notes':notes,'sample_rate':rate,'samples':samples,'method':'CQT chroma DTW + dual-window harmonic change + register-aware state + ordered candidate DP + reviewed anchors','flags':flags,'review_required':True,'accuracy_claim':None,'physical_attacks_measured':False,'parameters':{'analysis_rate':24000,'harmonic_hop':240,'fft_windows':[1024,4096],'cqt_hop':256,'pitch_range':[lo,hi],'score_step':step,'candidate_search_halfwidth_seconds':5,'coarse':meta},'anchors':anchors,'terminal_basis':'source envelope display projection, not physical release'}
    with gzip.open(out/'alignment-evidence.jsonl.gz','wt') as f:
        for node in nodes:f.write(json.dumps(node)+'\n')
    (out/'alignment.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    return result
