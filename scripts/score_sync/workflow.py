"""Project lifecycle, user-preview gate, deterministic resume and scoped cleanup."""
from pathlib import Path
from fractions import Fraction
from contextlib import contextmanager
import hashlib,json,os,re,shutil,subprocess,sys,time,math,fcntl

SKILL=Path(__file__).resolve().parents[2]

def read(p):return json.loads(Path(p).read_text())
def write(p,data):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2));tmp.replace(p)
def digest(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
    return h.hexdigest()
def load_project(path):
    path=Path(path).resolve();cfg=read(path)
    if cfg.get('schema')!=1 or not cfg.get('movements'):raise ValueError('schema=1 and movements required')
    cfg['_root']=str(path.parent);cfg['_config']=str(path)
    ids=[]
    for m in cfg['movements']:
        mid=m.get('id','')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}',mid) or mid in ids:raise ValueError('Movement ids must be unique safe identifiers')
        ids.append(mid)
        for key in ['score','pdf','audio']:
            if not m.get(key):raise ValueError(f'{mid}: missing {key}')
            m[key]=str((path.parent/m[key]).resolve())
        for key in ['layout_overrides','engraving_overrides']:
            if isinstance(m.get(key),str):m[key]=str((path.parent/m[key]).resolve())
        alignment=m.setdefault('alignment',{})
        if isinstance(alignment.get('constraints'),str):
            alignment['constraints']=str((path.parent/alignment['constraints']).resolve())
    output=(path.parent/cfg.get('output','output')).resolve()
    if output==path.parent or path.parent in output.parents and '.score-sync' in output.relative_to(path.parent).parts:raise ValueError('Output must not be project root or cache')
    cfg['_output']=str(output)
    cfg.setdefault('settings',{})
    for k,v in dict(preview_height=360,fps=60,final_height=2160,chunk_seconds=30,min_free_gib=25).items():cfg['settings'].setdefault(k,v)
    if cfg['settings']['fps']!=60:raise ValueError('This style currently requires 60 fps')
    return cfg

def movement_dir(cfg,m):return Path(cfg['_root'])/'.score-sync'/m['id']

def fingerprint(cfg):
    """Bind input config, raw sources, semantic artifacts and installed implementation."""
    refs={'config':digest(cfg['_config'])}
    for m in cfg['movements']:
        for k in ['score','pdf','audio']:refs[f'{m["id"]}/source/{k}']=digest(m[k])
        for k in ['layout_overrides','engraving_overrides']:
            if isinstance(m.get(k),str):refs[f'{m["id"]}/{k}']=digest(m[k])
        constraints=m.get('alignment',{}).get('constraints')
        if isinstance(constraints,str):refs[f'{m["id"]}/constraints']=digest(constraints)
        d=movement_dir(cfg,m)
        for p in sorted(d.rglob('*')):
            if p.is_file() and p.suffix in ('.json','.svg','.mei','.xml','.css','.wav') and p.name not in ['alignment-review.json']:
                refs[f'{m["id"]}/{p.relative_to(d)}']=digest(p)
        if (d/'alignment-review.json').exists():refs[f'{m["id"]}/alignment-review.json']=digest(d/'alignment-review.json')
    for folder in ['scripts','assets']:
        for p in sorted((SKILL/folder).rglob('*')):
            if p.is_file() and '__pycache__' not in p.parts:refs[f'skill/{p.relative_to(SKILL)}']=digest(p)
    return hashlib.sha256(json.dumps(refs,sort_keys=True).encode()).hexdigest()

def validate_structure(data,total):
    if not data.get('reviewed'):raise ValueError('Musical structure requires agent review before user preview')
    def check(parts,a,b):
        if not parts:raise ValueError('Both structural navigation levels require coverage')
        pos=a
        for part in parts:
            x=float(part['start_q']);y=float(part['end_q'])
            if not part.get('label') or abs(x-pos)>1e-6 or y<=x:raise ValueError('Structural segments must be named, ordered, contiguous')
            pos=y
        if abs(pos-b)>1e-6:raise ValueError('Structural segments must cover full score extent')
    sec=data['sections'];check(sec,0,float(total))
    for s in sec:check(s.get('children',[]),float(s['start_q']),float(s['end_q']))
    if 'cohort_sections' in data:
        check([dict(x,label='cohort') for x in data['cohort_sections']],0,float(total))

