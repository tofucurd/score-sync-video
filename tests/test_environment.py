"""Environment diagnostics never launch a browser or encode media."""
from types import SimpleNamespace
import pytest


@pytest.fixture
def system(tmp_path,monkeypatch):
    from score_sync import environment
    paths={name:str(tmp_path/name) for name in ['node','ffmpeg','ffprobe','chromium']}
    for p in paths.values():
        from pathlib import Path
        Path(p).touch()
    monkeypatch.setattr(environment.shutil,'which',lambda name:paths.get(name))
    monkeypatch.setenv('SCORE_SYNC_CHROME',paths['chromium'])
    answers={'node':'v22.20.0\n','ffmpeg':'ffmpeg version 7.1\n',
             'ffprobe':'ffprobe version 7.1\n','chromium':'Chromium 130.0.0.0\n',
             'libx265':'Encoder libx265 [libx265 H.265 / HEVC]:\n Supported pixel formats: yuv420p yuv444p10le\n'}
    calls=[]
    def run(argv,**kwargs):
        calls.append(argv)
        name=next(k for k,v in paths.items() if v==argv[0])
        if argv[1:]==['-hide_banner','-h','encoder=libx265']:
            key='libx265'
        elif argv[1:] in (['--version'],['-version']):key=name
        else:raise AssertionError('Unexpected program execution: '+str(argv))
        return SimpleNamespace(returncode=0,stdout=answers[key],stderr='')
    monkeypatch.setattr(environment.subprocess,'run',run)
    return environment,paths,answers,calls


def test_doctor_reports_available_environment_without_rendering(system):
    env,paths,answers,calls=system
    result=env.check_environment()
    assert result['ok'] is True and result['errors']==[]
    assert result['tools']['chromium']['path']==paths['chromium']
    assert result['tools']['ffmpeg']['hevc_444_10bit'] is True
    assert len(calls)==5


def test_doctor_rejects_old_node(system):
    env,paths,answers,calls=system;answers['node']='v20.19.0\n'
    result=env.check_environment()
    assert not result['ok']
    assert any('Node' in x and '22' in x for x in result['errors'])


def test_doctor_rejects_missing_encoder_format(system):
    env,paths,answers,calls=system
    answers['libx265']='Encoder libx265 [HEVC]:\n Supported pixel formats: yuv420p\n'
    result=env.check_environment()
    assert not result['ok']
    assert any('yuv444p10le' in x for x in result['errors'])


def test_doctor_reports_missing_external_tools(system):
    env,paths,answers,calls=system;paths.pop('ffprobe')
    result=env.check_environment()
    assert not result['ok']
    assert any('ffprobe' in x for x in result['errors'])


def test_doctor_reports_command_failure(system,monkeypatch):
    env,paths,answers,calls=system
    monkeypatch.setattr(env.subprocess,'run',lambda *a,**kw:SimpleNamespace(returncode=1,stdout='',stderr='unavailable'))
    result=env.check_environment()
    assert not result['ok'] and result['errors']


def test_resolved_browser_path_is_passed_to_renderer_without_launch(tmp_path,monkeypatch):
    from score_sync import visual
    captured=[]
    monkeypatch.setattr(visual.shutil,'which',lambda name:'/custom/node' if name=='node' else None)
    monkeypatch.setattr(visual,'chrome_path',lambda:'/custom/chrome')
    monkeypatch.setenv('UNRELATED_ENV','preserved')
    class Process:
        def __init__(self,args,**kwargs):captured.append((args,kwargs));self.args=args
        def wait(self,timeout=None):return 0
    monkeypatch.setattr(visual.subprocess,'Popen',Process)
    visual.run_browser({'frames':[]},tmp_path/'unused.mov')
    assert captured[0][1]['env']['SCORE_SYNC_CHROME']=='/custom/chrome'
    assert captured[0][1]['env']['UNRELATED_ENV']=='preserved'
    assert not (tmp_path/'unused.mov').exists()
