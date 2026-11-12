"""Permissions are user initiated; tests never grant access or open Settings."""
import sys
from types import SimpleNamespace
import pytest
from remotehub import controller, permissions
from remotehub.inventory import USBDevice
from remotehub.ui import MainWindow


@pytest.mark.parametrize('state', ['未授权', '无法检测，请在系统设置中查看', None])
def test_collector_missing_does_not_open_permission_or_installer(qtbot, tmp_path, monkeypatch, state):
    w = MainWindow(tmp_path, safe=True)
    qtbot.addWidget(w)
    c = w.controller
    monkeypatch.setattr(c, 'permission_status', lambda: {'input': state})
    starts, opens = [], []
    def missing(*args):
        starts.append('start')
        raise RuntimeError('设备组件尚未安装，请到通用设置安装')
    monkeypatch.setattr(c.device, 'start', missing)
    monkeypatch.setattr(permissions, 'open_permission_settings', opens.append)
    receiver = USBDevice(0x0416, 0x0602, '', 'Receiver', 'port')
    monkeypatch.setattr(c.monitor, 'refresh', lambda: c.monitor.apply([receiver]))
    c.auto_mapping = True
    for _ in range(3):
        c.monitor.apply([receiver])
    assert starts == ['start'] and not opens and not c.enabled
    assert c.device_view().title == '设备连接出错'
    assert c.device_view().settings_link
    # USB capture is not a GUI IOHID open; Input Monitoring is not its gate.
    monkeypatch.setattr(c.device, 'start', lambda *args: starts.append('connected'))
    c.retry_connection()
    assert starts[-1] == 'connected' and c.enabled and not opens
    c.input_ready(c.device.generation)
    assert c.keys_ready
    w.shutdown()


def test_running_bundle_follows_actual_executable_not_app_name(tmp_path, monkeypatch):
    bundle = tmp_path / '含空格 current.app'
    exe = bundle / 'Contents/MacOS/10RemoteHub'
    exe.parent.mkdir(parents=True)
    exe.touch()
    (bundle / 'Contents/Info.plist').write_text('test')
    alias = tmp_path / 'entry'
    alias.symlink_to(exe)
    monkeypatch.setattr(permissions, 'sys', SimpleNamespace(platform='darwin', frozen=True, executable=str(alias)))
    assert permissions.running_app_bundle() == bundle
    calls = []
    monkeypatch.setattr(permissions.subprocess, 'run', lambda argv, **kw: calls.append(argv))
    permissions.reveal_running_app()
    assert calls == [['/usr/bin/open', '-R', str(bundle)]]
    monkeypatch.setattr(permissions, 'sys', SimpleNamespace(platform='darwin', executable=str(exe)))
    assert permissions.running_app_bundle() is None
    monkeypatch.setattr(permissions, 'sys', SimpleNamespace(platform='win32', frozen=True, executable=str(exe)))
    assert permissions.running_app_bundle() is None


@pytest.mark.skipif(sys.platform != "darwin", reason="drag-into-Settings is macOS-only")
def test_drag_exports_app_bundle_url_and_has_click_alternative(qtbot, tmp_path, monkeypatch):
    from remotehub.ui.permission_app import ApplicationDragButton
    from PySide6.QtCore import Qt
    bundle = tmp_path / '含空格 current.app'
    button = ApplicationDragButton(bundle)
    qtbot.addWidget(button)
    data = button.mime_data()
    assert data.hasUrls() and data.urls()[0].toLocalFile() == str(bundle)
    calls = []
    monkeypatch.setattr(permissions, 'reveal_running_app', lambda: calls.append('reveal'))
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)
    assert calls == ['reveal']


