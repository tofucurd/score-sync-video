#!/usr/bin/env python3
"""Portable score-sync-video command entrypoint."""
from pathlib import Path
import argparse,json,sys,signal

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['init','prepare','align','preflight','preview','approve','render','resume','covers','status','clean','profiles','components','doctor']);p.add_argument('--project',type=Path)
    p.add_argument('--score',action='append');p.add_argument('--pdf',action='append');p.add_argument('--audio',action='append');p.add_argument('--title',default='曲谱同步');p.add_argument('--composer',default='');p.add_argument('--statement');p.add_argument('--apply',action='store_true');p.add_argument('--reference');p.add_argument('--profile-dir',type=Path);p.add_argument('--inherit',action='store_true');a=p.parse_args()
    if a.command=='doctor':
        from score_sync.environment import check_environment
        result=check_environment();print(json.dumps(result,ensure_ascii=False,indent=2));return 0 if result['ok'] else 1
    from score_sync import workflow as w
    if a.command=='profiles':
        from score_sync.profiles import list_profiles
        print(json.dumps(list_profiles(registry=a.profile_dir),ensure_ascii=False,indent=2));return
    if a.command=='components':
        print((w.SKILL/'references/components.json').read_text());return
    if a.project is None:p.error('--project is required for this command')
    if a.reference and a.command!='init':p.error('--reference is only used with init')
    if a.profile_dir is not None and not(a.command=='init' and a.reference):p.error('--profile-dir is used with profiles or init --reference')
    if a.command=='init':
        if a.project.exists():raise ValueError('Project config already exists')
        scores=a.score or [];pdfs=a.pdf or [];audios=a.audio or []
        if a.reference:
            from score_sync.profiles import restore_reference
            result=restore_reference(a.reference,a.project,scores=scores,pdfs=pdfs,audios=audios,registry=a.profile_dir)
            print(json.dumps(result,ensure_ascii=False,indent=2));return
        if not scores or len(scores)!=len(audios) or len(pdfs) not in (1,len(scores)):raise ValueError('Provide one score/audio per movement and one PDF or one PDF per movement')
        w.write(a.project,{'schema':1,'work':{'title':a.title,'composer':a.composer,'number':'','performer':'','ensemble':''},'output':'output','movements':[{'id':f'm{i+1}','title':f'第{i+1}乐章','score':str(Path(s).resolve()),'pdf':str(Path(pdfs[min(i,len(pdfs)-1)]).resolve()),'audio':str(Path(audios[i]).resolve())} for i,s in enumerate(scores)],'settings':{'preview_height':360,'final_height':2160,'fps':60,'chunk_seconds':30,'min_free_gib':25}});result={'project':str(a.project.resolve())}
    else:
        cfg=w.load_project(a.project)
        if a.command in ('prepare','align','preflight','preview'):result=getattr(w,a.command)(cfg)
        elif a.command in ('render','resume'):result=w.render(cfg)
        elif a.command=='approve':result=w.approve(cfg,a.statement,inherit=a.inherit)
        elif a.command=='clean':result=w.clean(cfg,a.apply)
        elif a.command=='status':
            f=Path(cfg['_root'])/'.score-sync/status.json';result=w.read(f) if f.exists() else {'stage':'not-rendering','approval':(Path(cfg['_output'])/'approval.json').exists()}
        elif a.command=='covers':
            from score_sync.visual import build_covers
            result=build_covers(cfg,w.movement_dir(cfg,cfg['movements'][0]),Path(cfg['_output'])/'covers')
    print(json.dumps(result,ensure_ascii=False,indent=2,default=str))
if __name__=='__main__':
    def pause_signal(signum, frame): raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,pause_signal)
    try:sys.exit(main() or 0)
    except KeyboardInterrupt:print('Paused; completed chunks retained.',file=sys.stderr);sys.exit(130)
    except (ValueError,RuntimeError,FileNotFoundError) as e:print(str(e),file=sys.stderr);sys.exit(2)
