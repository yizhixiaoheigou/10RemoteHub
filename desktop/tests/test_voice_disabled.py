from types import SimpleNamespace
import sys
import pytest
from remotehub.controller import AppController
from remotehub.store import ConfigStore
from remotehub.ui import MainWindow
from remotehub.audio import AudioBridge
from remotehub.virtual_mic import VirtualMic


def test_new_config_voice_disabled_even_with_ready_devices(qapp, tmp_path, monkeypatch):
    c = AppController(tmp_path)
    assert c.voice_settings()['voice_source'] == 'disabled'
    assert not c.remote_audio
    c.keys_ready = True
    c.device.capture_ready = True
    c.voice.output_id = b'virtual'
    monkeypatch.setattr(c, 'start_usb', lambda *a: pytest.fail('Disabled must not connect audio'))
    monkeypatch.setattr(c.usb, 'start_audio', lambda: pytest.fail('Disabled must not record'))
    monkeypatch.setattr(c.voice, 'start', lambda *a: pytest.fail('Disabled must not send recognition key'))
    c.ensure_remote_audio()
    voice = next(b for b in c.profile.buttons if b.id == 'tv-voice')
    c.on_key(voice.trigger, True)
    c.on_key(voice.trigger, False)
    assert not c.recording_requested and c.voice.owner is None
    assert c.voice_trigger is None and not c.pressed
    assert c.voice_view().title == '未启用'
    c.shutdown()


@pytest.mark.parametrize('source', ['disabled', 'remote', 'trigger'])
def test_voice_choice_saved_and_existing_choice_preserved(tmp_path, source):
    store = ConfigStore(tmp_path)
    store.settings.update(voice_source=source, voice_keys='b')
    store.save()
    again = ConfigStore(tmp_path)
    again.load()
    assert not again.load_error
    assert again.settings['voice_source'] == source and again.settings['voice_keys'] == 'b'


def test_voice_selector_can_return_to_disabled(qtbot, tmp_path, monkeypatch):
    w = MainWindow(tmp_path, safe=True)
    qtbot.addWidget(w)
    c = w.controller
    monkeypatch.setattr(c, 'ensure_remote_audio', lambda: None)
    c.select('tv-voice')
    editor = w.inspector.voice_editor
    assert editor.source.currentData() == w.voice_page.source.currentData() == 'disabled'
    assert editor.controls.isHidden() and w.voice_page.recognition_card.isHidden()
    for source in ('trigger', 'remote', 'disabled'):
        index = editor.source.findData(source)
        assert index >= 0
        editor.source.setCurrentIndex(index)
        editor.source.activated.emit(index)
        assert w.voice_page.source.currentData() == source
        assert editor.controls.isHidden() == (source == 'disabled')
        assert w.voice_page.audio_card.isHidden() == (source != 'remote')
    assert editor.microphone_setup.isHidden()
    w.shutdown()


@pytest.mark.skipif(sys.platform != 'darwin', reason='CoreAudio component activation is macOS-only')
def test_installed_microphone_pending_activation_has_completion_action(qtbot, tmp_path, monkeypatch):
    state = {'installed': False}
    monkeypatch.setattr(VirtualMic, 'installed', staticmethod(lambda: state['installed']))
    monkeypatch.setattr(AudioBridge, 'outputs', staticmethod(lambda: []))
    w = MainWindow(tmp_path, safe=True)
    qtbot.addWidget(w)
    c = w.controller
    c.update_voice(voice_source='remote')
    assert not w.voice_page.microphone_setup.isHidden()
    state['installed'] = True
    c._check_microphone_installation()
    assert not w.voice_page.microphone_setup.isHidden()
    assert w.voice_page.microphone_setup.text() == '完成设置'
    assert '已安装' in w.voice_page.microphone_status.text()
    assert '完成设置' in w.voice_page.microphone_detail.text()
    assert '前往安装' not in w.inspector.voice_editor.microphone_setup.text()
    seen = []
    c.message.connect(lambda text, error: seen.append(text))
    c.check_microphone()
    assert '已安装' in seen[-1]
    device = SimpleNamespace(description=lambda: '10RemoteHub Microphone', id=lambda: b'virtual')
    from remotehub.branding import BRAND
    device.description = lambda: BRAND['microphone_name']
    monkeypatch.setattr(AudioBridge, 'outputs', staticmethod(lambda: [device]))
    c.refresh_outputs()
    assert c.microphone_view().title == '已就绪'
    assert w.voice_page.microphone_setup.isHidden()
    w.shutdown()
