#!/usr/bin/env python3
"""Build signed, fixed-purpose XPC helper packages; never install/register them."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SERVICE = 'org.remotehub.device-helper'
DIRECTORY = '/Library/PrivilegedHelperTools/10RemoteHub'
PLIST = f'/Library/LaunchDaemons/{SERVICE}.plist'
STOP_SERVICE = '''if /bin/launchctl print system/org.remotehub.device-helper >/dev/null 2>&1; then
    /bin/launchctl bootout system/org.remotehub.device-helper
    remaining=10
    while /bin/launchctl print system/org.remotehub.device-helper >/dev/null 2>&1; do
        if [ "$remaining" -eq 0 ]; then
            echo '10RemoteHub collector has not finished stopping; installation aborted.' >&2
            exit 1
        fi
        /bin/sleep 1
        remaining=$((remaining - 1))
    done
fi
'''


def certificate_sha1(path):
    """SHA-1 of the leaf certificate that signed path (Apple-issued or self-made)."""
    with tempfile.TemporaryDirectory(prefix='rh-cert-') as directory:
        prefix = Path(directory) / 'cert'
        run('codesign', '-d', f'--extract-certificates={prefix}', path)
        leaf = Path(f'{prefix}0')
        if not leaf.is_file():
            raise RuntimeError('Device helper requires a certificate signing identity, not ad-hoc')
        return hashlib.sha1(leaf.read_bytes()).hexdigest().upper()


def libusb_license(prefix):
    """License text for the libusb build, wherever that prefix keeps it."""
    for candidate in (prefix / 'COPYING', prefix / 'share/doc/libusb/COPYING',
                      ROOT / 'native/libusb-LICENSE.txt'):
        if candidate.is_file():
            return candidate
    raise RuntimeError('找不到 libusb 的 LICENSE 文本，无法打包合规说明')


def run(*args):
    return subprocess.run([str(a) for a in args], cwd=ROOT, check=True, capture_output=True, text=True)


def build(identity=None):
    # Secondary-architecture builds point these at their own tree instead of
    # overwriting the native components. Defaults keep the Apple-silicon flow.
    out = Path(os.environ.get('RH_HELPER_OUT') or ROOT / 'build/device-helper-components').resolve()
    out.mkdir(parents=True, exist_ok=True)
    worker = out / 'device-capture'
    arch = os.environ.get('RH_ARCH_FLAGS', '').split()
    if os.environ.get('RH_LIBUSB_PREFIX'):
        # Cross builds ship a libusb built for the target architecture.
        prefix = Path(os.environ['RH_LIBUSB_PREFIX'])
    else:
        # Use the existing build-time libusb installation; runtime ships its own copy.
        brew = shutil.which('brew') or next((str(p) for p in (Path('/opt/homebrew/bin/brew'), Path('/usr/local/bin/brew')) if p.is_file()), 'brew')
        prefix = Path(run(brew, '--prefix', 'libusb').stdout.strip())
    library = prefix / 'lib/libusb-1.0.dylib'
    for source, name in ((library, 'libusb-1.0.dylib'),
                         (libusb_license(prefix), 'libusb-LICENSE.txt')):
        target = out / name
        if target.exists():
            target.unlink()  # only this builder's previous generated copy
        shutil.copyfile(source, target)
        target.chmod(0o755 if name.endswith('.dylib') else 0o644)
    run('install_name_tool', '-id', '@executable_path/libusb-1.0.dylib', out / 'libusb-1.0.dylib')
    run('clang', '-std=c11', '-Wall', '-Wextra', '-Werror', '-O2', *arch,
        '-I', prefix / 'include/libusb-1.0', 'native/device-helper/Capture.c',
        out / 'libusb-1.0.dylib', '-o', worker)
    for path, identifier in ((worker, 'org.remotehub.device-capture'),
                             (out / 'libusb-1.0.dylib', 'org.remotehub.libusb')):
        run('codesign', '--force', '--sign', identity or '-', '--identifier', identifier, path)
    # Both XPC peers pin this certificate; an ad-hoc build leaves it empty and refuses to run.
    certificate = certificate_sha1(worker) if identity else ''
    for source, target, extra in [('Daemon.m', 'device-helper', ['-framework', 'SystemConfiguration']),
                                   ('Client.m', 'libRemoteHubDevice.dylib', ['-dynamiclib'])]:
        run('clang', '-fobjc-arc', '-Wall', '-Wextra', '-Werror', '-mmacosx-version-min=13.0', *arch,
            f'-DRH_CERT_SHA1="{certificate}"', f'native/device-helper/{source}', '-framework', 'Foundation',
            '-framework', 'Security', *extra, '-o', out / target)
        run('codesign', '--force', '--sign', identity or '-', '--identifier',
            SERVICE if target == 'device-helper' else 'org.remotehub.device-client', out / target)
        run('codesign', '--verify', '--strict', out / target)
    # Scratch builds cannot install an unauthenticated privileged service.
    if not identity:
        return out, []
    return out, package_components(out)


def package_components(out):
    """Package already-built files. Only called for signed release builds or test fixtures."""
    packages = []
    with tempfile.TemporaryDirectory(prefix='remotehub-device-') as temporary:
        base = Path(temporary)
        root = base / 'root'
        payload = root / DIRECTORY.lstrip('/')
        payload.mkdir(parents=True)
        for name in ('device-helper', 'device-capture', 'libusb-1.0.dylib'):
            shutil.copy2(out / name, payload / name)
            (payload / name).chmod(0o755)
        shutil.copy2(out / 'libusb-LICENSE.txt', payload / 'libusb-LICENSE.txt')
        (payload / 'libusb-LICENSE.txt').chmod(0o644)
        daemon = root / PLIST.lstrip('/')
        daemon.parent.mkdir(parents=True)
        shutil.copy2(ROOT / 'native/device-helper/org.remotehub.device-helper.plist', daemon)
        daemon.chmod(0o644)
        for path in root.rglob('*'):
            if path.is_dir():
                path.chmod(0o755)
        scripts = base / 'install'
        scripts.mkdir()
        # Fixed paths only. Refuse symlinks or writable directories before root copy.
        preflight = '''#!/bin/sh
set -eu
for path in /Library /Library/PrivilegedHelperTools /Library/LaunchDaemons /Library/PrivilegedHelperTools/10RemoteHub; do
    [ ! -L "$path" ] || exit 1
    if [ -e "$path" ]; then
        [ -d "$path" ] || exit 1
        [ "$(/usr/bin/stat -f %u "$path")" = 0 ] || exit 1
        mode=$(/usr/bin/stat -f %Lp "$path")
        [ $((0$mode & 0022)) = 0 ] || exit 1
    fi
done
for path in /Library/PrivilegedHelperTools/10RemoteHub/device-helper /Library/PrivilegedHelperTools/10RemoteHub/device-capture /Library/PrivilegedHelperTools/10RemoteHub/libusb-1.0.dylib /Library/PrivilegedHelperTools/10RemoteHub/libusb-LICENSE.txt /Library/LaunchDaemons/org.remotehub.device-helper.plist; do
    [ ! -L "$path" ] || exit 1
done
''' + STOP_SERVICE
        (scripts / 'preinstall').write_text(preflight)
        (scripts / 'postinstall').write_text(f'#!/bin/sh\nset -eu\n/bin/launchctl bootstrap system "{PLIST}"\n')
        for script in scripts.iterdir():
            script.chmod(0o755)
        install = out / 'RemoteHubDevice.pkg'
        run('pkgbuild', '--root', root, '--ownership', 'recommended', '--filter', r'/\._',
            '--scripts', scripts, '--identifier', SERVICE, '--version', '1.0.0', install)
        packages.append(install)
        scripts = base / 'uninstall'
        scripts.mkdir()
        (scripts / 'postinstall').write_text(preflight + f'''/bin/rm -f "{DIRECTORY}/device-helper" "{DIRECTORY}/device-capture" "{DIRECTORY}/libusb-1.0.dylib" "{DIRECTORY}/libusb-LICENSE.txt" "{PLIST}"
if [ -d "{DIRECTORY}" ]; then
    /bin/rmdir "{DIRECTORY}" 2>/dev/null || :
fi
/usr/sbin/pkgutil --forget {SERVICE} >/dev/null 2>&1 || :
''')
        (scripts / 'postinstall').chmod(0o755)
        uninstall = out / 'RemoteHubDevice-Uninstall.pkg'
        run('pkgbuild', '--nopayload', '--scripts', scripts, '--identifier', SERVICE + '.uninstall',
            '--version', '1.0.0', uninstall)
        packages.append(uninstall)
    return packages


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--codesign-identity', default=os.environ.get('CODESIGN_IDENTITY'))
    parser.add_argument('--adhoc', action='store_true')
    args = parser.parse_args()
    identity = None if args.adhoc else args.codesign_identity
    if not args.adhoc and (not identity or identity == '-'):
        parser.error('Select --codesign-identity or explicitly use --adhoc')
    output, packages = build(identity)
    print('Built', output, 'packages:', len(packages), '; not installed or registered')
