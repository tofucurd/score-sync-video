"""Native SVG score animation. No synthesized notation or timing by score tempo."""
from __future__ import annotations
import base64, html, io, json, math, os, re, signal, shutil, subprocess, tempfile
from pathlib import Path
from fractions import Fraction
from .navigation import build_navigation, navigation_states, render_navigation
ROOT=Path(__file__).resolve().parents[2]
PALETTE={'main':'#C94732','purple':'#8650B6','green':'#27835D','ochre':'#AA7200'}
def read(path):return json.loads(Path(path).read_text())
def q(v):return float(Fraction(*v)) if isinstance(v,list) else float(v)
def roman(n):
 if n is None or n=='':return ''
 try:n=int(n)
 except (ValueError,TypeError):return str(n)
 if not 0<n<4000:return str(n)
 result=''
 for value,glyph in [(1000,'M'),(900,'CM'),(500,'D'),(400,'CD'),(100,'C'),(90,'XC'),(50,'L'),(40,'XL'),(10,'X'),(9,'IX'),(5,'V'),(4,'IV'),(1,'I')]:
  while n>=value:result+=glyph;n-=value
 return result

def smooth(x):
 x=min(1.,max(0.,x));return x*x*x*(10+x*(-15+6*x))
def note_envelope(t,start,end):
 if t<=start or t>=end:return 0.
 d=end-start
 return min(smooth((t-start)/min(1/120,.1*d)),smooth((end-t)/min(.1,.3*d)))
def cohort_weights(sections,t,lead=4.):
 keys={s for x in sections for s in x['staves']};result={s:0. for s in keys}
 for sec in sections:
  if sec['start']<=t<=sec['end']:w=1.
  elif t<sec['start']:w=smooth((t-sec['start']+lead)/lead)
  else:w=smooth((sec['end']+lead-t)/lead)
  for s in sec['staves']:result[s]=max(result[s],w)
 return result

def cohort_sections(structure):
 navigation=structure['sections']
 sections=structure.get('cohort_sections')
 if sections is None:sections=[child for sec in navigation for child in (sec.get('children') or [sec])]
 if not sections:raise ValueError('cohort_sections cannot be empty')
 cursor=q(navigation[0]['start_q'])
 for sec in sections:
  start,end=q(sec['start_q']),q(sec['end_q'])
  if abs(start-cursor)>1e-8 or end<=start:raise ValueError('cohort_sections must be ordered, contiguous, positive intervals')
  cursor=end
 if abs(cursor-q(navigation[-1]['end_q']))>1e-8:raise ValueError('cohort_sections must cover the full navigation extent')
 return sections

def build_axis(score,geometry):
 from statistics import median
 events={e['id']:e for e in score['events']};heads={}
 for n in geometry['notes']:
  e=events.get(n['id'])
  if e is None or e.get('grace') or e.get('kind')=='rest' or e.get('visible') is False or not e.get('is_player',True):continue
  at=q(e['q']);heads.setdefault(at,[]).append(n['x'])
 # Engraving shifts seconds/unisons sideways; follow the main rhythmic column.
 cols={at:float(median(xs)) for at,xs in heads.items()}
 for m in geometry['measures']:cols.setdefault(q(m['q']),m['x'])
 m=geometry['measures'][-1];cols[q(m['end'])]=m['x']+m['width']
 rows=sorted(cols.items());last=-float('inf');out=[]
 for at,x in rows:
  if x<last-1:raise ValueError('Native score x-axis reverses: multi-system/repeat route must be normalized before rendering')
  last=max(x,last);out.append([at,last])
 return out

def font_css(text):
 from fontTools import subset
 out=[]
 for weight,name in [(300,'Light'),(400,'Regular'),(500,'Medium')]:
  path=ROOT/'assets/fonts'/f'SourceHanSerifSC-{name}.otf'
  if not path.exists():raise FileNotFoundError(f'Bundled Source Han Serif font missing: {path}')
  options=subset.Options();font=subset.load_font(str(path),options);s=subset.Subsetter(options);s.populate(text=text);s.subset(font);b=io.BytesIO();font.save(b)
  out.append(f'@font-face{{font-family:Han; font-weight:{weight};src:url(data:font/otf;base64,{base64.b64encode(b.getvalue()).decode()})}}')
 return ''.join(out)

