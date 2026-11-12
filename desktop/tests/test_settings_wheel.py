"""Scroll gestures must not silently change persisted settings."""
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from remotehub.ui import MainWindow


def wheel(control, delta=-120):
    center = control.rect().center()
    event = QWheelEvent(QPointF(center), QPointF(control.mapToGlobal(center)),
                        QPoint(), QPoint(0, delta), Qt.MouseButton.NoButton,
                        Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(control, event)
    return event


def test_gain_wheel_never_changes_value_or_saves_even_after_focus(qtbot, tmp_path):
    w = MainWindow(tmp_path, safe=True)
    qtbot.addWidget(w)
    c, page = w.controller, w.voice_page
    c.update_voice(voice_source='remote')
    w.show_page(1)
    w.show()
    gain = page.gain
    initial = gain.value()
    gain.clearFocus()
    for focused in (False, True):
        if focused:
            gain.setFocus()
        for delta in (-120, 120):
            event = wheel(gain, delta)
            assert gain.value() == initial
            assert not event.isAccepted()  # available to the enclosing scroll area
            assert not page.gain_timer.isActive()
    assert c.voice_settings()['gain'] == initial
    gain.setFocus()
    qtbot.keyClick(gain, Qt.Key.Key_Up)
    assert gain.value() == initial + gain.singleStep()
    qtbot.waitUntil(lambda: c.voice_settings()['gain'] == gain.value())
    w.shutdown()


def test_closed_voice_dropdowns_ignore_wheel_but_keyboard_selection_works(qtbot, tmp_path):
    w = MainWindow(tmp_path, safe=True)
    qtbot.addWidget(w)
    w.controller.update_voice(voice_source='remote')
    w.show_page(1)
    w.show()
    for control in (w.voice_page.source, w.voice_page.record_mode, w.voice_page.mode,
                    w.inspector.voice_editor.source, w.inspector.voice_editor.record_mode):
        original = control.currentIndex()
        for delta in (120, -120):
            event = wheel(control, delta)
            assert control.currentIndex() == original
            assert not event.isAccepted()
    control = w.voice_page.record_mode
    control.setFocus()
    qtbot.keyClick(control, Qt.Key.Key_Down)
    assert control.currentIndex() == 1
    assert w.controller.voice_settings()['record_mode'] == control.currentData()
    w.shutdown()


def test_wheel_over_gain_scrolls_the_page(qtbot, tmp_path):
    w = MainWindow(tmp_path, safe=True)
    qtbot.addWidget(w)
    w.controller.update_voice(voice_source='remote')
    w.resize(1200, 720)
    w.show_page(1)
    w.show()
    qtbot.wait(30)
    area = w.stack.currentWidget()
    gain = w.voice_page.gain
    area.ensureWidgetVisible(gain)
    bar = area.verticalScrollBar()
    before = bar.value()
    assert before < bar.maximum()
    value = gain.value()
    pos = gain.mapTo(w, gain.rect().center())
    QTest.wheelEvent(w.windowHandle(), pos, QPoint(0, -120))
    qtbot.waitUntil(lambda: bar.value() > before)
    assert gain.value() == value and not w.voice_page.gain_timer.isActive()
    w.shutdown()
