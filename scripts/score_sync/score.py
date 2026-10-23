"""Rational MusicXML source model and native Verovio engraving.

Original files are never rewritten. Explicit performance routes are one-based source
measure indices, e.g. [1,2,1,2,3]. PDF remains an independently reviewed authority.
"""
from __future__ import annotations
import copy, hashlib, json, re, zipfile
from fractions import Fraction as F
from pathlib import Path
from xml.etree import ElementTree as ET

XMLID='{http://www.w3.org/XML/1998/namespace}id'
SVG='{http://www.w3.org/2000/svg}'
def rat(q): return [q.numerator,q.denominator]
def val(e,path,default=None):
 n=e.find(path);return n.text if n is not None and n.text is not None else default

def read_xml(path):
 path=Path(path)
 if zipfile.is_zipfile(path):
  with zipfile.ZipFile(path) as z:
   c=ET.fromstring(z.read('META-INF/container.xml'))
   files=[n.get('full-path') for n in c.iter() if n.tag.split('}')[-1]=='rootfile']
   if not files: raise ValueError('MXL has no rootfile')
   data=z.read(files[0])
 else:data=path.read_bytes()
 if b'<!ENTITY' in data: raise ValueError('XML entities are not accepted')
 root=ET.fromstring(data)
 for n in root.iter():n.tag=n.tag.split('}')[-1]
 if root.tag!='score-partwise':raise ValueError('Convert score-timewise to MusicXML score-partwise first')
 return root

