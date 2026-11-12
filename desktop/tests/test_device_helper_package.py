"""Inspect an uninstalled fixture package, including exact root destinations."""
import importlib.util
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

pytestmark = pytest.mark.skipif(sys.platform != 'darwin', reason='macOS package tools')


def test_helper_packages_have_fixed_payload_and_explicit_scripts(tmp_path):
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('helper_builder', root / 'scripts/build_device_helper.py')
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    # Fixture bytes are never executable and the package is never installed.
    for name in ('device-helper', 'device-capture', 'libusb-1.0.dylib', 'libusb-LICENSE.txt'):
        (tmp_path / name).write_bytes(b'fixture only; never install\n')
    packages = builder.package_components(tmp_path)
    assert [p.name for p in packages] == ['RemoteHubDevice.pkg', 'RemoteHubDevice-Uninstall.pkg']
    for index, package in enumerate(packages):
        expanded = tmp_path / str(index)
        subprocess.run(['pkgutil', '--expand-full', str(package), str(expanded)], check=True)
        info = ET.parse(expanded / 'PackageInfo').getroot()
        scripts = expanded / 'Scripts'
        for script in scripts.iterdir():
            subprocess.run(['/bin/sh', '-n', str(script)], check=True)
        if index == 0:
            payload = expanded / 'Payload'
            files = {p.relative_to(payload).as_posix() for p in payload.rglob('*') if p.is_file()}
            assert files == {
                'Library/PrivilegedHelperTools/10RemoteHub/device-helper',
                'Library/PrivilegedHelperTools/10RemoteHub/device-capture',
                'Library/PrivilegedHelperTools/10RemoteHub/libusb-1.0.dylib',
                'Library/PrivilegedHelperTools/10RemoteHub/libusb-LICENSE.txt',
                'Library/LaunchDaemons/org.remotehub.device-helper.plist',
            }
            job = plistlib.loads((payload / 'Library/LaunchDaemons/org.remotehub.device-helper.plist').read_bytes())
            assert job['ProgramArguments'] == ['/Library/PrivilegedHelperTools/10RemoteHub/device-helper']
            assert job['UserName'] == 'root'
            # Login Items shows the app name, not the signing developer's personal name.
            assert job['AssociatedBundleIdentifiers'] == ['org.remotehub.desktop']
            assert job['MachServices'] == {'org.remotehub.device-helper': True}
            assert 'bootstrap system' in (scripts / 'postinstall').read_text()
            assert 'bootout system/org.remotehub.device-helper' in (scripts / 'preinstall').read_text()
            assert builder.STOP_SERVICE in (scripts / 'preinstall').read_text()
            assert job['ExitTimeOut'] > 4  # daemon allows four seconds for USB cleanup
            bom = subprocess.run(['lsbom', '-p', 'MUGf', str(expanded / 'Bom')], check=True, capture_output=True, text=True).stdout
            for line in bom.splitlines():
                fields = line.split()
                assert fields[1:3] == ['root', 'wheel'], line  # ownership recommended = root:wheel
        else:
            assert info.find('payload') is None or info.find('payload').attrib.get('numberOfFiles') == '0'
            text = (scripts / 'postinstall').read_text()
            assert 'rm -f' in text and 'rm -rf' not in text
            assert '/Applications' not in text and 'tccutil' not in text


@pytest.mark.parametrize('delay', [0, 3, 99])
def test_upgrade_waits_for_service_removal_and_bounds_wait(tmp_path, delay):
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('helper_builder', root / 'scripts/build_device_helper.py')
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    # Execute the actual stop/wait shell with fake launchctl and time only.
    script = f'''set -eu
stopped=0
elapsed=0
fake_launchctl() {{
    [ "$2" = system/org.remotehub.device-helper ] || exit 90
    if [ "$1" = bootout ]; then stopped=1; return 0; fi
    [ "$1" = print ] || exit 91
    [ "$stopped" = 0 ] || [ "$elapsed" -lt {delay} ]
}}
fake_sleep() {{ elapsed=$((elapsed + 1)); echo wait; }}
'''
    script += builder.STOP_SERVICE.replace('/bin/launchctl', 'fake_launchctl').replace('/bin/sleep', 'fake_sleep')
    script += 'echo ready-to-replace\n'
    result = subprocess.run(['/bin/sh', '-c', script], capture_output=True, text=True)
    assert result.stdout.count('wait') == min(delay, 10)
    assert (result.returncode == 0) == (delay < 10)
    assert ('ready-to-replace' in result.stdout) == (delay < 10)


