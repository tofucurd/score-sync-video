"""Isolated full-route alignment. No old recording clock input."""
from pathlib import Path
import sys, math
import numpy as np
from numba import njit
from scipy.ndimage import gaussian_filter1d
from .guarded_alignment_v3 import local_features,source_tempo_events,source_tempo_hypothesis
from .guarded_alignment import norm,legacy
from score_sync.alignment import occupancy,descriptor,qvalue

# Explicit positive monotone moves. No zero-time/source transitions.
STEPS=np.array([(1,j)for j in range(1,17)]+[(1,24),(1,32),(1,48),(1,64)]+[(i,1)for i in range(2,9)],dtype=np.int64)

@njit(cache=True)
def global_banded_path(x,y,a,b,centres,width,rate,lower,upper,step_table,rate_weight=.06):
    n,nt,w=len(x),len(y),2*width+1
    maxdi=int(np.max(step_table[:,0]));back=np.zeros((n,w),np.uint8)
    history=np.full((maxdi+1,w),1e15);prefix=np.zeros(n+1,np.int64)
    for i in range(n):prefix[i+1]=prefix[i]+int(lower[i]>=0)
    for i in range(n):
        cur=np.full(w,1e15);base=centres[i]-width
        penalties=np.empty(len(step_table))
        for k in range(len(step_table)):
            di,dj=step_table[k];ratio=(dj/di)/rate[i]
            penalties[k]=rate_weight*math.log(ratio)**2 if .0625<=ratio<=16 else 1e15
        for k in range(w):
            j=base+k
            if j<0 or j>=nt or (lower[i]>=0 and (j<lower[i]or j>upper[i])):continue
            sim=0.;attack=0.
            for h in range(x.shape[1]):sim+=x[i,h]*y[j,h]
            for h in range(a.shape[1]):attack+=a[i,h]*b[j,h]
            cost=.7*(1-sim)+.3*(1-attack)
            if i==0:
                if lower[i]>=0 and lower[i]<=j<=upper[i]:cur[k]=cost;back[i,k]=255
                continue
            best=1e15;chosen=0
            for si in range(len(step_table)):
                di,dj=step_table[si]
                if di>i or penalties[si]>=1e14:continue
                pk=j-dj-(centres[i-di]-width)
                if pk<0 or pk>=w:continue
                if prefix[i]-prefix[i-di]>0:
                    valid=True
                    for r in range(i-di+1,i):
                        if lower[r]>=0:
                            tj=j-dj*(i-r)/di
                            if tj<lower[r]or tj>upper[r]:valid=False;break
                    if not valid:continue
                prev=history[(i-di)%(maxdi+1),pk]
                candidate=prev+(cost+penalties[si])*(di+dj)/2
                if candidate<best:best=candidate;chosen=si+1
            cur[k]=best;back[i,k]=chosen
        history[i%(maxdi+1)]=cur
    final=history[(n-1)%(maxdi+1)];k=int(np.argmin(final))
    if final[k]>=1e14:raise ValueError('No global ordered path satisfying fit windows')
    out=np.zeros((n+nt,2),np.int64);count=0;i=n-1;j=centres[i]-width+k
    while i>=0:
        out[count,0]=i;out[count,1]=j;count+=1
        code=int(back[i,j-(centres[i]-width)])
        if code==255:break
        if code<=0:raise ValueError('Broken backtrace')
        di,dj=step_table[code-1];i-=di;j-=dj
    return out[:count][::-1],float(np.min(final))

def coarse_block(score,features,left,right,lo=12,hi=107,max_axis=4000):
    """New audio/source solve, never receives old points. Boundaries are guide-only."""
    import librosa
    q0,q1=left['q'],right['q'];t0,t1=left['target'],right['target']
    nq=max(3,min(max_axis,int(np.ceil((q1-q0)/.125))+1));nt=max(3,min(max_axis,int(np.ceil((t1-t0)/.04))+1))
    sq=np.linspace(q0,q1,nq);tt=np.linspace(t0,t1,nt);step=(q1-q0)/(nq-1)
    events=[]
    for e in score['events']:
        q=qvalue(e['q']);d=qvalue(e['duration'])
        if q+d<=q0 or q>q1:continue
        z=dict(e);z['q']=q-q0;events.append(z)
    occ=occupancy(events,q1-q0,lo,hi,step)[:nq]
    if len(occ)!=nq:raise ValueError('Coarse grid mismatch')
    x=descriptor(occ,lo);y=descriptor(np.stack([np.interp(tt,features['ct'],features['cqt'][:,p])for p in range(hi-lo+1)],axis=1),lo)
    a=np.zeros_like(occ)
    for e in legacy.attacks(events):
        i=round(qvalue(e['q'])/step)
        if 0<=i<len(a):a[i,int(e['pitch'])-lo]=1
    a=norm(gaussian_filter1d(a,.7,axis=0));b=norm(np.stack([np.interp(tt,features['ts'],np.log1p(features['rise'][:,p]))for p in range(hi-lo+1)],axis=1))
    cost=np.clip(.8*(1-x@y.T)+.2*(1-a@b.T),0,2).astype(np.float32)
    # Standard unrestricted coarse DTW permits prolonged holds. Zero moves only
    # belong to this coarse hypothesis; final DP is strictly positive.
    _,path=librosa.sequence.dtw(C=cost,step_sizes_sigma=np.array([[1,1],[1,0],[0,1]]),weights_add=np.array([0,.02,.02]),backtrack=True)
    path=path[::-1];q=sq[path[:,0]];t=tt[path[:,1]];uq=np.unique(q);ut=np.array([np.median(t[q==v])for v in uq]);ut[0]=t0;ut[-1]=t1
    return {'q':uq.tolist(),'seconds':ut.tolist(),'raw_path_shape':list(path.shape),'cost_shape':list(cost.shape),'q_range':[q0,q1],'audio_range':[t0,t1],'cost_mean_on_path':float(np.mean(cost[path[:,0],path[:,1]])),'boundary_targets_are_not_measured_exact_onsets':True,'old_clock_used':False}

def fit_grid_limits(sq,ts,anchors):
    lower=np.full(len(sq),-1,np.int64);upper=np.full(len(sq),-1,np.int64)
    for row in anchors:
        i=int(np.argmin(abs(sq-row['q'])));a,b=row['window']
        if abs(sq[i]-row['q'])>1e-8:raise ValueError('Fit q not on dense grid; must explicitly support rational split')
        lower[i]=int(np.searchsorted(ts,a,side='left'));upper[i]=int(np.searchsorted(ts,b,side='right'))-1
        if lower[i]>upper[i]:raise ValueError('Fit window narrower than audio lattice')
    return lower,upper

def diagnostics(sq,tt,guide,path,width):
    q=sq[path[:,0]];t=tt[path[:,1]];slope=np.diff(t)/np.diff(q)
    edge=abs(t-guide[path[:,0]])/width
    return {'node_count':len(q),'strict_q_t':bool(np.all(np.diff(q)>0)&np.all(np.diff(t)>0)),
     'max_departure_seconds':float(np.max(abs(t-guide[path[:,0]]))), 'corridor_edge_fraction':float(np.mean(edge>.95)),
     'seconds_per_q_range':[float(slope.min()),float(slope.max())],
     'automatic_application_allowed':False,'physical_accuracy_claim':None}
