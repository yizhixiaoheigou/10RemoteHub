"""Audio setup binds only our virtual feed and follows the physical voice key."""
import base64
import sys
from remotehub.audio import AudioBridge
from remotehub.branding import BRAND
from remotehub.ui import MainWindow


class Device:
    def __init__(self, name, ident):
        self.name, self.ident = name, ident
    def description(self):
        return self.name
    def id(self):
        return self.ident


def test_virtual_mic_selected_automatically_and_never_falls_back_to_speakers(qtbot, tmp_path, monkeypatch):
    speakers = Device('MacBook Speakers', b'speakers')
    devices = [speakers]
    monkeypatch.setattr(AudioBridge, 'outputs', staticmethod(lambda: devices))
    w = MainWindow(tmp_path, safe=True)
    qtbot.addWidget(w)
    c = w.controller
    assert c.outputs == [] and c.voice.output_id == b''
    # Even legacy configurations cannot route the remote into physical speakers.
    c.settings['output'] = base64.b64encode(b'speakers').decode()
    name = 'CABLE Input (VB-Audio Virtual Cable)' if sys.platform == 'win32' else BRAND['microphone_name']
    devices.append(Device(name, b'virtual-mac'))
    c.media_devices.audioOutputsChanged.emit()
    assert c.outputs == [(name, b'virtual-mac')]
    assert c.voice.output_id == b'virtual-mac'
    assert '已就绪' in w.voice_page.microphone_status.text()
    assert w.voice_page.microphone_setup.isHidden()
    devices.pop()
    c.media_devices.audioOutputsChanged.emit()
    assert c.voice.output_id == b''
    alternate = 'Voicemeeter Input' if sys.platform == 'win32' else BRAND['audio_feed_name']
    devices.append(Device(alternate, b'virtual-linux'))
    c.refresh_outputs()
    assert c.voice.output_id == b'virtual-linux'
    assert not hasattr(w.voice_page, 'output')  # No generic output-device chooser.
    w.shutdown()


def test_voice_audio_setup_tracks_dedicated_voice_key_mode(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(AudioBridge, 'outputs', staticmethod(lambda: []))
    w = MainWindow(tmp_path, safe=True)
    qtbot.addWidget(w)
    c = w.controller
    c.select('tv-voice')
    editor = w.inspector.voice_editor
    index = editor.source.findData('trigger')
    editor.source.setCurrentIndex(index)
    editor.source.activated.emit(index)
    assert not c.remote_audio
    assert w.voice_page.audio_card.isHidden() and w.voice_page.audio_test.isHidden()
    assert '不需要虚拟麦克风' in w.voice_page.route.text()
    assert w.voice_page.source.currentData() == 'trigger'
    index = editor.source.findData('remote')
    editor.source.setCurrentIndex(index)
    editor.source.activated.emit(index)
    assert c.remote_audio and not w.voice_page.audio_card.isHidden()
    assert not hasattr(w.voice_page, 'codec_status')
    assert not hasattr(w.voice_page, 'choose_codec')
    assert c.usb.client is None and not c.usb.server.isListening()
    w.shutdown()


def test_windows_uses_a_signed_virtual_cable(monkeypatch):
    """Windows cannot host a userland microphone; a signed cable is the target."""
    from types import SimpleNamespace
    from remotehub import virtual_mic

    cable = SimpleNamespace(description=lambda: "CABLE Input (VB-Audio Virtual Cable)")
    speaker = SimpleNamespace(description=lambda: "扬声器 (Realtek(R) Audio)")
    microphone = SimpleNamespace(description=lambda: "CABLE Output (VB-Audio Virtual Cable)")

    assert virtual_mic.is_windows_cable(cable)
    assert not virtual_mic.is_windows_cable(speaker)
    monkeypatch.setattr(virtual_mic.sys, "platform", "win32")
    assert virtual_mic.is_voice_output(cable)
    assert not virtual_mic.is_voice_output(speaker)
    assert not virtual_mic.is_voice_output(microphone)  # capture side, not a sink


def test_windows_without_a_cable_explains_how_to_get_one(qtbot, tmp_path, monkeypatch):
    from remotehub.ui import MainWindow
    import remotehub.controller as controller_module

    w = MainWindow(tmp_path, safe=True); qtbot.addWidget(w)
    c = w.controller
    monkeypatch.setattr(controller_module.sys, "platform", "win32")
    monkeypatch.setattr(c.audio, "outputs", lambda: [])
    c.refresh_outputs()
    view = c.microphone_view()
    assert "VB-CABLE" in view.detail and view.title != "已就绪"
    w.shutdown()
