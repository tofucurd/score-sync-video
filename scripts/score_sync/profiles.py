"""Input-bound reference projects, portable without their original workspace."""
from pathlib import Path, PurePosixPath
import hashlib,json,re,zipfile
from .workflow import SKILL,read,write,digest

REGISTRY=SKILL/'assets/profiles'


def list_profiles(registry=None):
    base=Path(registry).resolve() if registry is not None else REGISTRY
    return [{**{k:m[k] for k in ('id','version','title') if k in m},
             'available':(base/m['archive']).is_file()}
            for p in sorted(base.glob('*.json')) if (m:=read(p)).get('archive')]


def _manifest(identifier,registry=None):
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]*',identifier):
        raise ValueError('Invalid reference identifier')
    base=Path(registry).resolve() if registry is not None else REGISTRY
    m=read(base/f'{identifier}.json')
    if m.get('schema')!=1 or m.get('id')!=identifier:
        raise ValueError('Reference schema or identity mismatch')
    return m


def _safe_name(name):
    path=PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or '\\' in name or name!=str(path):
        raise ValueError(f'Unsafe reference archive path: {name}')
    return path


def restore_reference(identifier,project_path,*,scores,pdfs,audios,registry=None):
    """Restore reviewed data only when every raw input matches; never restore approval."""
    base=Path(registry).resolve() if registry is not None else REGISTRY
    m=_manifest(identifier,base);project_path=Path(project_path).resolve();root=project_path.parent
    if project_path.exists():raise ValueError('Project config already exists')
    if not (base/m['archive']).is_file():
        raise ValueError('Reference archive is not bundled or not available; provide your local pack with --profile-dir')
    inputs={'score':list(scores),'pdf':list(pdfs),'audio':list(audios)}
    expected={role:sum(x['role']==role for x in m['inputs']) for role in inputs}
    if any(len(inputs[role])!=expected[role] for role in inputs):
        raise ValueError(f'Reference requires these raw input counts: {expected}')
    records=[]
    for item in m['inputs']:
        role=item['role'];p=Path(inputs[role][item['index']]).resolve()
        if digest(p)!=item['sha256']:
            raise ValueError(f'{role}[{item["index"]}] SHA256 hash mismatch; this reference is bound to another source')
        records.append(dict(item,path=str(p)))
    archive=base/m['archive']
    if archive.parent.resolve()!=base.resolve() or digest(archive)!=m['archive_sha256']:
        raise ValueError('Reference archive integrity mismatch')
    # Verify the complete archive before creating anything in the new project.
    with zipfile.ZipFile(archive) as z:
        if len(z.namelist())!=len(set(z.namelist())) or set(z.namelist())!=set(m['files']):
            raise ValueError('Reference archive inventory mismatch')
        for name in z.namelist():
            _safe_name(name)
            if name.endswith(('approval.json','preview-manifest.json','team-review.json')):
                raise ValueError('A reference cannot carry current user or preview approval')
            if hashlib.sha256(z.read(name)).hexdigest()!=m['files'][name]:
                raise ValueError(f'Reference member hash mismatch: {name}')
            target=root/name
            if name!='project-template.json' and (target.exists() or target.is_symlink()):
                raise ValueError(f'Reference target already exists: {target}')
            if not target.resolve().is_relative_to(root):
                raise ValueError(f'Unsafe reference target: {name}')
        cfg=json.loads(z.read('project-template.json'))
        for movement in cfg['movements']:
            mapping=m['movements'][movement['id']]
            movement['audio']=str(Path(audios[mapping['audio_index']]).resolve())
            movement['pdf']=str(Path(pdfs[mapping['pdf_index']]).resolve())
        cfg['reference']={'id':identifier,'version':m['version'],
                          'manifest':'.score-sync/reference/manifest.json',
                          'inputs':records,'mode':'frozen-reviewed-data'}
        if registry is not None:cfg['reference']['registry']=str(base)
        root.mkdir(parents=True,exist_ok=True)
        for name in z.namelist():
            if name=='project-template.json':continue
            target=root/name;target.parent.mkdir(parents=True,exist_ok=True)
            with target.open('xb') as f:f.write(z.read(name))
    write(root/'.score-sync/reference/manifest.json',m)
    write(project_path,cfg)
    return {'stage':'reference-restored','project':str(project_path),'reference':identifier,
            'next':'prepare (audio only); inspect/preflight; preview when requested. No approval was copied.'}


def verify_reference(cfg):
    ref=cfg.get('reference')
    if not ref:raise ValueError('This project has no frozen reference')
    root=Path(cfg['_root']);m=read(root/ref['manifest'])
    base=Path(ref.get('registry',REGISTRY))
    installed=_manifest(ref['id'],base)
    if m!=installed:raise ValueError('Reference manifest differs from installed reference')
    with zipfile.ZipFile(base/m['archive']) as z:
        template=json.loads(z.read('project-template.json'))
    for key in ['work','cover']:
        if cfg.get(key,{})!=template.get(key,{}):raise ValueError(f'Reference {key} configuration changed')
    settings=dict(preview_height=360,fps=60,final_height=2160,chunk_seconds=30,min_free_gib=25)
    settings.update(template.get('settings',{}))
    if cfg.get('settings')!=settings:raise ValueError('Reference settings configuration changed')
    if len(cfg['movements'])!=len(template['movements']):raise ValueError('Reference movement order/count changed')
    for actual,expected in zip(cfg['movements'],template['movements']):
        expected=dict(expected);expected.setdefault('alignment',{})
        for key in ['score','layout_overrides','engraving_overrides']:
            if isinstance(expected.get(key),str):expected[key]=str((root/expected[key]).resolve())
        semantic=lambda x:{k:v for k,v in x.items() if k not in ('audio','pdf')}
        if semantic(actual)!=semantic(expected):raise ValueError(f'Reference movement configuration changed: {actual.get("id")}')
    for item in ref['inputs']:
        if digest(item['path'])!=item['sha256']:
            raise ValueError(f'Reference {item["role"]} input changed')
    for movement in cfg['movements']:
        expected=m['movements'][movement['id']]
        for role in ('pdf','audio'):
            item=next(x for x in ref['inputs'] if x['role']==role and x['index']==expected[f'{role}_index'])
            if digest(movement[role])!=item['sha256']:
                raise ValueError(f'{movement["id"]}: reference {role} changed')
        audio_meta=read(root/'.score-sync'/movement['id']/'audio.json') if (root/'.score-sync'/movement['id']/'audio.json').exists() else None
        if audio_meta is not None:
            for key in ['samples','sample_rate','channels','bits']:
                if key in expected and audio_meta.get(key)!=expected[key]:
                    raise ValueError(f'{movement["id"]}: reference audio metadata {key} changed')
    frozen=m.get('frozen_files',[n for n in m['files'] if n!='project-template.json'])
    for name in frozen:
        if digest(root/name)!=m['files'][name]:raise ValueError(f'Reference data changed: {name}')
    return {'matched':True,'reference':m['id'],'version':m['version'],'frozen_files':len(frozen)}