def validate_ready(cfg):
    if cfg.get('reference'):
        from .profiles import verify_reference
        verify_reference(cfg)
    for m in cfg['movements']:
        from .bindings import validate_alignment_binding
        validate_alignment_binding(cfg,m)
        d=movement_dir(cfg,m);score=read(d/'score.json');alignment=read(d/'alignment.json')
        validate_structure(read(d/'structure.json'),float(Fraction(*score['total_q'])))
        review=read(d/'alignment-review.json') if (d/'alignment-review.json').exists() else {}
        if not review.get('reviewed') or review.get('alignment_sha256')!=digest(d/'alignment.json') or review.get('unresolved'):
            raise ValueError(f'{m["id"]}: alignment-review.json must review current alignment with unresolved=[]')
        pdf=read(d/'pdf-review.json') if (d/'pdf-review.json').exists() else {}
        if not pdf.get('reviewed') or pdf.get('source_pdf_sha256')!=digest(m['pdf']) or pdf.get('source_score_sha256')!=digest(m['score']) or pdf.get('unresolved'):
            raise ValueError(f'{m["id"]}: original PDF comparison pending (pdf-review.json)')
        notes={n['id'] for n in alignment['notes']}
        missing=[e['id'] for e in score['events'] if e['kind']!='rest' and e.get('visible',True) and e['id'] not in notes]
        if missing:raise ValueError(f'Missing note times: {missing[:5]}')

def artifact_refs(out,paths):
    return [{'path':str(Path(p).resolve().relative_to(Path(out).resolve())),'sha256':digest(p)} for p in paths]

def preflight(cfg):
    """Inspect the actual production inputs and cover specs without launching a renderer."""
    from .visual import bundle,frame_state
    from .covers import build_cover_specs
    validate_ready(cfg);rows=[]
    for m in cfg['movements']:
        d=movement_dir(cfg,m);b=bundle(cfg,d)
        for second in [0.,min(15.,b['duration']/2),max(0,b['duration']-1)]:
            state=frame_state(b,second)
            if not math.isfinite(state['x']):raise ValueError(f'{m["id"]}: invalid score projection')
        rows.append({'id':m['id'],'events':len(b['score']['events']),
                     'timed_notes':len(b['alignment']['notes']),'duration':b['duration'],
                     'prepared_audio_present':(d/'audio.wav').is_file()})
    first=bundle(cfg,movement_dir(cfg,cfg['movements'][0]))
    specs=build_cover_specs(cfg,first)
    return {'stage':'preflight-data-checked','rendered':False,'movements':rows,
            'cover_specs':list(specs) if isinstance(specs,dict) else len(specs),
            'environment':runtime(),'note':'Data/spec validation only; not a new visual or acoustic approval.'}

def approve(cfg,statement,inherit=False):
    if not statement or len(statement.strip())<8:raise ValueError('Record the actual explicit user approval statement')
    out=Path(cfg['_output']);manifest=read(out/'preview-manifest.json');h=fingerprint(cfg)
    if manifest['fingerprint']!=h:raise ValueError('Inputs changed since previews; regenerate affected previews')
    for a in manifest['artifacts']:
        if digest(out/a['path'])!=a['sha256']:raise ValueError('Preview artifact changed')
    review=read(out/'team-review.json')
    people={x['name'] for x in review.get('reviewers',[]) if x.get('approved') and x.get('scope')=='whole-program'}
    if review.get('fingerprint')!=h or len(people)<3:raise ValueError('Three actual reviewers must review the whole current programme')
    previous=None
    if inherit:
        if not (out/'approval.json').exists():raise ValueError('No existing user authorization to inherit')
        previous=read(out/'approval.json')
        if not previous.get('statement'):raise ValueError('Previous authorization has no user statement')
    receipt={'fingerprint':h,'statement':statement,'preview_manifest_sha256':digest(out/'preview-manifest.json'),'time':time.time(),
             'new_user_confirmation':not inherit}
    if previous is not None:receipt['inherited_authorization']=previous
    write(out/'approval.json',receipt);return receipt

