from fractions import Fraction
from pathlib import Path
import sys, zipfile
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from score_sync import score

XML='''<score-partwise version="4.0"><part-list><score-part id="P1"><part-name>Clarinet</part-name></score-part></part-list><part id="P1"><measure number="0" implicit="yes"><attributes><divisions>3</divisions><time><beats>4</beats><beat-type>4</beat-type></time><staves>2</staves><transpose><diatonic>-1</diatonic><chromatic>-2</chromatic></transpose><clef number="1"><sign>G</sign><line>2</line></clef><clef number="2"><sign>F</sign><line>4</line></clef></attributes><note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration><voice>1</voice><type>eighth</type><staff>1</staff><tie type="start"/></note><note><chord/><pitch><step>E</step><octave>4</octave></pitch><duration>1</duration><voice>1</voice><type>eighth</type><staff>2</staff></note><backup><duration>1</duration></backup><note><rest/><duration>1</duration><voice>2</voice><type>eighth</type><staff>2</staff></note></measure><measure number="1"><note><grace/><pitch><step>D</step><octave>4</octave></pitch><type>16th</type><staff>1</staff></note><note><pitch><step>C</step><octave>4</octave></pitch><duration>12</duration><type>whole</type><staff>1</staff><tie type="stop"/></note></measure></part></score-partwise>'''

def test_rational_pickup_chord_backup_transpose(tmp_path):
 p=tmp_path/'score.xml';p.write_text(XML)
 s,xml=score.parse_musicxml(p)
 assert s['measures'][0]['end']==[1,3]
 assert s['events'][0]['pitch']==58
 assert s['events'][1]['q']==[0,1]
 assert s['events'][1]['staff']=='P1:2'
 assert s['events'][2]['kind']=='rest'
 assert s['events'][3]['grace'] and s['events'][3]['q']==[1,3]
 assert s['events'][4]['tie_stop']
 assert s['total_q']==[13,3]
 assert len({e['id'] for e in s['events']})==5
 assert s==score.parse_musicxml(p)[0]

def test_mxl_container_and_ambiguous_repeat(tmp_path):
 p=tmp_path/'s.mxl'
 with zipfile.ZipFile(p,'w') as z:
  z.writestr('META-INF/container.xml','<container><rootfiles><rootfile full-path="a/score.xml"/></rootfiles></container>')
  z.writestr('a/score.xml',XML.replace('</measure>','<barline><repeat direction="backward"/></barline></measure>',1))
 with pytest.raises(ValueError,match='source_route'):
  score.parse_musicxml(p)
 s,_=score.parse_musicxml(p,source_route=[1,1,2])
 assert len(s['measures'])==3 and len(s['events'])==8
 assert s['events'][0]['source_id']==s['events'][3]['source_id']
 assert s['events'][0]['id']!=s['events'][3]['id']

def test_prepare_native_exact_binding(tmp_path):
 pytest.importorskip('verovio');pypdf=pytest.importorskip('pypdf')
 p=tmp_path/'s.xml';p.write_text(XML)
 writer=pypdf.PdfWriter();writer.add_blank_page(width=595,height=842)
 pdf=tmp_path/'s.pdf'
 with pdf.open('wb') as f:writer.write(f)
 out=tmp_path/'out';score.prepare_score({'id':'sample','score':str(p),'pdf':str(pdf)},out)
 import json
 g=json.loads((out/'geometry.json').read_text());s=json.loads((out/'score.json').read_text())
 assert len(g['notes'])==len([e for e in s['events'] if e['visible']])
 assert all(n['x']>=0 for n in g['notes'])
 assert g['width']>0 and len(g['staves'])==2
 assert s['pdf']['pages']==1

def test_nonimplicit_short_measure_is_not_padded(tmp_path):
 # Numbered pickups often omit implicit="yes" in exports. Actual musical duration
 # is authoritative; a nonempty short bar must not acquire invented rests.
 p=tmp_path/'s.xml';p.write_text(XML.replace(' implicit="yes"',''))
 s,_=score.parse_musicxml(p)
 assert s['measures'][0]['end']==[1,3]

def test_native_coordinate_uses_notehead_not_accidental():
 from xml.etree import ElementTree as E
 n=E.fromstring('<g xmlns="http://www.w3.org/2000/svg"><g class="accid"><use transform="translate(10,20)"/></g><g class="notehead"><use transform="translate(30,20)"/></g></g>')
 assert score._xy(n)==(30,20)

def test_native_repeat_occurrences_have_distinct_bound_glyphs(tmp_path):
 pytest.importorskip('verovio');pypdf=pytest.importorskip('pypdf')
 p=tmp_path/'repeat.xml';p.write_text(XML)
 w=pypdf.PdfWriter();w.add_blank_page(width=595,height=842)
 pdf=tmp_path/'s.pdf'
 with pdf.open('wb') as f:w.write(f)
 out=tmp_path/'out'
 score.prepare_score({'score':str(p),'pdf':str(pdf),'source_route':[1,1,2]},out)
 import json
 g=json.loads((out/'geometry.json').read_text())
 assert len(g['notes'])==8
 assert g['notes'][3]['x']>g['notes'][0]['x']
 assert len(set(n['svg_id'] for n in g['notes']))==8
 assert g['measures'][-1]['width']>0

def test_cue_note_does_not_claim_instrument_sounds(tmp_path):
 p=tmp_path/'cue.xml';p.write_text(XML.replace('<note><pitch>','<note><cue/><pitch>',1))
 s,_=score.parse_musicxml(p)
 assert s['events'][0]['is_player'] is False
 assert s['events'][0]['visible'] is True
 assert s['events'][1]['is_player'] is True
