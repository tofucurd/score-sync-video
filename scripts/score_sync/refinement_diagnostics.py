"""Independent local PCM checks for competing attack/neighbor-pitch hypotheses.

These diagnostics do not share the fitted CQT/FFT feature cache. They still
observe a mixture and must not be reported as isolated-instrument ground truth.
"""
from pathlib import Path
import json
import numpy as np
from scipy.signal import butter, sosfiltfilt, hilbert, find_peaks
from scipy.ndimage import gaussian_filter1d


def raw_pitch_rise(signal, rate, pitches, *, offset_seconds=0., hop_seconds=.005):
    """±4% fundamental band, analytic envelope, 8 ms smoothing, 20 ms rise."""
    y=np.asarray(signal,float)
    if y.ndim==1:
        y=y[:,None]
    if y.ndim!=2 or len(y)<rate*.15 or rate<=0:
        raise ValueError('Raw pitch diagnostic requires at least 150 ms of PCM')
    step=max(1,round(rate*hop_seconds));times=np.arange(len(y))[::step]/rate+offset_seconds
    result={}
    for pitch in sorted(set(pitches)):
        f=440*2**((pitch-69)/12)
        if f*1.04>=rate/2:
            raise ValueError('Pitch band exceeds PCM Nyquist frequency')
        sos=butter(3,[f*.96,f*1.04],btype='bandpass',fs=rate,output='sos')
        envelope=np.sqrt(sum(abs(hilbert(sosfiltfilt(sos,y[:,c])))**2 for c in range(y.shape[1])))
        envelope=gaussian_filter1d(envelope,rate*.008)[::step]
        lag=max(1,round(.02/(step/rate)))
        earlier=np.r_[np.repeat(envelope[0],lag),envelope[:-lag]] if len(envelope)>lag else np.repeat(envelope[0],len(envelope))
        rise=np.maximum(0,envelope-earlier)
        result[pitch]=np.minimum(rise/max(float(np.percentile(rise,99)),1e-10),3)
    return times,result


def joint_neighbor_envelopes(signal, rate, pitches, *, offset_seconds=0., window_seconds=.1, hop_seconds=.005):
    """Joint weighted least squares of neighboring sine/cosine fundamentals."""
    y=np.asarray(signal,float)
    if y.ndim==1:
        y=y[:,None]
    pitches=sorted(set(pitches));n=round(rate*window_seconds);hop=max(1,round(rate*hop_seconds))
    if not pitches or n<8 or len(y)<n:
        raise ValueError('Insufficient PCM/pitches for joint neighboring-tone diagnostic')
    frequencies=440*2**((np.array(pitches)-69)/12)
    if frequencies.max()>=rate/2:
        raise ValueError('Neighbor fundamental exceeds PCM Nyquist frequency')
    relative=(np.arange(n)-n/2)/rate;window=np.hanning(n)
    basis=np.array([wave for f in frequencies for wave in [np.cos(2*np.pi*f*relative),np.sin(2*np.pi*f*relative)]]).T
    weighted=basis*window[:,None];inverse=np.linalg.pinv(weighted)
    times,amplitudes=[],[]
    for start in range(0,len(y)-n+1,hop):
        c=inverse@(y[start:start+n]*window[:,None])
        amplitudes.append(np.sqrt((c.reshape(-1,2,y.shape[1])**2).sum(axis=(1,2))))
        times.append(offset_seconds+(start+n/2)/rate)
    return np.asarray(times),np.asarray(amplitudes),dict(pitches=pitches,
        condition_number=float(np.linalg.cond(weighted)),window_seconds=n/rate,
        method='joint weighted least squares neighboring fundamentals; harmonic/vibrato ambiguity remains')


def sequence_shift_evidence(rows,times,pitch_rise, *, max_shift_seconds=.6,step_seconds=.01):
    if not rows or max_shift_seconds<=0 or step_seconds<=0:
        raise ValueError('Sequence diagnostic needs rows and positive shift grid')
    shifts=np.arange(-max_shift_seconds,max_shift_seconds+step_seconds/2,step_seconds)
    shifts[np.argmin(abs(shifts))]=0.
    matrix=[];detail=[]
    for row in rows:
        if not row['pitches']:
            raise ValueError('Sequence row has no expected pitch')
        values=np.mean([np.interp(row['seconds']+shifts,times,pitch_rise[p]) for p in row['pitches']],axis=0)
        matrix.append(values)
    matrix=np.asarray(matrix);joint=matrix.mean(0);best=int(np.argmax(joint));zero=int(np.argmin(abs(shifts)))
    for row,values in zip(rows,matrix):
        k=int(np.argmax(values))
        detail.append(dict(q=row['q'],seconds=row['seconds'],pitches=row['pitches'],
            zero_evidence=float(values[zero]),maximum_shift_seconds=float(shifts[k]),maximum_evidence=float(values[k])))
    return dict(attack_count=len(rows),best_shift_seconds=float(shifts[best]),
        current_mean_evidence=float(joint[zero]),best_mean_evidence=float(joint[best]),
        shifts=shifts.tolist(),mean_evidence=joint.tolist(),nodes=detail,
        automatic_clock_change=False,physical_instrument_isolation_claim=False)


def audit_recording_interval(out_dir, alignment, score, start_seconds, end_seconds, *, neighbor_pitches=None):
    """Read just an interval from analysis-24k.f32; never modifies its timing map."""
    from .alignment_pipeline import attacks
    from .alignment import qvalue
    out=Path(out_dir);audio=json.loads((out/'audio.json').read_text());rate=24000
    duration=audio['samples']/audio['sample_rate']
    if not 0<=start_seconds<end_seconds<=duration:
        raise ValueError('Diagnostic interval outside recording')
    points=np.asarray(alignment['points'],float);groups={}
    for event in attacks(score['events']):
        groups.setdefault(qvalue(event['q']),set()).add(int(event['pitch']))
    rows=[]
    for q,pitches in sorted(groups.items()):
        t=float(np.interp(q,points[:,1],points[:,0]/alignment['sample_rate']))
        if start_seconds<=t<=end_seconds:
            rows.append(dict(q=q,seconds=t,pitches=sorted(pitches)))
    if not rows:
        raise ValueError('No score attacks in diagnostic interval')
    raw=np.memmap(out/'analysis-24k.f32',dtype='<f4',mode='r').reshape(-1,audio['channels'])
    lo,hi=max(0,start_seconds-1),min(len(raw)/rate,end_seconds+1)
    first,last=int(lo*rate),int(hi*rate)
    signal=np.asarray(raw[first:last]).copy();offset=first/rate
    pitches=sorted({p for row in rows for p in row['pitches']})
    times,rise=raw_pitch_rise(signal,rate,pitches,offset_seconds=offset)
    report=sequence_shift_evidence(rows,times,rise)
    report.update(start_seconds=start_seconds,end_seconds=end_seconds,method='independent raw PCM fundamental bandpass / Hilbert envelope',
                  feature_times=times.tolist(),per_pitch_rise={str(p):v.tolist() for p,v in rise.items()})
    if neighbor_pitches:
        tt,amplitudes,meta=joint_neighbor_envelopes(signal,rate,neighbor_pitches,offset_seconds=offset)
        report['neighbor_separation']={**meta,'times':tt.tolist(),'amplitudes':amplitudes.tolist()}
    return report