def require_approval(cfg):
    out=Path(cfg['_output']);p=out/'approval.json'
    if not p.exists():raise ValueError('User preview approval is required before full rendering')
    a=read(p)
    if a['fingerprint']!=fingerprint(cfg):raise ValueError('Inputs changed after approval; new preview approval required')
    if a['preview_manifest_sha256']!=digest(out/'preview-manifest.json'):raise ValueError('Approved previews changed')
    for item in read(out/'preview-manifest.json')['artifacts']:
        if digest(out/item['path'])!=item['sha256']:raise ValueError('Approved preview artifact changed')
    return a

def prepare(cfg):
    from .score import prepare_score
    from .audio import prepare_audio
    if cfg.get('reference'):
        from .profiles import verify_reference
        from .bindings import write_alignment_binding
        from .audio import probe
        verify_reference(cfg)
        for m in cfg['movements']:
            d=movement_dir(cfg,m);expected=read(d/'audio.json')
            if (d/'audio.wav').exists() and digest(d/'audio.wav')==expected.get('prepared_sha256'):
                actual=expected
            else:actual=prepare_audio(m,d)
            for key in ['source_sha256','sample_rate','samples','channels','bits']:
                if actual[key]!=expected[key]:raise ValueError(f'{m["id"]}: reference audio {key} mismatch')
            write_alignment_binding(cfg,m)
        return {'stage':'reference-prepared','next':'preflight; reviewed score and alignment retained; preview when requested'}
    for m in cfg['movements']:
        d=movement_dir(cfg,m);d.mkdir(parents=True,exist_ok=True)
        prepare_score(m,d);prepare_audio(m,d)
        s=read(d/'score.json');total=float(Fraction(*s['total_q']))
        if not (d/'structure.json').exists():
            write(d/'structure.json',{'reviewed':False,'sections':[{'label':m.get('title',m['id']),'start_q':0,'end_q':total,'children':[{'label':'待完成结构分析','start_q':0,'end_q':total}]}]})
        if not (d/'materials.json').exists():write(d/'materials.json',{'assignments':{}})
    return {'stage':'prepared','next':'align; agent compares original PDF and writes reviewed musical structure'}

def align(cfg):
    from .alignment import align_movement
    from .bindings import write_alignment_binding
    if cfg.get('reference'):
        raise ValueError('Frozen reference already contains reviewed alignment. Use a new generic project to align a different recording.')
    for m in cfg['movements']:
        options=m.get('alignment',{});pipeline=options.get('pipeline','refined')
        if pipeline=='refined':
            from .alignment_pipeline import refine_movement,constraints_from_anchors,validate_constraints
            constraints=options.get('constraints')
            if isinstance(constraints,str):constraints=read(constraints)
            anchors=m.get('anchors')
            if isinstance(anchors,str):anchors=read(Path(cfg['_root'])/anchors)
            if anchors:
                d=movement_dir(cfg,m);audio=read(d/'audio.json')
                migrated=constraints_from_anchors(read(d/'score.json'),anchors,audio['samples']/audio['sample_rate'])
                if constraints:
                    validate_constraints(constraints,read(d/'score.json'),audio['samples']/audio['sample_rate'])
                    rows=constraints.get('rows',[]) if isinstance(constraints,dict) else constraints
                    constraints={**migrated,'rows':migrated['rows']+rows}
                else:constraints=migrated
            refine_movement(movement_dir(cfg,m),source_path=m['score'],constraints=constraints,
                            config=options.get('config'),output_path=movement_dir(cfg,m)/'alignment.json')
            write_alignment_binding(cfg,m)
            continue
        if pipeline!='coarse':raise ValueError(f'Unknown alignment pipeline: {pipeline}')
        anchors=m.get('anchors')
        if isinstance(anchors,str):anchors=read(Path(cfg['_root'])/anchors)
        align_movement(movement_dir(cfg,m),anchors=anchors)
        (movement_dir(cfg,m)/'alignment-review.json').unlink(missing_ok=True)
        write_alignment_binding(cfg,m)
    return {'stage':'alignment-candidate','next':'inspect flags and excerpts, correct anchors; write alignment-review.json'}

