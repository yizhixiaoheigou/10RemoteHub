"""No privilege, launchd registration or hardware access in these tests."""
import sys
import ctypes
import json

import pytest

from remotehub.mac_device_helper import MacDeviceHelper
from remotehub.devices import DeviceInput


class Library:
    def __init__(self):
        self.events = []
        self.connect_result = 0
        self.disconnect_result = 0
        self.connections = self.disconnects = self.beats = 0

    def rh_device_connect(self):
        self.connections += 1
        return self.connect_result

    def rh_device_disconnect(self):
        self.disconnects += 1
        return self.disconnect_result

    def rh_device_heartbeat(self):
        self.beats += 1

    def rh_device_next(self, buffer, capacity):
        if not self.events:
            return 0
        line = self.events.pop(0)
        if len(line) >= capacity:
            return -1
        ctypes.memmove(buffer, line + b'\0', len(line) + 1)
        return 1


def test_ready_requires_worker_event_and_stale_generation_is_ignored(qtbot):
    lib = Library()
    d = DeviceInput()
    h = MacDeviceHelper(d, library=lib)
    d.mac = h
    h.failed.connect(lambda _: None)
    h.line.connect(lambda line: d._event(line, d.generation))
    ready, keys = [], []
    d.ready.connect(ready.append)
    d.key.connect(lambda *value: keys.append(value))
    h.start()
    assert not ready and not h.confirmed
    d._event(b'{"type":"ready","interfaces":3}', d.generation - 1)
    assert not ready
    lib.events = [b'{"type":"ready","interfaces":3}',
                  b'{"type":"key","trigger":"hid:7:30","down":true}']
    h.poll()
    assert ready == [d.generation] and h.confirmed
    assert keys == [('hid:7:30', True)]
    assert d.stop()
    assert lib.disconnects == 1
    assert not h.poller.isActive()


def test_timeout_stops_polling_and_releases(qtbot):
    lib = Library()
    now = [1.0]
    h = MacDeviceHelper(library=lib, clock=lambda: now[0])
    failures = []
    h.failed.connect(failures.append)
    h.start()
    now[0] = 14
    h.poll()
    assert failures and '超时' in failures[0]
    assert lib.disconnects == 1
    assert not h.active and not h.poller.isActive()


def test_native_error_propagates_and_failed_release_is_not_forgotten(qtbot):
    lib = Library()
    lib.disconnect_result = -1
    d = DeviceInput()
    h = MacDeviceHelper(d, library=lib)
    d.mac = h
    h.failed.connect(lambda _: None)
    h.line.connect(lambda line: d._event(line, d.generation))
    failed, stopped = [], []
    d.failed.connect(failed.append)
    d.stopped.connect(stopped.append)
    h.start()
    lib.events = [json.dumps({'type': 'error', 'message': '设备助手连接已中断'}).encode()]
    h.poll()
    assert stopped == [d.generation]
    assert failed == ['设备助手连接已中断']
    assert not d.stop()
    assert not d.stop()  # No new listener may imply that the old worker exited.


def test_missing_helper_never_starts_polling(qtbot):
    lib = Library()
    lib.connect_result = 1
    h = MacDeviceHelper(library=lib)
    with pytest.raises(RuntimeError, match='尚未安装'):
        h.start()
    assert not h.active and not h.poller.isActive()
    assert h.stop() and lib.disconnects == 0


def test_poll_work_is_bounded(qtbot):
    lib = Library()
    h = MacDeviceHelper(library=lib)
    h.start()
    lib.events = [b'{}'] * 200
    h.poll()
    assert len(lib.events) == 136
    h.stop()


def test_unsigned_installer_is_refused(monkeypatch):
    from remotehub import mac_device_helper as helper
    monkeypatch.setattr(helper.sys, 'platform', 'darwin')
    monkeypatch.setattr(helper, 'installation_status', lambda: (2, '需要正式签名'))
    monkeypatch.setattr(helper.subprocess, 'run', lambda *a, **k: pytest.fail('must not open installer'))
    with pytest.raises(RuntimeError, match='正式签名'):
        helper.open_installer()


@pytest.mark.skipif(sys.platform != "darwin", reason="unified collector is macOS-only")
def test_unified_audio_never_restarts_key_capture(qtbot, tmp_path, monkeypatch):
    from remotehub.ui import MainWindow
    w = MainWindow(tmp_path, safe=True)
    qtbot.addWidget(w)
    c = w.controller
    c.usb.collector = c.device
    calls = []
    monkeypatch.setattr(c.usb, 'start', lambda: calls.append('attach audio'))
    with monkeypatch.context() as patch:
        patch.setattr(c.device, 'stop', lambda: pytest.fail('must keep key capture'))
        c.start_usb(c.profile)
    assert calls == ['attach audio']
    w.shutdown()


@pytest.mark.skipif(__import__('sys').platform != 'darwin', reason='Mac native ABI')
def test_adhoc_native_library_read_only_status():
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / 'build/device-helper-components/libRemoteHubDevice.dylib'
    if not path.exists():
        pytest.skip('Build scratch helper first')
    lib = ctypes.CDLL(str(path))
    # Only exercise unsigned refusal; do not connect a signed installed helper.
    status = lib.rh_device_status()
    if status != 2:
        pytest.skip('Not an unsigned fixture')
    assert lib.rh_device_connect() == 2
    assert lib.rh_device_disconnect() == 0


def test_bundled_installer_drops_download_quarantine(monkeypatch, tmp_path):
    from remotehub import installers
    pkg = tmp_path / 'RemoteHubDevice.pkg'
    pkg.write_bytes(b'x')
    calls = []
    monkeypatch.setattr(installers.sys, 'platform', 'darwin')
    monkeypatch.setattr(installers.subprocess, 'run', lambda *a, **k: calls.append([str(x) for x in a[0]]))
    installers.open_package(pkg)
    assert calls == [['/usr/bin/xattr', '-d', 'com.apple.quarantine', str(pkg)],
                     ['/usr/bin/open', str(pkg)]]


def test_installer_package_is_macos_only(monkeypatch, tmp_path):
    from remotehub import installers
    monkeypatch.setattr(installers.sys, 'platform', 'win32')
    with pytest.raises(RuntimeError, match='macOS'):
        installers.open_package(tmp_path / 'x.pkg')
