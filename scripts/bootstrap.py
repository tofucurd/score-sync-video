"""Install isolated dependencies; never alter a user's global Python."""
from pathlib import Path
import subprocess,shutil,sys,os,re,platform
if os.name!='posix':raise SystemExit('Native Windows is not supported. Use a macOS or Linux POSIX environment.')
if sys.platform=='darwin' and platform.machine() in ('x86_64','i386'):
 print('Note: the locked llvmlite has no Intel macOS wheel; Apple Silicon macOS or Linux x86_64 is the tested binary installation route.',file=sys.stderr)
node=shutil.which('node')
if not node:raise SystemExit('Missing Node.js 22+. Install it before bootstrapping.')
version=subprocess.check_output([node,'--version'],text=True).strip()
major=re.search(r'\bv?(\d+)\.',version)
if not major or int(major[1])<22:raise SystemExit(f'Node.js 22+ is required; found {version}.')
root=Path(__file__).resolve().parents[1];env=root/'.runtime';uv=shutil.which('uv')
if uv:
 if not (env/'bin/python').exists():subprocess.run([uv,'venv','--python','3.14',str(env)],check=True)
 subprocess.run([uv,'pip','install','--python',str(env/'bin/python'),'-r',str(root/'requirements.lock')],check=True)
else:
 if sys.version_info < (3,14):raise SystemExit('Use Python 3.14+ or install uv for the tested isolated runtime.')
 if not (env/'bin/python').exists():subprocess.run([sys.executable,'-m','venv',str(env)],check=True)
 subprocess.run([str(env/'bin/python'),'-m','pip','install','-r',str(root/'requirements.lock')],check=True)
for name in ['node','ffmpeg','ffprobe']:
 if not shutil.which(name):raise SystemExit(f'Missing external program: {name}. Install it before producing media.')
print(env/'bin/python')
print('Check external tools without rendering: '+str(env/'bin/python')+' '+str(root/'scripts/score_sync.py')+' doctor',file=sys.stderr)
