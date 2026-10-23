"""Source-time two-level structural navigation with staged label transitions."""
from pathlib import Path
from html import escape
from functools import lru_cache
from PIL import ImageFont

FONT=Path(__file__).resolve().parents[2]/'assets/fonts/SourceHanSerifSC-Regular.otf'
BLUE='#287D9F'

def ease(u):
    u=min(1.,max(0.,float(u)))
    return u*u*u*(10+u*(-15+6*u))

def _index(segments,sample):
    # Clamp before/after source range deliberately, never silently select last
    # segment for pre-source sample as the old default-next implementation did.
    if not segments:raise ValueError('Navigation domain must contain segments')
    return next((i for i,s in enumerate(segments) if sample<s['range'][1]),len(segments)-1)

def _snapshot(nav,sample):
    parents=nav['parents'];i=_index(parents,sample);parent=parents[i]
    children=parent['children'];j=_index(children,sample)
    return [dict(segments=parents,extent=nav['range'],active=parent),
            dict(segments=children,extent=parent['range'],active=children[j])],i,j

def _progress(sample,extent):
    a,b=extent
    if b<=a:raise ValueError('Navigation extent must have positive duration')
    return min(1.,max(0.,(sample-a)/(b-a)))

def _stage(u):
    """Never two readable old/new text or ticks at once; C2 at midpoint."""
    return 1-ease(2*u),ease(2*u-1)

def navigation_states(nav,sample,window=57600,*,previous_nav=None,
                      movement_elapsed_samples=None,movement_window=81600):
    """Return same rows/layers/ticks API with staged independent text_alpha.

    previous_nav: complete outgoing movement domain; optional.
    movement_elapsed_samples: elapsed since movement transition starts, default
       new local sample. Old/new transition exists on [0,movement_window).
       Use root's verified no-sounding interval; API never certifies silence.
    movement_window: 81600 samples = .85s at 96k; positive required.
    Outgoing movement tick freezes at its completed outgoing SOURCE endpoint (end),
    incoming tick uses current local sample. Never interpolates elapsed values.
    """
    if window<=0 or movement_window<=0:raise ValueError('Positive animation windows required')
    now,i,j=_snapshot(nav,sample);old=None;old_sample=sample;u=1.;kind='steady'
    elapsed=sample if movement_elapsed_samples is None else movement_elapsed_samples
    if previous_nav is not None and 0<=elapsed<movement_window:
        old_sample=previous_nav['range'][1]
        old,_,_=_snapshot(previous_nav,old_sample-1)
        u=elapsed/movement_window;kind='movement'
    else:
        parent=nav['parents'][i];children=parent['children']
        if i and 0<=sample-parent['range'][0]<window:
            old_sample=parent['range'][0];old,_,_=_snapshot(nav,old_sample-1)
            u=(sample-parent['range'][0])/window;kind='parent'
        elif j and 0<=sample-children[j]['range'][0]<window:
            old_sample=children[j]['range'][0];old,_,_=_snapshot(nav,old_sample-1)
            u=(sample-children[j]['range'][0])/window;kind='child'
    rows=[]
    for k,current in enumerate(now):
        different=old is not None and (kind=='movement' or old[k]['active']['id']!=current['active']['id'] or old[k]['extent']!=current['extent'])
        if different:
            e=ease(u);out_text,in_text=_stage(u)
            layers=[dict(**old[k],alpha=1-e,text_alpha=out_text,dy=-10*ease(2*u)),
                    dict(**current,alpha=e,text_alpha=in_text,dy=10*(1-ease(2*u-1)))]
        else:layers=[dict(**current,alpha=1.,text_alpha=1.,dy=0.)]
        if different and (kind=='movement' or old[k]['extent']!=current['extent']):
            out_tick,in_tick=1-e,e
            ticks=[dict(progress=_progress(old_sample,old[k]['extent']),alpha=out_tick,source_sample=old_sample,role='outgoing'),
                   dict(progress=_progress(sample,current['extent']),alpha=in_tick,source_sample=sample,role='incoming')]
        else:ticks=[dict(progress=_progress(sample,current['extent']),alpha=1.,source_sample=sample,role='continuous')]
        rows.append(dict(row=k,layers=layers,ticks=ticks,transition=kind))
    return rows