def preview(cfg):
    from .visual import render_clip,render_frame,build_covers
    validate_ready(cfg);out=Path(cfg['_output']);out.mkdir(parents=True,exist_ok=True);artifacts=[]
    for m in cfg['movements']:
        d=movement_dir(cfg,m);a=read(d/'audio.json');duration=min(30,a['samples']/a['sample_rate'])
        target=out/f'{m["id"]}-preview.mov';render_clip(cfg,d,target,duration=duration,height=cfg['settings']['preview_height']);artifacts.append(target)
        for sec in sorted(set([0.,min(duration/2,15.),max(0,duration-1)])):
            p=out/f'{m["id"]}-frame-{sec:g}.png';render_frame(cfg,d,p,seconds=sec,height=2160);artifacts.append(p)
    build_covers(cfg,movement_dir(cfg,cfg['movements'][0]),out/'covers')
    artifacts.extend(sorted((out/'covers').glob('*.*')))
    from .review_pdf import create_review_pdf
    pdf=out/'审片说明.pdf';create_review_pdf(cfg,artifacts,pdf);artifacts.append(pdf)
    h=fingerprint(cfg);write(out/'preview-manifest.json',{'fingerprint':h,'artifacts':artifact_refs(out,artifacts),'stage':'awaiting-user-approval'})
    # Never create fake review approvals. This is an agent-completed record.
    if not (out/'team-review.json').exists():write(out/'team-review.json',{'fingerprint':h,'reviewers':[]})
    return {'stage':'awaiting-user-approval','output':str(out),'fingerprint':h}

def frame_chunks(total,size):return [(i,min(size,total-i)) for i in range(0,total,size)]

def build_timeline(cfg):
    clock=Fraction(0);timeline=[]
    for m in cfg['movements']:
        d=movement_dir(cfg,m);a=read(d/'audio.json');duration=Fraction(a['samples'],a['sample_rate'])
        timeline.append({'id':m['id'],'start_seconds':float(clock),'duration_seconds':float(duration),'dir':str(d),'start_fraction':[clock.numerator,clock.denominator]});clock+=duration
    cfg['_timeline']=timeline
    return math.ceil(clock*60),timeline

def runtime():
    import importlib.metadata
    result={k:subprocess.check_output(v,text=True).splitlines()[0] for k,v in {'python':[sys.executable,'--version'],'node':['node','--version'],'ffmpeg':['ffmpeg','-version']}.items()}
    from .visual import chrome_path
    result['chrome']=subprocess.check_output([chrome_path(),'--version'],text=True).strip()
    result['packages']={n:importlib.metadata.version(n) for n in ['numpy','scipy','verovio','Pillow']}
    return result

