import json
from pathlib import Path
import sys
import numpy as np
import pytest

from remotehub.model import Action, Button, Profile, default_profiles, validate_keys
from remotehub.actions import ActionRunner, launch_command
from remotehub.hid_reports import HIDReports
from remotehub.audio import PCMProcessor, PCMQueue


def test_profile_roundtrip_with_file_and_hotspot(tmp_path):
    p=Profile(name="遥控器",buttons=[Button(name="文件",trigger="hid:7:40",action=Action("file",target=str(tmp_path/"含空格 $x.pdf")))])
    assert Profile.loads(p.dumps())==p


@pytest.mark.parametrize("change",[
    lambda p:setattr(p,"version",2),
    lambda p:setattr(p.buttons[0],"rect",[0,0,float("nan"),.1]),
    lambda p:setattr(p.buttons[0],"rect",[.9,0,.2,.1]),
    lambda p:p.buttons.append(Button(trigger=p.buttons[0].trigger)),
    lambda p:setattr(p.buttons[0],"action",Action("shell",target="rm")),
])
def test_import_rejects_unsafe_or_corrupt_profiles(change):
    p=Profile(buttons=[Button(trigger="hid:7:40")]); change(p)
    with pytest.raises(ValueError):p.dumps()


@pytest.mark.parametrize("platform,expected",[("darwin","/usr/bin/open"),("win32",None)])
def test_file_paths_are_not_shell_interpolated(tmp_path,platform,expected):
    file=tmp_path/"合同 $(touch bad); ' &.pdf"; file.touch()
    cmd=launch_command(Action("file",target=str(file)),platform)
    if expected is None:assert cmd is None
    else: assert cmd==[expected,str(file)]
    assert not (tmp_path/"bad").exists()


def test_missing_file_fails_before_launch(tmp_path):
    with pytest.raises(FileNotFoundError):launch_command(Action("file",target=str(tmp_path/"missing")))


@pytest.mark.parametrize("keys",[["a","b"],["ctrl","ctrl","a"],["shell"],[],["cmd"]])
def test_invalid_chords(keys):
    with pytest.raises(ValueError):validate_keys(keys)


def test_modifier_only_voice_and_single_key():
    validate_keys(["alt"],allow_modifier=True); validate_keys(["enter"])


def test_audio_chunking_does_not_change_output():
    rng=np.random.default_rng(42)
    pcm=rng.integers(-2000,2000,16000,dtype=np.int16).tobytes()
    a=PCMProcessor(); b=PCMProcessor()
    whole=a.process(pcm)
    pieces=np.concatenate([b.process(pcm[i:i+640]) for i in range(0,len(pcm),640)])
    assert whole.shape==pieces.shape
    np.testing.assert_allclose(whole,pieces,atol=1e-6)
    assert np.max(np.abs(whole))<=.89131
    np.testing.assert_allclose(a.flush(),b.flush(),atol=1e-6)
    assert whole.shape[0]+3==48000


def test_audio_queue_bounded_and_silence_on_underrun(qapp):
    queue=PCMQueue(100)
    queue.push(b"abcd")
    assert queue.readData(6)==b"abcd\0\0"
    assert queue.size==0
    with pytest.raises(BufferError):queue.push(b"x"*201)
    assert queue.readData(2)==b"\0\0"


def test_hid_keyboard_array_and_release():
    # Standard boot keyboard: modifiers + reserved + six array usages.
    desc=bytes.fromhex("05010906a101050719e029e71500250175019508810295017508810195067508150025650507190029658100c0")
    parser=HIDReports(desc)
    assert parser.decode(bytes([0,0,4,0,0,0,0,0]))==[("hid:7:4",True)]
    assert parser.decode(bytes([0,0,4,0,0,0,0,0]))==[]
    assert parser.decode(bytes(8))==[("hid:7:4",False)]
    with pytest.raises(ValueError):parser.decode(b"\0\0")


def test_hid_report_ids_do_not_release_other_report():
    desc=bytes.fromhex("050785011904290515002501750195028102750695018101850219062907750195028102750695018101")
    parser=HIDReports(desc)
    assert parser.decode(bytes([1,1]))==[("hid:7:4",True)]
    assert parser.decode(bytes([2,1]))==[("hid:7:6",True)]
    assert parser.decode(bytes([1,0]))==[("hid:7:4",False)]
    assert parser.decode(bytes([2,0]))==[("hid:7:6",False)]


def test_default_photo_template_has_observed_fixed_codes():
    profiles=default_profiles()
    for p in profiles:p.validate()
    photo=next(p for p in profiles if p.id=="tv-photo")
    assert photo.image and len(photo.buttons)==30
    assert all(b.action.kind==("voice" if b.id=="tv-voice" else "none") for b in photo.buttons)
    assert len({b.trigger for b in photo.buttons if b.trigger})==28
    assert all(bool(b.trigger)==b.configurable for b in photo.buttons)


class FakeKeys:
    def __init__(self):self.events=[]
    def press(self,keys):self.events.append(("down",keys))
    def release(self):self.events.append(("up",))
    def shortcut(self,keys):self.events.append(("chord",keys))


def test_action_release_does_not_repeat_shortcut():
    keys=FakeKeys(); runner=ActionRunner(keys)
    a=Action("shortcut",["ctrl","c"])
    runner.run(a,True); runner.run(a,False)
    assert keys.events==[("chord",["ctrl","c"])]
