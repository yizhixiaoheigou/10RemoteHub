"""The App offers its own uninstaller; the DMG stays a plain drag-install image."""
from pathlib import Path

from PySide6.QtWidgets import QMessageBox

from remotehub import devices, installers
from remotehub.ui import window as window_module


def test_uninstall_action_opens_packaged_installer(qtbot, tmp_path, monkeypatch):
    package = tmp_path / 'components' / 'RemoteHub-Uninstall.pkg'
    package.parent.mkdir(parents=True)
    package.write_bytes(b'pkg')
    monkeypatch.setattr(devices, 'resources', lambda: tmp_path)
    opened, scheduled = [], []
    monkeypatch.setattr(installers, 'open_package', lambda path: opened.append(Path(path)))
    monkeypatch.setattr(window_module.QTimer, 'singleShot', lambda ms, slot: scheduled.append((ms, slot)))
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.StandardButton.Yes)
    w = window_module.MainWindow(tmp_path / 'config', safe=True)
    qtbot.addWidget(w)
    monkeypatch.setattr(w, 'quit_app', lambda: scheduled.append('quit'))
    w.uninstall_app()
    assert opened == [package]
    assert scheduled and scheduled[0][0] == 800
    assert scheduled[0][1] == w.quit_app


def test_uninstall_action_is_cancellable(qtbot, tmp_path, monkeypatch):
    package = tmp_path / 'components' / 'RemoteHub-Uninstall.pkg'
    package.parent.mkdir(parents=True)
    package.write_bytes(b'pkg')
    monkeypatch.setattr(devices, 'resources', lambda: tmp_path)
    opened = []
    monkeypatch.setattr(installers, 'open_package', lambda path: opened.append(path))
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.StandardButton.Cancel)
    w = window_module.MainWindow(tmp_path / 'config', safe=True)
    qtbot.addWidget(w)
    w.uninstall_app()
    assert opened == []