def bundle(cfg,movement_dir):
 d=Path(movement_dir);score=read(d/'score.json');geo=read(d/'geometry.json');a=read(d/'alignment.json');audio=read(d/'audio.json')
 if (d/'labels.json').exists():
  labels=read(d/'labels.json')
  for staff in geo['staves']:staff['label']=labels.get(staff['id'],staff['label'])
 structure=read(d/'structure.json')
 if not structure.get('reviewed'):raise ValueError('Structure must be musically reviewed before rendering; structure.json reviewed=true is required')
 sections=structure['sections'];rate=a['sample_rate'];points=a['points']
 import numpy as np
 from scipy.interpolate import PchipInterpolator
 axis=build_axis(score,geo);xx=np.array(axis);pp=np.array(points,dtype=float)
 if len(pp)<2 or np.any(np.diff(pp[:,0])<=0) or np.any(np.diff(pp[:,1])<0):raise ValueError('Alignment points must increase in sample and never reverse score position')
 # PCHIP source-time to native x; exact anchors, no accumulated frame drift.
 xpos=np.interp(pp[:,1],xx[:,0],xx[:,1]);knots={float(t/rate):float(x) for t,x in zip(pp[:,0],xpos)}
 for at,x in axis:
  exact=np.flatnonzero(np.abs(pp[:,1]-at)<1e-9)
  sample=pp[exact[-1],0] if len(exact) else np.interp(at,pp[:,1],pp[:,0])
  knots[float(sample/rate)]=float(x)
 knot_rows=sorted(knots.items());curve=PchipInterpolator([r[0] for r in knot_rows],[r[1] for r in knot_rows])
 def time_at(at):return float(np.interp(q(at),pp[:,1],pp[:,0]))/rate
 ev={e['id']:e for e in score['events']};notes=[]
 mat=read(d/'materials.json') if (d/'materials.json').exists() else {'assignments':{}}
 from .ties import inherit_tie_colors
 assignments=inherit_tie_colors(score['events'],mat.get('assignments',{}))
 for n in a['notes']:
  e=ev.get(n['id'])
  if e is None or e.get('kind')=='rest' or e.get('visible') is False or not e.get('is_player',True):continue
  notes.append({**n,'start':n['range'][0]/rate,'end':n['range'][1]/rate,'staff':e['staff'],'color':PALETTE.get(assignments.get(n['id'],'main'),PALETTE['main'])})
 deps=geo.get('staff_dependencies',[{'staves':st.get('dependencies',[st['id']])} for st in geo['staves']])+[{'staves':c['staves']} for c in geo.get('controls',[]) if len(c['staves'])>1]
 cohorts=[]
 for sec in cohort_sections(structure):
  start=time_at(sec['start_q']);end=time_at(sec['end_q']);active={n['staff'] for n in notes if n['start']<end and n['end']>start}
  # Dependency closure keeps the native storage staff of cross-staff engraving.
  changed=True
  while changed:
   before=len(active)
   for dep in deps:
    rows=set(dep.get('staves',[]) if isinstance(dep,dict) else dep)
    if rows&active:active|=rows
   changed=len(active)!=before
  cohorts.append({'start':start,'end':end,'staves':sorted(active)})
 if not any(c['staves'] for c in cohorts):raise ValueError('No sounding staff belongs to reviewed structure sections')
 movement_titles=[m.get('title',m['id']) for m in cfg.get('movements',[])]
 movement_labels=[match.group(0) if (match:=re.match(r'第[一二三四五六七八九十百零〇两0-9IVXLCDM]+乐章',title)) else f'第{roman(i+1)}乐章' for i,title in enumerate(movement_titles)]
 movement_index=next((i for i,m in enumerate(cfg.get('movements',[])) if m['id']==d.name),None)
 labels=json.dumps(cfg.get('work',{}),ensure_ascii=False)+json.dumps(movement_titles+movement_labels,ensure_ascii=False)+json.dumps(structure,ensure_ascii=False)+json.dumps(geo['staves'],ensure_ascii=False)+'曲谱同步0123456789IVXLCDM'+(d/'score.svg').read_text()
 from .presentation_layers import load_layers
 layers,layer_text=load_layers(d,geo)
 labels+=layer_text
 return {**layers,'navigation_data':build_navigation(sections,time_at,a['samples'],rate),'score':score,'geometry':geo,'alignment':a,'audio':audio,'sections':[{**sec,'start_seconds':time_at(sec['start_q']),'children':[{**ch,'start_seconds':time_at(ch['start_q'])} for ch in sec.get('children',[])]} for sec in sections],'cohorts':cohorts,'notes':notes,'svg':(d/'score.svg').read_text(),'fonts':font_css(labels),'work':cfg.get('work',{}),'curve':curve,'time_at':time_at,'duration':a['samples']/rate,'axis':axis,'movement_title':movement_titles[movement_index] if movement_index is not None else d.name,'movement_label':movement_labels[movement_index] if movement_index is not None else ''}

