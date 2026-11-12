"""Foreground-aware application actions. All closes are cooperative requests."""
from __future__ import annotations
from dataclasses import dataclass
import os
from pathlib import Path
import sys
from .launch import LaunchRequest


@dataclass
class Window:
    handle: object
    pid: int
    executable: str


@dataclass
class PendingHide:
    """Check on later GUI turns: NSRunningApplication caches state per run loop."""
    application: object

    def poll(self, *, expired=False):
        if self.application.isTerminated():
            return "目标应用已退出，无法确认收起结果", True
        if self.application.isHidden():
            return "已收起应用", False
        if expired:
            return "未确认应用已收起，请检查目标窗口", True
        return None


class WindowController:
    def __init__(self, backend=None):
        self.backend=backend
        self.log = lambda *args, **kwargs: None

    def _get(self):
        if self.backend is None:
            self.backend=MacWindows() if sys.platform=="darwin" else WinWindows(log=self.log) if sys.platform=="win32" else None
        if self.backend is None:
            raise RuntimeError("当前版本只支持 macOS 与 Windows")
        return self.backend

    def toggle(self, target, launch):
        try:
            return self._toggle(target, launch)
        except Exception as exc:
            self.log("window_error", app=Path(target).name, exception=type(exc).__name__,
                     winerror=getattr(exc, "winerror", None), operation="toggle")
            raise

    def _toggle(self,target,launch):
        path=Path(target).expanduser().resolve()
        if not path.exists():raise FileNotFoundError(f"应用不存在：{path}")
        backend=self._get()
        matches=backend.find(str(path))
        self.log("window_matches", app=path.name, count=len(matches), handles=[w.handle for w in matches] if sys.platform == "win32" else [], pids=[w.pid for w in matches])
        if not matches:
            result = launch()
            return result if isinstance(result, LaunchRequest) else "已请求启动应用"
        active=backend.foreground()
        current=next((w for w in matches if active and w.pid==active.pid),None)
        if current:
            result = backend.hide(current)
            return result if isinstance(result, PendingHide) else "已收起应用"
        result = backend.show(matches[0])
        return result if isinstance(result, (LaunchRequest, PendingHide)) else "已请求显示应用"

    def close_current(self,whole_app=False):
        backend=self._get();active=backend.foreground()
        if active is None:raise RuntimeError("没有可关闭的前台应用")
        if active.pid==os.getpid():raise RuntimeError("当前前台是本软件；请切到要关闭的应用后再按遥控器")
        if whole_app:backend.quit(active)
        else:backend.close(active)
        return "已请求正常退出应用，请处理应用可能显示的保存提示" if whole_app else "已请求关闭当前窗口"

    def minimize_current(self):
        backend = self._get()
        active = backend.foreground()
        if active is None:
            raise RuntimeError("没有可收起的前台窗口")
        if active.pid == os.getpid():
            raise RuntimeError("请先切换到要收起的窗口")
        result = backend.minimize(active)
        return result if isinstance(result, PendingHide) else "已请求收起当前窗口"


