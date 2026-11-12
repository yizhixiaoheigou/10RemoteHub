import json
from pathlib import Path
import sys

import pytest
from remotehub.controller import AppController
from remotehub.devices import DeviceInput
from remotehub.hid_reports import HIDReports
from remotehub.launch import Launcher, LaunchRequest
from remotehub.model import Action, validate_keys
from remotehub.store import ConfigStore, validate_settings

DESCRIPTORS = json.loads((Path(__file__).parent / 'fixtures/receiver-descriptors.json').read_text())['descriptors']


def test_bad_key_packet_does_not_end_session_or_release_held_key(qapp):
    device = DeviceInput()
    failures, keys = [], []
    device.failed.connect(failures.append)
    device.key.connect(lambda *args: keys.append(args))
    def send(kind, **values):
        device._event(json.dumps({'type': kind, **values}), device.generation)
    for interface, descriptor in DESCRIPTORS.items():
        send('descriptor', interface=int(interface), hex=descriptor)
    send('ready', interfaces=4)
    send('report', interface=4, hex='00001e0000000000')
    send('report', interface=4, hex='0000')
    send('report', interface=4, hex='not hex')
    send('report', interface=99, hex='01')
    send('report', interface=0, hex='03' + '00' * 31)
    assert device.capture_ready and not failures
    assert keys == [('hid:7:30', True)] and device.ignored_reports == 3
    send('report', interface=4, hex='0000000000000000')
    send('report', interface=4, hex='00001f0000000000')
    assert keys[-2:] == [('hid:7:30', False), ('hid:7:31', True)]
    send('error', message='USB disconnected')
    assert failures == ['USB disconnected'] and not device.capture_ready


def test_keyboard_rollover_retains_state():
    parser = HIDReports(bytes.fromhex(DESCRIPTORS['4']))
    assert parser.decode(bytes.fromhex('00001e0000000000')) == [('hid:7:30', True)]
    assert parser.decode(bytes.fromhex('0000010101010101')) == []
    assert parser.decode(bytes(8)) == [('hid:7:30', False)]


def test_failed_import_and_edits_preserve_disk_and_active_profile(qapp, tmp_path, monkeypatch):
    ctl = AppController(tmp_path)
    ctl.save()
    original = ctl.store.path.read_bytes()
    imported = tmp_path / 'import.json'
    imported.write_text(ctl.profile.dumps())
    before = (len(ctl.profiles), ctl.index, ctl.selected_id, ctl.selected.name, ctl.selected.rect[:])
    messages = []
    ctl.message.connect(lambda *args: messages.append(args))
    monkeypatch.setattr(ctl.store, 'save', lambda: (_ for _ in ()).throw(OSError('disk full')))
    monkeypatch.setattr(ctl.device, 'start', lambda *args: pytest.fail('must not restart capture'))
    ctl.import_profile(imported)
    ctl.rename('new name')
    ctl.set_rect([.1, .1, .2, .2])
    ctl.add_button()
    ctl.remove_button()
    assert (len(ctl.profiles), ctl.index, ctl.selected_id, ctl.selected.name, ctl.selected.rect) == before
    assert ctl.store.path.read_bytes() == original
    assert messages and all(error for _, error in messages)
    ctl.shutdown()


@pytest.mark.parametrize('content', [b'{}', b'{ broken', b'{"profiles":true}', b'\xff'])
def test_bad_config_has_readable_error_and_is_preserved(tmp_path, content):
    path = tmp_path / 'profiles.json'
    path.write_bytes(content)
    store = ConfigStore(tmp_path)
    store.load()
    assert '原配置格式不完整或已损坏' in store.load_error
    assert 'profiles' not in store.load_error and 'line' not in store.load_error
    with pytest.raises(ValueError):
        store.save()
    assert path.read_bytes() == content


def test_bool_gain_remains_rejected():
    with pytest.raises(ValueError):
        validate_settings({'gain': True})


@pytest.mark.parametrize('key', ['f21', 'f22', 'f23', 'f24', 'print_screen'])
def test_portable_key_rejected_only_on_unsupported_platform(key):
    action = Action('shortcut', [key])
    action.validate()
    action.validate('win32')
    with pytest.raises(ValueError, match='macOS'):
        action.validate('darwin')
    with pytest.raises(ValueError, match='macOS'):
        validate_keys([key], allow_modifier=True, platform='darwin')


def test_launcher_keeps_event_loop_responsive_and_reports_failures(qtbot):
    from PySide6.QtCore import QTimer
    launcher = Launcher(timeout_ms=2000)
    results, ticks = [], []
    launcher.finished.connect(lambda *args: results.append(args))
    pulse = QTimer()
    pulse.timeout.connect(lambda: ticks.append(1))
    pulse.start(10)
    launcher.start(LaunchRequest([sys.executable, '-c', 'import time; time.sleep(.3)'], 'opened'))
    assert launcher.jobs and not results
    qtbot.waitUntil(lambda: bool(results), timeout=3000)
    assert results == [('opened', False)] and len(ticks) >= 5
    launcher.start(LaunchRequest([sys.executable, '-c', 'import sys; sys.stderr.write("application unavailable"); sys.exit(1)']))
    qtbot.waitUntil(lambda: len(results) == 2)
    assert results[-1] == ('application unavailable', True)
    pulse.stop()
    launcher.stop()


def test_launcher_timeout_and_failed_start(qtbot, tmp_path):
    launcher = Launcher(timeout_ms=100)
    results = []
    launcher.finished.connect(lambda *args: results.append(args))
    launcher.start(LaunchRequest([str(tmp_path / 'missing-opener')]))
    qtbot.waitUntil(lambda: len(results) == 1)
    assert results[0][1] and '无法启动' in results[0][0]
    launcher.start(LaunchRequest([sys.executable, '-c', 'import time; time.sleep(10)']))
    qtbot.waitUntil(lambda: len(results) == 2)
    assert results[-1][1] and '超时' in results[-1][0]
    assert not launcher.jobs
    qtbot.wait(100)  # process termination must not emit a second result
    assert len(results) == 2
    launcher.stop()


def test_launcher_shutdown_releases_process_objects(qtbot):
    from PySide6.QtCore import QCoreApplication, QEvent, QProcess
    launcher = Launcher()
    results = []
    launcher.finished.connect(lambda *args: results.append(args))
    for _ in range(3):
        launcher.start(LaunchRequest([sys.executable, '-c', 'pass']))
    qtbot.waitUntil(lambda: len(results) == 3)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not launcher.jobs and not launcher.findChildren(QProcess)
    launcher.start(LaunchRequest([sys.executable, '-c', 'import time; time.sleep(10)']))
    launcher.stop()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not launcher.jobs and not launcher.findChildren(QProcess)


def test_controller_executes_launch_requests_without_blocking(qapp, tmp_path, monkeypatch):
    ctl = AppController(tmp_path)
    requests = []
    monkeypatch.setattr(ctl.launcher, 'start', requests.append)
    request = LaunchRequest(['example-opener', 'example.app'])
    monkeypatch.setattr(ctl.runner, 'run', lambda *args: request)
    ctl.selected.action = Action('app', target='example.app')
    ctl.on_key(ctl.selected.trigger, True)
    assert requests == [request]
    ctl.on_key(ctl.selected.trigger, True)
    assert requests == [request]
    ctl.shutdown()
