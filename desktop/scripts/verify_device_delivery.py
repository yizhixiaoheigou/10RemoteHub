#!/usr/bin/env python3
"""Read-only signed collector delivery check; never installs or opens USB."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile


def run(*args):
    try:
        return subprocess.run([str(x) for x in args], check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f'{args[0]} 校验失败：{exc.stderr.strip()}') from exc


def verify_requirement(path, requirement):
    # codesign treats -R as a file path unless inline text starts with '='.
    run('codesign', '--verify', '--strict', '-R', '=' + requirement, path)


def certificate_sha1(path):
    with tempfile.TemporaryDirectory(prefix='rh-cert-') as directory:
        prefix = Path(directory) / 'cert'
        run('codesign', '-d', f'--extract-certificates={prefix}', path)
        leaf = Path(f'{prefix}0')
        if not leaf.is_file():
            raise RuntimeError('Collector delivery requires a stable signing certificate, not ad-hoc')
        return hashlib.sha1(leaf.read_bytes()).hexdigest().upper()


def verify(app):
    from release_policy import verify as verify_policy
    verify_policy(app)
    app = app.resolve()
    run('codesign', '--verify', '--deep', '--strict', app)
    # The App and every collector binary must share one pinned signing certificate.
    certificate = certificate_sha1(app)
    contents = app / 'Contents/Resources'
    install = contents / 'components/RemoteHubDevice.pkg'
    remove = contents / 'components/RemoteHubDevice-Uninstall.pkg'
    assert install.is_file() and remove.is_file()
    assert (contents / 'native/libRemoteHubDevice.dylib').is_file()
    with tempfile.TemporaryDirectory(prefix='collector-delivery-') as directory:
        expanded = Path(directory) / 'install'
        run('pkgutil', '--expand-full', install, expanded)
        payload = expanded / 'Payload/Library/PrivilegedHelperTools/10RemoteHub'
        for name, ident in [('device-helper', 'org.remotehub.device-helper'),
                            ('device-capture', 'org.remotehub.device-capture'),
                            ('libusb-1.0.dylib', 'org.remotehub.libusb')]:
            requirement = f'identifier "{ident}" and certificate leaf = H"{certificate}"'
            verify_requirement(payload / name, requirement)
        assert (payload / 'libusb-LICENSE.txt').is_file()
        assert '@executable_path/libusb-1.0.dylib' in run('otool', '-L', payload / 'device-capture').stdout
        assert '/opt/homebrew/' not in run('otool', '-L', payload / 'device-capture').stdout
        for script in (expanded / 'Scripts').iterdir():
            run('/bin/sh', '-n', script)
        run('pkgutil', '--expand-full', remove, Path(directory) / 'remove')
        run('/bin/sh', '-n', Path(directory) / 'remove/Scripts/postinstall')
    for name in ('THIRD_PARTY_NOTICES.txt', 'LGPL-3.0.txt', 'LGPL-2.1.txt', 'SOURCE.md',
                 'libusb-LICENSE.txt'):
        assert (contents / 'licenses' / name).is_file(), name
    print(json.dumps({'collector_packages': True, 'same_certificate_signatures': True,
                      'runtime_libusb_bundled': True, 'installed': False, 'hardware_tested': False}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('app', type=Path)
    verify(parser.parse_args().app)
