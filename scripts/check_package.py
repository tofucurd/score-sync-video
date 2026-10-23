"""Check the portable public package without rendering or accessing user projects."""
from pathlib import Path
from urllib.parse import unquote, urlsplit
import hashlib
import json
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
IGNORED = {'.git', '.runtime', '.venv', '__pycache__', '.pytest_cache'}
FORBIDDEN_SUFFIXES = {'.zip', '.pdf', '.musicxml', '.mxl', '.mei', '.wav', '.flac',
                      '.mp3', '.dsf', '.dff', '.mov', '.mp4', '.pem', '.key'}


def inventory():
    if (ROOT / '.git').exists():
        result = subprocess.run(
            ['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'],
            cwd=ROOT, check=True, capture_output=True)
        return sorted({ROOT / p for p in result.stdout.decode().split('\0') if p})
    return sorted(p for p in ROOT.rglob('*') if p.is_file()
                  and not set(p.relative_to(ROOT).parts).intersection(IGNORED)
                  and p.name != '.DS_Store')


def main():
    errors = []
    files = inventory()
    manifest = json.loads((ROOT / 'references/components.json').read_text())
    skill = (ROOT / 'SKILL.md').read_text()
    frontmatter = skill.split('---', 2)[1] if skill.startswith('---\n') else ''
    for field in ('name', 'description'):
        if not re.search(rf'^{field}:\s*\S', frontmatter, re.M):
            errors.append(f'SKILL.md lacks {field} frontmatter')
    if manifest.get('reference_profiles'):
        errors.append('Public release must not bundle work-specific profiles')
    fingerprints = 0
    for component in manifest['components']:
        for name, expected in component['files'].items():
            path = (ROOT / name).resolve()
            if not path.is_relative_to(ROOT) or not path.is_file():
                errors.append(f'Invalid component path: {name}')
                continue
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != expected:
                errors.append(f'Stale component fingerprint: {name}')
            fingerprints += 1
    links = 0
    for path in files:
        relative = path.relative_to(ROOT)
        if (set(relative.parts).intersection(IGNORED)
                or path.suffix.lower() in FORBIDDEN_SUFFIXES
                or path.name == '.env' or path.name.startswith('.env.')):
            errors.append(f'Unexpected public package member: {relative}')
        if path.suffix not in {'.md', '.py', '.mjs', '.json', '.yaml', '.yml', '.txt'}:
            continue
        body = path.read_text()
        if re.search(r'/(?:Users|home)/[A-Za-z0-9_-]+/', body):
            errors.append(f'Machine-specific home path: {relative}')
        if path.suffix != '.md':
            continue
        for target in re.findall(r'\[[^\]\n]*\]\(([^)\n]+)\)', body):
            target = target.strip('<>')
            parts = urlsplit(target)
            if parts.scheme or parts.netloc or not parts.path:
                continue
            resolved = (path.parent / unquote(parts.path)).resolve()
            if not resolved.is_relative_to(ROOT) or not resolved.exists():
                errors.append(f'Broken local link in {relative}: {target}')
            links += 1
    print(json.dumps({'ok': not errors, 'files': len(files),
                      'fingerprints': fingerprints, 'local_links': links,
                      'errors': errors, 'rendered': False}, ensure_ascii=False, indent=2))
    return int(bool(errors))


if __name__ == '__main__':
    raise SystemExit(main())
