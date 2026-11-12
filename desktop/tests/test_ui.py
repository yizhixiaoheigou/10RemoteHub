from PySide6.QtCore import QObject, Signal
import pytest
from remotehub.ui import MainWindow, sequence_keys, keys_sequence
from remotehub.model import Action
from remotehub.session import VoiceSession
from PySide6.QtGui import QKeySequence


class FakeAudio(QObject):
    ended=Signal(); failed=Signal(str)
    def __init__(self):super().__init__(); self.events=[]
    def start(self,*args):self.events.append("start")
    def feed(self,pcm):self.events.append(pcm)
    def finish(self):self.events.append("finish")
    def abort(self):self.ended.emit()


class FakeKeys:
    def __init__(self):self.events=[]
    def press(self,keys):self.events.append("down")
    def release(self):self.events.append("up")


def test_voice_releases_recognition_only_after_audio_drains(qapp):
    audio=FakeAudio(); keys=FakeKeys(); voice=VoiceSession(audio,keys)
    voice.start("usb"); voice.feed("usb",b"\0\0"); voice.finish("usb")
    assert keys.events==["down"]
    assert voice.owner=="usb"
    audio.ended.emit()
    assert keys.events==["down","up"] and voice.owner is None


def test_voice_one_minute_limit_finishes_normally(qapp):
    audio, keys = FakeAudio(), FakeKeys()
    voice = VoiceSession(audio, keys)
    expired, errors = [], []
    voice.expired.connect(lambda: expired.append(True))
    voice.failed.connect(errors.append)
    voice.start("usb")
    assert voice.timeout.interval() == 60_000
    voice.timeout.timeout.emit()
    assert expired == [True] and not errors
    assert audio.events == ["start", "finish"]
    assert keys.events == ["down"]
    audio.ended.emit()
    assert voice.owner is None and keys.events == ["down", "up"]
    assert not voice.timeout.isActive()
    voice.start("wav")
    assert not voice.timeout.isActive()
    voice.cancel()


def test_close_hides_dock_but_keeps_tray_until_quit(qtbot, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from PySide6.QtGui import QCloseEvent
    from remotehub.ui import window as window_module

    w = MainWindow(tmp_path, safe=True)
    qtbot.addWidget(w)
    visibility, hidden = [], []
    monkeypatch.setattr(window_module, 'set_dock_visible', visibility.append)
    w.tray = SimpleNamespace(hide=lambda: hidden.append(True))
    w.show()
    event = QCloseEvent()
    w.closeEvent(event)
    assert not w.isVisible() and not w.controller.shutting_down
    assert not event.isAccepted() and visibility == [False] and not hidden
    w.showNormal()
    assert w.isVisible() and visibility == [False, True]
    w.shutdown()
    assert hidden == [True] and w.controller.shutting_down


def test_ui_persists_actions_without_enabling_hardware(qtbot,tmp_path):
    window=MainWindow(tmp_path,safe=True); qtbot.addWidget(window)
    window.controller.add_button(); b=window.controller.selected
    assert window.controller.assign(Action("file",target=str(tmp_path/"some.pdf")))
    imported=MainWindow(tmp_path,safe=True); qtbot.addWidget(imported); c=imported.controller
    assert c.profile.buttons[-1].action==b.action
    assert not c.enabled and not c.auto_mapping
    assert [p.title for p in imported.pages]==["按键映射","语音设置","通用设置"]
    assert not hasattr(imported,"network") and not hasattr(c,"network")
    assert not c.usb.server.isListening()
    window.shutdown(); imported.shutdown()


def test_corrupt_config_not_overwritten(qtbot,tmp_path):
    path=tmp_path/"profiles.json"; path.write_text("broken")
    w=MainWindow(tmp_path,safe=True); qtbot.addWidget(w)
    assert not w.controller.save(); assert path.read_text()=="broken"
    assert "不会覆盖" in w.feedback.text() and w.feedback.property("error")
    w.shutdown()


def test_shortcut_recording_is_one_chord(qapp):
    # Qt reports ⌘ as Ctrl on macOS; stored names are physical keys.
    assert sequence_keys(QKeySequence("Ctrl+Shift+4"),"win32")==["ctrl","shift","4"]
    assert sequence_keys(QKeySequence("Ctrl+C"),"darwin")==["cmd","c"]
    assert sequence_keys(QKeySequence("Meta+C"),"darwin")==["ctrl","c"]
    assert sequence_keys(QKeySequence("Ctrl+C"),"win32")==["ctrl","c"]


@pytest.mark.parametrize("platform",["darwin","win32"])
@pytest.mark.parametrize("keys",[["cmd","c"],["ctrl","shift","a"],["alt","enter"],["f5"],["ctrl",","],["pagedown"],["space"]])
def test_recorder_round_trips_stored_keys(qapp,platform,keys):
    assert sorted(sequence_keys(keys_sequence(keys,platform),platform))==sorted(keys)
