"""Derive optional notation labels from the current XML and performed route."""
from pathlib import Path
from fractions import Fraction as Q
import copy, hashlib, json
from xml.etree import ElementTree as ET
from .score import read_xml


def bindings(directory):
    return {n:{'path':n+'.json','sha256':hashlib.sha256((directory/(n+'.json')).read_bytes()).hexdigest()}
            for n in ('score','geometry','alignment')}


def compile_signatures(xml, score, geometry, svg):
    rows={}
    for part in xml.findall('part'):
        pid=part.get('id');ids=[s['id'] for s in geometry['staves'] if s['id'].split(':')[0]==pid]
        state={s:{'sign':None,'line':2,'octave':0,'fifths':0,'diatonic':None,'chromatic':0} for s in ids}
        source=[];div=Q(1)
        for measure in part.findall('measure'):
            events=[(Q(0),copy.deepcopy(state))];pos=Q(0)
            for node in measure:
                if node.tag=='attributes':
                    if node.find('divisions') is not None:div=Q(node.findtext('divisions'))
                    for a in node:
                        selected=[pid+':'+a.get('number')] if a.get('number') else ids
                        for sid in selected:
                            if sid not in state:continue
                            if a.tag=='clef':
                                state[sid].update(sign=a.findtext('sign'),line=int(a.findtext('line','2')),octave=int(a.findtext('clef-octave-change','0')))
                            elif a.tag=='key':
                                if a.find('fifths') is None:raise ValueError('Nontraditional key signature needs an explicit label adapter')
                                state[sid]['fifths']=int(a.findtext('fifths'))
                            elif a.tag=='transpose':
                                state[sid].update(diatonic=int(a.findtext('diatonic')) if a.find('diatonic') is not None else None,chromatic=int(a.findtext('chromatic','0')))
                    events.append((pos,copy.deepcopy(state)))
                elif node.tag in ('backup','forward'):
                    pos+=(1 if node.tag=='forward' else -1)*Q(node.findtext('duration','0'))/div
                elif node.tag=='note' and node.find('chord') is None and node.find('grace') is None:
                    pos+=Q(node.findtext('duration','0'))/div
            source.append(events)
        for sid in ids:
            out=[]
            for measure in score['measures']:
                start,end=Q(*measure['q']),Q(*measure['end'])
                local={float(start+offset):states[sid] for offset,states in source[measure['source_index']-1]}
                for q,st in sorted(local.items()):
                    if q>=float(end) and q!=float(start):continue
                    v=copy.deepcopy(st);tag=''
                    if v['chromatic']%12 and v['diatonic'] is not None:
                        letter='CDEFGAB'[v['diatonic']%7];natural={'C':0,'D':2,'E':4,'F':5,'G':7,'A':9,'B':11}[letter]
                        alter=(v['chromatic']-natural+6)%12-6
                        tag=letter+('♭'*(-alter) if alter<0 else '♯'*alter)
                    v['pitch_label']=tag
                    if not out or {k:x for k,x in out[-1].items() if k!='q'}!=v:out.append({'q':q,**v})
            rows[sid]={'events':out}
    glyphs={}
    for n in ET.fromstring(svg).iter():
        code=n.get('id','').split('-')[0]
        if code in ('E050','E062','E05C','E069','E260','E262'):
            glyphs[code]=[dict(p.attrib) for p in n.iter() if p.tag.split('}')[-1]=='path']
    return {'staves':rows,'glyphs':glyphs,'options':{'clef':True,'key':True,'transposition':True}}


def compile_locators(xml, score, geometry, *, interval=8, number_offset=0, min_spacing=120):
    if interval<1 or min_spacing<=0:raise ValueError('Positive locator interval/spacing required')
    # Rehearsals from every part; equivalent copies deduplicated by source position.
    rehearsals={}
    for part in xml.findall('part'):
        div=Q(1)
        for index,measure in enumerate(part.findall('measure'),1):
            pos=Q(0)
            for node in measure:
                if node.tag=='attributes' and node.find('divisions') is not None:div=Q(node.findtext('divisions'))
                elif node.tag in ('backup','forward'):pos+=(1 if node.tag=='forward' else -1)*Q(node.findtext('duration','0'))/div
                elif node.tag=='note' and node.find('chord') is None and node.find('grace') is None:pos+=Q(node.findtext('duration','0'))/div
                elif node.tag=='direction':
                    offset=pos+Q(node.findtext('offset','0'))/div
                    for mark in node.findall('./direction-type/rehearsal'):
                        if mark.text:rehearsals.setdefault(index,set()).add((offset,mark.text))
    from .visual import build_axis
    import numpy as np
    axis=build_axis(score,geometry);qs,xs=zip(*axis)
    min_scale=min(.22,1640/max(1,sum(s['height']+1140 for s in geometry['staves'])))
    source_measures=xml.find('part').findall('measure');candidates=[]
    for m in geometry['measures']:
        source=source_measures[m['source_index']-1];label=source.get('number','')
        marks=[]
        if label.isdigit():
            number=int(label)-number_offset
            if number>0 and (number==1 or (number-1)%interval==0):marks.append((Q(0),str(number),1))
        marks += [(offset,label,2) for offset,label in rehearsals.get(m['source_index'],set())]
        # Coincident rehearsal text takes priority; don't overlap two labels.
        for offset,label,priority in marks:
            at=Q(*m['q'])+offset
            if not Q(*m['q'])<=at<Q(*m['end']):raise ValueError('Rehearsal offset lies outside source measure')
            x=m['x'] if offset==0 else float(np.interp(float(at),qs,xs))
            x=max(m['x'],min(m['x']+m['width'],x))
            candidates.append({'id':f"locator-{m['index']}-{offset}-{priority}",'text':label,'performed_index':m['index'],'source_index':m['source_index'],'occurrence':m['occurrence'],'q':m['q'],'native_x':x,'priority':priority})
    chosen=[]
    for item in sorted(candidates,key=lambda x:(-x['priority'],x['native_x'],x['text'])):
        if all(abs(item['native_x']-p['native_x'])*min_scale>=min_spacing for p in chosen):chosen.append(item)
    return {'font_size':30,'baseline_y':80,'color':'#778077','opacity':.84,'left':390,'right':3720,'edge_fade_width':50,
            'items':sorted(chosen,key=lambda x:x['native_x']),
            'policy':{'interval':interval,'number_offset':number_offset,'minimum_spacing':min_spacing,'source_rehearsals_only':True}}