def test_native_collector_restores_after_partial_claim_and_cancel(tmp_path):
    root = Path(__file__).resolve().parents[1]
    brew = shutil.which('brew') or '/opt/homebrew/bin/brew'
    prefix = subprocess.run([brew, '--prefix', 'libusb'], check=True, capture_output=True, text=True).stdout.strip()
    binary = tmp_path / 'collector-test'
    subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror',
                    '-I' + prefix + '/include/libusb-1.0', str(root / 'native/tests/collector_test.c'),
                    '-o', str(binary)], check=True)
    import json
    for scenario in list(range(13)) + [14, 15]:
        result = subprocess.run([str(binary), str(scenario)], check=True, capture_output=True, text=True)
        events = [json.loads(line) for line in result.stdout.splitlines()]
        kinds = [e['type'] for e in events]
        if scenario in (0, 6, 7, 14):
            assert kinds.index('ready') < kinds.index('start') < kinds.index('audio') < kinds.index('end')
            if scenario in (6, 7):
                assert [e['hex'] for e in events if e['type'] == 'report'] == [
                    '00001e0000000000', '0000000000000000',
                    '00001e0000000000', '0000000000000000']
        elif scenario in (1, 2, 4, 5, 8):
            assert 'error' in kinds and 'ready' not in kinds
            if scenario == 5:
                assert 'interface 0 length 2' in events[-1]['message']
        elif scenario in (9, 10):
            assert 'ready' in kinds and 'error' in kinds
        elif scenario in (11, 12):
            assert kinds.index('ready') < kinds.index('start') < kinds.index('audio') < kinds.index('end')
            assert 'error' not in kinds
        else:
            assert 'ready' in kinds and 'end' in kinds and 'start' not in kinds and 'audio' not in kinds
            if scenario == 15:
                assert 'error' not in kinds


