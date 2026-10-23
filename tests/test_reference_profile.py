"""Portable reconstruction must not silently borrow another recording's clock."""
import hashlib,json,zipfile
from pathlib import Path
import pytest
from score_sync import workflow as w


def fixture_profile(tmp_path):
    registry=tmp_path/'registry';registry.mkdir()
    inputs={k:tmp_path/f'input.{k}' for k in ('score','pdf','audio')}
    for k,p in inputs.items():p.write_bytes(k.encode())
    cfg={'schema':1,'work':{'title':'fixture'},'movements':[{'id':'m1','title':'第一乐章','score':'derived/m1.musicxml','pdf':'INPUT','audio':'INPUT'}]}
    files={'project-template.json':json.dumps(cfg).encode(),'derived/m1.musicxml':b'<score/>','.score-sync/m1/alignment.json':b'{"points":[[0,0],[10,1]]}'}
    archive=registry/'fixture.zip'
    with zipfile.ZipFile(archive,'w') as z:
        for path,data in files.items():z.writestr(path,data)
    manifest={'schema':1,'id':'fixture','version':'1.0.0','archive':archive.name,'archive_sha256':w.digest(archive),'files':{n:hashlib.sha256(v).hexdigest() for n,v in files.items()},'inputs':[{'role':k,'index':0,'sha256':w.digest(p)} for k,p in inputs.items()],'movements':{'m1':{'audio_index':0,'pdf_index':0}}}
    (registry/'fixture.json').write_text(json.dumps(manifest))
    return registry,inputs,manifest


def test_restore_reference_into_unrelated_directory_without_approval(tmp_path,monkeypatch):
    from score_sync import profiles
    registry,inputs,_=fixture_profile(tmp_path)
    monkeypatch.setattr(profiles,'REGISTRY',registry)
    dest=tmp_path/'new-session/project.json'
    result=profiles.restore_reference('fixture',dest,scores=[inputs['score']],pdfs=[inputs['pdf']],audios=[inputs['audio']])
    cfg=w.load_project(dest)
    assert Path(cfg['movements'][0]['audio'])==inputs['audio']
    assert (dest.parent/'.score-sync/m1/alignment.json').read_text()=='{"points":[[0,0],[10,1]]}'
    assert not (dest.parent/'output/approval.json').exists()
    assert result['stage']=='reference-restored'
    assert profiles.verify_reference(cfg)['matched'] is True


def test_wrong_recording_rejected_before_writing(tmp_path,monkeypatch):
    from score_sync import profiles
    registry,inputs,_=fixture_profile(tmp_path);monkeypatch.setattr(profiles,'REGISTRY',registry)
    inputs['audio'].write_bytes(b'another performance')
    dest=tmp_path/'wrong/project.json'
    with pytest.raises(ValueError,match='audio.*hash|audio.*SHA'):
        profiles.restore_reference('fixture',dest,scores=[inputs['score']],pdfs=[inputs['pdf']],audios=[inputs['audio']])
    assert not dest.parent.exists()


def test_reference_detects_later_data_change(tmp_path,monkeypatch):
    from score_sync import profiles
    registry,inputs,_=fixture_profile(tmp_path);monkeypatch.setattr(profiles,'REGISTRY',registry)
    dest=tmp_path/'new/project.json'
    profiles.restore_reference('fixture',dest,scores=[inputs['score']],pdfs=[inputs['pdf']],audios=[inputs['audio']])
    (dest.parent/'.score-sync/m1/alignment.json').write_text('{}')
    with pytest.raises(ValueError,match='alignment.json'):
        profiles.verify_reference(w.load_project(dest))


def test_reference_does_not_report_match_after_changing_art_direction(tmp_path,monkeypatch):
    from score_sync import profiles
    registry,inputs,_=fixture_profile(tmp_path);monkeypatch.setattr(profiles,'REGISTRY',registry)
    dest=tmp_path/'new/project.json'
    profiles.restore_reference('fixture',dest,scores=[inputs['score']],pdfs=[inputs['pdf']],audios=[inputs['audio']])
    cfg=w.load_project(dest);cfg['work']['title']='另一作品'
    with pytest.raises(ValueError,match='work configuration'):
        profiles.verify_reference(cfg)


def test_profile_rejects_unsafe_archive_paths(tmp_path,monkeypatch):
    from score_sync import profiles
    registry,inputs,m=fixture_profile(tmp_path);monkeypatch.setattr(profiles,'REGISTRY',registry)
    archive=registry/'fixture.zip'
    with zipfile.ZipFile(archive,'a') as z:z.writestr('../escape',b'bad')
    m['files']['../escape']=hashlib.sha256(b'bad').hexdigest();m['archive_sha256']=w.digest(archive)
    (registry/'fixture.json').write_text(json.dumps(m))
    with pytest.raises(ValueError,match='Unsafe'):
        profiles.restore_reference('fixture',tmp_path/'new/project.json',scores=[inputs['score']],pdfs=[inputs['pdf']],audios=[inputs['audio']])


def test_mux_keeps_chapter_names_with_global_metadata_disabled():
    assert hasattr(w,'final_mux_command'), 'Final mux needs an explicit chapter-title builder'
    manifest={'chapters':[{'title':'第一乐章 稍持重地—活泼地'},{'title':'第二乐章 小快板'}]}
    args=w.final_mux_command('list.txt','audio.m4a','chapters.ffmetadata','final.mov',manifest)
    assert args[args.index('-metadata:c:0')+1]=='title=第一乐章 稍持重地—活泼地'
    assert args[args.index('-metadata:c:1')+1]=='title=第二乐章 小快板'
    assert args[args.index('-c')+1]=='copy'


def test_audio_range_cannot_be_relabelled_without_preparing_again(tmp_path):
    from score_sync.bindings import alignment_binding
    d=tmp_path/'.score-sync/m1';d.mkdir(parents=True)
    src=tmp_path/'source.xml';src.write_bytes(b'score')
    audio=tmp_path/'source.flac';audio.write_bytes(b'audio')
    w.write(d/'score.json',{'source_sha256':w.digest(src),'source_route':[1]})
    w.write(d/'audio.json',{'source_sha256':w.digest(audio),'sample_rate':96000,
                           'samples':96000,'channels':2,'bits':24,'audio_range':None})
    w.write(d/'alignment.json',{})
    movement={'id':'m1','score':str(src),'audio':str(audio),'audio_range':[1,2]}
    with pytest.raises(ValueError,match='audio_range'):
        alignment_binding({'_root':str(tmp_path)},movement)


def test_rebinding_unchanged_data_preserves_frozen_serialization(tmp_path):
    from score_sync.bindings import alignment_binding,write_alignment_binding
    d=tmp_path/'.score-sync/m1';d.mkdir(parents=True)
    src=tmp_path/'source.xml';src.write_bytes(b'score')
    audio=tmp_path/'source.flac';audio.write_bytes(b'audio')
    w.write(d/'score.json',{'source_sha256':w.digest(src),'source_route':[1]})
    w.write(d/'audio.json',{'source_sha256':w.digest(audio),'sample_rate':96000,'samples':96000,'channels':2,'bits':24})
    w.write(d/'alignment.json',{})
    cfg={'_root':str(tmp_path)};m={'id':'m1','score':str(src),'audio':str(audio)}
    path=d/'alignment-inputs.json';path.write_text(json.dumps(alignment_binding(cfg,m),indent=4)+'\n')
    before=path.read_bytes();write_alignment_binding(cfg,m)
    assert path.read_bytes()==before
