"""Resolve continuous written ties without changing source voice identities."""
from fractions import Fraction
from itertools import groupby

def rational(v):
 return Fraction(*v) if isinstance(v,(list,tuple)) else Fraction(str(v))

def tie_chains(events):
 """Return event-id chains. Ambiguous or discontinuous links remain separate."""
 chains=[];active=[]
 def actor(e):return (e.get('storage_staff',e.get('staff')),e.get('pitch'))
 rows=sorted(events,key=lambda e:rational(e['q']))
 for onset,group in groupby(rows,key=lambda e:rational(e['q'])):
  group=list(group);active=[a for a in active if a['end']>=onset]
  stops=[e for e in group if e.get('tie_stop') and e.get('pitch') is not None and not e.get('grace')]
  available=[a for a in active if a['end']==onset];matched={};used=set()
  for same_voice in (True,False):
   proposals={}
   for e in stops:
    if e['id'] in matched:continue
    possible=[a for a in available if id(a) not in used and actor(a['event'])==actor(e) and (not same_voice or a['event'].get('voice')==e.get('voice'))]
    if len(possible)==1:proposals[e['id']]=possible[0]
   for eid,a in proposals.items():
    if sum(v is a for v in proposals.values())==1:matched[eid]=a;used.add(id(a))
  active=[a for a in active if id(a) not in used]
  for e in group:
   if e['id'] in matched:chain=matched[e['id']]['chain'];chain.append(e['id'])
   else:chain=[e['id']];chains.append(chain)
   if e.get('tie_start') and e.get('pitch') is not None and not e.get('grace'):
    active.append(dict(event=e,end=onset+rational(e['duration']),chain=chain))
 return chains

def inherit_tie_colors(events,assignments,default='main'):
 result=dict(assignments)
 for chain in tie_chains(events):
  color=result.get(chain[0],default)
  for eid in chain:result[eid]=color
 return result
