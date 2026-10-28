import copy, hashlib, json, subprocess
from pathlib import Path
import pytest
from score_sync.presentation_layers import load_layers
from score_sync.vocal_schedule import compile_schedule, digest, project_window
from score_sync.vocal_layout import compile_layout


def fixture(tmp_path, different_translation=False):
    geo={'notes':[{'id':'n','staff':'a','svg_id':'note','x':1000,'y':1000}],
         'staves':[{'id':k,'label':k,'y':1000+2000*i,'height':400,'svg_ids':['staff'+k]} for i,k in enumerate(['a','b'])],
         'measures':[{'svg_id':'measure','index':1,'source_index':1,'occurrence':1,'q':[0,1],'end':[4,1],'x':0,'width':6000}], 'controls':[]}
    bindings={}
    for name,value in [('score',{}),('geometry',geo),('alignment',{})]:
        data=json.dumps(value).encode();(tmp_path/(name+'.json')).write_bytes(data)
        bindings[name]={'path':name+'.json','sha256':hashlib.sha256(data).hexdigest()}
    lanes=[]
    for k in ['a','b']:
        pid=k+'-phrase';run=k+'-run'
        seg={'source_lyric_event_id':k+'-syllable','text':'La','start_char':0,'end_char':2,'start':2,'end':4,'sounding_intervals_samples':[[200,400]]}
        phrase={'id':pid,'staff':k,'run_id':run,'de':'La','zh':'歌' if k=='a' or not different_translation else '声','start':2,'end':4,'start_sample':200,'end_sample':400,'start_q':0,'end_q':2,'continuity_from_previous':False,'preview_at':None,'motion':{'rise_seconds':.3,'clear_seconds':.1,'entrance_seconds':.2,'exit_seconds':.25},'segments':[seg]}
        lanes.append({'id':k,'family':'choir','label':k,'color':'#C94732' if k=='a' else '#27835D','runs':[{'id':run,'staff':k,'start':2,'end':4,'phrases':[pid]}],'phrases':[phrase]})
    full={'sample_rate':100,'movement':'any-id','source_hashes':bindings,'unowned_notes':[],'lanes':lanes}
    entries={'phrases':[{'id':l['phrases'][0]['id'],'run_id':l['runs'][0]['id'],'admit':.6,'full':1.8} for l in lanes]}
    presence={'windows':[{'enter_start':.6,'enter_end':1.8,'exit_start':4.25,'exit_end':5.1}]}
    schedule=compile_schedule(full,entries,presence);layout=compile_layout(full,schedule)
    folder=tmp_path/'vocals';folder.mkdir(exist_ok=True)
    for name,obj in [('timeline',full),('cohort-schedule',schedule),('layout-schedule',layout)]:
        (folder/(name+'.json')).write_text(json.dumps(obj))
    return geo,full,schedule,layout


def test_exact_merge_translation_and_solo_are_significant(tmp_path):
    _,full,schedule,_=fixture(tmp_path)
    assert schedule['cohorts'][0]['phases'][0]['groups'][0]['members']==['a','b']
    changed=copy.deepcopy(full);changed['lanes'][1]['phrases'][0]['zh']='不同'
    s=compile_schedule(changed,schedule['panel_entries'],schedule['panel_presence'])
    assert len(s['cohorts'][0]['phases'][0]['groups'])==2
    changed=copy.deepcopy(full);changed['lanes'][1]['family']='solo'
    s=compile_schedule(changed,schedule['panel_entries'],schedule['panel_presence'])
    assert len(s['cohorts'][0]['phases'][0]['groups'])==2


def test_global_layout_and_window_do_not_refit(tmp_path):
    geo,_,schedule,layout=fixture(tmp_path,True)
    a=project_window(schedule,2,2.5);b=project_window(schedule,3,4)
    assert a['cohorts']==b['cohorts']==schedule['cohorts']
    payload,text=load_layers(tmp_path,geo)
    assert payload['vocalProgramme']['layout']==layout
    assert '歌' in text and '声' in text
    (tmp_path/'alignment.json').write_text('{"new_clock":true}')
    with pytest.raises(ValueError,match='source changed'):load_layers(tmp_path,geo)


