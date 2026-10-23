"""Repair MusicXML dashes import in temporary MEI; source/events stay untouched."""
import xml.etree.ElementTree as E
from fractions import Fraction as F
N='{http://www.music-encoding.org/ns/mei}'
ID='{http://www.w3.org/XML/1998/namespace}id'
def restore_dashes(xml,mei,score):
 xr=E.fromstring(xml);mr=E.fromstring(mei);starts={m['index']:F(*m['q'])for m in score['measures']};controls={};report=[]
 staffmap={s['id']:i+1 for i,s in enumerate(score['staves'])}
 def text(e):return ' '.join(''.join(e.itertext()).split())
 for mi,m in enumerate(mr.iter(N+'measure'),1):
  controls[mi]=[x for x in m if x.tag in (N+'dir',N+'dynam')]
 for p in xr.findall('part'):
  div=F(1);beat=4;stream=[];texts={};meters={}
  for mi,m in enumerate(p.findall('measure'),1):
   cur=F(0)
   for n in m:
    if n.tag=='attributes':
     div=F(n.findtext('divisions',str(div)));beat=int(n.findtext('time/beat-type',str(beat)))
    elif n.tag=='backup':cur-=F(n.findtext('duration'))/div
    elif n.tag=='forward':cur+=F(n.findtext('duration'))/div
    elif n.tag=='note' and n.find('chord')is None and n.find('grace')is None:cur+=F(n.findtext('duration','0'))/div
    elif n.tag=='direction':
     local=cur+F(n.findtext('offset','0'))/div;staff=staffmap[p.get('id')+':'+n.findtext('staff','1')];place=n.get('placement');ws=' '.join(text(w)for w in n.findall('direction-type/words')+n.findall('direction-type/dynamics/other-dynamics'))
     if ws:texts.setdefault((mi,local,staff,place),[]).append(ws)
     for dash in n.findall('direction-type/dashes'):stream.append(dict(mi=mi,q=starts[mi]+local,local=local,staff=staff,place=place,text=ws,type=dash.get('type'),number=dash.get('number','1'),stamp=1+local*F(beat,4)))
   meters[mi]=beat
  for a in stream:
   ts=texts.get((a['mi'],a['local'],a['staff'],a['place']),[])
   if not a['text'] and len(ts)==1:a['text']=ts[0]
  stream.sort(key=lambda a:(a['q'],0 if a['type']=='stop'else 1));opened={}
  for b in stream:
   key=(b['staff'],b['number'])
   if b['type']=='start':
    if key in opened:raise ValueError('Overlapping source dashes number')
    opened[key]=b;continue
   if b['type']!='stop':continue
   if key not in opened:raise ValueError('Orphan source dashes stop')
   a=opened.pop(key);matches=[x for x in controls[a['mi']]if x.get('staff')==str(a['staff']) and x.get('tstamp')is not None and abs(float(x.get('tstamp'))-float(a['stamp']))<1e-3 and text(x)==a['text'] and (not a['place']or x.get('place')==a['place'])]
   if len(matches)!=1:raise ValueError(f'Dashes MEI target not unique: {a}, matches={len(matches)}')
   target=matches[0];endstamp=1+b['local']*F(meters[b['mi']],4);endpoint=f"{b['mi']-a['mi']}m+{float(endstamp):g}"
   target.set('tstamp2',endpoint);target.set('extender','true');target.set('lform','dashed')
   report.append({'id':target.get(ID),'start_measure':a['mi'],'end_measure':b['mi'],'tstamp2':endpoint})
  if opened:raise ValueError('Unclosed source dashes')
 E.register_namespace('',N[1:-1])
 return E.tostring(mr,encoding='unicode'),report
