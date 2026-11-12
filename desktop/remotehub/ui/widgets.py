"""Small shared widgets and the key-recording conversions."""
from __future__ import annotations

import sys

from PySide6.QtCore import QEvent, QKeyCombination, Qt, Signal
from PySide6.QtGui import QKeySequence, QPalette
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFrame, QHBoxLayout, QKeySequenceEdit, QLabel, QLineEdit, QPushButton, QScrollArea, QWidget,
    QListView, QStyledItemDelegate, QStyleOptionViewItem,
)

from ..theme import repolish, qcolor
from ..model import MODIFIERS, validate_keys
from ..presentation import key_label


class ScrollSafeDoubleSpinBox(QDoubleSpinBox):
    """Use buttons/typing to edit; leave wheel gestures to the page."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event):
        event.ignore()


class ComboItemDelegate(QStyledItemDelegate):
    """Use item-view painting, not the platform's native combo menu delegate."""
    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(max(36, option.fontMetrics.height() + 16, size.height()))
        return size

    def paint(self, painter, option, index):
        option = QStyleOptionViewItem(option)
        # Popup windows can be inactive while the combo's owner retains focus.
        # Define both groups rather than inherit native dark-menu text colours.
        for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
            option.palette.setColor(group, QPalette.ColorRole.Text, qcolor('INK'))
            option.palette.setColor(group, QPalette.ColorRole.HighlightedText, qcolor('ACCENT_DEEP'))
            option.palette.setColor(group, QPalette.ColorRole.Highlight, qcolor('ACCENT_SOFT'))
            option.palette.setColor(group, QPalette.ColorRole.Base, qcolor('PANEL'))
        option.palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, qcolor('MUTED'))
        super().paint(painter, option, index)


