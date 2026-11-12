"""Exercise the real application-selection entry point without showing dialogs."""
from types import SimpleNamespace
import pytest
from remotehub.model import Action
from remotehub.ui import MainWindow
from remotehub.ui import inspector as module


@pytest.mark.parametrize("purpose", ["toggle_app", "file_application"])
def test_mac_application_bundle_can_be_picked_and_saved(qtbot, tmp_path, monkeypatch, purpose):
    app = tmp_path / "示例 Editor.app"
    (app / "Contents").mkdir(parents=True)
    calls = []
    def pick(parent, title, directory, file_filter):
        calls.append((directory, file_filter))
        assert directory == "/Applications" and "*.app" in file_filter
        return str(app), file_filter
    monkeypatch.setattr(module, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(module.QFileDialog, "getOpenFileName", pick)
    monkeypatch.setattr(module.QFileDialog, "getExistingDirectory",
                        lambda *args, **kwargs: pytest.fail("Folder-only mode disables macOS application bundles"))
    w = MainWindow(tmp_path / "config", safe=True)
    qtbot.addWidget(w)
    monkeypatch.setattr(w.controller.runner, "run", lambda *args: pytest.fail("Picking must not launch an app"))
    if purpose == "toggle_app":
        w.inspector.choose_kind("toggle_app")
        w.inspector.pick_app()
        expected = Action("toggle_app", target=str(app))
    else:
        w.controller.assign(Action("file", target=str(tmp_path / "文档.txt")))
        w.inspector.pick_file_app()
        expected = Action("file", target=str(tmp_path / "文档.txt"), application=str(app))
    assert calls and w.controller.selected.action == expected
    again = MainWindow(tmp_path / "config", safe=True)
    qtbot.addWidget(again)
    assert again.controller.selected.action == expected
    w.shutdown()
    again.shutdown()


def test_cancel_application_picker_keeps_existing_mapping(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(module, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(module.QFileDialog, "getOpenFileName", lambda *args: ("", ""))
    monkeypatch.setattr(module.QFileDialog, "getExistingDirectory",
                        lambda *args: pytest.fail("Do not open a folder picker"))
    w = MainWindow(tmp_path, safe=True)
    qtbot.addWidget(w)
    previous = Action("toggle_app", target="/Applications/Previous.app")
    w.controller.assign(previous)
    w.inspector.pick_app()
    assert w.controller.selected.action == previous
    w.shutdown()
