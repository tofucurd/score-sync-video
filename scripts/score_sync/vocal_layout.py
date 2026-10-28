"""Conservative full-source stable slots; review actual Chromium wrapping before approval.

This portable baseline retains whole phrases. Project-specific optimized layouts
can be supplied via the same production layout schema instead.
"""
import copy, math, re
from pathlib import Path
from functools import lru_cache
from PIL import ImageFont
from .vocal_schedule import digest
FONT=str(Path(__file__).resolve().parents[2]/'assets/fonts/SourceHanSerifSC-Regular.otf')
rnd=lambda x:math.floor(x+.5)
def font(size):return ImageFont.truetype(FONT,size)

def width(text,size):return font(size).getlength(text)

def line_count(text,size):
 tokens=[m.group() for m in re.finditer(r'\S+',text)]
 if len(tokens)==1 and width(text,size)>840:
  n=1;s=''
  for ch in text:
   if s and width(s+ch,size)>840:n+=1;s=''
   s+=ch
  return n
 n=0;i=0
 while i<len(tokens):
  j=i+1
  while j<len(tokens) and width(' '.join(tokens[i:j+1]),size)<=840:j+=1
  if width(' '.join(tokens[i:j]),size)>840:raise ValueError('Word exceeds width')
  n+=1;i=j
 return n

def estimate(timeline):
 for size in range(55,15,-1):
  role=min(40,max(16,rnd(size*.72)));zh=max(16,rnd(size*.7));lead=rnd(size*1.28);zl=rnd(zh*1.28);rh=rnd(role*1.3)+8;slots=[]
  for l in timeline['lanes']:
   ps=[p for p in l['phrases'] if not p.get('context_only')]
   block=max(line_count(p['de'],size)*lead+10+line_count(p['zh'],zh)*zl for p in ps)
   pre=max(line_count(p['de'],size)*lead*40/55 for p in ps);h=rh+2*(block+14)+pre+4
   slots.append({'id':l['id'],'height':h,'block_height':block,'preview_offset':block+14,'preview_height':pre,'role_height':rh})
  total=sum(s['height'] for s in slots)
  if total<=1620:
   y=max(150,min(1200-total/2,1770-total))
   for slot in slots:slot['top']=y;y+=slot['height']
   return {'de_size':size,'zh_size':zh,'role_size':role,'de_leading':lead,'zh_leading':zl,'height':total,'top':slots[0]['top'],'width':840,'slots':slots}
 raise ValueError('Does not fit')

def materialize(full,schedule,c,phase):
 ls={l['id']:l for l in full['lanes']};ps={p['id']:p for l in full['lanes'] for p in l['phrases']};out=[]
 for g in phase['groups']:
  l=ls[g['id']];sel=[]
  for pid in g['context_phrase_ids']+g['representative_phrase_ids']:
   p=copy.deepcopy(ps[pid]);p['context_only']=pid in g['context_phrase_ids'];sel.append(p)
  if not any(not p['context_only'] for p in sel):continue
  out.append({**copy.deepcopy(l),'members':g['members'],'label':g['label'],'color':g['color'],'phrases':sel,
   'runs':[copy.deepcopy(r) for r in l['runs'] if r['id'] in c['run_ids']]})
 return {**copy.deepcopy(full),'lanes':out,'panel_entries':schedule['panel_entries'],'panel_presence':schedule['panel_presence'],
  'clip':{'start':c['start'],'end':c['display_end'],'start_seconds':c['start'],'end_seconds':c['display_end']},
  'global_cohort':c['id'],'global_phase':phase['id'],'layout_selection_policy':'All complete global phase phrases; never an output clip'}

def compile_layout(full, schedule):
 result=[]
 for c in schedule['cohorts']:
  base=estimate(materialize(full,schedule,c,c['phases'][0]))
  size=base['de_size'];pm={}
  phrases={p['id']:p for l in full['lanes'] for p in l['phrases']}
  for group in c['phases'][0]['groups']:
   slot=next(s for s in base['slots'] if s['id']==group['id'])
   for pid in group['context_phrase_ids']+group['representative_phrase_ids']:
    p=phrases[pid];dl=line_count(p['de'],size);zl=line_count(p['zh'],base['zh_size'])
    pm[pid]={'de_line_count':dl,'zh_line_count':zl,'block_height':dl*base['de_leading']+10+zl*base['zh_leading'],'preview_height':dl*base['de_leading']*40/55,'preview_offset':slot['preview_offset']}
  # Keep each surviving representative at its original baseline after a merge.
  phases=[{**copy.deepcopy(base),'id':phase['id'],'start':phase['start'],'end':phase['end'],'slots':[copy.deepcopy(s) for s in base['slots'] if s['id'] in {g['id'] for g in phase['groups']}]} for phase in c['phases']]
  result.append({'id':c['id'],'de_size':size,'phrase_layout':pm,'phases':phases})
 return {'schema_version':1,'fps':60,'coordinate_space':'3840x2160','status':'font_metric_estimate_requires_browser_review','compile_inputs':{'cohort_schedule':digest(schedule),'full_timeline':digest(full)},'cohorts':result}
