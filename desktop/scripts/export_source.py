#!/usr/bin/env python3
"""Prepare an inspectable, history-free public-source candidate. Never publish."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import tarfile

ROOT = Path(__file__).resolve().parents[2]
TOP = ('LICENSE', '.gitignore', 'CONTRIBUTING.md', 'SECURITY.md')
DESKTOP = ('pyproject.toml', 'requirements-release.txt', 'VERSION', 'entry.py',
           'requirements-macos-arm64.lock', 'requirements-macos-x86_64.lock', 'requirements-windows-x64.lock',
           'THIRD_PARTY_NOTICES.txt', 'RELEASE.md', 'INSTALL-macOS.md',
           'INSTALL-Windows.md', 'TROUBLESHOOTING.md', 'ARCHITECTURE.md', 'DESIGN.md', 'KEYMAP.md',
           'docs/PLATFORM-ACTIONS.md', 'docs/WINDOWS-TESTING.md', 'docs/SOURCE-README.md',
           'docs/screenshots/mapping.png', 'docs/screenshots/voice.png')
TREES = ('remotehub', 'native', 'scripts', 'tests', 'licenses', 'assets')
SUFFIXES = {'.py','.c','.h','.m','.md','.txt','.json','.svg','.png','.plist','.pem',
            '.ps1','.sh','.command','.toml','.inf','.wav'}
EXCLUDE = {'ico.py', 'audit_preopensource.py'}
# Paths can contain shell variable usernames; literal personal home paths cannot.
PRIVATE = re.compile(r'/Users/(?!\$|audit-example/)[A-Za-z0-9_.-]+/|/home/[A-Za-z0-9_.-]+/|'
                     r'[A-Za-z]:[\\/]+Users[\\/]+(?!\$|%|Public[\\/]|Default[\\/])[^\\/\s\x22\x27]+[\\/]|'
                     r'\b192\.168\.\d{1,3}\.\d{1,3}\b|'
                     r'\b(?:10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b|'
                     r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----', re.IGNORECASE)


def public_mode(path):
    # NTFS does not preserve chmod's POSIX executable bit. Shell entry points
    # must remain executable when a Windows-created archive is opened on macOS.
    executable = path.suffix in {'.sh', '.command'} or path.name == 'postinstall'
    return 0o755 if executable or path.stat().st_mode & 0o111 else 0o644


def export(output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    files = [ROOT / p for p in TOP] + [ROOT / 'desktop' / p for p in DESKTOP]
    for tree in TREES:
        for path in (ROOT / 'desktop' / tree).rglob('*'):
            if (path.is_file() and not path.is_symlink() and '__pycache__' not in path.parts
                    and path.name not in EXCLUDE
                    and (path.suffix in SUFFIXES or path.name == 'postinstall'
                         or path.name.startswith(('COPYING', 'LICENSE')))):
                files.append(path)
    records = []
    for path in sorted(set(files)):
        relative = path.relative_to(ROOT)
        data = path.read_bytes()
        if path.suffix not in ('.png','.wav') and PRIVATE.search(data.decode('utf-8', errors='replace')):
            raise RuntimeError('Review private identifier before exporting: ' + str(relative))
        dest = output / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        # File contents and executable bit only; do not copy timestamps/xattrs.
        dest.write_bytes(data)
        dest.chmod(public_mode(path))
        records.append({'path':relative.as_posix(), 'sha256':hashlib.sha256(data).hexdigest()})
    readme = (ROOT / 'desktop/docs/SOURCE-README.md').read_bytes()
    (output / 'README.md').write_bytes(readme)
    records.append({'path':'README.md', 'sha256':hashlib.sha256(readme).hexdigest()})
    (output / 'SOURCE-INVENTORY.json').write_text(json.dumps({'schema':1, 'files':records},indent=2)+'\n')
    return {'output':str(output), 'files':len(records), 'git_history':False, 'published':False}


def write_archive(output, archive):
    """Archive only verified inventory files, without workstation metadata."""
    output = Path(output).resolve()
    if Path(archive).resolve().is_relative_to(output):
        raise ValueError('Place the archive outside the source inventory directory')
    inventory = (output / 'SOURCE-INVENTORY.json').read_bytes()
    rows = json.loads(inventory)['files']
    payloads = {'SOURCE-INVENTORY.json': inventory}
    for row in rows:
        relative = PurePosixPath(row['path'])
        path = output / relative
        if (relative.is_absolute() or '..' in relative.parts or '\\' in str(relative)
                or path.is_symlink() or not path.resolve().is_relative_to(output)
                or str(relative) in payloads):
            raise RuntimeError('Unsafe source inventory path')
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != row['sha256']:
            raise RuntimeError('Changed source inventory file: ' + str(relative))
        payloads[str(relative)] = data
    actual = {p.relative_to(output).as_posix() for p in output.rglob('*') if p.is_file() or p.is_symlink()}
    if actual != set(payloads):
        raise RuntimeError('Files outside source inventory; export a fresh snapshot')
    with Path(archive).open('xb') as raw:
        with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode='w', format=tarfile.USTAR_FORMAT) as tar:
                for name, data in sorted(payloads.items()):
                    info = tarfile.TarInfo('10RemoteHub/' + name)
                    info.size = len(data)
                    info.mode = public_mode(output / name)
                    # TarInfo defaults: no owner names, uid/gid=0, mtime=0, no xattrs.
                    tar.addfile(info, io.BytesIO(data))
    return str(archive)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--archive', type=Path, help='New tar.gz with normalized file metadata')
    args = parser.parse_args()
    result = export(args.output)
    if args.archive:
        result['archive'] = write_archive(args.output, args.archive)
    print(json.dumps(result, ensure_ascii=False))
