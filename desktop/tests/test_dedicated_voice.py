import json
from dataclasses import asdict

import pytest
from PySide6.QtCore import Qt
from remotehub.model import Action
from remotehub.photo_template import television_profile
from remotehub.store import ConfigStore
from remotehub.ui import MainWindow
from remotehub.session import VoiceSession
from test_ui import FakeAudio, FakeKeys


def test_old_voice_mapping_is_reserved_and_backed_up(tmp_path):
    p = television_profile()
    next(b for b in p.buttons if b.id == "tv-voice").action = Action("close_window")
    next(b for b in p.buttons if b.id == "tv-number-1").action = Action("shortcut", ["a"])
    original = json.dumps({"profiles": [asdict(p)], "settings": {"voice_mode": "manual"}})
    (tmp_path / "profiles.json").write_text(original)
    store = ConfigStore(tmp_path)
    store.load()
    assert next(b for b in store.profiles[0].buttons if b.id == "tv-voice").action == Action("voice")
    assert next(b for b in store.profiles[0].buttons if b.id == "tv-number-1").action == Action("shortcut", ["a"])
    assert store.settings["voice_mode"] == "hold"
    assert (tmp_path / "profiles.json").read_text() == original
    store.save()
    assert next(tmp_path.glob("profiles-before-standalone-*.json")).read_text() == original


def test_voice_key_has_only_voice_editor_and_cannot_be_reassigned(qtbot, tmp_path):
    w = MainWindow(tmp_path, safe=True)
    qtbot.addWidget(w)
    w.show()
    c = w.controller
    c.select("tv-voice")
    assert c.selected.action == Action("voice")
    assert not c.assign(Action("close_window"))
    assert not c.clear_action()
    assert not c.update_voice(voice_mode="manual")
    assert w.inspector.voice_editor.isVisible()
    assert not w.inspector.action_palette.isVisible()
    assert not w.inspector.clear_current.isVisible()
    assert not w.inspector.pages.isVisible()
    from PySide6.QtWidgets import QScrollArea
    w.resize(1200, 720)
    qtbot.wait(30)
    for area in w.findChildren(QScrollArea):
        if area.isVisible():
            assert area.horizontalScrollBar().maximum() == 0
    c.select("tv-number-1")
    assert w.inspector.action_palette.isVisible()
    assert not w.inspector.voice_editor.isVisible()
    assert not w.inspector.kinds["voice"].isVisible()
    assert c.assign(Action("shortcut", ["a"]))
    w.shutdown()


def test_unchanged_voice_shortcut_does_not_save_when_recording_disables_editor(qtbot, tmp_path, monkeypatch):
    w = MainWindow(tmp_path, safe=True)
    qtbot.addWidget(w)
    monkeypatch.setattr(w.controller, "update_voice", lambda **changes: pytest.fail("unchanged shortcut must not save"))
    w.controller.recording_requested = True
    w.controller.voice_changed.emit()
    assert not w.inspector.voice_editor.shortcut.isEnabled()
    w.controller.recording_requested = False
    w.shutdown()


def test_import_reserves_physical_voice_key_without_changing_source_file(qtbot, tmp_path):
    p = television_profile()
    voice = next(b for b in p.buttons if b.id == "tv-voice")
    voice.id = "imported-voice"  # still the same physical HID key
    voice.action = Action("shortcut", ["a"])
    path = tmp_path / "import.json"
    original = p.dumps()
    path.write_text(original)
    w = MainWindow(tmp_path / "config", safe=True)
    qtbot.addWidget(w)
    w.controller.import_profile(path)
    w.controller.select("imported-voice")
    assert w.controller.selected_voice_key
    assert w.controller.selected.action == Action("voice")
    assert not w.controller.assign(Action("file", target="/example.txt"))
    assert path.read_text() == original
    w.shutdown()


@pytest.mark.parametrize("gesture", ["hold", "toggle"])
def test_dedicated_voice_key_controls_recognition_and_editor_saves(qtbot, tmp_path, gesture):
    w = MainWindow(tmp_path, safe=True)
    qtbot.addWidget(w)
    c = w.controller
    c.select("tv-voice")
    editor = w.inspector.voice_editor
    editor.source.setCurrentIndex(editor.source.findData("trigger"))
    editor.source.activated.emit(editor.source.currentIndex())
    editor.shortcut.click()
    qtbot.keyClick(editor.shortcut, Qt.Key.Key_B)
    editor.record_mode.setCurrentIndex(editor.record_mode.findData(gesture))
    editor.record_mode.activated.emit(editor.record_mode.currentIndex())
    assert c.voice_settings()["voice_keys"] == "b"
    assert c.voice_settings()["record_mode"] == gesture
    keys, audio = FakeKeys(), FakeAudio()
    c.voice = VoiceSession(audio, keys)
    c.voice.finished.connect(c._voice_finished)
    c._apply_voice_settings()
    # Enforce the physical-key role even if runtime data is changed externally.
    c.selected.action = Action("close_window")
    c.on_key(c.selected.trigger, True)
    c.on_key(c.selected.trigger, False)
    if gesture == "toggle":
        assert c.voice.owner == "trigger"
        c.on_key(c.selected.trigger, True)
        c.on_key(c.selected.trigger, False)
    assert keys.events == ["down", "up"] and not audio.events
    assert c.voice.owner is None
    restored = ConfigStore(tmp_path)
    restored.load()
    assert restored.settings["voice_keys"] == "b"
    w.shutdown()


