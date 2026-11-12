"""Read-only permission checks; settings links open only on a user click."""
import sys
import os
from pathlib import Path
import subprocess


MAC_PANES = {
    "accessibility": "Privacy_Accessibility",
    "input": "Privacy_ListenEvent",
}


def settings_window():
    """Return visible Settings bounds and whether the guide may be shown.

    Read public window metadata only: no titles, screen capture, Accessibility
    automation, permission request or changes to another application's window.
    Coordinates are logical screen points, with the main screen's top-left origin.
    """
    if sys.platform != "darwin":
        return None
    from AppKit import NSRunningApplication, NSWorkspace
    from Quartz import (
        CGWindowListCopyWindowInfo, kCGWindowListOptionOnScreenOnly,
        kCGWindowListExcludeDesktopElements, kCGNullWindowID,
    )
    apps = NSRunningApplication.runningApplicationsWithBundleIdentifier_("com.apple.systempreferences")
    pids = {int(app.processIdentifier()) for app in apps}
    if not pids:
        return None
    front = NSWorkspace.sharedWorkspace().frontmostApplication()
    front_pid = int(front.processIdentifier()) if front else None
    foreground = "settings" if front_pid in pids else "self" if front_pid == os.getpid() else "other"
    windows = CGWindowListCopyWindowInfo(
        kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements, kCGNullWindowID,
    ) or []
    for window in windows:  # Front-to-back order; ignore sheets/menus/tiny panels.
        if window.get("kCGWindowOwnerPID") not in pids or window.get("kCGWindowLayer") != 0:
            continue
        bounds = window.get("kCGWindowBounds", {})
        if bounds.get("Width", 0) >= 480 and bounds.get("Height", 0) >= 320:
            rect = tuple(round(bounds[k]) for k in ("X", "Y", "Width", "Height"))
            return rect, foreground
    return None


def running_app_bundle():
    """Use this process's bundle, never a name search that could pick an old build."""
    if sys.platform != "darwin" or not getattr(sys, "frozen", False):
        return None
    executable = Path(sys.executable).resolve()
    for path in executable.parents:
        if path.suffix.lower() == ".app" and (path / "Contents/Info.plist").is_file():
            return path
    return None


def reveal_running_app():
    bundle = running_app_bundle()
    if bundle is None:
        raise RuntimeError("无法定位当前应用，请从打包后的 App 打开此功能")
    subprocess.run(["/usr/bin/open", "-R", str(bundle)], check=True, timeout=10)


def permission_status():
    if sys.platform == "darwin":
        result = {}
        for name in MAC_PANES:
            try:
                if name == "accessibility":
                    from ApplicationServices import AXIsProcessTrusted
                    allowed = AXIsProcessTrusted()
                else:
                    from Quartz import CGPreflightListenEventAccess
                    allowed = CGPreflightListenEventAccess()
                result[name] = "已授权" if allowed else "未授权"
            except Exception:
                result[name] = "无法检测，请在系统设置中查看"
        return result
    return {}


def open_permission_settings(name):
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    if sys.platform != "darwin" or name not in MAC_PANES:
        raise ValueError("此平台没有对应的 macOS 授权页面")
    url = "x-apple.systempreferences:com.apple.preference.security?" + MAC_PANES[name]
    if not QDesktopServices.openUrl(QUrl(url)):
        raise RuntimeError("无法打开系统设置，请手动前往“隐私与安全性”")
