"""Detached, bounded full-production queue. Cleanup is owned by the parent controller.

Interface: production_worker.py start|run|status --job /absolute/package/root
The package contains queue.json and a frozen renderer selected by its relative
manifest renderer path (default scripts/browser_render.mjs). Renderer settings
belong to that frozen renderer. Runtime paths are supplied by the current host.
Exit codes: 0 complete, 75 resource/signal checkpoint, 1 permanent failure.
Failed jobs require an explicit operator decision; restarting never retries them.
"""
import argparse
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

GIB = 2 ** 30
DEFAULT_RENDERER = 'scripts/browser_render.mjs'


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f'.{os.getpid()}.tmp')
    with temp.open('w') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def checked_path(root, relative):
    relative = Path(relative)
    if relative.is_absolute():
        raise ValueError('Package path must be relative')
    path = (Path(root).resolve() / relative).resolve()
    path.relative_to(Path(root).resolve())
    return path


def env_with_tools(manifest, env):
    tools = manifest['runtime']['tools']
    env['PATH'] = str(Path(tools['ffmpeg']).parent) + ':' + env.get('PATH', '')
    env['SCORE_SYNC_CHROME'] = tools['chrome']
    return env


def env_for(manifest):
    tools = manifest['runtime']['tools']
    env = dict(os.environ)
    graphics_root = manifest['runtime'].get('graphics_root')
    if not graphics_root:
        return env_with_tools(manifest, env)
    graphics = Path(graphics_root)
    env = dict(os.environ)
    env['PATH'] = str(Path(tools['ffmpeg']).parent) + ':' + env.get('PATH', '')
    env['SCORE_SYNC_CHROME'] = tools['chrome']
    env['LD_LIBRARY_PATH'] = str(graphics / 'usr/lib64') + (
        ':' + env['LD_LIBRARY_PATH'] if env.get('LD_LIBRARY_PATH') else '')
    env['VK_DRIVER_FILES'] = env['VK_ICD_FILENAMES'] = str(graphics / 'nvidia-portable-icd.json')
    env['__EGL_VENDOR_LIBRARY_FILENAMES'] = str(graphics / 'usr/share/glvnd/egl_vendor.d/10_nvidia.json')
    env['__GL_SHADER_DISK_CACHE_PATH'] = str(graphics / 'shader-cache')
    return env


def resources(root):
    mem = {line.split(':')[0]: int(line.split()[1])
           for line in Path('/proc/meminfo').read_text().splitlines()}
    return {'free_bytes': shutil.disk_usage(root).free,
            'available_ram_bytes': mem['MemAvailable'] * 1024}


def validate_manifest(root, manifest):
    if manifest.get('purpose') != 'approved-full-production-2160p':
        raise ValueError('Only approved-full-production-2160p packages are accepted')
    if type(manifest.get('max_workers')) is not int or not 1 <= manifest['max_workers'] <= 10:
        raise ValueError('At most ten production workers')
    if not manifest.get('job_id') or not isinstance(manifest.get('jobs'), list):
        raise ValueError('Missing job identity/queue')
    seen = set()
    for row in manifest['jobs']:
        ident = row['id']
        if not isinstance(ident, str) or not re.fullmatch(r'[0-9]{9}', ident) or ident in seen:
            raise ValueError('Invalid or duplicate job ID')
        seen.add(ident)
        if (row.get('width'), row.get('height'), row.get('fps')) != (3840, 2160, 60):
            raise ValueError('Production contract must be 3840x2160 at 60 fps')
        if type(row.get('frames')) is not int or row['frames'] <= 0:
            raise ValueError('Invalid frame count')
        if type(row.get('start_frame')) is not int or row['start_frame'] < 0 or ident != f"{row['start_frame']:09d}":
            raise ValueError('Chunk identity must equal its global start frame')
        duration = row.get('duration')
        if type(duration) not in (int, float) or not math.isfinite(duration) or abs(duration - row['frames'] / 60) > 1e-8:
            raise ValueError('Duration must match the exact frame count')
        if digest(checked_path(root, row['scene'])) != row['scene_sha256']:
            raise ValueError('Frozen scene changed: ' + ident)
    for relative, sha in manifest['files'].items():
        if digest(checked_path(root, relative)) != sha:
            raise ValueError('Frozen package file changed: ' + relative)
    if manifest.get('renderer', DEFAULT_RENDERER) not in manifest['files']:
        raise ValueError('Renderer must be included in frozen files')
    for name in ('node', 'ffmpeg', 'chrome'):
        path = manifest['runtime']['tools'][name]
        if path not in manifest['runtime']['binary_sha256']:
            raise ValueError('Missing runtime hash: ' + name)
    for path, sha in manifest['runtime']['binary_sha256'].items():
        if digest(path) != sha:
            raise ValueError('Frozen runtime changed: ' + path)


