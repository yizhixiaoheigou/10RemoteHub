"""Drag the running .app into Settings; keyboard/click fallback reveals it."""
from PySide6.QtCore import QMimeData, QPoint, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QApplication, QPushButton

from .. import permissions
from ..branding import APP_NAME
from ..icons import app_icon


class ApplicationDragButton(QPushButton):
    failed = Signal(str)
    drag_started = Signal()
    drag_finished = Signal()
    drop_accepted = Signal()

    def __init__(self, bundle, parent=None):
        super().__init__(APP_NAME + " · 拖入授权列表", parent)
        self.bundle = bundle
        self.origin = None
        self.setIcon(app_icon())
        self.setIconSize(QSize(36, 36))
        self.setMinimumHeight(52)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setAccessibleName("将当前应用拖入系统授权列表；点击或按回车可在访达中显示")
        self.setToolTip("拖动此处添加当前应用；单击可在访达中显示。\n" + str(bundle))
        self.clicked.connect(self.reveal)

    def reveal(self):
        try:
            permissions.reveal_running_app()
        except Exception as exc:
            self.failed.emit(str(exc))

    def mime_data(self):
        data = QMimeData()
        data.setUrls([QUrl.fromLocalFile(str(self.bundle))])
        return data

    def mousePressEvent(self, event):
        self.origin = event.position().toPoint() if event.button() == Qt.MouseButton.LeftButton else None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (self.origin is not None and event.buttons() & Qt.MouseButton.LeftButton
                and (event.position().toPoint() - self.origin).manhattanLength() >= QApplication.startDragDistance()):
            self.origin = None
            self.setDown(False)
            drag = QDrag(self)
            drag.setMimeData(self.mime_data())
            drag.setPixmap(self.icon().pixmap(48, 48))
            drag.setHotSpot(QPoint(24, 24))
            try:
                # Pass a file URL, never move the running application on disk.
                self.drag_started.emit()
                action = drag.exec(Qt.DropAction.CopyAction, Qt.DropAction.CopyAction)
            finally:
                drag.deleteLater()
                self.drag_finished.emit()
            if action == Qt.DropAction.CopyAction:
                self.drop_accepted.emit()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.origin = None
        super().mouseReleaseEvent(event)