def frame_state(b,t,with_navigation=True):
 import numpy as np
 a=b['alignment'];rate=a['sample_rate'];t=max(0.,min(t,b['duration']))
 if '_render_points' not in a:
  a['_render_points']=np.asarray(a['points'],dtype=float);a['_render_starts']=np.asarray([n['start'] for n in b['notes']]);a['_render_ends']=np.asarray([n['end'] for n in b['notes']])
 pp=a['_render_points'];at=float(np.interp(t*rate,pp[:,0],pp[:,1]));indices=np.flatnonzero((a['_render_starts']<t)&(a['_render_ends']>t))
 active={n['id']:{'weight':w,'color':n['color']} for i in indices if (n:=b['notes'][i]) and (w:=note_envelope(t,n['start'],n['end']))>0}
 state={'seconds':t,'q':at,'x':float(b['curve'](min(t,b['alignment']['points'][-1][0]/rate))),'weights':cohort_weights(b['cohorts'],t),'highlights':active,'progress':t/b['duration'] if b['duration'] else 0}
 if with_navigation:state['navigation']=render_navigation(navigation_states(b['navigation_data'],round(t*rate),window=round(.6*rate)))
 return state

def run_browser(spec,output,mode='video'):
 node=shutil.which('node')
 if not node:raise RuntimeError('Node.js 22+ required')
 Path(output).parent.mkdir(parents=True,exist_ok=True)
 with tempfile.TemporaryDirectory(prefix='score-scene-') as temp:
  p=Path(temp)/'scene.json';p.write_text(json.dumps(spec,ensure_ascii=False))
  child_env={**os.environ,'SCORE_SYNC_CHROME':chrome_path()}
  process=subprocess.Popen([node,str(ROOT/'scripts/browser_render.mjs'),'--spec',str(p),'--output',str(Path(output).resolve()),'--mode',mode],start_new_session=True,env=child_env)
  try:
   code=process.wait()
   if code:raise subprocess.CalledProcessError(code,process.args)
  except BaseException:
   try:os.killpg(process.pid,signal.SIGTERM)
   except ProcessLookupError:pass
   try:process.wait(timeout=5)
   except subprocess.TimeoutExpired:
    try:os.killpg(process.pid,signal.SIGKILL)
    except ProcessLookupError:pass
    process.wait()
   raise

def render_clip(project_cfg,movement_dir,output,start_seconds=0,duration=30,height=360,silent=False):
 b=bundle(project_cfg,movement_dir);fps=project_cfg.get('settings',{}).get('fps',60)
 duration=min(duration,b['duration']-start_seconds)
 if duration<=0:raise ValueError('Requested clip outside recording')
 frames=math.ceil(duration*fps);spec={k:v for k,v in b.items() if k not in ('curve','time_at','score','alignment','audio','notes')}
 spec.update({'frames':[frame_state(b,start_seconds+i/fps) for i in range(frames)],'height':height,'width':round(height*16/9),'fps':fps,'start_seconds':start_seconds,'duration':duration,'audio':str(Path(movement_dir)/'audio.wav'),'bits':b['audio'].get('bits',24),'silent':silent,'final':height>=2160})
 run_browser(spec,output);return Path(output)

def render_frame(project_cfg,movement_dir,output,seconds=0,height=2160):
 b=bundle(project_cfg,movement_dir);spec={k:v for k,v in b.items() if k not in ('curve','time_at','score','alignment','audio','notes')};spec.update({'frames':[frame_state(b,seconds)],'height':height,'width':round(height*16/9)})
 run_browser(spec,output,'frame');return Path(output)

def build_covers(project_cfg,movement_dir,out_dir):
 from .covers import build_cover_specs
 b=bundle(project_cfg,movement_dir);out=Path(out_dir);out.mkdir(parents=True,exist_ok=True);files=[]
 for tag,spec in build_cover_specs(project_cfg,b).items():
  svg=out/f'封面-{tag}.svg';run_browser(spec,svg,'cover');files.extend([svg,svg.with_suffix('.png'),svg.with_suffix('.jpg')])
 return files

