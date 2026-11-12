import json
from pathlib import Path
import pytest
from remotehub.model import Action
from remotehub.ui import MainWindow
from remotehub.session import VoiceSession
from remotehub.actions import KeyOutput
from test_ui import FakeAudio, FakeKeys


def test_learning_release_cannot_trigger_action(qtbot,tmp_path):
    w=MainWindow(tmp_path,safe=True); qtbot.addWidget(w); c=w.controller
    c.add_button(); c.assign(Action("voice"))
    calls=[]; c.runner.voice=lambda down:calls.append(down)
    c.learning=True; c.on_key("hid:7:110",True); c.on_key("hid:7:110",False)
    assert c.selected.trigger=="hid:7:110" and not calls and not c.learning
    w.shutdown()


def test_voice_second_owner_cannot_interleave(qapp):
    audio=FakeAudio(); voice=VoiceSession(audio,FakeKeys())
    voice.start("usb")
    with pytest.raises(RuntimeError):voice.start("wav")
    with pytest.raises(ValueError):voice.feed("wav",b"\0\0")
    assert voice.owner=="usb"; voice.cancel()


def test_failed_keypress_unwinds_modifiers():
    output=KeyOutput(); seen=[]
    def send_key(key,down,flags):
        seen.append((key,down,list(flags)))
        if key=="c" and down:raise RuntimeError("injection failed")
    output._send=send_key
    with pytest.raises(RuntimeError):output.shortcut(["ctrl","c"])
    assert not output.held
    assert seen[-1]==("ctrl",False,[])


def test_saved_voice_settings_are_loaded(qtbot,tmp_path):
    w=MainWindow(tmp_path,safe=True);qtbot.addWidget(w)
    assert w.controller.update_voice(voice_keys="Ctrl + Shift + Space",voice_mode="toggle",gain=6)
    w.shutdown()
    other=MainWindow(tmp_path,safe=True);qtbot.addWidget(other); voice=other.controller.voice
    assert voice.trigger_keys==["ctrl","shift","space"]
    assert voice.trigger_mode=="toggle" and voice.gain==6
    assert other.voice_page.shortcut.keys==["ctrl","shift","space"] and other.voice_page.gain.value()==6
    other.shutdown()


@pytest.mark.parametrize("settings",[[1],{"gain":"bad"},{"voice_mode":"arbitrary"},{"voice_keys":3}])
def test_corrupt_settings_load_transactionally(qtbot,tmp_path,settings):
    from dataclasses import asdict
    from remotehub.model import default_profiles
    (tmp_path/"profiles.json").write_text(json.dumps({"profiles":[asdict(p) for p in default_profiles()],"settings":settings}))
    w=MainWindow(tmp_path,safe=True);qtbot.addWidget(w)
    assert w.controller.load_error and w.controller.settings=={}
    w.shutdown()