def test_permission_card_has_no_duplicate_drag_entry_and_fits(qtbot, tmp_path, monkeypatch):
    from remotehub.ui import general
    from PySide6.QtWidgets import QLabel, QPushButton
    monkeypatch.setattr(general, 'sys', SimpleNamespace(platform='darwin'))
    monkeypatch.setattr(permissions, 'running_app_bundle', lambda: tmp_path / '10RemoteHub.app')
    w = MainWindow(tmp_path / 'config', safe=True)
    qtbot.addWidget(w)
    w.resize(1200, 720)
    w.show_page(2)
    w.show()
    qtbot.wait(30)
    card = w.general.connection_status.parentWidget()
    assert not hasattr(w.general, 'permission_app')
    assert all('拖入授权列表' not in b.text() for b in card.findChildren(QPushButton))
    for child in card.findChildren(QPushButton):
        assert child.parentWidget().rect().contains(child.geometry())
    for child in card.findChildren(QLabel):
        if child.isVisible() and child.hasHeightForWidth():
            assert child.height() >= child.heightForWidth(child.width())
    w.shutdown()


@pytest.mark.parametrize('accepted', [True, False])
def test_drag_result_emits_completion_only_for_accepted_drop(qtbot, tmp_path, monkeypatch, accepted):
    from remotehub.ui import permission_app
    from PySide6.QtCore import QPoint, QPointF, Qt
    button = permission_app.ApplicationDragButton(tmp_path / '10RemoteHub.app')
    qtbot.addWidget(button)
    events = []
    button.drag_started.connect(lambda: events.append('started'))
    button.drag_finished.connect(lambda: events.append('finished'))
    button.drop_accepted.connect(lambda: events.append('accepted'))
    def execute(supported, default):
        assert supported == default == Qt.DropAction.CopyAction
        return Qt.DropAction.CopyAction if accepted else Qt.DropAction.IgnoreAction
    drag = SimpleNamespace(setMimeData=lambda _: None, setPixmap=lambda _: None,
                           setHotSpot=lambda _: None, exec=execute, deleteLater=lambda: None)
    monkeypatch.setattr(permission_app, 'QDrag', lambda _: drag)
    button.origin = QPoint(0, 0)
    event = SimpleNamespace(buttons=lambda: Qt.MouseButton.LeftButton,
                            position=lambda: QPointF(100, 100))
    button.mouseMoveEvent(event)
    assert events == ['started', 'finished'] + (['accepted'] if accepted else [])


def test_permission_cli_does_not_start_window_or_devices(monkeypatch, capsys, tmp_path):
    import json
    from remotehub import app
    from remotehub import ui
    def forbidden(*args, **kwargs):
        raise AssertionError('diagnostic must not start the application')
    monkeypatch.setattr(ui, 'MainWindow', forbidden)
    monkeypatch.setattr(app.sys, 'argv', ['10RemoteHub', '--permission-status'])
    bundle = tmp_path / '10RemoteHub.app'
    monkeypatch.setattr(permissions, 'running_app_bundle', lambda: bundle)
    states = {'input': '已授权', 'accessibility': '未授权'}
    monkeypatch.setattr(permissions, 'permission_status', lambda: states)
    assert app.main() == 0
    assert json.loads(capsys.readouterr().out) == {'bundle': str(bundle), 'permissions': states}


def test_permission_guide_moves_main_window_out_of_the_way(qtbot, tmp_path, monkeypatch):
    """The Settings drag target must not be covered by our own window."""
    import remotehub.ui.permission_overlay as overlay_module
    monkeypatch.setattr(permissions, 'running_app_bundle', lambda: tmp_path / '10RemoteHub.app')
    opened = []

    class FakeSignal:
        def connect(self, slot):
            pass

    class FakeOverlay:
        failed = FakeSignal()
        authorized = FakeSignal()

        def __init__(self, bundle):
            opened.append(bundle)

        def begin(self, name):
            opened.append(name)

        def close(self):
            opened.append('close')

    monkeypatch.setattr(overlay_module, 'PermissionOverlay', FakeOverlay)
    w = MainWindow(tmp_path / 'config', safe=True)
    qtbot.addWidget(w)
    w.show()
    assert not w.isMinimized()
    w.general.show_permission_overlay('accessibility')
    assert w.isMinimized()
    assert opened == [tmp_path / '10RemoteHub.app', 'accessibility']
    w.shutdown()
