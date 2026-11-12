import sys
import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QInputMethodEvent, QKeyEvent
from PySide6.QtWidgets import QApplication
from remotehub.ui.widgets import VoiceKeyRecorder
from remotehub.ui import MainWindow


@pytest.mark.parametrize('keys,expected', [
    ([Qt.Key.Key_Alt], ['alt']),
    ([Qt.Key.Key_B], ['b']),
    ([Qt.Key.Key_Control, Qt.Key.Key_Space], ['cmd' if sys.platform == 'darwin' else 'ctrl', 'space']),
    ([Qt.Key.Key_Shift, Qt.Key.Key_F5], ['shift', 'f5']),
    ([Qt.Key.Key_Tab], ['tab']),
])
def test_records_physical_chord_on_release(qtbot, keys, expected):
    recorder = VoiceKeyRecorder()
    qtbot.addWidget(recorder)
    recorder.show()
    seen = []
    recorder.recorded.connect(seen.append)
    recorder.click()
    for key in keys:
        qtbot.keyPress(recorder, key)
    assert seen == []
    for key in reversed(keys):
        qtbot.keyRelease(recorder, key)
    assert seen == [expected] and recorder.keys == expected
    assert not recorder.recording


def test_does_not_accept_chinese_or_ime_commit(qtbot):
    recorder = VoiceKeyRecorder()
    qtbot.addWidget(recorder)
    recorder.set_keys(['alt'])
    seen = []
    recorder.recorded.connect(seen.append)
    recorder.click()
    event = QInputMethodEvent()
    event.setCommitString('中文ALT')
    QApplication.sendEvent(recorder, event)
    for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
        QApplication.sendEvent(recorder, QKeyEvent(kind, Qt.Key.Key_unknown, Qt.KeyboardModifier.NoModifier, '中'))
    assert seen == [] and recorder.keys == ['alt']


def test_cancel_recording_keeps_saved_key(qtbot):
    recorder = VoiceKeyRecorder()
    qtbot.addWidget(recorder)
    recorder.set_keys(['alt'])
    seen = []
    recorder.recorded.connect(seen.append)
    recorder.click()
    qtbot.keyPress(recorder, Qt.Key.Key_Shift)
    recorder.click()
    qtbot.keyRelease(recorder, Qt.Key.Key_Shift)
    assert not seen and recorder.keys == ['alt']


def test_recorded_voice_key_syncs_both_pages_and_persists(qtbot, tmp_path):
    w = MainWindow(tmp_path, safe=True)
    qtbot.addWidget(w)
    w.controller.update_voice(voice_source='trigger')
    recorder = w.voice_page.shortcut
    recorder.click()
    qtbot.keyClick(recorder, Qt.Key.Key_B)
    assert w.controller.voice_settings()['voice_keys'] == 'b'
    assert w.inspector.voice_editor.shortcut.keys == ['b']
    w.shutdown()
    other = MainWindow(tmp_path, safe=True)
    qtbot.addWidget(other)
    assert other.voice_page.shortcut.keys == ['b']
    other.shutdown()
