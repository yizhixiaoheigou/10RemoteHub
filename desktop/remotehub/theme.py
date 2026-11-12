"""Design tokens and the Qt stylesheet built from them.

Light workbench: the black remote reads best on a soft neutral ground, like
product photography. Every colour used by widgets or the canvas comes from
TOKENS; nothing else in the UI should hard-code a hex value. The full UI
definition (layout, components, states) lives in desktop/DESIGN.md.
"""
import sys
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

TOKENS = {
    # surfaces
    "WINDOW": "#F2F3F7",       # workspace ground
    "SIDEBAR": "#E9EAEF",
    "PANEL": "#FFFFFF",        # cards
    "SUNKEN": "#F7F8FA",       # read-only fields, hovered rows
    "PRESSED": "#E4E6EC",
    "LINE": "#E1E3EA",         # hairlines inside cards
    "LINE_STRONG": "#D8DAE1",  # control borders, sidebar edge
    "LINE_HOVER": "#C6C9D2",
    # text
    "INK": "#1C1C1E",
    "MUTED": "#626268",
    "FAINT": "#A8A8AE",
    # the one accent: selection, assigned, primary action
    "ACCENT": "#0A84FF",
    "ACCENT_HOVER": "#005BB5",
    "ACCENT_DEEP": "#0066CC",
    "ACCENT_PRESSED": "#004C99",
    "ACCENT_SOFT": "#E6F1FF",
    "ACCENT_EDGE": "#B5D6FF",
    # status (always paired with text, never colour alone)
    "GOOD": "#1E7E34", "GOOD_SOFT": "#E4F5EA",
    "WARN": "#B25000", "WARN_SOFT": "#FDF0E0", "WARN_EDGE": "#F5D5A8",
    "BAD": "#D70015", "BAD_SOFT": "#FCE5E7",
}
globals().update(TOKENS)  # theme.ACCENT etc. for canvas painting

# Back-compat names used by key_survey and older code.
RAISED = TOKENS["WINDOW"]
BLUE = TOKENS["ACCENT"]

# Spacing scale (px) and radii; layouts should only use these.
SPACE = {"xs": 4, "s": 8, "m": 12, "l": 16, "xl": 24}
RADIUS = {"control": 7, "row": 8, "card": 14}

SIDEBAR_WIDTH = 220
INSPECTOR_WIDTH = 320

