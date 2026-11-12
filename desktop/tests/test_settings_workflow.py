"""No tests here open system settings, claim USB or inject real keys."""
import json
from types import SimpleNamespace
import pytest
from PySide6.QtWidgets import QCheckBox, QMenu
from remotehub import common_actions, permissions
from remotehub.ui import MainWindow
from remotehub.model import Action, validate_keys
from remotehub.inventory import USBDevice
from remotehub.session import VoiceSession
from remotehub.usb_bridge import USBBridge
from test_ui import FakeAudio, FakeKeys


@pytest.mark.parametrize("platform", ["darwin", "win32"])
def test_common_operations_resolve_on_executing_platform(platform):
    for name in common_actions.available_actions(platform):
        Action("common", target=name).validate()
        if name not in common_actions.MEDIA_ACTIONS | common_actions.SCROLL_ACTIONS | {"system_settings"} | (set(common_actions.MAC_SYSTEM_ACTIONS) if platform == "darwin" else set()):
            validate_keys(common_actions.common_keys(name, platform))
    assert common_actions.common_keys("copy", platform) == ["cmd" if platform=="darwin" else "ctrl", "c"]


def test_windows_does_not_offer_the_macos_app_updater(qtbot, tmp_path, monkeypatch):
    import remotehub.controller as controller_module
    w = MainWindow(tmp_path, safe=True); qtbot.addWidget(w)
    errors = []
    w.controller.update_error.connect(errors.append)
    with monkeypatch.context() as patch:
        patch.setattr(controller_module, "sys", SimpleNamespace(platform="win32"))
        w.controller.check_updates(manual=True)
    assert errors and "自动更新" in errors[0]
    w.shutdown()


def test_flat_actions_save_without_dialog_or_execution(qtbot,tmp_path,monkeypatch):
    w=MainWindow(tmp_path,safe=True);qtbot.addWidget(w);w.show();c=w.controller;ins=w.inspector
    monkeypatch.setattr(c.runner,"run",lambda *args:pytest.fail("Editing must not run action"))
    assert "common" not in ins.kinds
    for kind in ("common:copy","common:system_settings","minimize_window","close_window"):
        ins.kinds[kind].click()
        assert ins.kinds[kind].isChecked() and ins.draft_kind is None
        assert not ins.pages.isVisible()  # no second-level picker
    ins.kinds["common:paste"].click()
    other=MainWindow(tmp_path,safe=True);qtbot.addWidget(other)
    assert other.controller.selected.action==Action("common",target="paste")
    assert not any("启用按键" in b.text() for b in w.findChildren(QCheckBox))
    assert w.voice_page.isAncestorOf(w.voice_page.audio_test) and not w.general.isAncestorOf(w.voice_page.audio_test)
    w.shutdown();other.shutdown()


@pytest.mark.parametrize("gesture",["hold","toggle"])
@pytest.mark.parametrize("recognition",["hold","toggle"])
def test_trigger_only_records_without_audio_device(qtbot,tmp_path,gesture,recognition):
    w=MainWindow(tmp_path,safe=True);qtbot.addWidget(w);c=w.controller
    audio=FakeAudio();keys=FakeKeys();c.voice=VoiceSession(audio,keys)
    c.voice.finished.connect(c._voice_finished)
    c.voice.trigger_mode=recognition
    c.settings.update(voice_source="trigger",record_mode=gesture)
    c.voice_button(True)
    assert c.voice.owner=="trigger" and not audio.events
    c.voice_button(False)
    if gesture=="toggle":
        assert c.voice.owner=="trigger"
        c.voice_button(True)
    assert c.voice.owner is None and not c.recording_requested
    assert keys.events == (["down","up"] if recognition=="hold" else ["down","up","down","up"])
    assert not audio.events
    w.shutdown()


def test_disconnect_cancels_held_recognition_key(qtbot,tmp_path,monkeypatch):
    w=MainWindow(tmp_path,safe=True);qtbot.addWidget(w);c=w.controller
    monkeypatch.setattr(c,"permission_status",lambda:{"input":"已授权"})
    keys=FakeKeys();c.voice=VoiceSession(FakeAudio(),keys);c.voice.finished.connect(c._voice_finished)
    c.settings["voice_source"]="trigger"
    monkeypatch.setattr(c.device,"start",lambda *args:None)
    c.auto_mapping=True
    c.monitor.apply([USBDevice(0x0416,0x0602,"","Receiver","port")])
    c.voice_button(True)
    c.monitor.apply([])
    assert keys.events==["down","up"] and c.voice.owner is None
    w.shutdown()


def test_reassigning_held_voice_key_still_releases_recording(qtbot,tmp_path):
    w=MainWindow(tmp_path,safe=True);qtbot.addWidget(w);c=w.controller
    keys=FakeKeys();c.voice=VoiceSession(FakeAudio(),keys);c.voice.finished.connect(c._voice_finished)
    c.settings["voice_source"]="trigger"
    b=c.selected;b.action=Action("voice")
    c.on_key(b.trigger,True)
    b.action=Action()
    c.on_key(b.trigger,False)
    assert keys.events==["down","up"] and not c.recording_requested
    w.shutdown()


