"""Render actual popup rows, including the macOS style, without touching hardware."""
import os
import sys
import pytest
from PySide6.QtCore import Qt, QModelIndex
from PySide6.QtWidgets import QApplication, QStyleFactory, QWidget, QVBoxLayout
from remotehub.theme import apply_theme
from remotehub.ui.widgets import ScrollSafeComboBox


@pytest.fixture(params=['Fusion', 'macOS'])
def selector(qtbot, request):
    if request.param.lower() not in [key.lower() for key in QStyleFactory.keys()]:
        pytest.skip('Native style unavailable on this OS')
    old = QApplication.style().objectName()
    QApplication.setStyle(QStyleFactory.create(request.param))
    host = QWidget(); qtbot.addWidget(host); apply_theme(host)
    host.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    layout = QVBoxLayout(host)
    combo = ScrollSafeComboBox()
    combo.addItems(['未启用', '遥控器麦克风', '电脑麦克风'])
    layout.addWidget(combo)
    combo.view().window().setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    host.resize(440, 120); host.show()
    qtbot.wait(20)
    combo.showPopup(); qtbot.wait(20)
    yield combo
    combo.hidePopup(); host.close()
    QApplication.setStyle(QStyleFactory.create(old))


def test_popup_all_rows_are_readable_before_hover(selector, qtbot):
    view = selector.view()
    view.clearSelection(); view.setCurrentIndex(QModelIndex())
    qtbot.wait(10)
    pixmap = view.viewport().grab()
    image = pixmap.toImage()
    ratio = pixmap.devicePixelRatio()
    for row in range(selector.count()):
        rect = view.visualRect(selector.model().index(row, 0))
        assert rect.height() >= 36, (row, rect.height())
        # Normal rows must contain dark glyph pixels, even without selection or hover.
        area = rect.adjusted(8, 5, -8, -5)
        pixels = [image.pixelColor(x, y)
                  for y in range(int(area.top()*ratio), int(area.bottom()*ratio))
                  for x in range(int(area.left()*ratio), min(int((area.left()+180)*ratio), image.width()))]
        assert sum(c.red() < 100 and c.green() < 100 and c.blue() < 100 for c in pixels) > 15
    assert selector.height() >= 40
    assert view.window().width() >= selector.width()


def test_popup_click_and_keyboard_selection(selector, qtbot):
    view = selector.view()
    rect = view.visualRect(selector.model().index(2, 0))
    qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    assert selector.currentIndex() == 2
    selector.showPopup(); qtbot.wait(10)
    qtbot.keyClick(view, Qt.Key.Key_Up)
    qtbot.keyClick(view, Qt.Key.Key_Return)
    assert selector.currentIndex() == 1


def test_disabled_option_does_not_activate(selector, qtbot):
    selector.hidePopup()
    selector.setCurrentIndex(0)
    selector.model().item(1).setEnabled(False)
    selector.showPopup(); qtbot.wait(10)
    view = selector.view()
    qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton,
                    pos=view.visualRect(selector.model().index(1, 0)).center())
    assert selector.currentIndex() == 0


@pytest.mark.skipif(sys.platform != 'darwin' or os.environ.get('QT_QPA_PLATFORM') == 'offscreen',
                    reason='Mac forces the light-only theme; offscreen QPA does not track the scheme')
def test_mac_theme_ignores_system_dark_mode(qtbot):
    host = QWidget(); qtbot.addWidget(host); apply_theme(host)
    assert QApplication.styleHints().colorScheme() == Qt.ColorScheme.Light
