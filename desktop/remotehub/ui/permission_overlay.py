"""A companion drag panel anchored over the bottom of the real Settings window.

This is our own labelled window, not a reproduction or embedding of macOS UI.
The user still adds/enables the application in the real system permission list.
"""
from PySide6.QtCore import QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication, QDialog, QFrame, QGraphicsDropShadowEffect, QHBoxLayout,
    QLabel, QPushButton, QVBoxLayout,
)

from .. import permissions
from ..branding import APP_NAME
from ..theme import TOKENS, stylesheet
from .permission_app import ApplicationDragButton


def panel_geometry(window: QRect, screen: QRect, height: int) -> QRect:
    """Place inside the Settings content column; leave its bottom controls free."""
    visible = window.intersected(screen)
    sidebar = 200 if window.width() >= 700 else 176
    width = min(600, max(320, window.width() - sidebar - 24), visible.width() - 16)
    height = min(height, visible.height() - 32)
    left = window.right() - width - 12
    left = max(visible.left() + 8, min(left, visible.right() - width - 7))
    top = window.bottom() - 48 - height
    top = max(visible.top() + 16, min(top, visible.bottom() - height - 15))
    return QRect(left, top, width, height)


class PermissionOverlay(QDialog):
    failed = Signal(str)
    authorized = Signal()

    def __init__(self, bundle):
        # Independent tool window: works even when the main window is hidden
        # and Settings was opened from our menu-bar menu.
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)
        self.setWindowTitle(APP_NAME + " · 授权引导")
        self.setModal(False)
        self.setStyleSheet(stylesheet() + f"""
            QDialog {{ background: transparent; }}
            QFrame#permissionGuide {{ background: {TOKENS['PANEL']};
                border: 1px solid {TOKENS['LINE_STRONG']}; border-radius: 12px; }}
            QPushButton#permissionDrag {{ background: {TOKENS['SUNKEN']};
                border: 1px solid {TOKENS['LINE']}; border-radius: 8px;
                text-align: left; padding: 8px 12px; font-size: 15px; font-weight: 600; }}
            QPushButton#permissionDrag:hover {{ background: {TOKENS['ACCENT_SOFT']}; }}
            QPushButton#permissionDrag:focus {{ border: 2px solid {TOKENS['ACCENT']}; }}
            QLabel#guideHeading {{ font-size: 14px; font-weight: 600; }}
            QPushButton#guideClose {{ padding: 0; border: none; background: transparent;
                font-size: 20px; color: {TOKENS['MUTED']}; }}
        """)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 12)
        card = QFrame()
        card.setObjectName("permissionGuide")
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(14)
        shadow.setOffset(0, 3)
        shadow.setColor(QColor(0, 0, 0, 45))
        card.setGraphicsEffect(shadow)
        outer.addWidget(card)
        box = QVBoxLayout(card)
        box.setContentsMargins(16, 12, 16, 12)
        box.setSpacing(10)
        heading = QHBoxLayout()
        self.title = QLabel()
        self.title.setObjectName("guideHeading")
        self.title.setWordWrap(True)
        heading.addWidget(self.title, 1)
        close = QPushButton("×")
        close.setObjectName("guideClose")
        close.setFixedSize(28, 28)
        close.setAccessibleName("关闭授权引导")
        close.setToolTip("关闭引导，保留系统设置窗口")
        close.clicked.connect(self.close)
        heading.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        box.addLayout(heading)
        self.app = ApplicationDragButton(bundle)
        self.app.setObjectName("permissionDrag")
        self.app.setText(APP_NAME + "   ↑ 拖到上方列表")
        self.app.setMinimumHeight(64)
        self.app.failed.connect(self.failed)
        self.app.drag_started.connect(lambda: self._set_dragging(True))
        self.app.drag_finished.connect(lambda: self._set_dragging(False))
        # A successful drop completes this guide, not the OS permission grant.
        self.app.drop_accepted.connect(self.close)
        box.addWidget(self.app)
        self.note = QLabel("拖入后引导自动关闭，请在系统列表中打开开关。也可点击图标在访达中显示。")
        self.note.setWordWrap(True)
        self.note.setStyleSheet(f"color: {TOKENS['MUTED']}; font-size: 12px;")
        box.addWidget(self.note)
        self.follow = QTimer(self)
        self.follow.setInterval(250)
        self.follow.timeout.connect(self.sync)
        self.poll = QTimer(self)
        self.poll.setInterval(1500)
        self.poll.timeout.connect(self.check_permission)
        self.permission = None
        self.dragging = False
        self.seen = False
        self.attempts = 0

    def _set_dragging(self, dragging):
        self.dragging = dragging

    def begin(self, permission):
        if permission not in permissions.MAC_PANES:
            raise ValueError("unknown permission")
        self.permission = permission
        title = "辅助功能" if permission == "accessibility" else "输入监控"
        self.title.setText(f"{title}授权 · 将 {APP_NAME} 拖到上方列表")
        self.seen = False
        self.attempts = 0
        self.follow.start()
        self.poll.start()
        self.sync()

    def sync(self):
        if self.dragging:
            return
        try:
            state = permissions.settings_window()
        except Exception:
            state = None
        if state is None:
            self.hide()
            self.attempts += 1
            if self.seen or self.attempts >= 40:
                self.close()
                if not self.seen:
                    self.failed.emit("尚未定位到系统设置窗口，请重新点击「前往授权」。也可用系统列表的「＋」添加本应用。")
            return
        bounds, foreground = state
        self.seen = True
        self.attempts = 0
        if foreground == "other" or (foreground == "self" and QApplication.activeWindow() is not self):
            self.hide()
            return
        window = QRect(*bounds)
        screens = QApplication.screens()
        screen = max(screens, key=lambda s: window.intersected(s.availableGeometry()).width()
                     * window.intersected(s.availableGeometry()).height()).availableGeometry()
        if window.intersected(screen).width() < 336 or window.intersected(screen).height() < 260:
            self.hide()
            return
        area = panel_geometry(window, screen, 180)
        if self.width() != area.width():
            self.resize(area.width(), self.height())
        self.layout().activate()
        wanted = max(180, self.layout().totalHeightForWidth(area.width()))
        area = panel_geometry(window, screen, wanted)
        if self.geometry() != area:
            self.setGeometry(area)
        if not self.isVisible():
            self.show()  # WA_ShowWithoutActivating leaves Settings focused.

    def check_permission(self):
        if self.dragging:
            return
        if permissions.permission_status().get(self.permission) == "已授权":
            self.close()
            self.authorized.emit()

    def closeEvent(self, event):
        self.follow.stop()
        self.poll.stop()
        super().closeEvent(event)

    def reject(self):
        # Escape uses reject(), not necessarily a window close event.
        self.follow.stop()
        self.poll.stop()
        super().reject()
