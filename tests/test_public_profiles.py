import pytest
from score_sync import profiles
from score_sync.workflow import load_project
from test_reference_profile import fixture_profile


def test_public_catalog_marks_unbundled_archive_unavailable(tmp_path,monkeypatch):
    registry,inputs,manifest=fixture_profile(tmp_path)
    monkeypatch.setattr(profiles,'REGISTRY',registry)
    (registry/manifest['archive']).unlink()
    rows=profiles.list_profiles()
    assert rows[0]['available'] is False
    with pytest.raises(ValueError,match='not bundled|not available'):
        profiles.restore_reference('fixture',tmp_path/'out/project.json',scores=[inputs['score']],pdfs=[inputs['pdf']],audios=[inputs['audio']])


def test_external_profile_directory_is_used_after_import(tmp_path,monkeypatch):
    registry,inputs,manifest=fixture_profile(tmp_path)
    empty=tmp_path/'public-profiles';empty.mkdir();monkeypatch.setattr(profiles,'REGISTRY',empty)
    dest=tmp_path/'new/project.json'
    profiles.restore_reference('fixture',dest,scores=[inputs['score']],pdfs=[inputs['pdf']],audios=[inputs['audio']],registry=registry)
    assert profiles.verify_reference(load_project(dest))['matched'] is True
    assert profiles.list_profiles(registry=registry)[0]['available'] is True