def test_stale_layout_rejected(tmp_path):
    geo,_,_,layout=fixture(tmp_path)
    layout['compile_inputs']['full_timeline']='old'
    (tmp_path/'vocals/layout-schedule.json').write_text(json.dumps(layout))
    with pytest.raises(ValueError,match='layout input'):load_layers(tmp_path,geo)


def test_optional_material_layer_and_unknown_note(tmp_path):
    geo,full,_,_=fixture(tmp_path)
    material={'source_hashes':full['source_hashes'],'x_shift':0,'regions':[{'staff':'a','start_x':500,'end_x':2000,'theme':'one'}],'palette':{'one':'#353BB5'},'short_names':{'one':'主题'},'assignments':{'n':'one'}}
    (tmp_path/'material-regions.json').write_text(json.dumps(material))
    payload,text=load_layers(tmp_path,geo)
    assert payload['material_regions']==material and '主题' in text
    material['assignments']['unknown']='one'
    (tmp_path/'material-regions.json').write_text(json.dumps(material))
    with pytest.raises(ValueError,match='unknown event'):load_layers(tmp_path,geo)


def test_region_ownership_overlap_and_neutral():
    module=(Path(__file__).parents[1]/'scripts/layers/region_ink.mjs').as_uri()
    code=f'''import {{createMaterialIndex}} from {json.dumps(module)};
    import assert from 'node:assert/strict';
    const i=createMaterialIndex({{x_shift:0,regions:[{{staff:'s',start_x:0,end_x:100,theme:'a'}},{{staff:'s',start_x:50,end_x:150,theme:'b'}}],shared_staff_neutral_intervals:[{{staff:'s',start_x:10,end_x:20}}]}});
    assert.equal(i.at('s',5),'a');assert.equal(i.at('s',15),null);
    assert.equal(i.at('s',75),null);assert.equal(i.at('s',125),'b');
    assert.equal(i.span('s',5,25),null);assert.equal(i.span('s',110,140),'b');'''
    subprocess.run(['node','--input-type=module','-e',code],check=True)


def test_notation_route_restarts_and_source_rehearsals():
    from xml.etree import ElementTree as ET
    from score_sync.notation_labels import compile_signatures,compile_locators
    xml=ET.fromstring('''<score-partwise><part id="p"><measure number="101"><attributes><divisions>1</divisions><clef><sign>G</sign><line>2</line></clef><key><fifths>-2</fifths></key><transpose><diatonic>-1</diatonic><chromatic>-2</chromatic></transpose></attributes><direction><direction-type><rehearsal>A</rehearsal></direction-type></direction><note><duration>4</duration></note></measure><measure number="102"><attributes><clef><sign>F</sign><line>4</line></clef><key><fifths>1</fifths></key></attributes><note><duration>4</duration></note></measure></part></score-partwise>''')
    measures=[{'index':i+1,'source_index':source,'occurrence':2 if i==2 else 1,'q':[i*4,1],'end':[(i+1)*4,1],'x':i*2000,'width':2000} for i,source in enumerate([1,2,1])]
    score={'measures':measures,'events':[]}
    geo={'staves':[{'id':'p:1','height':400}],'measures':measures,'notes':[]}
    notation=compile_signatures(xml,score,geo,'<svg/>')
    states=notation['staves']['p:1']['events']
    assert [s['sign'] for s in states]==['G','F','G']
    assert [s['fifths'] for s in states]==[-2,1,-2]
    assert all(s['pitch_label']=='B♭' for s in states)
    locators=compile_locators(xml,score,geo,interval=1,number_offset=100)
    assert [s['text'] for s in locators['items']]==['A','2','A']
    assert [s['occurrence'] for s in locators['items']]==[1,1,2]


def test_opening_only_changes_visibility():
    module=(Path(__file__).parents[1]/'scripts/layers/opening.mjs').as_uri()
    code=f'''import {{openingState}} from {json.dumps(module)};import assert from 'node:assert/strict';
    const f={{seconds:.1,q:9,x:123,highlights:{{n:{{weight:1}}}},weights:{{s:1}}}};
    const out=openingState(f,{{duration_seconds:2,initial_phase:0}});
    assert.equal(out.x,f.x);assert.equal(out.q,f.q);assert.equal(out.highlights,f.highlights);assert.ok(out.weights.s<1);
    assert.equal(f.weights.s,1);'''
    subprocess.run(['node','--input-type=module','-e',code],check=True)