def test_native_pipe_forwards_small_events_without_waiting_for_full_buffer(tmp_path):
    root = Path(__file__).resolve().parents[1]
    binary = tmp_path / 'pipe-test'
    subprocess.run(['clang', '-fobjc-arc', '-Wall', '-Wextra', '-Werror',
                    str(root / 'native/tests/collector_pipe_test.m'), '-framework', 'Foundation',
                    '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True, timeout=5)


def test_codesign_requirement_is_checked_as_text_not_filename(tmp_path):
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('delivery_verifier', root/'scripts/verify_device_delivery.py')
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    source = tmp_path/'fixture.c'
    source.write_text('int main(void) { return 0; }\n')
    binary = tmp_path/'fixture'
    subprocess.run(['clang', str(source), '-o', str(binary)], check=True)
    subprocess.run(['codesign', '--force', '--sign', '-', '--identifier', 'org.remotehub.test-fixture', str(binary)], check=True)
    verifier.verify_requirement(binary, 'identifier "org.remotehub.test-fixture"')
    with pytest.raises(RuntimeError, match='校验失败'):
        verifier.verify_requirement(binary, 'identifier "org.remotehub.wrong-identity"')


@pytest.mark.skipif(sys.platform != 'darwin', reason='Mac native heartbeat')
def test_native_heartbeat_survives_main_thread_stall(tmp_path):
    root = Path(__file__).resolve().parents[1]
    binary = tmp_path / 'client-heartbeat-test'
    subprocess.run(['clang', '-fobjc-arc', '-Wall', '-Wextra', '-Werror',
                    '-mmacosx-version-min=13.0', str(root / 'native/tests/client_heartbeat_test.m'),
                    '-framework', 'Foundation', '-framework', 'Security', '-o', str(binary)], check=True)
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=20, check=True)
    assert 'CLIENT_HEARTBEAT_PASS' in result.stdout


def load_script(name):
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(name, root / f'scripts/{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def throwaway_identity(tmp_path):
    """A 2-day self-made code-signing certificate in a temporary keychain, never the login keychain."""
    config = tmp_path / 'cert.cnf'
    config.write_text('[req]\ndistinguished_name=dn\nprompt=no\nx509_extensions=e\n[dn]\nCN=RemoteHub Test\n'
                      '[e]\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=critical,codeSigning\n')
    key, cert, p12 = tmp_path / 'k.pem', tmp_path / 'c.pem', tmp_path / 'i.p12'
    keychain = tmp_path / 'test.keychain-db'
    for command in (
        ['/usr/bin/openssl', 'req', '-new', '-x509', '-newkey', 'rsa:2048', '-nodes', '-sha256', '-days', '2',
         '-config', config, '-keyout', key, '-out', cert],
        ['/usr/bin/openssl', 'pkcs12', '-export', '-inkey', key, '-in', cert, '-out', p12, '-passout', 'pass:x'],
        ['security', 'create-keychain', '-p', 'x', keychain],
        ['security', 'unlock-keychain', '-p', 'x', keychain],
        ['security', 'import', p12, '-k', keychain, '-P', 'x', '-T', '/usr/bin/codesign'],
        ['security', 'set-key-partition-list', '-S', 'apple-tool:,apple:', '-s', '-k', 'x', keychain],
    ):
        subprocess.run([str(x) for x in command], check=True, capture_output=True)
    fingerprint = subprocess.run(['/usr/bin/openssl', 'x509', '-in', str(cert), '-noout', '-fingerprint', '-sha1'],
                                 check=True, capture_output=True, text=True).stdout
    try:
        yield keychain, fingerprint.split('=')[1].strip().replace(':', '')
    finally:
        subprocess.run(['security', 'delete-keychain', str(keychain)], capture_output=True)


def fixture_binary(tmp_path, name='fixture'):
    source = tmp_path / f'{name}.c'
    source.write_text('int main(void) { return 0; }\n')
    binary = tmp_path / name
    subprocess.run(['clang', str(source), '-o', str(binary)], check=True)
    return binary


def test_self_made_certificate_is_pinned_without_apple_team(tmp_path, throwaway_identity):
    keychain, sha1 = throwaway_identity
    binary = fixture_binary(tmp_path)
    subprocess.run(['codesign', '--force', '--keychain', str(keychain), '--sign', sha1,
                    '--identifier', 'org.remotehub.device-capture', str(binary)], check=True, capture_output=True)
    builder, verifier = load_script('build_device_helper'), load_script('verify_device_delivery')
    assert builder.certificate_sha1(binary) == verifier.certificate_sha1(binary) == sha1
    verifier.verify_requirement(binary, f'identifier "org.remotehub.device-capture" and certificate leaf = H"{sha1}"')
    with pytest.raises(RuntimeError):
        verifier.verify_requirement(binary, f'identifier "org.remotehub.device-capture" and certificate leaf = H"{"0" * 40}"')

    # The collector's own native check (Protocol.h) accepts only the pinned certificate and identifier.
    root = Path(__file__).resolve().parents[1]
    def checker(pin):
        out = tmp_path / f'pin-{pin[:4]}'
        subprocess.run(['clang', '-fobjc-arc', '-Wall', '-Wextra', '-Werror', '-mmacosx-version-min=13.0',
                        f'-DRH_CERT_SHA1="{pin}"', str(root / 'native/tests/cert_pin_test.m'),
                        '-framework', 'Foundation', '-framework', 'Security', '-o', str(out)], check=True)
        return lambda path, ident: subprocess.run([str(out), str(path), ident]).returncode
    assert checker(sha1)(binary, 'org.remotehub.device-capture') == 0
    assert checker(sha1)(binary, 'org.remotehub.other') == 1
    assert checker('0' * 40)(binary, 'org.remotehub.device-capture') == 1
    adhoc = fixture_binary(tmp_path, 'adhoc')
    subprocess.run(['codesign', '--force', '--sign', '-', '--identifier', 'org.remotehub.device-capture', str(adhoc)],
                   check=True, capture_output=True)
    assert checker(sha1)(adhoc, 'org.remotehub.device-capture') == 1


def test_ad_hoc_signature_has_no_certificate_to_pin(tmp_path):
    binary = fixture_binary(tmp_path)
    subprocess.run(['codesign', '--force', '--sign', '-', str(binary)], check=True, capture_output=True)
    for module in (load_script('build_device_helper'), load_script('verify_device_delivery')):
        with pytest.raises(RuntimeError, match='ad-hoc'):
            module.certificate_sha1(binary)


def test_libusb_license_falls_back_to_repository_copy(tmp_path):
    from scripts.build_device_helper import libusb_license
    assert libusb_license(tmp_path).name == 'libusb-LICENSE.txt'
    (tmp_path / 'COPYING').write_text('local copy')
    assert libusb_license(tmp_path).read_text() == 'local copy'
