"""Exercise activation with harmless stubs; never restart the audio service."""
import importlib.util
from pathlib import Path
import plistlib
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS package-tool scripts")

ROOT = Path(__file__).resolve().parents[1]
POSTINSTALL = ROOT / 'native/macos-audio/installer/postinstall'


@pytest.mark.parametrize('delay,valid,target', [
    (0, True, '/'), (3, True, '/'), (99, True, '/'),
    (0, False, '/'), (0, True, '/Volumes/Offline'),
])
def test_activation_waits_once_and_reports_failure(tmp_path, delay, valid, target):
    # Replace every system mutation BEFORE execution. Probe is a shell stub.
    script = POSTINSTALL.read_text().replace('/usr/bin/codesign', 'fake_codesign')
    script = script.replace('/usr/bin/killall', 'fake_killall').replace('/bin/sleep', 'fake_sleep')
    script = script.replace('/usr/bin/pgrep', 'fake_pgrep')
    stub = f'''fake_codesign() {{ echo verify; return {0 if valid else 1}; }}
fake_killall() {{ echo restart; }}
fake_sleep() {{ echo wait; }}
fake_pgrep() {{ return 0; }}
'''
    path = tmp_path / 'postinstall'
    path.write_text(stub + script)
    probe = tmp_path / 'audio-plugin-probe'
    probe.write_text(f'''#!/bin/sh
test "$1" = --system || exit 99
count=0
if [ -f "{tmp_path}/count" ]; then count=$(cat "{tmp_path}/count"); fi
count=$((count + 1))
echo "$count" > "{tmp_path}/count"
test "$count" -gt {delay}
''')
    probe.chmod(0o755)
    result = subprocess.run(['/bin/sh', str(path), 'pkg', 'location', target],
                            capture_output=True, text=True, timeout=5)
    active = valid and target == '/'
    assert result.stdout.count('restart') == int(active)
    assert result.stdout.count('wait') == (min(delay, 15) if active else 0)
    success = target != '/' or (valid and delay < 15)
    assert (result.returncode == 0) == success
    assert ('registered and ready' in result.stdout) == (active and delay < 15)
    if active:
        assert int((tmp_path / 'count').read_text()) == min(delay + 1, 15)
    else:
        assert not (tmp_path / 'count').exists()


@pytest.mark.parametrize('states,success', [('1', True), ('0 1', True), ('0 0', False)])
def test_activation_handles_stopped_service_without_hiding_restart_errors(tmp_path, states, success):
    script = POSTINSTALL.read_text()
    for command in ('codesign', 'killall', 'pgrep'):
        script = script.replace('/usr/bin/' + command, 'fake_' + command)
    script = script.replace('/bin/sleep', 'fake_sleep')
    (tmp_path / 'states').write_text(states)
    stub = f'''fake_codesign() {{ return 0; }}
fake_killall() {{ echo restart-attempt; return 1; }}
fake_sleep() {{ return 0; }}
fake_pgrep() {{
    set -- $(cat "{tmp_path}/states")
    value="$1"; shift
    echo "$*" > "{tmp_path}/states"
    return "$value"
}}
'''
    path = tmp_path / 'postinstall'; path.write_text(stub + script)
    probe = tmp_path / 'audio-plugin-probe'
    probe.write_text('#!/bin/sh\nexit 0\n'); probe.chmod(0o755)
    result = subprocess.run(['/bin/sh', str(path)], capture_output=True, text=True, timeout=5)
    assert (result.returncode == 0) == success
    assert ('registered and ready' in result.stdout) == success
    assert result.stdout.count('restart-attempt') == int(states.startswith('0'))


@pytest.mark.skipif(sys.platform != 'darwin', reason='macOS package tools')
def test_standalone_installer_contains_one_fixed_payload_and_activation(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('audio_builder', ROOT / 'scripts/package_audio_component.py')
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    monkeypatch.setattr(builder, 'ROOT', tmp_path)
    driver = tmp_path / 'build/RemoteHubAudio.driver'
    (driver / 'Contents/MacOS').mkdir(parents=True)
    (driver / 'Contents/Info.plist').write_bytes(plistlib.dumps({
        'CFBundleIdentifier': 'org.remotehub.audio', 'CFBundleShortVersionString': '0.1.1',
        'CFBundleVersion': '2', 'CFBundleExecutable': 'RemoteHubAudio',
    }))
    (driver / 'Contents/MacOS/RemoteHubAudio').write_bytes(b'fixture; never install')
    (tmp_path / 'build/audio-plugin-probe').write_bytes(b'fixture; never execute')
    (tmp_path / 'remotehub').mkdir()
    (tmp_path / 'remotehub/branding.json').write_bytes((ROOT / 'remotehub/branding.json').read_bytes())
    installer = tmp_path / 'native/macos-audio/installer'
    installer.mkdir(parents=True)
    (installer / 'postinstall').write_bytes(POSTINSTALL.read_bytes())
    builder.build()
    expanded = tmp_path / 'expanded'
    subprocess.run(['pkgutil', '--expand-full', str(tmp_path / 'build/RemoteHubAudio.pkg'),
                    str(expanded)], check=True)
    distribution = ET.parse(expanded / 'Distribution').getroot()
    refs = [p for p in distribution.findall('pkg-ref') if p.text and p.text.strip()]
    assert len(refs) == 1 and refs[0].text == '#RemoteHubAudioComponent.pkg'
    assert 'RequireRestart' not in (expanded / 'Distribution').read_text()
    payload = expanded / 'RemoteHubAudioComponent.pkg'
    info = ET.parse(payload / 'PackageInfo').getroot()
    assert info.attrib['install-location'] == '/Library/Audio/Plug-Ins/HAL/RemoteHubAudio.driver'
    assert info.attrib['identifier'] == 'org.remotehub.audio'
    assert info.attrib['version'] == '0.1.1'
    assert (payload / 'Scripts/postinstall').read_bytes() == POSTINSTALL.read_bytes()
    assert (payload / 'Scripts/audio-plugin-probe').stat().st_mode & 0o111
    assert (payload / 'Payload/Contents/MacOS/RemoteHubAudio').read_bytes() == b'fixture; never install'
    bom = subprocess.run(['lsbom', '-p', 'MUGf', str(payload / 'Bom')],
                         check=True, capture_output=True, text=True).stdout
    assert all(line.split()[1:3] == ['root', 'wheel'] for line in bom.splitlines())
