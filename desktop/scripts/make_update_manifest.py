#!/usr/bin/env python3
"""Build and sign the update manifest published next to a release.

The private key stays outside the repository (~/.10remotehub-signing). The app
ships only the matching public key.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_KEY = Path.home() / ".10remotehub-signing/update-signing-private.pem"


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def build(dist, base_url, notes, key, output):
    dist = Path(dist)
    app = next(path for path in dist.iterdir() if path.suffix == '.app')
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    version, build_number = info['CFBundleShortVersionString'], info['CFBundleVersion']
    assets = {}
    for arch in ('arm64', 'x86_64'):
        matches = sorted(dist.glob(f'10RemoteHub-{version}-{build_number}-{arch}.zip'))
        if not matches:
            continue
        archive = matches[-1]
        assets[arch] = {'name': archive.name,
                        'url': base_url.rstrip('/') + '/' + archive.name,
                        'sha256': sha256(archive),
                        'size': archive.stat().st_size}
    if not assets:
        raise SystemExit('dist 目录里没有带版本号的 zip')
    manifest = {'schema': 1, 'version': version, 'build': build_number,
                'notes': notes, 'assets': assets}
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    output.write_bytes(raw)
    signature = output.with_suffix('.json.sig') if output.suffix == '.json' else Path(str(output) + '.sig')
    subprocess.run(['/usr/bin/openssl', 'dgst', '-sha256', '-sign', str(key),
                    '-out', str(signature), str(output)], check=True)
    print(f'wrote {output} and {signature.name}')
    return output, signature


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--dist-dir', type=Path, required=True)
    parser.add_argument('--base-url', required=True,
                        help='URL directory that will host the assets, e.g. a GitHub release download URL')
    parser.add_argument('--notes', default='')
    parser.add_argument('--notes-file', type=Path)
    parser.add_argument('--key', type=Path, default=DEFAULT_KEY)
    parser.add_argument('--output', type=Path, default=ROOT.parent / 'releases/latest.json')
    args = parser.parse_args()
    notes = args.notes or (args.notes_file.read_text() if args.notes_file else '')
    build(args.dist_dir, args.base_url, notes, args.key, args.output)