STYLE = """
QMainWindow, QDialog { background: @WINDOW@; }
QWidget { color: @INK@; font-size: 13px; }
QWidget#sidebar { background: @SIDEBAR@; border-right: 1px solid @LINE_STRONG@; }
QWidget#workspace, QWidget#page { background: @WINDOW@; }
QFrame#panel, QWidget#panel { background: @PANEL@; border: none; border-radius: 14px; }
QWidget#panel[settingsCard="true"] { border: 1px solid @LINE@; }
QWidget[settingsPage="true"] QLabel[role="caption"] { color: @MUTED@; font-size: 12px; letter-spacing: 0; }
QWidget[settingsPage="true"] QPushButton { min-height: 22px; }
QWidget[settingsPage="true"] QComboBox, QWidget[settingsPage="true"] QLineEdit,
QWidget[settingsPage="true"] QDoubleSpinBox { min-height: 24px; background: @SUNKEN@; }
QFrame#deviceCard { background: @PANEL@; border: 1px solid @LINE@; border-radius: 12px; }
QFrame#rule { background: @LINE@; border: none; min-height: 1px; max-height: 1px; }
QWidget#canvasPanel { background: transparent; border: none; }

QLabel { background: transparent; border: none; }
QLabel[role="title"] { font-size: 24px; font-weight: 700; letter-spacing: -0.4px; }
QLabel[role="section"] { font-size: 13px; font-weight: 600; letter-spacing: 0.2px; }
QLabel[role="heading"] { font-size: 17px; font-weight: 700; }
QLabel[role="muted"] { color: @MUTED@; }
QLabel[role="caption"] { color: @MUTED@; font-size: 12px; letter-spacing: 0; }
QLabel[role="value"] { color: @INK@; font-weight: 600; }
QLabel#brand { font-size: 15px; font-weight: 700; }
QLabel#brandSub { color: @MUTED@; font-size: 11px; }
QLabel#stepNumber { background: @ACCENT_SOFT@; color: @ACCENT_DEEP@; border-radius: 11px; font-weight: 700; font-size: 12px; min-width: 22px; max-width: 22px; min-height: 22px; max-height: 22px; }
QLabel#pill { background: @SUNKEN@; color: @MUTED@; border-radius: 10px; padding: 4px 10px; font-size: 12px; font-weight: 500; }
QLabel#pill[tone="ready"] { background: @ACCENT_SOFT@; color: @ACCENT_DEEP@; }
QLabel#pill[tone="busy"] { background: @WARN_SOFT@; color: @WARN@; }
QLabel#pill[tone="ok"] { background: @GOOD_SOFT@; color: @GOOD@; }
QLabel#pill[tone="error"] { background: @BAD_SOFT@; color: @BAD@; }
QLabel#feedback { color: @MUTED@; padding: 6px 2px; font-size: 12px; }
QLabel#feedback[error="true"] { color: @BAD@; }
QLabel#banner { background: @WARN_SOFT@; color: @WARN@; border: 1px solid @WARN_EDGE@; border-radius: 8px; padding: 7px 12px; font-weight: 600; }
QLabel#inlineError { color: @BAD@; font-size: 12px; }

QPushButton { background: @PANEL@; border: 1px solid @LINE_STRONG@; border-radius: 7px; padding: 6px 12px; min-height: 18px; color: @INK@; }
QPushButton:hover { background: @WINDOW@; border-color: @LINE_HOVER@; }
QPushButton:pressed { background: @PRESSED@; }
QPushButton:focus { border: 2px solid @ACCENT@; padding: 5px 11px; }
QPushButton:disabled { color: @FAINT@; background: @WINDOW@; border-color: @PRESSED@; }
QPushButton[role="primary"] { background: @ACCENT_DEEP@; color: white; border-color: @ACCENT_DEEP@; font-weight: 600; }
QPushButton[role="primary"]:hover { background: @ACCENT_HOVER@; border-color: @ACCENT_HOVER@; }
QPushButton[role="primary"]:pressed { background: @ACCENT_PRESSED@; }
QPushButton[role="primary"]:disabled { background: @ACCENT_EDGE@; color: white; border-color: @ACCENT_EDGE@; }
QPushButton[role="quiet"] { background: transparent; border-color: transparent; color: @MUTED@; }
QPushButton[role="quiet"]:hover { color: @INK@; background: @PANEL@; border-color: @LINE@; }
QPushButton[role="quiet"]:pressed { background: @PRESSED@; }
QPushButton[role="quiet"]:disabled { color: @FAINT@; background: transparent; border-color: transparent; }
QPushButton[role="link"] { background: transparent; border: none; color: @ACCENT_DEEP@; padding: 2px 0; min-height: 0; text-align: left; }
QPushButton[role="link"]:hover { color: @ACCENT_PRESSED@; text-decoration: underline; }
QPushButton[role="link"]:focus { border: none; text-decoration: underline; }
QPushButton[role="danger"] { color: @BAD@; background: transparent; border-color: transparent; }
QPushButton[role="danger"]:hover { background: @BAD_SOFT@; }
QPushButton[role="danger"]:disabled { color: @FAINT@; background: transparent; }
QPushButton[role="pending"] { background: @WARN_SOFT@; color: @WARN@; border-color: @WARN_EDGE@; font-weight: 600; }
QPushButton[role="nav"] { text-align: left; background: transparent; border: none; padding: 7px 10px; font-size: 13px; border-radius: 6px; }
QPushButton[role="nav"]:hover { background: @PANEL@; }
QPushButton[role="nav"]:checked { background: @PANEL@; color: @ACCENT_DEEP@; font-weight: 600; }
QPushButton[role="nav"]:focus { border: 2px solid @ACCENT@; padding: 5px 8px; }
QPushButton[role="kind"] { text-align: left; background: transparent; border: 1px solid transparent; border-radius: 7px; padding: 4px 9px; min-height: 16px; }
QPushButton[role="kind"]:hover { background: @SUNKEN@; border-color: @LINE@; }
QPushButton[role="kind"]:checked { background: @ACCENT_SOFT@; border-color: @ACCENT_EDGE@; color: @ACCENT_DEEP@; font-weight: 600; }
QPushButton[role="kind"]:focus { border: 2px solid @ACCENT@; padding: 3px 8px; }
QPushButton[role="kind"]:disabled { color: @FAINT@; background: transparent; border-color: transparent; }
QPushButton[role="disclosure"] { text-align: left; background: transparent; border: none; color: @MUTED@; padding: 4px 0; min-height: 0; font-weight: 600; }
QPushButton[role="disclosure"]:hover { color: @INK@; }
QPushButton[role="disclosure"]:focus { border: none; color: @ACCENT@; }

QPushButton[role="callout"] { text-align: left; border: 1px solid @LINE_STRONG@; border-radius: 6px; padding: 3px 8px; min-height: 0; font-size: 11px; background: @PANEL@; color: @MUTED@; }
QPushButton[role="callout"]:hover { border-color: @LINE_HOVER@; color: @INK@; }
QPushButton[role="callout"][state="assigned"] { color: @INK@; border-color: @ACCENT_EDGE@; background: @ACCENT_SOFT@; }
QPushButton[role="callout"][state="blocked"], QPushButton[role="callout"]:disabled { color: @FAINT@; background: @SUNKEN@; border: 1px dashed @LINE_STRONG@; }
QPushButton[role="callout"]:checked { background: @ACCENT@; border-color: @ACCENT@; color: white; font-weight: 600; }
QPushButton[role="callout"]:focus { border: 2px solid @ACCENT@; padding: 2px 7px; }

QComboBox, QLineEdit, QPlainTextEdit, QKeySequenceEdit, QSpinBox, QDoubleSpinBox { background: @PANEL@; border: 1px solid @LINE_STRONG@; border-radius: 6px; padding: 5px 9px; min-height: 20px; color: @INK@; selection-background-color: @ACCENT@; selection-color: white; }
QComboBox, QWidget[settingsPage="true"] QComboBox { min-height: 28px; padding-right: 28px; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox::down-arrow { image: url("@ASSETS@/chevron-down.svg"); width: 14px; height: 14px; }
QSpinBox::up-button, QDoubleSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right; width: 20px; border: none; }
QSpinBox::down-button, QDoubleSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right; width: 20px; border: none; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image: url("@ASSETS@/chevron-up.svg"); width: 11px; height: 11px; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image: url("@ASSETS@/chevron-down.svg"); width: 11px; height: 11px; }
QComboBox:focus, QLineEdit:focus, QPlainTextEdit:focus, QKeySequenceEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus { border: 2px solid @ACCENT@; padding: 4px 8px; }
QComboBox QAbstractItemView { background: @PANEL@; border: 1px solid @LINE_STRONG@; selection-background-color: @ACCENT_SOFT@; selection-color: @ACCENT_DEEP@; padding: 4px; color: @INK@; outline: 0; }
QListView#comboPopup::item { min-height: 28px; padding: 4px 10px; border: none; border-radius: 5px; background: @PANEL@; color: @INK@; }
QListView#comboPopup::item:hover { background: @SUNKEN@; color: @INK@; }
QListView#comboPopup::item:selected { background: @ACCENT_SOFT@; color: @ACCENT_DEEP@; }
QListView#comboPopup::item:disabled { color: @MUTED@; background: @SUNKEN@; }
QLineEdit:read-only { background: @SUNKEN@; color: @MUTED@; }
QLineEdit:disabled, QComboBox:disabled, QDoubleSpinBox:disabled { color: @FAINT@; background: @SUNKEN@; }
QLineEdit[invalid="true"], QPlainTextEdit[invalid="true"] { border: 2px solid @BAD@; padding: 4px 8px; }

QCheckBox { spacing: 8px; min-height: 22px; }
QCheckBox::indicator { width: 15px; height: 15px; border: 1px solid @LINE_HOVER@; border-radius: 4px; background: @PANEL@; }
QCheckBox::indicator:checked { background: @ACCENT@; border-color: @ACCENT@; image: url("@ASSETS@/check.svg"); }
QCheckBox::indicator:focus { border: 2px solid @ACCENT@; }
QCheckBox:disabled { color: @FAINT@; }
QCheckBox::indicator:disabled { background: @SUNKEN@; border-color: @PRESSED@; }

QScrollArea { background: transparent; border: none; }
QScrollBar:vertical { background: transparent; width: 9px; margin: 2px; }
QScrollBar::handle:vertical { background: @LINE_HOVER@; border-radius: 4px; min-height: 28px; }
QScrollBar::handle:vertical:hover { background: @FAINT@; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal { background: transparent; height: 9px; margin: 2px; }
QScrollBar::handle:horizontal { background: @LINE_HOVER@; border-radius: 4px; min-width: 28px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QProgressBar { border: none; border-radius: 4px; background: @PRESSED@; min-height: 8px; max-height: 8px; }
QProgressBar::chunk { background: @ACCENT@; border-radius: 4px; }
QProgressBar#audioLevel { min-height: 12px; max-height: 12px; border: 1px solid @LINE_STRONG@; border-radius: 6px; }
QProgressBar#audioLevel::chunk { background: @ACCENT@; border-radius: 5px; }
QToolTip { background: @INK@; color: white; padding: 6px 8px; border: none; }
QMenu { background: @PANEL@; border: 1px solid @LINE@; padding: 5px; border-radius: 8px; }
QMenu::item { padding: 6px 20px; border-radius: 4px; }
QMenu::item:selected { background: @ACCENT@; color: white; }
QStackedWidget, QTabWidget::pane { border: none; background: transparent; }
"""