def inspect_video(path, row, manifest):
    tools = manifest['runtime']['tools']
    probe = tools.get('ffprobe', str(Path(tools['ffmpeg']).with_name('ffprobe')))
    result = subprocess.run([probe, '-v', 'error', '-show_streams', '-of', 'json', str(path)],
                            check=True, capture_output=True, text=True, timeout=60)
    streams = json.loads(result.stdout)['streams']
    if len(streams) != 1:
        raise ValueError('Production chunks must contain exactly one silent video stream')
    s = streams[0]
    if (s.get('codec_type'), s.get('codec_name'), s.get('pix_fmt'),
        s.get('width'), s.get('height'), s.get('r_frame_rate'),
        int(s.get('nb_frames', 0))) != (
            'video', 'hevc', 'yuv444p10le', row['width'], row['height'], '60/1', row['frames']):
        raise ValueError('Encoded production contract mismatch')
    return {k: s.get(k) for k in ('codec_name', 'profile', 'codec_tag_string', 'pix_fmt',
                                'r_frame_rate', 'nb_frames', 'width', 'height', 'time_base',
                                'color_space', 'color_transfer', 'color_primaries')}


def receipt_valid(root, row, manifest, receipt):
    target = root / 'chunks' / (row['id'] + '.mov')
    if any(receipt.get(k) != row.get(k) for k in ('id', 'scene', 'scene_sha256', 'start_frame', 'duration', 'frames', 'width', 'height', 'fps')):
        raise ValueError('Receipt source or format identity mismatch')
    if receipt.get('job_id') != manifest['job_id'] or receipt.get('queue_sha256') != digest(root / 'queue.json'):
        raise ValueError('Receipt belongs to another package')
    if not target.is_file() or target.stat().st_size != receipt['bytes'] or digest(target) != receipt['sha256']:
        raise ValueError('Completed production chunk changed or disappeared: ' + row['id'])


def commit_video(root, row, manifest, path, elapsed, recovered=False):
    metadata = inspect_video(path, row, manifest)
    with path.open('rb') as stream:
        os.fsync(stream.fileno())
    target = root / 'chunks' / (row['id'] + '.mov')
    if path != target:
        path.replace(target)
    receipt = {**row, 'job_id': manifest['job_id'], 'purpose': manifest['purpose'],
               'queue_sha256': digest(root / 'queue.json'), 'worker_sha256': digest(__file__),
               'runtime': manifest['runtime'], 'sha256': digest(target),
               'bytes': target.stat().st_size, 'encoding': metadata, 'encoder': 'hevc_nvenc',
               'wall_seconds': elapsed, 'recovered_completed_file': recovered,
               'completed_unix': time.time()}
    write_json(root / 'receipts' / (row['id'] + '.json'), receipt)
    return receipt


def snapshot(root, manifest):
    receipts = []
    for row in manifest['jobs']:
        p = root / 'receipts' / (row['id'] + '.json')
        if p.exists():
            receipts.append(read(p))
    return {'job_id': manifest['job_id'], 'queue_sha256': digest(root / 'queue.json'),
            'state': read(root / 'status.json') if (root / 'status.json').exists() else {'stage': 'not-started'},
            'completed': receipts, 'total': len(manifest['jobs'])}


