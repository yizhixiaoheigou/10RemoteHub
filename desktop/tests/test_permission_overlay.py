"""Companion panel tests. Never open Settings, grant permissions or capture a screen."""
import os
import sys
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtWidgets import QApplication, QLabel

from remotehub import permissions
from remotehub.ui import MainWindow
from remotehub.ui.permission_overlay import PermissionOverlay, panel_geometry


@pytest.fixture
def overlay(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(permissions, "settings_window", lambda: ((20, 20, 668, 620), "settings"))
    monkeypatch.setattr(permissions, "permission_status", lambda: {"input": "未授权"})
    widget = PermissionOverlay(tmp_path / "10RemoteHub.app")
    qtbot.addWidget(widget)
    yield widget
    widget.close()


@pytest.mark.parametrize("window,screen", [
    ((100, 60, 820, 680), (0, 25, 1440, 875)),
    ((20, 40, 668, 620), (0, 25, 1280, 695)),
    ((-1100, 50, 820, 700), (-1280, 0, 1280, 800)),
    ((-120, -60, 700, 680), (0, 25, 1024, 743)),
])
def test_panel_stays_on_visible_screen_and_leaves_settings_controls(window, screen):
    window, screen = QRect(*window), QRect(*screen)
    panel = panel_geometry(window, screen, 180)
    assert window.intersected(screen).contains(panel)
    assert panel.width() >= 320 and panel.height() >= 160
    if screen.contains(window):
        assert panel.bottom() < window.bottom() - 40
        assert panel.left() > window.left() + 150


def test_follow_hide_return_and_close_when_settings_disappears(overlay, monkeypatch):
    overlay.begin("input")
    assert overlay.isVisible() and overlay.follow.isActive()
    first = overlay.geometry()
    monkeypatch.setattr(permissions, "settings_window", lambda: ((50, 50, 668, 620), "settings"))
    overlay.sync()
    assert overlay.geometry().x() == first.x() + 30
    monkeypatch.setattr(permissions, "settings_window", lambda: ((170, 70, 820, 680), "other"))
    overlay.sync()
    assert not overlay.isVisible() and overlay.follow.isActive()
    monkeypatch.setattr(permissions, "settings_window", lambda: ((170, 70, 820, 680), "settings"))
    overlay.sync()
    assert overlay.isVisible()
    monkeypatch.setattr(permissions, "settings_window", lambda: None)
    overlay.sync()
    assert not overlay.isVisible() and not overlay.follow.isActive() and not overlay.poll.isActive()


def test_no_guide_on_startup_and_reuse_for_both_permissions(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(permissions, "running_app_bundle", lambda: tmp_path / "10RemoteHub.app")
    monkeypatch.setattr(permissions, "settings_window", lambda: ((100, 40, 820, 680), "settings"))
    monkeypatch.setattr(permissions, "permission_status", lambda: {"input": "未授权"})
    opened = []
    monkeypatch.setattr(permissions, "open_permission_settings", opened.append)
    main = MainWindow(tmp_path / "config", safe=True)
    qtbot.addWidget(main)
    assert main.general.permission_overlay is None and opened == []
    main.controller.open_permission("input")
    panel = main.general.permission_overlay
    assert panel.isVisible() and "输入监控" in panel.title.text()
    main.controller.open_permission("accessibility")
    assert panel is main.general.permission_overlay
    assert "辅助功能" in panel.title.text() and opened == ["input", "accessibility"]
    main.shutdown()
    assert not panel.isVisible() and not panel.follow.isActive()


@pytest.mark.skipif(sys.platform != "darwin", reason="drag-into-Settings is macOS-only")
def test_drag_defers_follow_and_dismissal_and_keeps_real_bundle_url(overlay, monkeypatch):
    overlay.begin("input")
    overlay.app.drag_started.emit()
    monkeypatch.setattr(permissions, "settings_window", lambda: None)
    monkeypatch.setattr(permissions, "permission_status", lambda: {"input": "已授权"})
    overlay.sync()
    overlay.check_permission()
    assert overlay.isVisible()
    assert overlay.app.mime_data().urls()[0].toLocalFile() == str(overlay.app.bundle)
    overlay.app.drag_finished.emit()
    done = []
    overlay.authorized.connect(lambda: done.append(True))
    overlay.check_permission()
    assert done == [True] and not overlay.isVisible() and not overlay.poll.isActive()


def test_escape_stops_timers_and_content_fits(overlay, qtbot):
    overlay.begin("input")
    qtbot.wait(10)
    for child in overlay.findChildren(QLabel):
        assert child.parentWidget().rect().contains(child.geometry())
        if child.wordWrap():
            assert child.height() >= child.heightForWidth(child.width())
    qtbot.keyClick(overlay, Qt.Key.Key_Escape)
    assert not overlay.isVisible() and not overlay.follow.isActive() and not overlay.poll.isActive()


@pytest.mark.parametrize("accepted", [True, False])
def test_drop_closes_only_when_accepted_without_claiming_permission(overlay, accepted):
    overlay.begin("input")
    authorized = []
    overlay.authorized.connect(lambda: authorized.append(True))
    overlay.app.drag_started.emit()
    overlay.app.drag_finished.emit()
    if accepted:
        overlay.app.drop_accepted.emit()
    assert overlay.isVisible() is not accepted
    assert overlay.follow.isActive() is not accepted
    assert overlay.poll.isActive() is not accepted
    assert authorized == []  # Adding to the list does not enable the switch.
    overlay.begin("accessibility")
    assert overlay.isVisible() and overlay.follow.isActive()


def test_missing_settings_expires_without_an_orphan_panel(overlay, monkeypatch):
    monkeypatch.setattr(permissions, "settings_window", lambda: None)
    failures = []
    overlay.failed.connect(failures.append)
    overlay.begin("input")
    for _ in range(39):
        overlay.sync()
    assert not overlay.isVisible() and not overlay.follow.isActive() and not overlay.poll.isActive()
    assert len(failures) == 1 and "重新点击" in failures[0]


def test_return_to_main_app_hides_guide(overlay, monkeypatch):
    overlay.begin("input")
    monkeypatch.setattr(permissions, "settings_window", lambda: ((20, 20, 668, 620), "self"))
    monkeypatch.setattr(QApplication, "activeWindow", staticmethod(lambda: None))
    overlay.sync()
    assert not overlay.isVisible()


def test_settings_launch_failure_does_not_show_guide(qtbot, tmp_path, monkeypatch):
    def fail(_):
        raise RuntimeError("cannot open Settings")
    monkeypatch.setattr(permissions, "open_permission_settings", fail)
    main = MainWindow(tmp_path, safe=True)
    qtbot.addWidget(main)
    main.controller.open_permission("input")
    assert main.general.permission_overlay is None
    main.shutdown()


def test_settings_metadata_uses_bundle_pid_and_bounds_only(monkeypatch):
    settings = SimpleNamespace(processIdentifier=lambda: 42)
    front = SimpleNamespace(processIdentifier=lambda: 42)
    appkit = SimpleNamespace(
        NSRunningApplication=SimpleNamespace(runningApplicationsWithBundleIdentifier_=lambda name: [settings] if name == "com.apple.systempreferences" else []),
        NSWorkspace=SimpleNamespace(sharedWorkspace=lambda: SimpleNamespace(frontmostApplication=lambda: front)),
    )
    calls = []
    def read(options, ref):
        calls.append((options, ref))
        return [
            {"kCGWindowOwnerPID": 99, "kCGWindowLayer": 0, "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 800, "Height": 600}},
            {"kCGWindowOwnerPID": 42, "kCGWindowLayer": 1, "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 800, "Height": 600}},
            {"kCGWindowOwnerPID": 42, "kCGWindowLayer": 0, "kCGWindowBounds": {"X": 10, "Y": 30, "Width": 668, "Height": 620}},
        ]
    quartz = SimpleNamespace(CGWindowListCopyWindowInfo=read, kCGWindowListOptionOnScreenOnly=1,
                             kCGWindowListExcludeDesktopElements=16, kCGNullWindowID=0)
    monkeypatch.setitem(sys.modules, "AppKit", appkit)
    monkeypatch.setitem(sys.modules, "Quartz", quartz)
    monkeypatch.setattr(permissions, "sys", SimpleNamespace(platform="darwin"))
    assert permissions.settings_window() == ((10, 30, 668, 620), "settings")
    assert calls == [(17, 0)]
    front.processIdentifier = lambda: os.getpid()
    assert permissions.settings_window()[1] == "self"
    front.processIdentifier = lambda: 98765
    assert permissions.settings_window()[1] == "other"