def stylesheet():
    text = STYLE.replace("@ASSETS@", (Path(__file__).parent / "assets").as_posix())
    # Longest names first so @ACCENT@ never eats part of @ACCENT_SOFT@.
    for name in sorted(TOKENS, key=len, reverse=True):
        text = text.replace("@" + name + "@", TOKENS[name])
    return text


def qcolor(name, alpha=None):
    color = QColor(TOKENS[name])
    if alpha is not None:
        color.setAlpha(alpha)
    return color


def repolish(widget):
    """Re-apply QSS after a dynamic property (role/state/tone) changed."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def apply_theme(window):
    app = QApplication.instance()
    if sys.platform == "darwin":
        # The UI is light-only. In macOS Dark Mode native-drawn parts (popup
        # frames, menu rows) would otherwise use dark-appearance text colours.
        # Other platforms keep the OS scheme: their tray icon depends on it.
        app.styleHints().setColorScheme(Qt.ColorScheme.Light)
    palette = QPalette()
    for role, name in (
        (QPalette.ColorRole.Window, "WINDOW"),
        (QPalette.ColorRole.Base, "PANEL"),
        (QPalette.ColorRole.AlternateBase, "WINDOW"),
        (QPalette.ColorRole.WindowText, "INK"),
        (QPalette.ColorRole.Text, "INK"),
        (QPalette.ColorRole.Button, "PANEL"),
        (QPalette.ColorRole.ButtonText, "INK"),
        (QPalette.ColorRole.Highlight, "ACCENT"),
        (QPalette.ColorRole.PlaceholderText, "FAINT"),
        (QPalette.ColorRole.ToolTipBase, "INK"),
    ):
        palette.setColor(role, qcolor(name))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, qcolor("FAINT"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, qcolor("FAINT"))
    app.setPalette(palette)
    font = QFont()
    font.setFamilies(
        [".AppleSystemUIFont", "PingFang SC"] if sys.platform == "darwin"
        else ["Segoe UI", "Microsoft YaHei"] if sys.platform == "win32"
        else ["Noto Sans", "Noto Sans CJK SC", "DejaVu Sans"]
    )
    font.setPointSize(10)
    app.setFont(font)
    window.setStyleSheet(stylesheet())
