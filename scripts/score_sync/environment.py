"""Read-only installation diagnostics; no browser launch or media rendering."""
from pathlib import Path
import importlib.metadata
import os
import platform
import re
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
CORE_PACKAGES=('numpy','scipy','verovio','numba','librosa','Pillow','fonttools')


def _inspect_program(name,path,args,errors):
    item={'ok':False,'path':path,'version':None}
    if not path:
        errors.append(f'Missing {name}; install it and add its executable to PATH.')
        return item
    try:
        result=subprocess.run([str(path),*args],text=True,capture_output=True,timeout=15)
    except (OSError,subprocess.TimeoutExpired) as exc:
        errors.append(f'{name} could not be checked: {exc}')
        return item
    text=(result.stdout+'\n'+result.stderr).strip()
    if result.returncode or not text:
        errors.append(f'{name} version check failed (exit {result.returncode}).')
        return item
    item.update(ok=True,version=text.splitlines()[0])
    return item


def _find_chrome():
    override=os.environ.get('SCORE_SYNC_CHROME')
    if override:return os.path.expanduser(override)
    candidates=['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
                shutil.which('chromium'),shutil.which('chromium-browser'),shutil.which('google-chrome')]
    return next((str(p) for p in candidates if p and Path(p).is_file()),None)


def check_environment():
    """Return a JSON-serializable report. Only version/encoder help commands run."""
    errors=[];warnings=[]
    host={'system':platform.system(),'machine':platform.machine(),'posix':os.name=='posix'}
    python={'version':platform.python_version(),'executable':sys.executable,
            'ok':sys.version_info[:2]>=(3,14)}
    if not host['posix']:errors.append('POSIX is required: use macOS or Linux; native Windows is not supported.')
    if not python['ok']:errors.append('Python 3.14 or newer is required; bootstrap with uv uses the tested Python 3.14 series.')
    if host['system']=='Darwin' and host['machine'] in ('x86_64','i386'):
        warnings.append('The pinned llvmlite has no Intel macOS wheel. This platform is not an out-of-box supported installation.')
    tools={}
    for name in ('node','ffmpeg','ffprobe'):
        tools[name]=_inspect_program(name,shutil.which(name),['--version'] if name=='node' else ['-version'],errors)
    node=tools['node']
    if node['ok']:
        match=re.search(r'\bv?(\d+)\.',node['version'])
        if not match or int(match[1])<22:
            node['ok']=False;errors.append('Node.js 22 or newer is required for the built-in WebSocket API.')
    tools['chromium']=_inspect_program('Chromium/Google Chrome',_find_chrome(),['--version'],errors)
    if not tools['chromium']['ok']:
        warnings.append('Set SCORE_SYNC_CHROME to the Chromium/Google Chrome executable for a nonstandard installation.')
    encoder=tools['ffmpeg'];encoder['hevc_444_10bit']=False
    if encoder['ok']:
        try:
            result=subprocess.run([encoder['path'],'-hide_banner','-h','encoder=libx265'],text=True,capture_output=True,timeout=15)
            help_text=result.stdout+'\n'+result.stderr
            encoder['hevc_444_10bit']=(result.returncode==0 and bool(re.search(r'Encoder\s+libx265\b',help_text))
                                        and bool(re.search(r'\byuv444p10le\b',help_text)))
        except (OSError,subprocess.TimeoutExpired):pass
        if not encoder['hevc_444_10bit']:
            encoder['ok']=False;errors.append('FFmpeg must provide libx265 with yuv444p10le support for the final HEVC 4:4:4 10-bit video.')
    locked={}
    lock=ROOT/'requirements.lock'
    if lock.exists():
        for line in lock.read_text().splitlines():
            if '==' in line and not line.lstrip().startswith('#'):
                name,version=line.split('==',1);locked[name.lower()]=version
    packages={}
    for name in CORE_PACKAGES:
        try:installed=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:installed=None
        expected=locked.get(name.lower())
        packages[name]={'installed':installed,'locked':expected,'matches_lock':installed==expected if expected else None}
        if installed is None:errors.append(f'Missing Python package {name}; run scripts/bootstrap.py and use the returned Python executable.')
        elif expected and installed!=expected:warnings.append(f'{name} {installed} differs from the validated lock {expected}; use the isolated bootstrap environment for reference reproduction.')
    return {'ok':not errors,'errors':errors,'warnings':warnings,'python':python,
            'platform':host,'tools':tools,'packages':packages,'rendered':False}
