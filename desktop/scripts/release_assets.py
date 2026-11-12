#!/usr/bin/env python3
"""Give release assets stable names and record their SHA-256 sums.

Names follow Product-Version-Build-Arch, so a downloaded file can always be
matched to the build it came from; SHA256SUMS is what users can verify, since
the App is signed with a self-made certificate instead of a notarized one.
"""
import argparse
import hashlib
import plistlib
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LSREGISTER = ('/System/Library/Frameworks/CoreServices.framework/Frameworks/'
              'LaunchServices.framework/Support/lsregister')


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def build(dist):
    dist = Path(dist).resolve()
    app = next(p for p in dist.iterdir() if p.suffix == '.app')
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    version = info['CFBundleShortVersionString']
    number = info['CFBundleVersion']
    executable = app / 'Contents/MacOS' / app.stem
    archs = subprocess.run(['/usr/bin/lipo', '-archs', str(executable)],
                           capture_output=True, text=True, check=True).stdout.split()
    arch = archs[0] if len(archs) == 1 else 'universal'
    stem = f'{app.stem}-{version}-{number}-{arch}'
    # Older builds of the same architecture would be uploaded by mistake.
    for old in dist.glob(f'{app.stem}-*-{arch}*'):
        if old.is_file() and not old.name.startswith(stem):
            old.unlink()
    created = []
    archive = dist / f'{stem}.zip'
    subprocess.run(['/usr/bin/ditto', '-c', '-k', '--sequesterRsrc', '--keepParent',
                    str(app), str(archive)], check=True)
    created.append(archive)
    disk_image = dist / f'{stem}.dmg'
    if disk_image.is_file():
        created.append(disk_image)
    setup = dist / f'{app.stem}-Setup.pkg'
    if setup.is_file():
        created.append(Path(shutil.copyfile(setup, dist / f'{stem}-Setup.pkg')))
    uninstall = ROOT / 'build/RemoteHub-Uninstall.pkg'
    if uninstall.is_file():
        created.append(Path(shutil.copyfile(uninstall, dist / f'{stem}-Uninstall.pkg')))
    sums = dist / 'SHA256SUMS'
    sums.write_text(''.join(f'{sha256(path)}  {path.name}\n' for path in created))
    # Build output is not an installed App; keep it out of Finder's "open with".
    subprocess.run([LSREGISTER, '-u', str(app)], capture_output=True, check=False)
    return created, sums


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--dist-dir', type=Path, required=True)
    args = parser.parse_args()
    files, sums = build(args.dist_dir)
    for path in files:
        print(path.name)
    print('wrote', sums)
