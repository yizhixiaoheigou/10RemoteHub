#!/usr/bin/env python3
"""Verify a release zip the way a user receives it: fresh extraction, then run.

codesign keeps a per-path result cache, so verifying the build tree can report a
stale failure after packaging. Extracting the published zip to a new directory
checks the artifact users actually download.
"""
import argparse
import json
import os
import plistlib
import subprocess
import tempfile
from pathlib import Path


def verify(archive):
    from release_policy import verify as verify_policy
    verify_policy(archive)
    archive = Path(archive).resolve()
    with tempfile.TemporaryDirectory(prefix='rh-release-') as temporary:
        subprocess.run(['/usr/bin/ditto', '-x', '-k', str(archive), temporary], check=True)
        app = Path(temporary) / '10RemoteHub.app'
        subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)], check=True)
        info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
        executable = app / 'Contents/MacOS/10RemoteHub'
        archs = subprocess.run(['/usr/bin/lipo', '-archs', str(executable)],
                               capture_output=True, text=True, check=True).stdout.split()
        config = Path(temporary) / 'config'
        env = dict(os.environ, QT_QPA_PLATFORM='offscreen')
        run = subprocess.run([str(executable), '--smoke', '--config-dir', str(config)],
                             capture_output=True, text=True, env=env, timeout=120)
        if run.returncode:
            raise RuntimeError('离屏启动失败: ' + (run.stderr or run.stdout)[-800:])
        return {'zip': archive.name,
                'version': info.get('CFBundleShortVersionString'),
                'build': info.get('CFBundleVersion'),
                'archs': archs,
                'signature': True,
                'smoke': True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('archive', type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.archive), ensure_ascii=False))