def parse_musicxml(path,source_route=None):
 root=read_xml(path);parts=root.findall('part')
 if not parts:raise ValueError('No MusicXML parts')
 risky=any(n.tag in ('repeat','ending','segno','coda') or (n.tag=='sound' and any(k in n.attrib for k in ('dacapo','dalsegno','tocoda','fine'))) for n in root.iter())
 if risky and source_route is None:raise ValueError('Repeats/jumps require reviewed source_route (one-based source measure indices)')
 count=max(len(p.findall('measure')) for p in parts)
 if any(len(p.findall('measure'))!=count for p in parts):raise ValueError('Part measure counts differ; reconcile score before aligning')
 route=list(range(1,count+1)) if source_route is None else list(source_route)
 if not route or any(not isinstance(i,int) or i<1 or i>count for i in route):raise ValueError('Invalid source_route measure index')
 labels={p.get('id'):val(p,'part-name',p.get('id')) for p in root.findall('./part-list/score-part')}
 local={};lengths=[F(0)]*count;staffs={};measure_labels={};state_by_part={}
 for pi,p in enumerate(parts):
  pid=p.get('id',f'P{pi+1}');div=F(1);nominal=F(4);transpose={};attrs_state={};states=[]
  for mi,m in enumerate(p.findall('measure')):
   cursor=F(0);extent=F(0);previous=F(0);ev=[];noteordinal=0
   entry_state=copy.deepcopy(attrs_state)
   measure_labels[mi]=m.get('number',str(mi+1))
   for child in m:
    if child.tag=='attributes':
     for a in child:attrs_state[(a.tag,a.get('number',''))]=copy.deepcopy(a)
     div=F(val(child,'divisions',str(div)))
     if div<=0:raise ValueError('MusicXML divisions must be positive')
     time=child.find('time')
     if time is not None and time.find('senza-misura') is None:
      beats=time.findall('beats');types=time.findall('beat-type')
      if len(beats)!=len(types):raise ValueError('Invalid time signature')
      nominal=sum((sum(F(x) for x in b.text.split('+'))*4/F(t.text) for b,t in zip(beats,types)),F(0))
     for tr in child.findall('transpose'):
      if tr.find('double') is not None:raise ValueError('Double transposition requires explicit score normalization')
      transpose[tr.get('number','*')]=F(val(tr,'chromatic','0'))+12*F(val(tr,'octave-change','0'))
     for sn in range(1,int(val(child,'staves','1'))+1):staffs[f'{pid}:{sn}']=labels.get(pid,pid)+(f' {sn}' if int(val(child,'staves','1'))>1 else '')
    elif child.tag in ('backup','forward'):
     d=F(val(child,'duration','0'))/div;cursor+=(-d if child.tag=='backup' else d)
     if cursor<0:raise ValueError(f'Negative voice cursor in {pid} measure {mi+1}')
     extent=max(extent,cursor)
    elif child.tag=='note':
     noteordinal+=1;grace=child.find('grace') is not None;chord=child.find('chord') is not None
     duration=F(0) if grace else F(val(child,'duration','0'))/div
     if duration<0:raise ValueError('Negative note duration')
     q=previous if chord else cursor;previous=q
     staffnum=val(child,'staff','1');staff=f'{pid}:{staffnum}';staffs.setdefault(staff,labels.get(pid,pid))
     pitch=child.find('pitch');kind='pitched' if pitch is not None else ('rest' if child.find('rest') is not None else 'unpitched')
     midi=None
     if pitch is not None:
      midi=12*(int(val(pitch,'octave'))+1)+{'C':0,'D':2,'E':4,'F':5,'G':7,'A':9,'B':11}[val(pitch,'step')]+F(val(pitch,'alter','0'))+transpose.get(staffnum,transpose.get('*',F(0)))
      midi=float(midi)
     ties={n.get('type') for n in child.findall('tie')+child.findall('./notations/tied')}
     sid=f's-p{pi+1}-m{mi+1}-n{noteordinal}'
     child.set('id',sid)
     ev.append(dict(id=sid,source_id=sid,measure=mi+1,staff=staff,voice=val(child,'voice','1'),q=rat(q),duration=rat(duration),pitch=midi,grace=grace,tie_start='start' in ties,tie_stop='stop' in ties,visible=child.get('print-object')!='no',is_player=child.find('cue') is None,kind=kind))
     if not chord:cursor+=duration
     extent=max(extent,q+duration,cursor)
   states.append(entry_state)
   implicit=m.get('implicit')=='yes'
   length=extent if extent>0 else nominal
   lengths[mi]=max(lengths[mi],length);local[(pi,mi)]=ev
  state_by_part[pi]=states
 starts=[];q=F(0);events=[];measures=[];occ={}
 for oi,source in enumerate(route):
  mi=source-1;occ[source]=occ.get(source,0)+1;starts.append(q)
  measures.append(dict(index=oi+1,source_index=source,occurrence=occ[source],q=rat(q),end=rat(q+lengths[mi]),label=measure_labels[mi]))
  for pi in range(len(parts)):
   for src in local[(pi,mi)]:
    e=copy.deepcopy(src);e['id']=f"{src['source_id']}-o{oi+1}";e['q']=rat(q+F(*src['q']));e['measure']=oi+1;e['source_measure']=source;e['occurrence']=occ[source];events.append(e)
  q+=lengths[mi]
 # Expand the engraving to exactly the performance route; each occurrence owns IDs.
 for pi,p in enumerate(parts):
  originals=list(p.findall('measure'))
  for m in originals:p.remove(m)
  for oi,source in enumerate(route):
   mi=source-1;m=copy.deepcopy(originals[mi]);m.set('number',str(oi+1));m.set('id',f'm-p{pi+1}-o{oi+1}')
   if oi==0 or source!=route[oi-1]+1:
    # Verovio consumes only the first zero-time attributes block for scoreDef.
    # Merge inherited entry state with the destination's own prefix attributes;
    # leave any mid-measure changes at their original cursor positions.
    effective=copy.deepcopy(state_by_part[pi][mi])
    for child in list(m):
     if child.tag in ('note','forward','backup'):break
     if child.tag=='attributes':
      for n in child:effective[(n.tag,n.get('number',''))]=copy.deepcopy(n)
      m.remove(child)
    a=ET.Element('attributes')
    order={name:i for i,name in enumerate(('footnote','level','divisions','key','time','staves','part-symbol','instruments','clef','staff-details','transpose','directive','measure-style'))}
    for key,n in sorted(effective.items(),key=lambda item:(order.get(item[0][0],99),item[0][1])):a.append(n)
    if len(a):m.insert(0,a)
   for n in m.iter('note'):n.set('id',n.get('id')+f'-o{oi+1}')
   for parent in m.iter():
    for n in list(parent):
     if n.tag in ('repeat','ending'):parent.remove(n)
   p.append(m)
 return dict(schema=1,events=events,measures=measures,staves=[dict(id=k,label=v) for k,v in staffs.items()],total_q=rat(q),source_route=route),ET.tostring(root,encoding='unicode')

def _xy(node):
 # Native Verovio head/rest glyphs have absolute translations in drawing units.
 head=next((e for e in node.iter() if e.get('class')=='notehead'),node)
 for e in head.iter():
  if e.tag==SVG+'use':
   match=re.search(r'translate\(\s*([-\d.]+)[ ,]+([-\d.]+)',e.get('transform',''))
   if match:return float(match[1]),float(match[2])
 return None