@lru_cache(None)
def font(size):return ImageFont.truetype(str(FONT),size)
def clean(label):return label.split('·',1)[0].strip()

def render_navigation(rows):
    out=['<rect x="0" y="1834" width="3840" height="326" fill="#faf8f1"/>']
    for row in rows:
        k=row['row'];top=[1848,2000][k];line=top+102;x=144;width=3552
        out.append(f'<rect data-nav-base="{k}" x="{x}" y="{line}" width="{width}" height="12" fill="#faf8f1"/>')
        out.append(f'<defs><clipPath id="nav-header-{k}"><rect x="{x}" y="{top-6}" width="{width}" height="58"/></clipPath></defs>')
        for layer in row['layers']:
            alpha=layer['alpha'];ta=layer.get('text_alpha',alpha);dy=layer['dy'];a,b=layer['extent'];active=layer['active']['id'];label=escape(clean(layer['active']['label']))
            if ta>0:
                out.append(f'<text data-nav-header="{k}" x="{x}" y="{top+39+dy:.4f}" fill="#263c41" font-size="42" opacity="{ta:.8f}" clip-path="url(#nav-header-{k})">{label}</text>')
            for index,segment in enumerate(layer['segments']):
                left=x+width*(segment['range'][0]-a)/(b-a);right=x+width*(segment['range'][1]-a)/(b-a);is_active=segment['id']==active
                gap=8 if index<len(layer['segments'])-1 else 0
                out.append(f'<rect x="{left:.4f}" y="{line}" width="{max(0,right-left-gap):.4f}" height="12" fill="{BLUE if is_active else "#d3d0c7"}" opacity="{alpha:.8f}"/>')
                if not is_active and ta>0:
                    label=clean(segment['label'])
                    if font(36).getlength(label)>right-left-22:label=clean(segment.get('short_label',label))
                    if font(36).getlength(label)<=right-left-22:
                        out.append(f'<text x="{(left+right)/2:.4f}" y="{top+83+dy/2:.4f}" text-anchor="middle" fill="#827e72" font-size="36" opacity="{ta:.8f}">{escape(label)}</text>')
        for tick in row['ticks']:
            pos=x+width*tick['progress'];out.append(f'<line x1="{pos:.5f}" x2="{pos:.5f}" y1="{line-15}" y2="{line+25}" stroke="{BLUE}" stroke-width="6" opacity="{tick["alpha"]:.8f}"/>')
    return ''.join(out)


def build_navigation(sections,time_at,samples,rate):
    """Map reviewed score boundaries to recording samples; preserve all source audio."""
    parents=[]
    for i,section in enumerate(sections):
        a=0 if i==0 else round(time_at(section['start_q'])*rate)
        b=samples if i==len(sections)-1 else round(time_at(section['end_q'])*rate)
        parent={'id':f'parent-{i}','label':section['label'],'range':[a,b],'children':[]}
        if 'short_label' in section:parent['short_label']=section['short_label']
        children=section.get('children') or [section]
        for j,child in enumerate(children):
            start=a if j==0 else round(time_at(child['start_q'])*rate)
            end=b if j==len(children)-1 else round(time_at(child['end_q'])*rate)
            if end<=start:raise ValueError('Navigation segment must occupy positive recording time')
            item={'id':f'parent-{i}-child-{j}','label':child['label'],'range':[start,end]}
            if 'short_label' in child:item['short_label']=child['short_label']
            parent['children'].append(item)
        parents.append(parent)
    return {'parents':parents,'range':[0,samples]}