class MacWindows:
    def __init__(self):
        from AppKit import NSWorkspace
        self.workspace=NSWorkspace.sharedWorkspace()
    @staticmethod
    def _info(app):
        if not app:return None
        url=app.bundleURL()
        return Window(app,int(app.processIdentifier()),str(url.path()) if url else "")
    def foreground(self):return self._info(self.workspace.frontmostApplication())
    def find(self,path):
        return [self._info(a) for a in self.workspace.runningApplications() if a.bundleURL() and Path(str(a.bundleURL().path())).resolve()==Path(path)]
    def hide(self,window):
        # Edge can return False while the hide request succeeds on the next turn.
        # Verify actual state asynchronously, including when hide() returns True.
        window.handle.hide()
        return PendingHide(window.handle)
    def show(self,window):
        # Reopen through LaunchServices, as opening the application in Finder.
        # Activating a running process alone leaves an app with no windows invisible.
        return LaunchRequest(['/usr/bin/open', '-a', window.executable], "已请求显示应用")
    def close(self,window):
        import ApplicationServices as ax
        if not ax.AXIsProcessTrusted():raise PermissionError("关闭窗口需要辅助功能权限")
        app=ax.AXUIElementCreateApplication(window.pid)
        ax.AXUIElementSetMessagingTimeout(app, 1.0)
        error,focused=ax.AXUIElementCopyAttributeValue(app,ax.kAXFocusedWindowAttribute,None)
        if error or focused is None:raise RuntimeError("无法获取前台应用的当前窗口")
        error,close_button=ax.AXUIElementCopyAttributeValue(focused,ax.kAXCloseButtonAttribute,None)
        if error or close_button is None:raise RuntimeError("当前窗口未提供可用的关闭按钮")
        if ax.AXUIElementPerformAction(close_button,ax.kAXPressAction):raise RuntimeError("窗口未接受关闭请求")
    def minimize(self,window):
        import ApplicationServices as ax
        if not ax.AXIsProcessTrusted():raise PermissionError("收起窗口需要辅助功能权限")
        app=ax.AXUIElementCreateApplication(window.pid)
        ax.AXUIElementSetMessagingTimeout(app, 1.0)
        error,focused=ax.AXUIElementCopyAttributeValue(app,ax.kAXFocusedWindowAttribute,None)
        if error or focused is None:raise RuntimeError("无法获取前台应用的当前窗口")
        if ax.AXUIElementSetAttributeValue(focused,ax.kAXMinimizedAttribute,True):
            raise RuntimeError("当前窗口不支持收起")
    def quit(self,window):
        if window.handle.bundleIdentifier() in ("com.apple.finder","com.apple.dock","com.apple.loginwindow"):
            raise RuntimeError("不通过遥控器退出系统桌面组件")
        if not window.handle.terminate():raise RuntimeError("应用尚未同意退出；请查看保存提示")


class PendingWindows(PendingHide):
    """Verify asynchronous Win32 changes on later GUI turns, without blocking."""
    def __init__(self, backend, window, operation, targets=None):
        self.backend, self.window, self.operation = backend, window, operation
        self.targets = targets or [window]
        self.retried = False
        self.request_message = "正在收起应用" if operation == "hide" else "正在切换到应用"

    def poll(self, *, expired=False):
        b, w = self.backend, self.window
        if self.operation == "hide":
            success = all(not b.user.IsWindow(x.handle) or b.user.IsIconic(x.handle) for x in self.targets)
            message = "已收起应用" if success else "窗口未接受最小化请求，请检查应用是否有阻塞对话框或权限差异"
        else:
            if not b.user.IsWindow(w.handle):
                b.log("window_result", operation="show", pid=w.pid, hwnd=w.handle, success=False, reason="window_closed")
                return "目标窗口已关闭，请重新调出应用", True
            foreground = b.foreground()
            success = bool(foreground and foreground.pid == w.pid and not b.user.IsIconic(w.handle))
            if not success and not self.retried and not expired:
                self.retried = True
                b._activate(w.handle)
                return None
            message = "已调出应用" if success else "Windows 未允许切换到目标前台窗口；窗口状态已保留，请检查权限或当前对话框"
        if success or expired:
            b.log("window_result", operation=self.operation, pid=w.pid, hwnd=w.handle, success=bool(success), reason="confirmed" if success else "state_timeout")
            return message, not success
        return None