def acquire_lock(root):
    lock = (root / 'worker.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BaseException:
        lock.close()
        raise
    return lock


def stop_children(active):
    for item in active.values():
        if item['process'].poll() is None:
            try:
                os.killpg(item['process'].pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    for item in active.values():
        try:
            item['process'].wait(timeout=15)
        except subprocess.TimeoutExpired:
            os.killpg(item['process'].pid, signal.SIGKILL)
            item['process'].wait()
        item['log'].close()


def execution_policy(root, manifest):
    path = root / 'execution-policy.json'
    if not path.exists():
        return {'max_workers': manifest['max_workers'], 'admission_ram_gib': 6}
    value = read(path)
    if value['queue_sha256'] != digest(root / 'queue.json'):
        raise ValueError('Execution policy belongs to another frozen queue')
    cap = manifest['max_workers']
    override = root / 'execution-cap-override.json'
    if override.exists():
        authorized = read(override)
        if authorized['queue_sha256'] != digest(root / 'queue.json'):
            raise ValueError('Execution-cap authorization belongs to another queue')
        cap = authorized['max_workers']
        if type(cap) is not int or not 1 <= cap <= 10 or not authorized.get('user_statement'):
            raise ValueError('Invalid explicit execution-cap authorization')
    if type(value.get('max_workers')) is not int or not 1 <= value['max_workers'] <= min(10, cap):
        raise ValueError('Worker count exceeds explicitly authorized execution cap')
    if type(value.get('admission_ram_gib')) not in (int,float) or not math.isfinite(value['admission_ram_gib']) or value['admission_ram_gib'] < 6:
        raise ValueError('At least six GiB RAM admission reserve')
    return value


def run(root, manifest, lock_fd=None):
    lock = os.fdopen(lock_fd, 'a') if lock_fd is not None else acquire_lock(root)
    active, completed = {}, set()
    stop_requested = False
    previous_signals = {}
    current_id = None
    last_launch = 0.0
    def stopping(*_):
        nonlocal stop_requested
        stop_requested = True
    def state(stage, **extra):
        write_json(root / 'status.json', {'stage': stage, 'pid': os.getpid(), 'job_id': manifest['job_id'],
                   'active_jobs': list(active), 'completed': len(completed), 'total': len(manifest['jobs']),
                   'updated_unix': time.time(), **extra})
    try:
        for name in ('chunks', 'logs', 'receipts', 'errors', 'attempts'):
            (root / name).mkdir(exist_ok=True)
        refuse_recorded_failure(root)
        validate_manifest(root, manifest)
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            previous_signals[sig] = signal.signal(sig, stopping)
        for row in manifest['jobs']:
            current_id = row['id']
            if (root / 'errors' / (current_id + '.json')).exists():
                raise RuntimeError('Recorded failure requires operator review; no automatic retry: ' + current_id)
            rp = root / 'receipts' / (current_id + '.json')
            if rp.exists():
                receipt_valid(root, row, manifest, read(rp))
                completed.add(current_id)
            elif (root / 'chunks' / (current_id + '.mov')).exists():
                commit_video(root, row, manifest, root / 'chunks' / (current_id + '.mov'), 0, True)
                completed.add(current_id)
        current_id = None
        env = env_for(manifest)
        reserve = max(10.0, float(manifest.get('remote_min_free_gib', 10))) * GIB
        while True:
            if stop_requested:
                stop_children(active)
                active.clear()
                state('checkpoint', reason='signal', resumable=True)
                return 75
            for ident, item in list(active.items()):
                code = item['process'].poll()
                if code is None:
                    continue
                current_id = ident
                if code:
                    raise RuntimeError(f'Production chunk {ident} exited {code}; not retried')
                commit_video(root, item['row'], manifest, root / 'chunks' / (ident + '.partial.mov'),
                             time.monotonic() - item['started'])
                item['log'].close()
                del active[ident]
                completed.add(ident)
                current_id = None
            if len(completed) == len(manifest['jobs']):
                state('complete', retained_outputs=True, ack_required=False)
                return 0
            resource = resources(root)
            if resource['available_ram_bytes'] < 2 * GIB or resource['free_bytes'] < reserve:
                stop_children(active)
                active.clear()
                state('checkpoint', reason='resource-hard-floor', resumable=True, **resource)
                return 75
            pending = [r for r in manifest['jobs'] if r['id'] not in completed and r['id'] not in active]
            policy = execution_policy(root, manifest)
            while pending and len(active) < policy['max_workers']:
                resource = resources(root)
                # Native 2160p chunks stream frames to the encoder, not disk.
                # At the reference 25 Mb/s maxrate a <=30s chunk stays below
                # the conservative 512 MiB per-worker reservation.
                # Keep the existing 10 GiB absolute disk reserve.
                disk_per_worker = .5 if all(r['frames'] <= 1800 for r in manifest['jobs']) else 2
                if resource['available_ram_bytes'] < policy['admission_ram_gib'] * GIB or resource['free_bytes'] < reserve + disk_per_worker * GIB * (len(active) + 1):
                    break
                # Let new Chrome processes allocate before admitting another.
                if active and time.monotonic()-last_launch < 10:
                    break
                row = pending.pop(0)
                current_id = ident = row['id']
                scene = checked_path(root, row['scene'])
                if digest(scene) != row['scene_sha256']:
                    raise ValueError('Frozen scene changed before launch: ' + ident)
                partial = root / 'chunks' / (ident + '.partial.mov')
                if partial.exists():
                    try:
                        # The scheduler may have died after encoding but before its
                        # receipt. A complete, valid file can be committed losslessly.
                        commit_video(root, row, manifest, partial, 0, True)
                    except (ValueError, subprocess.CalledProcessError, json.JSONDecodeError):
                        pass
                    else:
                        completed.add(ident)
                        current_id = None
                        continue
                    # A partial from a resource/signal interruption can be rendered again.
                    # Permanent renderer errors are blocked above, never retried here.
                    partial.unlink()
                log = (root / 'logs' / (ident + '.log')).open('a')
                command = [manifest['runtime']['tools']['node'], str(checked_path(root, manifest.get('renderer', DEFAULT_RENDERER))),
                           '--spec', str(scene), '--output', str(partial), '--mode', 'video']
                try:
                    child = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT,
                                             stdin=subprocess.DEVNULL, start_new_session=True,
                                             pass_fds=(lock.fileno(),))
                except BaseException:
                    log.close()
                    raise
                active[ident] = {'row': row, 'process': child, 'log': log, 'started': time.monotonic()}
                last_launch = time.monotonic()
                write_json(root / 'attempts' / (ident + '.json'), {'id': ident, 'pid': child.pid,
                           'scene_sha256': row['scene_sha256'], 'started_unix': time.time(), 'command': command})
                current_id = None
            if not active:
                if len(completed) == len(manifest['jobs']):
                    state('complete', retained_outputs=True, ack_required=False)
                    return 0
                state('checkpoint', reason='resource-admission', resumable=True, **resource)
                return 75
            state('rendering', max_workers=policy['max_workers'], admission_ram_gib=policy['admission_ram_gib'], execution_policy_sha256=digest(root/'execution-policy.json') if (root/'execution-policy.json').exists() else None, ack_required=False, **resource)
            time.sleep(1)
    except Exception as exc:
        if current_id:
            write_json(root / 'errors' / (current_id + '.json'), {'id': current_id,
                       'job_id': manifest['job_id'], 'error': str(exc), 'unix': time.time()})
        state('failed', error=str(exc), failed_job=current_id, automatic_retry=False)
        raise
    finally:
        stop_children(active)
        for sig, handler in previous_signals.items():
            signal.signal(sig, handler)
        lock.close()


def refuse_recorded_failure(root):
    status = root / 'status.json'
    if status.exists() and read(status).get('stage') == 'failed':
        raise RuntimeError('Recorded permanent failure requires an explicit operator decision; no automatic retry')


def start(root):
    refuse_recorded_failure(root)
    lock = acquire_lock(root)
    try:
        with (root / 'scheduler.log').open('a') as log:
            child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), 'run',
                                      '--job', str(root), '--lock-fd', str(lock.fileno())],
                                     stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                     pass_fds=(lock.fileno(),), start_new_session=True, close_fds=True)
        return {'pid': child.pid, 'detached': True, 'ack_required': False}
    finally:
        lock.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('start', 'run', 'status'))
    parser.add_argument('--job', type=Path, required=True)
    parser.add_argument('--lock-fd', type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()
    root = args.job.resolve()
    manifest = read(root / 'queue.json')
    if args.action == 'status':
        print(json.dumps(snapshot(root, manifest)))
    elif args.action == 'start':
        print(json.dumps(start(root)))
    else:
        return run(root, manifest, args.lock_fd)
    return 0


if __name__ == '__main__':
    sys.exit(main())
