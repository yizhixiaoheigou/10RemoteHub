"""The uninstaller must delete only files it can prove belong to this project."""
import plistlib
import subprocess
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import package_uninstall as uninstall

pytestmark = pytest.mark.skipif(sys.platform != 'darwin', reason='macOS package/uninstall tools')


def bundle(path, identifier):
    (path / 'Contents').mkdir(parents=True, exist_ok=True)
    (path / 'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': identifier}))
    return path


def simulated_script(tmp_path, *, app_id=None, driver_id=None):
    """Rewrite the constant block into tmp_path so the behaviour runs safely."""
    app_id = app_id or uninstall.CONSTANTS['APP_ID']
    driver_id = driver_id or uninstall.CONSTANTS['DRIVER_ID']
    moved = {
        'APP': tmp_path / 'Applications/10RemoteHub.app',
        'HELPER': tmp_path / 'PrivilegedHelperTools/10RemoteHub',
        'DAEMON': tmp_path / 'LaunchDaemons/org.remotehub.device-helper.plist',
        'DRIVER': tmp_path / 'HAL/RemoteHubAudio.driver',
    }
    text = uninstall.POSTINSTALL
    for key, value in moved.items():
        text = text.replace(f'{key}="{uninstall.CONSTANTS[key]}"', f'{key}="{value}"')
    text = text.replace(f'APP_ID="{uninstall.CONSTANTS["APP_ID"]}"', f'APP_ID="{app_id}"')
    text = text.replace(f'SERVICE="{uninstall.CONSTANTS["SERVICE"]}"', 'SERVICE="test.service"')
    text = text.replace(f'DRIVER_ID="{uninstall.CONSTANTS["DRIVER_ID"]}"', f'DRIVER_ID="{driver_id}"')
    # The console-user login item lives outside tmp_path; skip that block.
    return text.replace('if [ -n "$console_user" ]', 'if false')


def test_package_is_built_with_guarded_fixed_paths(tmp_path):
    pkg = uninstall.build(tmp_path / 'Uninstall.pkg')
    assert pkg.is_file()
    expanded = tmp_path / 'expanded'
    subprocess.run(['/usr/sbin/pkgutil', '--expand-full', str(pkg), str(expanded)], check=True)
    text = (expanded / 'Scripts/postinstall').read_text()
    assert 'set -eu' in text
    for constant in ('APP', 'DRIVER', 'HELPER', 'DAEMON', 'APP_ID', 'DRIVER_ID'):
        assert f'{constant}="{uninstall.CONSTANTS[constant]}"' in text
    assert 'plutil -extract CFBundleIdentifier' in text
    assert 'pkgutil --forget' in text
    assert 'LaunchAgents/org.remotehub.desktop.plist' in text
    assert '/usr/bin/killall -TERM coreaudiod' in text
    assert '$HOME' not in text


def test_removes_owned_files_and_keeps_user_configuration(tmp_path):
    app = bundle(tmp_path / 'Applications/10RemoteHub.app', uninstall.CONSTANTS['APP_ID'])
    driver = bundle(tmp_path / 'HAL/RemoteHubAudio.driver', uninstall.CONSTANTS['DRIVER_ID'])
    helper = tmp_path / 'PrivilegedHelperTools/10RemoteHub'
    helper.mkdir(parents=True)
    (helper / 'device-helper').write_text('x')
    daemon = tmp_path / 'LaunchDaemons/org.remotehub.device-helper.plist'
    daemon.parent.mkdir(parents=True, exist_ok=True)
    daemon.write_text('{}')
    config = tmp_path / 'Application Support/RemoteHub/profiles.json'
    config.parent.mkdir(parents=True)
    config.write_text('{}')

    result = subprocess.run(['/bin/sh', '-c', simulated_script(tmp_path)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert not app.exists() and not driver.exists() and not helper.exists() and not daemon.exists()
    assert config.is_file()


def test_refuses_to_delete_a_foreign_bundle(tmp_path):
    app = bundle(tmp_path / 'Applications/10RemoteHub.app', 'com.example.other')
    driver = bundle(tmp_path / 'HAL/RemoteHubAudio.driver', uninstall.CONSTANTS['DRIVER_ID'])
    result = subprocess.run(['/bin/sh', '-c', simulated_script(tmp_path)],
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert app.is_dir() and driver.is_dir()


def test_skips_missing_paths(tmp_path):
    result = subprocess.run(['/bin/sh', '-c', simulated_script(tmp_path)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