class WinWindows:
    def __init__(self, log=None):
        import ctypes as c
        from ctypes import wintypes as w
        self.c,self.w=c,w
        self.log = log or (lambda *args, **kwargs: None)
        self.saved_states = {}
        class Placement(c.Structure):
            _fields_ = [("length", w.UINT), ("flags", w.UINT), ("showCmd", w.UINT),
                        ("ptMinPosition", w.POINT), ("ptMaxPosition", w.POINT), ("rcNormalPosition", w.RECT)]
        self.Placement = Placement
        self.user=c.WinDLL("user32",use_last_error=True);self.kernel=c.WinDLL("kernel32",use_last_error=True)
        self.user.GetForegroundWindow.restype=w.HWND
        self.user.GetWindowThreadProcessId.argtypes=[w.HWND,c.POINTER(w.DWORD)]
        self.user.IsWindowVisible.argtypes=[w.HWND];self.user.IsWindow.argtypes=[w.HWND]
        self.user.ShowWindow.argtypes=[w.HWND,c.c_int]
        self.user.ShowWindowAsync.argtypes=[w.HWND,c.c_int]
        self.user.IsIconic.argtypes=[w.HWND]
        self.user.IsZoomed.argtypes=[w.HWND]
        self.user.GetWindowPlacement.argtypes=[w.HWND,c.POINTER(self.Placement)]
        self.user.GetWindow.argtypes=[w.HWND,w.UINT]; self.user.GetWindow.restype=w.HWND
        self.user.GetWindowLongW.argtypes=[w.HWND,c.c_int]
        self.user.AttachThreadInput.argtypes=[w.DWORD,w.DWORD,w.BOOL]
        self.user.GetAsyncKeyState.argtypes=[c.c_int]
        self.kernel.GetCurrentThreadId.restype=w.DWORD
        self.dwm=c.WinDLL("dwmapi")
        self.dwm.DwmGetWindowAttribute.argtypes=[w.HWND,w.DWORD,c.c_void_p,w.DWORD]
        self.user.SetForegroundWindow.argtypes=[w.HWND]
        self.user.PostMessageW.argtypes=[w.HWND,w.UINT,w.WPARAM,w.LPARAM]
        self.kernel.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];self.kernel.OpenProcess.restype=w.HANDLE
        self.kernel.CloseHandle.argtypes=[w.HANDLE]
        self.kernel.QueryFullProcessImageNameW.argtypes=[w.HANDLE,w.DWORD,w.LPWSTR,c.POINTER(w.DWORD)]
        self.enum_callback=c.WINFUNCTYPE(w.BOOL,w.HWND,w.LPARAM)
        self.user.EnumWindows.argtypes=[self.enum_callback,w.LPARAM]
    def _info(self,hwnd):
        if not hwnd or not self.user.IsWindow(hwnd):return None
        pid=self.w.DWORD();self.user.GetWindowThreadProcessId(hwnd,self.c.byref(pid))
        process=self.kernel.OpenProcess(0x1000,False,pid.value)
        if not process:return Window(hwnd,pid.value,"")
        try:
            size=self.w.DWORD(32768);buf=self.c.create_unicode_buffer(size.value)
            path=buf.value if self.kernel.QueryFullProcessImageNameW(process,0,buf,self.c.byref(size)) else ""
            return Window(hwnd,pid.value,path)
        finally:self.kernel.CloseHandle(process)
    def _all(self):
        windows=[]
        @self.enum_callback
        def each(hwnd,_):
            if self._eligible(hwnd):
                info=self._info(hwnd)
                if info:windows.append(info)
            return True
        if not self.user.EnumWindows(each,0):raise self.c.WinError(self.c.get_last_error())
        return windows
    def foreground(self):return self._info(self.user.GetForegroundWindow())
    def find(self,path):
        norm=lambda s:os.path.normcase(os.path.realpath(s))
        return [w for w in self._all() if w.executable and norm(w.executable)==norm(path)]
    def _eligible(self, hwnd):
        if not self.user.IsWindowVisible(hwnd):
            return False
        style = self.user.GetWindowLongW(hwnd, -20)  # GWL_EXSTYLE
        if style & 0x80:  # WS_EX_TOOLWINDOW: invisible/helper palettes are not app roots
            return False
        if self.user.GetWindow(hwnd, 4) and not style & 0x40000:  # GW_OWNER / WS_EX_APPWINDOW
            return False
        cloaked = self.w.DWORD()
        if self.dwm.DwmGetWindowAttribute(hwnd, 14, self.c.byref(cloaked), self.c.sizeof(cloaked)) == 0 and cloaked.value:
            return False
        return True

    def _restore_maximized(self, window):
        placement = self.Placement()
        placement.length = self.c.sizeof(placement)
        return bool(self.user.GetWindowPlacement(window.handle, self.c.byref(placement))
                    and (placement.flags & 2 or placement.showCmd == 3))

    def _activate_attached(self, hwnd):
        # Short-lived input-queue attachment, never a global foreground-lock
        # setting change or synthetic Alt press (Alt may start voice input).
        # Avoid resetting an in-progress keyboard modifier state.
        if any(self.user.GetAsyncKeyState(k) & 0x8000 for k in (0x10, 0x11, 0x12, 0x5b, 0x5c)):
            self.log("window_activate", hwnd=hwnd, method="attached", reason="modifier_held")
            return False
        current = self.kernel.GetCurrentThreadId()
        foreground = self.user.GetForegroundWindow()
        thread = self.user.GetWindowThreadProcessId(foreground, None) if foreground else 0
        if not thread or thread == current:
            return False
        attached = self.user.AttachThreadInput(current, thread, True)
        if not attached:
            self.log("window_activate", hwnd=hwnd, method="attached", reason="attach_denied", winerror=self.c.get_last_error())
            return False
        try:
            return bool(self.user.SetForegroundWindow(hwnd))
        finally:
            self.user.AttachThreadInput(current, thread, False)

    def _activate(self, hwnd):
        direct = bool(self.user.SetForegroundWindow(hwnd))
        attached = False
        if not direct and self.user.GetForegroundWindow() != hwnd:
            attached = self._activate_attached(hwnd)
        self.log("window_activate", hwnd=hwnd, direct=direct, attached=attached,
                 foreground=self.user.GetForegroundWindow())

    def hide(self, window):
        norm = lambda path: os.path.normcase(os.path.realpath(path))
        targets = [x for x in self._all() if x.executable and norm(x.executable) == norm(window.executable)
                   and not self.user.IsIconic(x.handle)]
        if not targets:
            raise RuntimeError("未找到可收起的应用主窗口")
        for item in targets:
            self.saved_states[(item.handle, item.pid)] = bool(self.user.IsZoomed(item.handle))
            accepted = bool(self.user.ShowWindowAsync(item.handle, 6))
            self.log("window_request", operation="hide", app=Path(item.executable).name,
                     pid=item.pid, hwnd=item.handle, maximized=self.saved_states[(item.handle, item.pid)], accepted=accepted)
        return PendingWindows(self, window, "hide", targets)

    def minimize(self, window):
        self.saved_states[(window.handle, window.pid)] = bool(self.user.IsZoomed(window.handle))
        self.user.ShowWindowAsync(window.handle, 6)
        return PendingWindows(self, window, "hide")

    def show(self, window):
        iconic = bool(self.user.IsIconic(window.handle))
        mode = None
        if iconic:
            maximized = self.saved_states.get((window.handle, window.pid), self._restore_maximized(window))
            mode = 3 if maximized else 9
            self.user.ShowWindowAsync(window.handle, mode)
        self.log("window_request", operation="show", app=Path(window.executable).name,
                 pid=window.pid, hwnd=window.handle, was_minimized=iconic, show_mode=mode)
        self._activate(window.handle)
        return PendingWindows(self, window, "show")

    def close(self,window):
        if not self.user.PostMessageW(window.handle,0x0010,0,0):raise self.c.WinError(self.c.get_last_error())
    def quit(self,window):
        if Path(window.executable).name.lower() in ("explorer.exe","applicationframehost.exe","shellexperiencehost.exe","winlogon.exe"):
            raise RuntimeError("此窗口由系统宿主管理，请使用“关闭当前窗口”")
        # WM_CLOSE lets each window display its own unsaved-document prompt. Apps
        # configured to stay in the tray may keep their background process alive.
        for item in self._all():
            if item.pid==window.pid:self.close(item)