class ScrollSafeComboBox(QComboBox):
    """Readable, roomy popup shared by every selector; closed wheel is ignored."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumHeight(40)
        view = QListView(self)
        view.setObjectName('comboPopup')
        view.setUniformItemSizes(True)
        view.setSpacing(2)
        view.setMouseTracking(True)
        self.setView(view)
        self.setItemDelegate(ComboItemDelegate(view))
        self.setMaxVisibleItems(10)

    def showPopup(self):
        self.view().setMinimumWidth(self.width())
        super().showPopup()

    def wheelEvent(self, event):
        if self.view().isVisible():
            super().wheelEvent(event)
        else:
            event.ignore()


class VoiceKeyRecorder(QPushButton):
    """Record one physical chord, including a modifier alone; never accept text."""
    recorded = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.keys = []
        self.recording = False
        self.down = set()
        self.chord = []
        self.setCheckable(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, False)
        self.setAccessibleName("录制语音唤起键")
        self.setToolTip("点击后按下单键或组合键，松开保存；点其他位置取消。")
        self.clicked.connect(self._clicked)
        self.set_keys([])

    def set_keys(self, keys):
        self.keys = list(keys)
        if not self.recording:
            title = key_label(self.keys)
            if sys.platform == 'darwin' and len(self.keys) == 1:
                title = {'alt': '⌥ Option', 'ctrl': '⌃ Control', 'cmd': '⌘ Command',
                         'shift': '⇧ Shift'}.get(self.keys[0], title)
            self.setText(f"{title} · 点击录制" if self.keys else "点击录制按键")

    def _clicked(self):
        if self.recording:
            self._cancel()
            return
        self.recording = True
        self.down.clear()
        self.chord = []
        self.setChecked(True)
        self.setText("请按下按键，松开保存…")
        self.setFocus(Qt.FocusReason.MouseFocusReason)

    def _cancel(self):
        self.recording = False
        self.down.clear()
        self.chord = []
        self.setChecked(False)
        self.set_keys(self.keys)

    def event(self, event):
        if self.recording and event.type() == QEvent.Type.ShortcutOverride:
            event.accept()
            return True
        return super().event(event)

    def focusNextPrevChild(self, next):
        return False if self.recording else super().focusNextPrevChild(next)

    def focusOutEvent(self, event):
        self._cancel()
        super().focusOutEvent(event)

    def keyPressEvent(self, event):
        if not self.recording:
            return super().keyPressEvent(event)
        event.accept()
        if event.isAutoRepeat():
            return
        self.down.add(event.key())
        modifier_keys = {Qt.Key.Key_Control: 'cmd' if sys.platform == 'darwin' else 'ctrl',
                         Qt.Key.Key_Meta: 'ctrl' if sys.platform == 'darwin' else 'cmd',
                         Qt.Key.Key_Alt: 'alt', Qt.Key.Key_Shift: 'shift'}
        names = [name for flag, name in _modifier_names(sys.platform) if event.modifiers() & flag]
        if event.key() in modifier_keys:
            names.append(modifier_keys[event.key()])
        else:
            names += sequence_keys(QKeySequence(event.key()))
        for key in names:
            if key not in self.chord:
                self.chord.append(key)
        self.setText(key_label(self.chord) or "不支持此按键，请重新录制")

    def keyReleaseEvent(self, event):
        if not self.recording:
            return super().keyReleaseEvent(event)
        event.accept()
        if event.isAutoRepeat():
            return
        self.down.discard(event.key())
        if self.down:
            return
        keys = [k for k in MODIFIERS if k in self.chord] + [k for k in self.chord if k not in MODIFIERS]
        self._cancel()
        try:
            validate_keys(keys, allow_modifier=True, platform=sys.platform)
        except ValueError:
            self.setText("不支持此按键，请重新录制")
            return
        self.set_keys(keys)
        self.recorded.emit(keys)


def label(text="", role=None, *, wrap=True):
    widget = QLabel(text)
    widget.setWordWrap(wrap)
    if role:
        widget.setProperty("role", role)
    return widget


def button(text, callback=None, role=None):
    widget = QPushButton(text)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    if role:
        widget.setProperty("role", role)
    if callback is not None:
        widget.clicked.connect(lambda checked=False: callback())
    return widget


def rule():
    line = QFrame()
    line.setObjectName("rule")
    return line


def row(*widgets, spacing=8, stretch_last=False):
    """Horizontal strip of widgets; ints are spacings, None is a stretch.
    Input fields take the spare width; buttons keep their natural size."""
    holder = QWidget()
    box = QHBoxLayout(holder)
    box.setContentsMargins(0, 0, 0, 0)
    box.setSpacing(spacing)
    for widget in widgets:
        if widget is None:
            box.addStretch(1)
        elif isinstance(widget, int):
            box.addSpacing(widget)
        else:
            grow = isinstance(widget, (QLineEdit, QComboBox, QKeySequenceEdit))
            box.addWidget(widget, 1 if grow else 0)
    if stretch_last:
        box.addStretch(1)
    return holder


def hbox(*widgets, spacing=6):
    """Like row() but returns a layout: QFormLayout sizes nested layouts
    correctly, while a wrapper widget there can end up shorter than its
    fields once the stylesheet adds padding."""
    box = QHBoxLayout()
    box.setContentsMargins(0, 0, 0, 0)
    box.setSpacing(spacing)
    for widget in widgets:
        grow = isinstance(widget, (QLineEdit, QComboBox, QKeySequenceEdit))
        box.addWidget(widget, 1 if grow else 0)
    return box


def scroll(widget, *, horizontal=False):
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    if not horizontal:
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setWidget(widget)
    return area


class Pill(QLabel):
    """Status text with a tone: neutral | ready | busy | ok | error."""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setObjectName("pill")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)

    def show_status(self, view):
        self.setText(view.title)
        self.setToolTip(view.detail)
        if self.property("tone") != view.tone:
            self.setProperty("tone", view.tone)
            repolish(self)


def set_role(widget, role):
    if widget.property("role") != role:
        widget.setProperty("role", role)
        repolish(widget)


def set_invalid(widget, invalid):
    if bool(widget.property("invalid")) != invalid:
        widget.setProperty("invalid", invalid)
        repolish(widget)


# -- key recording ---------------------------------------------------------
#
# Qt on macOS reports the Command key as ControlModifier and the Control key
# as MetaModifier (unless AA_MacDontSwapCtrlAndMeta is set). Our stored names
# are physical: "cmd" is ⌘/Win/Super, "ctrl" is the Control key. Without this
# mapping, recording ⌘C on a Mac would save ctrl+c and send Control-C.

_KEY_ALIASES = {"return": "enter", "escape": "esc", "pgup": "pageup", "pgdown": "pagedown",
                "del": "delete", "ins": "insert"}
_QT_NAMES = {"enter": "Return", "esc": "Esc", "pageup": "PgUp", "pagedown": "PgDown",
             "delete": "Del", "insert": "Ins", "backspace": "Backspace", "space": "Space",
             "tab": "Tab", "home": "Home", "end": "End", "up": "Up", "down": "Down",
             "left": "Left", "right": "Right"}


def _modifier_names(platform):
    if platform == "darwin":
        return (Qt.KeyboardModifier.ControlModifier, "cmd"), (Qt.KeyboardModifier.MetaModifier, "ctrl"), \
               (Qt.KeyboardModifier.AltModifier, "alt"), (Qt.KeyboardModifier.ShiftModifier, "shift")
    return (Qt.KeyboardModifier.ControlModifier, "ctrl"), (Qt.KeyboardModifier.MetaModifier, "cmd"), \
           (Qt.KeyboardModifier.AltModifier, "alt"), (Qt.KeyboardModifier.ShiftModifier, "shift")


def sequence_keys(sequence: QKeySequence, platform=sys.platform):
    """First chord of a recorded QKeySequence -> stored key names."""
    if sequence.isEmpty():
        return []
    combo = sequence[0]
    mods = combo.keyboardModifiers()
    keys = [name for flag, name in _modifier_names(platform) if mods & flag]
    main = QKeySequence(combo.key()).toString(QKeySequence.SequenceFormat.PortableText).lower()
    if main:
        keys.append(_KEY_ALIASES.get(main, main))
    return keys


def keys_sequence(keys, platform=sys.platform) -> QKeySequence:
    """Stored key names -> QKeySequence for showing in the recorder."""
    mods = Qt.KeyboardModifier.NoModifier
    lookup = {name: flag for flag, name in _modifier_names(platform)}
    main = ""
    for key in keys:
        if key in lookup:
            mods |= lookup[key]
        else:
            main = _QT_NAMES.get(key, key.upper() if len(key) == 1 else key.capitalize())
    if not main:
        return QKeySequence()
    parsed = QKeySequence(main)
    if parsed.isEmpty():
        return QKeySequence()
    return QKeySequence(QKeyCombination(mods, parsed[0].key()))