@contextmanager
def render_lock(root):
    root.mkdir(parents=True,exist_ok=True)
    with (root/'render.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield

def master_audio(cfg,root):
    """One continuous PCM stream, one lossless encode, no movement-frame padding."""
    specs=[read(movement_dir(cfg,m)/'audio.json') for m in cfg['movements']]
    channels={a['channels'] for a in specs}
    if len(channels)!=1:raise ValueError('Different channel layouts require an explicit user-selected conversion; no automatic downmix')
    rate=max(a['sample_rate'] for a in specs);bits=max(a['bits'] for a in specs);channels=channels.pop()
    codec='alac' if bits<=24 else 'pcm_s32le';target=root/('audio.m4a' if codec=='alac' else 'audio.mov')
    cmd=['ffmpeg','-v','error','-nostdin','-y','-f','s32le','-ar',str(rate),'-ac',str(channels),'-i','pipe:0','-c:a',codec]
    if codec=='alac':cmd+=['-sample_fmt','s32p','-bits_per_raw_sample',str(bits)]
    cmd+=[str(target)];encoder=subprocess.Popen(cmd,stdin=subprocess.PIPE);h=hashlib.sha256();count=0;chapters=[]
    try:
        for m in cfg['movements']:
            start_sample=count//(4*channels)
            decoder=subprocess.Popen(['ffmpeg','-v','error','-nostdin','-i',str(movement_dir(cfg,m)/'audio.wav'),'-map','0:a:0','-ar',str(rate),'-c:a','pcm_s32le','-f','s32le','pipe:1'],stdout=subprocess.PIPE)
            try:
                for b in iter(lambda:decoder.stdout.read(1024*1024),b''):h.update(b);count+=len(b);encoder.stdin.write(b)
                if decoder.wait()!=0:raise RuntimeError('Audio decode failed')
                chapters.append({'id':m['id'],'title':m.get('title',m['id']),'start_sample':start_sample,'end_sample':count//(4*channels)})
            finally:
                decoder.stdout.close()
                if decoder.poll() is None:decoder.terminate();decoder.wait()
        encoder.stdin.close()
        if encoder.wait()!=0:raise RuntimeError('Audio encode failed')
    finally:
        if encoder.poll() is None:encoder.terminate();encoder.wait()
    decoder=subprocess.Popen(['ffmpeg','-v','error','-i',str(target),'-f','s32le','-c:a','pcm_s32le','pipe:1'],stdout=subprocess.PIPE)
    actual=hashlib.sha256();size=0
    for b in iter(lambda:decoder.stdout.read(1024*1024),b''):actual.update(b);size+=len(b)
    if decoder.wait()!=0 or size!=count or actual.hexdigest()!=h.hexdigest():raise RuntimeError('Lossless master PCM check failed')
    write(root/'audio-manifest.json',{'sample_rate':rate,'bits':bits,'channels':channels,'samples':count//(4*channels),'sha256_pcm_s32':h.hexdigest(),'codec':codec,'path':str(target),'no_added_gap':True,'chapters':chapters})
    return target

def write_chapters(manifest,out):
    """Use actual assembled PCM sample boundaries, never rounded frame lengths."""
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    rate=manifest['sample_rate'];rows=manifest['chapters'];lines=[';FFMETADATA1'];text=[]
    def escape(value):
        value=str(value).replace('\r',' ').replace('\n',' ')
        for ch in ['\\','=',';','#']:value=value.replace(ch,'\\'+ch)
        return value
    for row in rows:
        lines.extend(['[CHAPTER]',f'TIMEBASE=1/{rate}',f"START={row['start_sample']}",f"END={row['end_sample']}",f"title={escape(row['title'])}"])
        seconds=row['start_sample']//rate
        stamp=f'{seconds//3600:02d}:{seconds//60%60:02d}:{seconds%60:02d}' if seconds>=3600 else f'{seconds//60:02d}:{seconds%60:02d}'
        text.append(f"{stamp} {str(row['title']).replace(chr(10),' ').replace(chr(13),' ')}")
    meta=out/'chapters.ffmetadata';meta.write_text('\n'.join(lines)+'\n')
    (out/'B站章节.txt').write_text('\n'.join(text)+'\n')
    write(out/'chapters.json',{'sample_rate':rate,'chapters':rows})
    return meta


def chapter_mux_args(manifest,input_index=2):
    """Preserve chapter titles even when global/source metadata is suppressed."""
    args=['-map_metadata','-1','-map_chapters',str(input_index)]
    for i,row in enumerate(manifest['chapters']):
        args.extend([f'-metadata:c:{i}',f'title={row["title"]}'])
    return args


def final_mux_command(listing,audio,chapter_file,target,manifest):
    """Build the production stream-copy mux, including explicit chapter titles."""
    cmd=['ffmpeg','-v','error','-nostdin','-y','-f','concat','-safe','1','-i',str(listing),
         '-i',str(audio),'-f','ffmetadata','-i',str(chapter_file),'-map','0:v:0','-map','1:a:0',
         '-c','copy','-tag:v','hvc1']
    return cmd+chapter_mux_args(manifest)+['-movflags','+faststart',str(target)]


def render(cfg):
    from .visual import render_program
    validate_ready(cfg);receipt=require_approval(cfg);root=Path(cfg['_root'])/'.score-sync/render';root.mkdir(parents=True,exist_ok=True)
    with render_lock(root):
        env=runtime();job=root/receipt['fingerprint'][:16];job.mkdir(exist_ok=True)
        journal_path=job/'chunks.json';journal=read(journal_path) if journal_path.exists() else {'fingerprint':receipt['fingerprint'],'environment':env,'chunks':[]}
        if journal['environment']!=env:raise ValueError('Runtime changed: use a fresh reviewed render; never mix old chunks')
        total,timeline=build_timeline(cfg);chunk_size=round(cfg['settings']['chunk_seconds']*60)
        if chunk_size<=0:raise ValueError('chunk_seconds must be positive')
        completed=0
        for item in journal['chunks']:
            if item['start']!=completed or digest(job/item['file'])!=item['sha256']:raise ValueError('Checkpoint is not contiguous or chunk changed')
            completed+=item['frames']
        status=Path(cfg['_root'])/'.score-sync/status.json'
        awake=None
        if sys.platform=='darwin':awake=subprocess.Popen(['caffeinate','-i','-w',str(os.getpid())])
        try:
            for start,n in frame_chunks(total,chunk_size):
                if start<completed:continue
                if shutil.disk_usage(root).free<cfg['settings']['min_free_gib']*2**30:raise RuntimeError('Insufficient free space; checkpoint preserved')
                write(status,{'stage':'rendering','pid':os.getpid(),'completed_frames':completed,'total_frames':total})
                part=job/f'{start:09d}.partial.mov';target=job/f'{start:09d}.mov'
                render_program(cfg,[Path(t['dir']) for t in timeline],part,start_frame=start,frame_count=n,height=cfg['settings']['final_height'],silent=True)
                meta=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(part)]))['streams'][0]
                if int(meta.get('nb_frames',0))!=n or meta['codec_name']!='hevc':raise RuntimeError('Chunk frame/codec check failed')
                part.replace(target);journal['chunks'].append({'start':start,'frames':n,'file':target.name,'sha256':digest(target)});write(journal_path,journal);completed=start+n
            if fingerprint(cfg)!=receipt['fingerprint']:raise ValueError('Frozen inputs changed during render; no final assembly')
            audio=master_audio(cfg,job);chapter_file=write_chapters(read(job/'audio-manifest.json'),Path(cfg['_output']));listing=job/'concat.txt';listing.write_text(''.join("file '"+c['file']+"'\n" for c in journal['chunks']))
            output=Path(cfg['_output'])/'曲谱同步-2160p.mov';tmp=job/'final.partial.mov'
            subprocess.run(final_mux_command(listing,audio,chapter_file,tmp,read(job/'audio-manifest.json')),check=True)
            meta=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_chapters','-of','json',str(tmp)]))
            vs=next(s for s in meta['streams'] if s['codec_type']=='video')
            if int(vs['nb_frames'])!=total:raise RuntimeError('Final frame count mismatch')
            expected=read(job/'audio-manifest.json');embedded=meta.get('chapters',[])
            if len(embedded)!=len(expected['chapters']):raise RuntimeError('Missing embedded movement chapters')
            for actual,wanted in zip(embedded,expected['chapters']):
                if actual.get('tags',{}).get('title')!=wanted['title'] or abs(float(actual['start_time'])-wanted['start_sample']/expected['sample_rate'])>.002:raise RuntimeError('Movement chapter mismatch')
            shutil.move(str(tmp),output);result={'stage':'complete','output':str(output),'fingerprint':receipt['fingerprint'],'frames':total,'bytes':output.stat().st_size,'sha256':digest(output)}
            write(Path(cfg['_output'])/'delivery.json',result);write(status,result);return result
        except KeyboardInterrupt:
            write(status,{'stage':'paused','completed_frames':completed,'total_frames':total});raise
        except Exception as exc:
            write(status,{'stage':'failed','completed_frames':completed,'total_frames':total,
                          'error':str(exc),'checkpoint':str(journal_path),'resume':'resume the same frozen version'})
            raise
        finally:
            if awake and awake.poll() is None:awake.terminate();awake.wait()

def clean_candidates(cfg):
    root=Path(cfg['_root'])/'.score-sync';items=[]
    for m in cfg['movements']:
        for name in ['audio.wav','analysis-24k.f32','alignment-features.npz']:
            p=movement_dir(cfg,m)/name
            if p.is_file() and not p.is_symlink():items.append(p)
    render_root=root/'render'
    if render_root.exists():
        for p in render_root.rglob('*'):
            if p.is_file() and not p.is_symlink() and p.suffix in ('.mov','.m4a','.png'):items.append(p)
    return items

def clean(cfg,apply=False):
    items=clean_candidates(cfg)
    if apply:
        delivery=Path(cfg['_output'])/'delivery.json'
        if not delivery.exists() or not Path(read(delivery)['output']).exists():raise ValueError('Cache cleanup requires a delivered final video; only listing now')
        root=Path(cfg['_root'])/'.score-sync'
        with render_lock(root/'render'):
            for p in items:
                if not p.resolve().is_relative_to(root.resolve()):raise ValueError('Cleanup path escapes workspace')
                p.unlink()
    return {'apply':apply,'files':[str(p) for p in items]}
