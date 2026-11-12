import pytest
from remotehub.store import validate_settings
from remotehub.ui import MainWindow
from remotehub.session import VoiceSession
from test_ui import FakeAudio, FakeKeys
from test_default_input_route import Route


@pytest.mark.parametrize('value', ['unknown', True, None])
def test_invalid_routing_is_rejected(value):
    with pytest.raises(ValueError):
        validate_settings({'input_routing': value})


def test_fixed_mode_does_not_touch_system_default(qapp):
    audio, keys, route = FakeAudio(), FakeKeys(), Route()
    voice = VoiceSession(audio, keys, route=route)
    voice.switch_input = False
    voice.start('usb'); voice.feed('usb', b'\0\0'); voice.finish('usb')
    audio.ended.emit()
    assert not route.events and keys.events == ['down', 'up'] and voice.owner is None


def test_settings_persist_and_runtime_follows_choice(qtbot, tmp_path):
    w = MainWindow(tmp_path, safe=True); qtbot.addWidget(w)
    c = w.controller
    assert c.update_voice(input_routing='fixed')
    assert not c.voice.switch_input
    w.shutdown()
    other = MainWindow(tmp_path, safe=True); qtbot.addWidget(other)
    assert other.controller.voice_settings()['input_routing'] == 'fixed'
    assert not other.controller.voice.switch_input
    assert other.controller.update_voice(input_routing='automatic')
    assert other.controller.voice.switch_input
    other.shutdown()


def test_mac_mode_control_context_hints_and_save_failure(qtbot, tmp_path, monkeypatch):
    import remotehub.ui.voice as ui
    monkeypatch.setattr(ui.sys, 'platform', 'darwin')
    w = MainWindow(tmp_path, safe=True); qtbot.addWidget(w)
    c, page = w.controller, w.voice_page
    monkeypatch.setattr(c, 'ensure_remote_audio', lambda: None)
    assert page.input_routing.isHidden()
    c.update_voice(voice_source='remote')
    assert not page.input_routing.isHidden()
    assert '系统默认' in page.routing_hint.text() and '不要固定选择' in page.routing_hint.text()
    fixed = page.input_routing.findData('fixed')
    page.input_routing.setCurrentIndex(fixed); page.input_routing.activated.emit(fixed)
    assert c.voice_settings()['input_routing'] == 'fixed' and not c.voice.switch_input
    assert '固定选择' in page.routing_hint.text() and '结束时停止' in page.routing_hint.text()
    c.voice.output_id = b'virtual'; c.voice_changed.emit()
    assert '固定选择' in w.inspector.voice_editor.route.text()
    assert '系统默认' not in c.microphone_view().detail
    c.voice.owner = 'usb'; c.voice_changed.emit()
    assert not page.input_routing.isEnabled()
    assert not c.update_voice(input_routing='automatic')
    c.voice.owner = None
    monkeypatch.setattr(c, 'save', lambda: False)
    assert not c.update_voice(input_routing='automatic')
    assert page.input_routing.currentData() == 'fixed' and not c.voice.switch_input
    monkeypatch.undo()
    c.settings['voice_source'] = 'trigger'; c.voice_changed.emit()
    assert page.input_routing.isHidden() and page.routing_hint.isHidden()
    w.shutdown()


def test_unsupported_platform_keeps_the_switch_hidden(qtbot, tmp_path, monkeypatch):
    w = MainWindow(tmp_path, safe=True); qtbot.addWidget(w)
    import remotehub.ui.voice as ui
    monkeypatch.setattr(ui.sys, 'platform', 'linux')
    c = w.controller
    c.settings.update(voice_source='remote', input_routing='automatic')
    c.voice_changed.emit()
    assert w.voice_page.input_routing.isHidden()
    assert '固定选择' in w.voice_page.routing_hint.text()
    w.shutdown()


def test_windows_offers_the_temporary_switch(qtbot, tmp_path, monkeypatch):
    """Windows now switches the default microphone like macOS does."""
    w = MainWindow(tmp_path, safe=True); qtbot.addWidget(w)
    import remotehub.ui.voice as ui
    monkeypatch.setattr(ui.sys, 'platform', 'win32')
    c = w.controller
    c.settings.update(voice_source='remote', input_routing='automatic')
    c.voice_changed.emit()
    assert not w.voice_page.input_routing.isHidden()
    assert 'CABLE Output' in w.voice_page.routing_hint.text()
    w.shutdown()
