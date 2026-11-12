"""Generated brand assets, separate application and menu-bar representations."""
from pathlib import Path
import sys
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon,QPixmap,QPainter,QColor
from PySide6.QtWidgets import QApplication

ASSETS=Path(__file__).parent/"assets"

def app_icon():return QIcon(str(ASSETS/"app-icon.png"))

def tray_icon():
    pixmap=QPixmap(str(ASSETS/"tray-icon.png"))
    if sys.platform!="darwin" and QApplication.styleHints().colorScheme()==Qt.ColorScheme.Dark:
        # OS dark tray backgrounds need the same alpha silhouette in white.
        painter=QPainter(pixmap); painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(pixmap.rect(),QColor("white")); painter.end()
    icon=QIcon(pixmap); icon.setIsMask(sys.platform=="darwin"); return icon

def set_dock_visible(visible):
    if sys.platform == "darwin":
        from AppKit import NSApplication
        NSApplication.sharedApplication().setActivationPolicy_(0 if visible else 1)


def configure_application(app,*,native=True):
    app.setWindowIcon(app_icon()); app.setDesktopFileName("org.remotehub.desktop")
    if native and sys.platform=="darwin":
        from AppKit import NSApplication,NSImage
        image=NSImage.alloc().initWithContentsOfFile_(str(ASSETS/"app-icon.png"))
        if image:NSApplication.sharedApplication().setApplicationIconImage_(image)
