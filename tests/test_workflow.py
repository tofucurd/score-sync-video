import sys,json
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from score_sync.workflow import load_project, fingerprint, approve, require_approval, clean_candidates, frame_chunks, validate_structure

def project(tmp_path):
 p=tmp_path/'project.json';p.write_text(json.dumps({'schema':1,'work':{'title':'测试'},'movements':[{'id':'m1','score':'a.xml','pdf':'a.pdf','audio':'a.wav'}]}));
 for n in ['a.xml','a.pdf','a.wav']:(tmp_path/n).write_text(n)
 d=tmp_path/'.score-sync/m1';d.mkdir(parents=True)
 for n in ['score.json','alignment.json','geometry.json','structure.json','materials.json']:(d/n).write_text('{}')
 (d/'audio.wav').write_text('cached');return load_project(p)

def test_approval_bound_to_data_and_preview(tmp_path):
 cfg=project(tmp_path)
 with pytest.raises(ValueError,match='approval'):require_approval(cfg)
 out=tmp_path/'output';out.mkdir();(out/'preview.mov').write_text('preview')
 h=fingerprint(cfg)
 (out/'preview-manifest.json').write_text(json.dumps({'fingerprint':h,'artifacts':[{'path':'preview.mov','sha256':__import__('hashlib').sha256(b'preview').hexdigest()}]}))
 (out/'team-review.json').write_text(json.dumps({'fingerprint':h,'reviewers':[{'name':x,'approved':True,'scope':'whole-program'} for x in ['A','B','C']]}))
 approve(cfg,'User explicitly accepted the shown previews')
 assert require_approval(cfg)['fingerprint']==h
 (tmp_path/'.score-sync/m1/alignment.json').write_text('{"changed":true}')
 with pytest.raises(ValueError,match='changed'):require_approval(cfg)

def test_cleanup_preserves_inputs_and_alignment(tmp_path):
 cfg=project(tmp_path);items=clean_candidates(cfg)
 assert tmp_path/'.score-sync/m1/audio.wav' in items
 assert not any(p.name in ['a.wav','alignment.json','score.json'] for p in items)

def test_no_duplicate_or_missing_global_frames():
 chunks=frame_chunks(3601,1800)
 assert chunks==[(0,1800),(1800,1800),(3600,1)]

def test_nested_sections_cover_exactly():
 validate_structure({'reviewed':True,'sections':[{'label':'A','start_q':0,'end_q':4,'children':[{'label':'a','start_q':0,'end_q':4}]}]},4)
 with pytest.raises(ValueError):validate_structure({'reviewed':True,'sections':[{'label':'A','start_q':1,'end_q':4,'children':[]}]},4)

def test_project_paths_cannot_escape_generated_workspace(tmp_path):
 cfg=project(tmp_path);p=tmp_path/'project.json';data=json.loads(p.read_text());data['movements'][0]['id']='../escape';p.write_text(json.dumps(data))
 with pytest.raises(ValueError):load_project(p)

def test_prepared_audio_changes_freeze(tmp_path):
 cfg=project(tmp_path);before=fingerprint(cfg)
 (tmp_path/'.score-sync/m1/audio.wav').write_text('altered source master')
 assert fingerprint(cfg)!=before

def test_inherited_authorization_preserves_original_statement(tmp_path):
 cfg=project(tmp_path);out=tmp_path/'output';out.mkdir();(out/'preview.mov').write_text('reviewed')
 from score_sync.workflow import digest,write
 def reviewed_manifest():
  h=fingerprint(cfg)
  write(out/'preview-manifest.json',{'fingerprint':h,'artifacts':[{'path':'preview.mov','sha256':digest(out/'preview.mov')}]})
  write(out/'team-review.json',{'fingerprint':h,'reviewers':[{'name':n,'approved':True,'scope':'whole-program'} for n in ['A','B','C']]})
 reviewed_manifest();first=approve(cfg,'开始渲染已审核的这套预览')
 (tmp_path/'.score-sync/m1/alignment.json').write_text('{"revised":true}')
 reviewed_manifest();new=approve(cfg,'修改当前已授权作品的音符显示',inherit=True)
 assert new['new_user_confirmation'] is False
 assert new['inherited_authorization']==first
 assert require_approval(cfg)['fingerprint']==fingerprint(cfg)