def movement_handoff(t,boundary,first_onset):
 """Staged 48px handoff, settled before the next sounding attack."""
 end=boundary+min(.85,max(0.,first_onset));start=end-.85
 if not start<=t<end:return None
 elapsed=t-start;out=smooth(elapsed/.4);incoming=smooth((elapsed-.4)/.45);nav=smooth(elapsed/.85)
 text_out=1-smooth(2*elapsed/.85);text_in=smooth(2*elapsed/.85-1)
 return {'start':start,'end':end,'out_opacity':1-out,'out_offset':-48*out,'in_opacity':incoming,'in_offset':48*(1-incoming),'nav':nav,'nav_text_out':text_out,'nav_text_in':text_in,'nav_dy_out':-10*(1-text_out),'nav_dy_in':10*(1-text_in)}

def render_program(project_cfg,movement_dirs,output,start_frame,frame_count,height=2160,silent=True):
 """Render global frame interval; movement boundaries never rounded to frames."""
 fps=project_cfg.get('settings',{}).get('fps',60);timeline=project_cfg['_timeline'];cache={};scenes=[];scene_index={};frames=[]
 dirs={Path(d).name:Path(d) for d in movement_dirs}
 def obtain(i):
  if i not in cache:
   item=timeline[i];cache[i]=bundle(project_cfg,item.get('dir',dirs[item['id']]))
   scene_index[i]=len(scenes);scenes.append({k:v for k,v in cache[i].items() if k not in ('curve','time_at','score','alignment','audio','notes')})
  return cache[i]
 for f in range(start_frame,start_frame+frame_count):
  t=f/fps;i=max(j for j,m in enumerate(timeline) if t>=m['start_seconds']);local=t-timeline[i]['start_seconds'];b=obtain(i);actors=[]
  handoff=None
  for j in (i,i+1):
   if not 0<j<len(timeline):continue
   boundary=timeline[j]['start_seconds']
   if not boundary-.85<=t<boundary+.85:continue
   new=obtain(j);first=min((n['start'] for n in new['notes']),default=0.)
   state=movement_handoff(t,boundary,first)
   if state is not None:handoff=(j,state);break
  if handoff is not None:
   j,h=handoff;old=obtain(j-1);new=obtain(j)
   old_time=min(old['duration']-1/fps,max(0,t-timeline[j-1]['start_seconds']))
   new_time=max(0,t-timeline[j]['start_seconds']);old_state=frame_state(old,old_time,False);new_state=frame_state(new,new_time,False)
   if t<timeline[j]['start_seconds']:new_state['highlights']={}
   actors.append({'scene':scene_index[j-1],'state':old_state,'opacity':h['out_opacity'],'offset':h['out_offset'],'nav_opacity':1-h['nav'],'nav_text_opacity':h['nav_text_out'],'nav_dy':h['nav_dy_out'],'title_opacity':h['out_opacity']})
   actors.append({'scene':scene_index[j],'state':new_state,'opacity':h['in_opacity'],'offset':h['in_offset'],'nav_opacity':h['nav'],'nav_text_opacity':h['nav_text_in'],'nav_dy':h['nav_dy_in'],'title_opacity':h['in_opacity']})
  else:actors.append({'scene':scene_index[i],'state':frame_state(b,local,False),'opacity':1.,'offset':0.,'nav_opacity':1.,'title_opacity':1.})
  if handoff is not None:
   rate=new['alignment']['sample_rate']
   nav_rows=navigation_states(new['navigation_data'],round((t-timeline[j]['start_seconds'])*rate),window=round(.6*rate),previous_nav=old['navigation_data'],movement_elapsed_samples=round((t-h['start'])*rate),movement_window=round(.85*rate))
  else:
   rate=b['alignment']['sample_rate'];nav_rows=navigation_states(b['navigation_data'],round(local*rate),window=round(.6*rate))
  frames.append({'actors':actors,'navigation':render_navigation(nav_rows)})
 spec={'scenes':scenes,'frames':frames,'height':height,'width':round(height*16/9),'fps':fps,'start_seconds':start_frame/fps,'duration':frame_count/fps,'silent':silent,'final':height>=2160}
 if not silent:raise ValueError('Program chunks must be silent; mux one continuous PCM stream after global assembly')
 run_browser(spec,output);return Path(output)


def chrome_path():
 candidates=[os.environ.get('SCORE_SYNC_CHROME'),'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',shutil.which('chromium'),shutil.which('chromium-browser'),shutil.which('google-chrome')]
 for p in candidates:
  if p and Path(p).exists():return p
 raise RuntimeError('Chromium not found; set SCORE_SYNC_CHROME')
