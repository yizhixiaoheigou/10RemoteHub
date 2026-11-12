#!/usr/bin/env python3
"""Build and validate a new macOS release candidate; never install or publish."""
import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codesign-identity', required=True)
    parser.add_argument('--license-supplement', required=True, type=Path)
    args = parser.parse_args()
    if sys.platform != 'darwin':
        parser.error('Run this entry point on macOS')
    if sys.version_info < (3, 12):
        parser.error('Release verification requires Python 3.12 or newer')
    dist = ROOT / 'dist' / ('candidate-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    dist.mkdir(parents=True, exist_ok=False)
    def run(*cmd):
        subprocess.run([str(x) for x in cmd], cwd=ROOT, check=True,
                       env=dict(os.environ, QT_QPA_PLATFORM='offscreen'))
    run(sys.executable, 'scripts/verify.py', '--output', dist / 'verification.json')
    run(sys.executable, 'scripts/build.py', '--codesign-identity', args.codesign_identity,
        '--license-supplement', args.license_supplement.resolve(), '--dist-dir', dist)
    run(sys.executable, 'scripts/verify_device_delivery.py', dist / '10RemoteHub.app')
    run(sys.executable, 'scripts/package_macos.py', '--dist-dir', dist)
    run(sys.executable, 'scripts/build_dmg.py', '--dist-dir', dist)
    run(sys.executable, 'scripts/release_assets.py', '--dist-dir', dist)
    for archive in dist.glob('*.zip'):
        run(sys.executable, 'scripts/verify_release_zip.py', archive)
    print('Candidate validated; installation, USB tests and publication remain separate:', dist)


if __name__ == '__main__':
    main()
