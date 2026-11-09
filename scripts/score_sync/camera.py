"""Display-only camera knots for leading grace notes sharing the first beat.

The musical q clock deliberately has no negative beats. Its initial hold must
not erase independently scheduled, engraved grace notes before the main attack.
"""
from statistics import median


def leading_grace_knots(knots, events, geometry_notes, aligned_notes, sample_rate):
    source={e['id']:e for e in events}
    positions={n['id']:float(n['x']) for n in geometry_notes}
    rows=[n for n in aligned_notes if n['id'] in positions and n['id'] in source
          and source[n['id']].get('kind')=='pitched'
          and source[n['id']].get('visible') is not False
          and source[n['id']].get('is_player',True)]
    main=[n for n in rows if not source[n['id']].get('grace')]
    if not main:
        return knots, {'applied':False,'reason':'no_main_attack'}
    first_sample=min(n['range'][0] for n in main)
    first=first_sample/sample_rate
    main_x=knots.get(first)
    if main_x is None:
        return knots, {'applied':False,'reason':'first_main_attack_not_a_camera_knot'}
    grace=[n for n in rows if source[n['id']].get('grace')
           and 0<=n['range'][0]<n['range'][1]<=first_sample
           and positions[n['id']]<main_x]
    if not grace:
        return knots, {'applied':False,'reason':'no_leading_graces'}
    grouped={}
    for n in grace:
        grouped.setdefault(n['range'][0]/sample_rate,[]).append(n)
    lead=[(t,float(median(positions[n['id']] for n in ns)))
          for t,ns in sorted(grouped.items())]
    if any(b[1]<a[1] for a,b in zip(lead,lead[1:])):
        raise ValueError('Leading grace camera order reverses; inspect source ownership')
    revised={t:x for t,x in knots.items() if t>=first}
    revised[0.]=lead[0][1]
    revised.update(lead)
    return revised, {'applied':True,'main_seconds':first,'main_x':main_x,
                     'leading_knots':[{'seconds':t,'x':x,'ids':[n['id'] for n in grouped[t]]}
                                      for t,x in lead],
                     'musical_clock_and_audio_changed':False}
