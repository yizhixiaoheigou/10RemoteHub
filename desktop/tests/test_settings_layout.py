"""Settings use the workspace; tests simulate audio without USB or playback."""
import sys
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QLabel, QWidget
from remotehub.ui import MainWindow


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS virtual-microphone install link")
def test_voice_key_missing_microphone_has_direct_setup_link(qtbot, tmp_path, monkeypatch):
    from remotehub.virtual_mic import VirtualMic
    monkeypatch.setattr(VirtualMic, 'installed', staticmethod(lambda: False))
    w = MainWindow(tmp_path, safe=True)
    qtbot.addWidget(w)
    c = w.controller
    monkeypatch.setattr(c, 'ensure_remote_audio', lambda: None)
    monkeypatch.setattr(c, 'setup_virtual_mic', lambda: pytest.fail('Navigation must not install'))
    c.select('tv-voice')
    c.voice.output_id = b''
    c.settings['voice_source'] = 'remote'
    c.voice_changed.emit()
    editor = w.inspector.voice_editor
    assert not editor.microphone_setup.isHidden()
    assert '虚拟麦克风' in editor.route.text() and '尚未' in editor.route.text()
    w.resize(1200, 720)
    w.show()
    editor.microphone_setup.click()
    qtbot.wait(50)
    assert w.stack.currentIndex() == 1
    area = w.stack.currentWidget()
    install = w.voice_page.microphone_setup
    assert area.viewport().rect().contains(install.mapTo(area.viewport(), install.rect().center()))
    c.voice.output_id = b'remotehub-device'
    c.voice_changed.emit()
    assert editor.microphone_setup.isHidden()
    c.voice.output_id = b''
    c.settings['voice_source'] = 'trigger'
    c.voice_changed.emit()
    assert editor.microphone_setup.isHidden()
    assert '不需要虚拟麦克风' in editor.route.text()
    w.shutdown()


def test_all_audio_controls_belong_to_voice_settings(qtbot, tmp_path):
    w = MainWindow(tmp_path, safe=True)
    qtbot.addWidget(w)
    for name in ('source', 'record_mode', 'shortcut', 'mode', 'gain',
                 'microphone_setup', 'microphone_detail', 'usb_start', 'meter', 'wav_test', 'stop'):
        control = getattr(w.voice_page, name)
        assert w.voice_page.isAncestorOf(control)
        assert not w.general.isAncestorOf(control)
    assert not hasattr(w.general, 'audio_card')
    assert w.general.isAncestorOf(w.general.start_at_login)
    assert w.general.isAncestorOf(w.general.connection_status)
    w.controller.select('tv-voice')
    w.inspector.voice_settings_requested.emit()
    assert w.stack.currentIndex() == 1
    w.shutdown()


@pytest.mark.parametrize('width', [1200, 1440])
@pytest.mark.parametrize('page_index', [1, 2])
def test_settings_cards_fill_viewport_and_fields_align_left(qtbot, tmp_path, width, page_index):
    w = MainWindow(tmp_path, safe=True)
    qtbot.addWidget(w)
    w.controller.settings["voice_source"] = "remote"
    w.controller.voice_changed.emit()
    w.resize(width, 840)
    w.show_page(page_index)
    w.show()
    qtbot.wait(30)
    page = w.pages[page_index]
    area = w.stack.currentWidget()
    cards = [c for c in page.findChildren(QWidget) if c.objectName() == 'panel' and not c.isHidden()]
    assert cards
    for card in cards:
        assert card.width() >= area.viewport().width() - 12
        for text in card.findChildren(QLabel):
            if text.isVisible() and text.hasHeightForWidth():
                assert text.height() >= text.heightForWidth(text.width()), text.text()
    assert area.horizontalScrollBar().maximum() == 0
    if page_index == 1:
        for field in (page.source, page.record_mode, page.shortcut, page.mode, page.gain):
            assert field.mapTo(page, QPoint(0, 0)).x() < 160
        assert page.source.width() > 500
        for button in (page.microphone_setup, page.usb_stop):
            assert button.property('role') != 'quiet'
        assert not page.microphone_status.wordWrap()
        assert page.meter.width() > 450
    w.shutdown()


def test_level_explains_missing_setup_and_updates_only_from_audio(qtbot, tmp_path):
    w = MainWindow(tmp_path, safe=True)
    qtbot.addWidget(w)
    c, page = w.controller, w.voice_page
    c.voice.output_id = b''
    page.refresh()
    assert '虚拟麦克风' in page.meter_hint.text()
    assert not page.wav_test.isEnabled()
    assert page.meter_value.text() == '0%'
    c.voice.output_id = b'virtual'
    c.usb.ready = False
    page.refresh()
    assert page.wav_test.isEnabled() and '连接' in page.meter_hint.text()
    c.usb.ready = True
    page.refresh()
    assert '语音键' in page.meter_hint.text()
    c.level.emit(0.1)
    assert page.meter.value() == 50 and page.meter_value.text() == '50%'
    assert page.meter.focusPolicy() == Qt.FocusPolicy.NoFocus
    c.voice.owner = 'wav'
    page.refresh()
    assert page.stop.isEnabled() and not page.wav_test.isEnabled()
    c.voice.owner = None
    page.refresh()
    assert page.meter.value() == 0 and page.meter_value.text() == '0%'
    c.usb.ready = False
    w.shutdown()


def test_voice_flow_summary_and_gain_follow_remote_audio(qtbot, tmp_path):
    w = MainWindow(tmp_path, safe=True)
    qtbot.addWidget(w)
    c, page = w.controller, w.voice_page
    assert c.update_voice(voice_source='remote', record_mode='hold', voice_mode='hold', voice_keys='alt')
    assert page.audio_card.isAncestorOf(page.gain)
    assert not page.recognition_card.isAncestorOf(page.gain)
    assert '按住遥控器语音键' in page.flow_summary.text()
    assert '电脑按住' in page.flow_summary.text()
    assert '松开遥控器后结束' in page.flow_summary.text()
    assert '仅触发识别' in page.source.itemText(page.source.findData('trigger'))
    w.shutdown()