def engraving_musicxml(xml):
 """Temporary Verovio compatibility copy; canonical source keeps direction voices.

 Verovio's MusicXML importer leaks a direction/voice into subsequent note-layer
 assignment. Note voice, staff, offsets, IDs and direction content
 are retained. Never save this copy over the standard source XML.
 """
 root=ET.fromstring(xml)
 for direction in root.findall('.//direction'):
  for voice in list(direction.findall('voice')):direction.remove(voice)
 return ET.tostring(root,encoding='unicode')

def prepare_score(movement,out_dir):
 import verovio
 from pypdf import PdfReader
 out=Path(out_dir);out.mkdir(parents=True,exist_ok=True)
 pdf=Path(movement['pdf'])
 if not pdf.is_file():raise ValueError(f'Original PDF missing: {pdf}')
 reader=PdfReader(str(pdf));s,xml=parse_musicxml(movement['score'],movement.get('source_route'))
 s['pdf']=dict(path=str(pdf),sha256=hashlib.sha256(pdf.read_bytes()).hexdigest(),pages=len(reader.pages),review='pending',discrepancies=[])
 s['source_sha256']=hashlib.sha256(Path(movement['score']).read_bytes()).hexdigest()
 tk=verovio.toolkit();tk.setOptions(dict(inputFrom='musicxml',xmlIdSeed=314159265,breaks='none',condense='none',header='none',footer='none',svgViewBox=True,pageWidth=60000,pageHeight=60000,adjustPageHeight=True,systemMaxPerPage=1,minLastJustification=0,spacingStaff=10))
 engraving=engraving_musicxml(xml)
 if movement.get('engraving_overrides'):
  from .engraving_overrides import apply_engraving_overrides
  engraving,projection=apply_engraving_overrides(engraving,movement['engraving_overrides'],s['source_sha256'])
  (out/'engraving-projection.json').write_text(json.dumps(projection,ensure_ascii=False,indent=2))
 (out/'engraving.musicxml').write_text(engraving)
 if not tk.loadData(engraving):raise ValueError('Verovio could not load normalized MusicXML')
 from .dashes import restore_dashes
 repaired_mei,dash_report=restore_dashes(xml,tk.getMEI(),s)
 if dash_report:
  reload_options=tk.getOptions();reload_options.update(inputFrom='mei',xmlIdSeed=314159266)
  tk=verovio.toolkit();tk.setOptions(reload_options)
  if not tk.loadData(repaired_mei):raise ValueError('Verovio could not load repaired temporary MEI')
 (out/'engraving-dashes.json').write_text(json.dumps(dash_report,ensure_ascii=False,indent=2))
 if tk.getPageCount()!=1:raise ValueError('Native canonical engraving must have one continuous system')
 from .hidden_ink import suppress_hidden_beams,suppress_hidden_spanners
 svg,hidden_beams=suppress_hidden_beams(tk.renderToSVG(1),s['events'])
 svg,hidden_spanners=suppress_hidden_spanners(svg,s['events'],tk.getMEI())
 (out/'engraving-hidden-beams.json').write_text(json.dumps(hidden_beams,ensure_ascii=False,indent=2))
 (out/'engraving-hidden-spanners.json').write_text(json.dumps(hidden_spanners,ensure_ascii=False,indent=2))
 if movement.get('layout_overrides'):
  from .layout_overrides import apply_layout_overrides
  svg,layout_report=apply_layout_overrides(svg,movement['layout_overrides'],s['source_sha256'])
  (out/'engraving-layout-overrides.json').write_text(json.dumps(layout_report,ensure_ascii=False,indent=2))
 root=ET.fromstring(svg)
 id_nodes=[n for n in root.iter() if n.get('id')]
 ids={n.get('id'):n for n in id_nodes}
 if len(ids)!=len(id_nodes):raise ValueError('Duplicate native SVG IDs; refusing ambiguous geometry bindings')
 # Verovio's drawing coordinate system is the nested definition-scale SVG viewBox.
 inner=next((e for e in root.iter(SVG+'svg') if e is not root and e.get('viewBox')),root)
 box=[float(x) for x in inner.get('viewBox',root.get('viewBox')).split()]
 parents={c:p for p in root.iter() for c in p}
 def offset(node):
  x=y=0
  while node is not None and node is not inner:
   m=re.search(r'translate\(\s*([-\d.]+)[ ,]+([-\d.]+)',node.get('transform',''))
   if m:x+=float(m[1]);y+=float(m[2])
   node=parents.get(node)
  return x,y
 native_staves=[e for e in root.iter() if e.get('class')=='staff'];staves=[]
 mei_root=ET.fromstring(tk.getMEI());M='{http://www.music-encoding.org/ns/mei}'
 defs=list(mei_root.iter(M+'staffDef'))
 staff_number={d.get('n'):st['id'] for d,st in zip(defs,s['staves'])}
 native_staff_ids={st['id']:[] for st in s['staves']}
 storage={}
 for st in mei_root.iter(M+'staff'):
  sid=staff_number.get(st.get('n'))
  if sid:
   native_staff_ids[sid].append(st.get(XMLID))
   for note in st.iter():
    if note.get(XMLID):storage[note.get(XMLID)]=sid
 dependencies={st['id']:{st['id']} for st in s['staves']}
 for e in s['events']:
  owner=storage.get(e['id'],e['staff']);e['storage_staff']=owner
  if owner!=e['staff']:
   dependencies[owner].add(e['staff']);dependencies[e['staff']].add(owner)
 for i,st in enumerate(s['staves']):
  ys=[]
  if i<len(native_staves):
   for e in native_staves[i]:
    if e.tag==SVG+'path':
     nums=re.findall(r'[-+]?(?:\d*\.)?\d+',e.get('d',''))
     if len(nums)==4 and nums[1]==nums[3]:ys.append(float(nums[1]))
  dy=offset(native_staves[i])[1] if i<len(native_staves) else 0
  staves.append(dict(**st,y=(sum(ys)/len(ys)+dy if ys else 0),height=(max(ys)-min(ys) if ys else 720),svg_ids=native_staff_ids[st['id']],dependencies=sorted(dependencies[st['id']])))
 notes=[];missing=[]
 for e in s['events']:
  if not e['visible']:continue
  node=ids.get(e['id']);xy=_xy(node) if node is not None else None
  if xy is None:missing.append(e['id']);continue
  dx,dy=offset(node);notes.append(dict(id=e['id'],svg_id=e['id'],x=xy[0]+dx,y=xy[1]+dy,staff=e['staff'],storage_staff=storage.get(e['id'],e['staff'])))
 if missing:raise ValueError(f'Native note binding incomplete ({len(missing)}): {missing[:8]}')
 measure_nodes=[n for n in root.iter() if n.get('class')=='measure'];measures=[]
 event_measures={e['id']:e['measure'] for e in s['events']}
 points_by_measure={}
 for n in notes:points_by_measure.setdefault(event_measures[n['id']],[]).append(n['x'])
 for m in s['measures']:
  points=points_by_measure.get(m['index'],[])
  # Note anchors supply the musical axis; measure bounds are supplementary.
  node=measure_nodes[m['index']-1] if m['index']<=len(measure_nodes) else None
  bounds=[]
  if node is not None:
   for st in node:
    if st.get('class')!='staff':continue
    for path in st:
     if path.tag!=SVG+'path':continue
     nums=re.findall(r'[-+]?(?:\d*\.)?\d+',path.get('d',''))
     if len(nums)==4 and nums[1]==nums[3]:
      dx,_=offset(path);bounds.extend([float(nums[0])+dx,float(nums[2])+dx])
  bounds=bounds or points or [0,0]
  measures.append(dict(**m,svg_id=node.get('id') if node is not None else None,x=min(bounds),width=max(bounds)-min(bounds)))
 mei_ids={e.get(XMLID):e for e in mei_root.iter() if e.get(XMLID)}
 controls=[]
 for measure in measure_nodes:
  for node in measure:
   if node.get('class') in ('staff','barLine','mNum') or not node.get('id'):continue
   source=mei_ids.get(node.get('id'));owners=set()
   if source is not None:
    owners.update(staff_number[n] for n in source.get('staff','').split() if n in staff_number)
    for key in ('startid','endid'):
     target=source.get(key,'').lstrip('#')
     if target in storage:owners.add(storage[target])
   controls.append({'svg_id':node.get('id'),'staves':sorted(owners),'class':node.get('class'),'ownership_known':bool(owners)})
 for control in controls:
  for owner in control['staves']:dependencies[owner].update(control['staves'])
 for st in staves:st['dependencies']=sorted(dependencies[st['id']])
 g=dict(schema=1,controls=controls,viewBox=box,width=box[2],height=box[3],staves=staves,staff_dependencies=[{'staves':sorted(v)} for v in dependencies.values() if len(v)>1],measures=measures,notes=notes,svg_ids={n['id']:n['svg_id'] for n in notes})
 (out/'normalized.musicxml').write_text(xml);(out/'score.svg').write_text(svg);(out/'score.mei').write_text(tk.getMEI())
 for name,data in [('score',s),('geometry',g)]: (out/f'{name}.json').write_text(json.dumps(data,ensure_ascii=False,indent=2))
 return s