def test_voice_save_failure_preserves_runtime_and_reports_failure(qtbot,tmp_path,monkeypatch):
    w=MainWindow(tmp_path,safe=True);qtbot.addWidget(w);c=w.controller
    monkeypatch.setattr(c.store,"save",lambda:(_ for _ in ()).throw(OSError("disk full")))
    errors=[];c.message.connect(lambda text,error:errors.append(error))
    assert not c.update_voice(voice_source="trigger",voice_keys="ctrl+space")
    assert not c.settings and c.voice.trigger_keys==["alt"] and errors and all(errors)
    assert w.voice_page.source.currentData()=="disabled" and w.voice_page.shortcut.keys==["alt"]
    w.shutdown()


def test_auto_mapping_failure_does_not_retry_every_scan(qtbot,tmp_path,monkeypatch):
    w=MainWindow(tmp_path,safe=True);qtbot.addWidget(w);c=w.controller;calls=[]
    def fail(*args):calls.append("start");raise PermissionError("denied")
    monkeypatch.setattr(c.device,"start",fail)
    monkeypatch.setattr(c,"permission_status",lambda:{"input":"已授权"})
    c.auto_mapping=True
    receiver=USBDevice(0x0416,0x0602,"","Receiver","port")
    for _ in range(3):c.monitor.apply([receiver])
    assert calls==["start"] and w.sidebar.status.text()=="设备连接出错"
    assert w.sidebar.status.property("tone")=="error" and "denied" in w.sidebar.detail.text()
    monkeypatch.setattr(c.monitor,"refresh",lambda: c.monitor.apply([receiver]))
    monkeypatch.setattr(c,"permission_status",lambda:{"input":"已授权"})
    w.sidebar.retry_requested.emit()
    assert calls==["start","start"]
    w.shutdown()


def test_permission_menu_opens_only_clicked_target(qtbot,tmp_path,monkeypatch):
    from remotehub.ui import window as ui
    from PySide6.QtGui import QDesktopServices
    calls=[]
    monkeypatch.setattr(permissions,"sys",SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(QDesktopServices,"openUrl",lambda url:calls.append(url.toString()) or True)
    permissions.open_permission_settings("input")
    assert calls==["x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent"]
    w=MainWindow(tmp_path,safe=True);qtbot.addWidget(w);menu=QMenu(w)
    monkeypatch.setattr(ui,"sys",SimpleNamespace(platform="darwin"))
    w.add_permission_actions(menu)
    assert len(calls)==1
    menu.actions()[0].trigger()
    assert calls[-1].endswith("Privacy_Accessibility")
    w.shutdown()


class Socket:
    def __init__(self):self.events=[];self.pending=b""
    def write(self,data):self.events.append(json.loads(data))
    def flush(self):pass
    def readAll(self):data,self.pending=self.pending,b"";return data


def test_usb_release_waits_for_worker_tail_then_sink_drain(qapp,tmp_path):
    audio=FakeAudio();keys=FakeKeys();voice=VoiceSession(audio,keys)
    bridge=USBBridge(voice,tmp_path);sock=Socket();bridge.client=sock
    bridge.authenticated=bridge.ready=True
    bridge.start_audio()
    sock.pending=b'{"type":"start"}\n';bridge._read()
    bridge.stop_audio()
    assert voice.owner=="usb" and "finish" not in audio.events
    sock.pending=b'{"type":"pcm","data":"AAA="}\n{"type":"end"}\n';bridge._read()
    assert audio.events==["start",b"\0\0","finish"] and keys.events==["down"]
    audio.ended.emit()
    assert keys.events==["down","up"]
    bridge.client=None;bridge.stop()


def test_usb_release_before_handshake_does_not_start_recognition(qapp,tmp_path):
    audio=FakeAudio();keys=FakeKeys();voice=VoiceSession(audio,keys)
    bridge=USBBridge(voice,tmp_path);sock=Socket();bridge.client=sock
    bridge.authenticated=bridge.ready=True
    bridge.start_audio();bridge.stop_audio()
    sock.pending=b'{"type":"start"}\n{"type":"pcm","data":"AAA="}\n{"type":"end"}\n';bridge._read()
    assert not audio.events and not keys.events and voice.owner is None
    bridge.client=None;bridge.stop()


def test_named_system_settings_launch_uses_no_shell(monkeypatch):
    calls=[]
    monkeypatch.setattr(common_actions.subprocess,"Popen",lambda args:calls.append(args))
    common_actions.open_system_settings("darwin")
    assert calls==[["/usr/bin/open","-b","com.apple.systempreferences"]]
    opened=[]
    monkeypatch.setattr(common_actions.os,"startfile",lambda target:opened.append(target),raising=False)
    common_actions.open_system_settings("win32")
    assert opened==["ms-settings:"]
