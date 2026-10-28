"""Compile exact lyric groups over the entire movement, independent of render chunks."""
import copy,hashlib,json
MERGE_SECONDS=.45

def digest(value):
 return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def compile_schedule(full,entries,presence):
 sr=full['sample_rate'];sample=lambda t:round(t*sr)
 lanes={l['id']:l for l in full['lanes']};order={lid:i for i,lid in enumerate(lanes)}
 ps={p['id']:p for l in full['lanes'] for p in l['phrases']}
 entry={p['id']:p for p in entries['phrases']}
 runs=sorted([copy.deepcopy(r) for l in full['lanes'] for r in l['runs']],key=lambda r:(sample(r['start']),sample(r['end']),order[r['staff']]))
 components=[]
 for r in runs:
  if components and sample(r['start'])<sample(components[-1]['end']):
   components[-1]['runs'].append(r);components[-1]['end']=max(components[-1]['end'],r['end'])
  else:components.append({'start':r['start'],'end':r['end'],'runs':[r]})
 def admit(p):return entry[p['id']]['admit'] if p['id'] in entry else p['preview_at'] if p['preview_at'] is not None else p['start']
 def groups_for(c,cut,prior=None):
  source={lid:[ps[pid] for r in c['runs'] if r['staff']==lid for pid in r['phrases']] for lid in lanes}
  result={}
  for lid,allps in source.items():
   if not allps:continue
   remain=[p for p in allps if p['end']+.25>cut+1e-8]
   unsafe=[n['id'] for n in full['unowned_notes'] if n['staff']==lid and any(n['range_samples'][0]<p['end_sample'] and n['range_samples'][1]>p['start_sample'] for p in remain)]
   signature={'family':lanes[lid]['family'],
    'phrases':[{'de':p['de'],'zh':p['zh'],'start_sample':p['start_sample'],'end_sample':p['end_sample'],
      'admit_sample':sample(admit(p)),'preview_at':p['preview_at'],'continuity':p['continuity_from_previous'],'motion':p['motion'],
      'syllables':[(s['text'],s['start_char'],s['end_char'],s['sounding_intervals_samples']) for s in p['segments']]} for p in remain],
    'remaining_role_intervals':[(max(sample(cut),sample(r['start'])),sample(r['end']+.25)) for r in c['runs'] if r['staff']==lid and r['end']+.25>cut+1e-8]}
   h=digest(signature);key=lid if unsafe or not remain else h
   if not remain and prior:key='empty:'+next(g['id'] for g in prior if lid in g['members'])
   if key not in result:
    # One prior phrase is kept only as motion context, never rendered twice.
    context=[]
    if remain and remain[0]['continuity_from_previous']:
     k=allps.index(remain[0]);context=allps[max(0,k-1):k]
    result[key]={'id':lid,'members':[],'label':'','color':lanes[lid]['color'],'signature_sha256':h,'signature':signature,
     'source_phrase_ids':{},'representative_phrase_ids':[p['id'] for p in remain],
     'context_phrase_ids':[p['id'] for p in context],'run_ids':[], 'unowned_notes':[]}
   g=result[key];g['members'].append(lid);g['source_phrase_ids'][lid]=[p['id'] for p in remain]
   g['run_ids'] += [r['id'] for r in c['runs'] if r['staff']==lid]
   g['unowned_notes']+=unsafe
   g['label']='、'.join(lanes[m]['label'] for m in g['members'])
   if len(g['members'])>1:g['color']='#A34878'
  return list(result.values())
 def safe_silence(members,start,end):
  a,b=sample(start),sample(end)
  return not any(x<b and y>a for lid in members for p in lanes[lid]['phrases'] for s in p['segments'] for x,y in s['sounding_intervals_samples'])
 out=[]
 for ix,c in enumerate(components,1):
  c['id']=f'vocal-cohort-{ix:02d}'
  c['run_ids']=[r['id'] for r in c['runs']];c['phrase_ids']=[p for r in c['runs'] for p in r['phrases']]
  c['display_start']=min(admit(ps[p]) for p in c['phrase_ids']);c['display_end']=c['end']+.25
  c['members']=sorted({r['staff'] for r in c['runs']},key=order.get)
  current=groups_for(c,c['display_start']);phases=[{'id':c['id']+'-phase-01','start':c['display_start'],'end':c['display_end'],'groups':current}];transitions=[]
  candidates=sorted({round(ps[p]['end']+.25,9) for p in c['phrase_ids'] if ps[p]['end']+.25+MERGE_SECONDS<c['end']})
  for t in candidates:
   if t<phases[-1]['start']+1e-8:continue
   proposed=groups_for(c,t,current)
   # A partition can only become coarser. Never split a prior exact merge because
   # later lyrics diverge: that divergence is already in the complete suffix hash.
   merges=[];accepted=[]
   for g in proposed:
    m=set(g['members']);old=[v for v in current if set(v['members'])<=m]
    if set().union(*(set(v['members']) for v in old))!=m:
     raise AssertionError('A whole-suffix grouping unexpectedly split')
    if len(old)>1 and g['representative_phrase_ids'] and safe_silence(g['members'],t,t+MERGE_SECONDS):
     accepted.append(g);merges.append({'members':g['members'],'from_groups':[v['id'] for v in old],'to_group':g['id'],'signature_sha256':g['signature_sha256']})
    else:accepted.extend(old)
   accepted.sort(key=lambda g:order[g['members'][0]])
   if not merges:continue
   # Refresh unchanged groups at the new full-source epoch without pruning output
   # windows. Keep their existing membership; source IDs remain auditable.
   t_end=round(t+MERGE_SECONDS,9)
   transitions.append({'start':t,'end':t_end,'type':'coalesce_in_shared_source_rest','merges':merges,
     'all_merging_members_silent':True,'whole_remaining_phrase_chains_equal':True,
     'ownership':'one live phrase instance per source occurrence; interpolate group geometry; switch membership atomically at end; never crossfade duplicate phrase ink',
     'geometry_requires_actual_frame_review':True})
   phases[-1]['end']=t_end
   phases.append({'id':c['id']+f'-phase-{len(phases)+1:02d}','start':t_end,'end':c['display_end'],'groups':accepted})
   current=accepted
  c['phases']=phases;c['merge_transitions']=transitions
  c['maximum_display_groups']=max(len(p['groups']) for p in phases)
  out.append(c)
 handoffs=[]
 for a,b in zip(out,out[1:]):
  if sample(a['end'])!=sample(b['start']):continue
  old=[p for pid in a['phrase_ids'] if (p:=ps[pid])['end']+.25>b['start']]
  new=[p for pid in b['phrase_ids'] if (p:=ps[pid]) and admit(p)<=b['start']+.25]
  handoffs.append({'id':a['id']+'--'+b['id'],'from_cohort':a['id'],'to_cohort':b['id'],'boundary':b['start'],
   'tail_role_until':a['end']+.25,'bridge_duration_seconds':.45,'clear_seconds':.25,'settle_end':round(b['start']+.45,9),'old_phrase_exit_ends':{p['id']:p['end']+p['motion']['exit_seconds'] for p in old},
   'outgoing_phrase_ids':[p['id'] for p in old],'incoming_phrase_ids':[p['id'] for p in new],
   'outgoing_groups':[g['members'] for g in a['phases'][-1]['groups']],
   'incoming_groups':[g['members'] for g in b['phases'][0]['groups']],
   'paper_policy':'one global panel paper; cohort groups never own paper',
   'body_policy':'outgoing tail unique instance and incoming unique instance coexist; source clocks and active syllable colors unchanged',
   'geometry_policy':'fixed full-source bridge for tail and incoming groups during at most .25s; no hard switch or duplicate shared phrase; review actual bounds before integration',
   'geometry_requires_actual_frame_review':True})
 for c in out:c['render_context_end']=max([c['display_end']]+[h['settle_end'] for h in handoffs if h['from_cohort']==c['id']])
 return {'schema_version':1,'status':'research_data_validated_browser_geometry_pending','movement':full.get('movement',''),'sample_rate':sr,
  'compile_inputs':{'full_timeline':digest(full),'panel_entries':digest(entries),'panel_presence':digest(presence)},
  'policy':{'cohort':'strict positive source-run overlap, integer samples; touching endpoints not unioned','partition':'complete remaining phrase-clock chains; solo-choir isolation; ambiguous notes veto; only coalesce during .45s common source rest','layout':'one fixed layout per full-source phase, never fit by output clip','paper':'one shared full-movement horizontal paper'},
  'source_hashes':copy.deepcopy(full['source_hashes']),'panel_presence':copy.deepcopy(presence),'panel_entries':copy.deepcopy(entries),'cohorts':out,'handoffs':handoffs}

def project_window(schedule,start,end):
 """Select complete global objects; output bounds never mutate their contents."""
 return {'schema_version':schedule['schema_version'],'clip':{'start':start,'end':end},
  'cohorts':[copy.deepcopy(c) for c in schedule['cohorts'] if c['display_start']<end and c['render_context_end']>start],
  'handoffs':[copy.deepcopy(h) for h in schedule['handoffs'] if h['boundary']<end and h['settle_end']>start]}
