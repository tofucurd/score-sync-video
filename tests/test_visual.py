import sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from score_sync.visual import roman, note_envelope, cohort_weights, build_axis, frame_state
class VisualTests(unittest.TestCase):
 def test_roman(self):
  self.assertEqual(roman(9),'IX'); self.assertEqual(roman(14),'XIV'); self.assertEqual(roman('IX'),'IX')
 def test_highlight_stays_inside_recorded_interval(self):
  self.assertEqual(note_envelope(.9,1,2),0); self.assertEqual(note_envelope(2.1,1,2),0)
  self.assertEqual(note_envelope(1.3,1,2),1); self.assertGreater(note_envelope(1.02,1,2),0)
 def test_cohort_not_per_note(self):
  sections=[{'start':0,'end':20,'staves':['a']},{'start':20,'end':30,'staves':['b']}]
  self.assertEqual(cohort_weights(sections,10),{'a':1.0,'b':0.0})
  self.assertGreater(cohort_weights(sections,19)['b'],0)
  self.assertEqual(cohort_weights(sections,22)['b'],1)
 def test_axis_monotone_and_onset_favored(self):
  geometry={'notes':[{'id':'a','x':100},{'id':'b','x':200}], 'measures':[{'q':[0,1],'end':[2,1],'x':90,'width':150}]}
  score={'events':[{'id':'a','q':[0,1],'grace':False},{'id':'b','q':[1,1],'grace':False}]}
  self.assertEqual(build_axis(score,geometry),[[0.,100.],[1.,200.],[2.,240.]])
if __name__=='__main__':unittest.main()

def test_source_time_curve_hits_native_columns(tmp_path,monkeypatch):
 import json
 from score_sync import visual
 monkeypatch.setattr(visual,'font_css',lambda _: '')
 def put(name,data):(tmp_path/name).write_text(json.dumps(data))
 events=[{'id':'a','q':[0,1],'duration':[1,1],'staff':'s','kind':'pitched'}, {'id':'b','q':[1,1],'duration':[1,1],'staff':'s','kind':'pitched'}]
 put('score.json',{'events':events});put('geometry.json',{'notes':[{'id':'a','x':100},{'id':'b','x':200}],'measures':[{'q':[0,1],'end':[2,1],'x':90,'width':410}],'staves':[{'id':'s','label':'Violin'}]})
 put('alignment.json',{'sample_rate':100,'samples':200,'points':[[0,0],[200,2]],'notes':[{'id':'a','range':[0,100]},{'id':'b','range':[100,200]}]});put('audio.json',{'bits':24});put('structure.json',{'reviewed':True,'sections':[{'label':'Phrase','start_q':0,'end_q':2}]});(tmp_path/'score.svg').write_text('<svg/>')
 b=visual.bundle({'work':{},'movements':[]},tmp_path)
 assert b['curve'](1)==200 # Pure endpoint interpolation would incorrectly give300.
 assert b['curve'](2)==500
 assert visual.frame_state(b,.5)['highlights']['a']['weight']==1

def test_visible_cue_keeps_geometry_without_playing_highlight(tmp_path,monkeypatch):
 import json
 from score_sync import visual
 monkeypatch.setattr(visual,'font_css',lambda _: '')
 def put(name,data):(tmp_path/name).write_text(json.dumps(data))
 events=[{'id':'real','q':[0,1],'duration':[1,1],'staff':'s','kind':'pitched','is_player':True},{'id':'cue','q':[0,1],'duration':[1,1],'staff':'c','kind':'pitched','is_player':False}]
 put('score.json',{'events':events});put('geometry.json',{'notes':[{'id':'real','x':100},{'id':'cue','x':100}],'measures':[{'q':[0,1],'end':[1,1],'x':90,'width':200}],'staves':[{'id':'s','label':'Player'},{'id':'c','label':'Cue'}]})
 put('alignment.json',{'sample_rate':100,'samples':100,'points':[[0,0],[100,1]],'notes':[{'id':'real','range':[0,100]},{'id':'cue','range':[0,100]}]});put('audio.json',{'bits':24});put('structure.json',{'reviewed':True,'sections':[{'label':'Phrase','start_q':0,'end_q':1}]});(tmp_path/'score.svg').write_text('<svg/>')
 b=visual.bundle({'work':{},'movements':[]},tmp_path)
 assert len(b['geometry']['notes'])==2
 assert 'cue' not in visual.frame_state(b,.5)['highlights']
 assert b['cohorts'][0]['staves']==['s']

def test_cohort_sections_independent_from_navigation():
 from score_sync.visual import cohort_sections
 s={'sections':[{'start_q':0,'end_q':8,'children':[{'start_q':0,'end_q':4},{'start_q':4,'end_q':8}]}]}
 assert len(cohort_sections(s))==2
 s['cohort_sections']=[{'start_q':0,'end_q':2},{'start_q':2,'end_q':8}]
 assert cohort_sections(s)[0]['end_q']==2
 s['cohort_sections']=[{'start_q':0,'end_q':3},{'start_q':4,'end_q':8}]
 import pytest
 with pytest.raises(ValueError,match='contiguous'):cohort_sections(s)


def test_cached_frame_state_supports_backward_seek():
 b={'alignment':{'sample_rate':100,'points':[[0,0],[300,3]]},'duration':3,'notes':[{'id':'a','start':0.2,'end':1.8,'color':'red'},{'id':'b','start':1.5,'end':2.5,'color':'blue'}],'curve':lambda t:t*100,'cohorts':[{'start':0,'end':3,'staves':['s']}]}
 early=frame_state(b,.8,with_navigation=False)
 assert set(frame_state(b,1.7,with_navigation=False)['highlights'])=={'a','b'}
 assert set(frame_state(b,2.2,with_navigation=False)['highlights'])=={'b'}
 assert frame_state(b,.8,with_navigation=False)==early
 assert not frame_state(b,3,with_navigation=False)['highlights']


def test_cursor_uses_main_column_despite_displaced_chord_heads():
 # Synthetic engraving displaces a few chord heads around the rhythmic column.
 xs=[1000.,990.,1000.,975.,1000.,1000.,1000.,1030.]+[1000.]*12
 score={'events':[{'id':str(i),'q':[2,1],'grace':False} for i in range(len(xs))]}
 geometry={'notes':[{'id':str(i),'x':x} for i,x in enumerate(xs)],'measures':[{'q':[2,1],'end':[6,1],'x':950.,'width':300.}]}
 assert build_axis(score,geometry)[0]==[2.,1000.]


def test_centered_whole_bar_rests_do_not_move_played_onset_column():
 events=[{'id':'a','q':[0,1],'kind':'pitched'},{'id':'b','q':[1,1],'kind':'pitched'}]+[{'id':f'r{i}','q':[0,1],'kind':'rest'} for i in range(4)]
 geometry={'notes':[{'id':'a','x':100},{'id':'b','x':200}]+[{'id':f'r{i}','x':300} for i in range(4)],'measures':[{'q':[0,1],'end':[4,1],'x':90,'width':410}]}
 assert build_axis({'events':events},geometry)==[[0.,100.],[1.,200.],[4.,500.]]


def test_fast_attack_is_visible_within_one_video_frame():
 assert note_envelope(1+1/60,1,1.1)>.95