def test_voice_key_edge_closes_session_even_when_voice_disabled(qtbot, tmp_path, monkeypatch):
    """Releasing the physical key must always stop the collector session.

    Voice disabled used to clear voice_trigger on press, so the release was
    dropped and the receiver stayed in its session (LED on) until a timeout.
    """
    import remotehub.controller as controller_module
    from remotehub.photo_template import is_voice_button
    from remotehub.ui import MainWindow

    monkeypatch.setattr(controller_module.sys, "platform", "win32")
    w = MainWindow(tmp_path, safe=True); qtbot.addWidget(w)
    c = w.controller
    c.settings["voice_source"] = "disabled"
    edges = []
    monkeypatch.setattr(c, "_voice_edge", lambda down: edges.append(down))
    voice = next(b for b in c.profile.buttons if is_voice_button(c.profile, b))
    c.on_key(voice.trigger, True)
    c.on_key(voice.trigger, False)
    assert edges == [True, False]
    assert c.voice_trigger is None
    w.shutdown()


def test_voice_key_edge_repeats_are_ignored(qtbot, tmp_path, monkeypatch):
    import remotehub.controller as controller_module
    from remotehub.photo_template import is_voice_button
    from remotehub.ui import MainWindow

    monkeypatch.setattr(controller_module.sys, "platform", "win32")
    w = MainWindow(tmp_path, safe=True); qtbot.addWidget(w)
    c = w.controller
    edges = []
    monkeypatch.setattr(c, "_voice_edge", lambda down: edges.append(down))
    voice = next(b for b in c.profile.buttons if is_voice_button(c.profile, b))
    c.on_key(voice.trigger, True)
    c.on_key(voice.trigger, False)
    c.on_key(voice.trigger, True)
    c.on_key(voice.trigger, False)
    assert edges == [True, False, True, False]
    w.shutdown()


@pytest.mark.parametrize("mode", ["hold", "toggle"])
def test_receiver_start_before_key_press_is_adopted(qtbot, tmp_path, mode):
    from types import SimpleNamespace
    from remotehub.controller import AppController
    from remotehub.photo_template import is_voice_button

    c = AppController(tmp_path)
    c.settings.update(voice_source="remote", record_mode=mode)
    voice = SimpleNamespace(owner=None, routing=False, ending=False)
    voice.start = lambda owner: setattr(voice, "owner", owner)
    def finish(owner):
        voice.owner = None
        c._voice_finished()
    def cancel():
        voice.owner = None
    voice.finish = finish
    voice.cancel = cancel
    voice.close = lambda: None
    c.voice = c.usb.voice = voice
    c.usb.ready = c.usb.authenticated = True
    c.usb.decoder = SimpleNamespace(reset=lambda: None)
    commands = []
    c.device.capture_ready = True
    c.device.record = lambda active: commands.append(active)
    errors = []
    c.message.connect(lambda text, error: errors.append(text) if error else None)
    key = next(b for b in c.profile.buttons if is_voice_button(c.profile, b))
    c.usb._collected({"type": "start"})
    assert c.recording_requested and c.voice_auto_pending
    c.on_key(key.trigger, True)
    c.on_key(key.trigger, False)
    assert not errors
    assert c.voice_trigger is None
    assert voice.owner == "usb"
    assert commands == ([False] if mode == "hold" else [])
    if mode == "toggle":
        c.on_key(key.trigger, True)
        c.on_key(key.trigger, False)
    c.usb._collected({"type": "end"})
    assert voice.owner is None and not c.recording_requested
    assert commands == [False]
    c.shutdown()


def test_failed_start_still_sends_stop_on_release(qtbot, tmp_path, monkeypatch):
    from remotehub.controller import AppController
    from remotehub.photo_template import is_voice_button

    c = AppController(tmp_path)
    c.settings['voice_source'] = 'remote'
    commands = []
    c.device.capture_ready = True
    c.usb.ready = False
    monkeypatch.setattr(c.device, 'record', lambda active: commands.append(active))
    voice = next(b for b in c.profile.buttons if is_voice_button(c.profile, b))
    c.on_key(voice.trigger, True)
    assert not c.recording_requested
    c.on_key(voice.trigger, False)
    assert commands == [False, False]
    c.shutdown()
