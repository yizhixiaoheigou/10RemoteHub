"""Authenticated native XPC bridge. Loading/status never installs or opens HID."""
from __future__ import annotations

import ctypes
from pathlib import Path
import subprocess
import sys
import time

from PySide6.QtCore import QObject, QTimer, Signal

from .installers import open_package

MESSAGES = {
    0: "已安装 · 连接后检查运行状态",
    1: "尚未安装",
    2: "当前版本无法连接设备，请安装正式版 10RemoteHub",
    3: "校验失败，需要重装",
}


def resources():
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


def load_library():
    path = resources() / "native/libRemoteHubDevice.dylib"
    if not path.is_file():
        raise RuntimeError("设备组件缺失，请更新完整 App")
    lib = ctypes.CDLL(str(path))
    for name in ("status", "connect", "disconnect"):
        fn = getattr(lib, "rh_device_" + name)
        fn.argtypes = []
        fn.restype = ctypes.c_int
    lib.rh_device_record.argtypes = [ctypes.c_int]
    lib.rh_device_record.restype = None
    lib.rh_device_heartbeat.argtypes = []
    lib.rh_device_heartbeat.restype = None
    lib.rh_device_next.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    lib.rh_device_next.restype = ctypes.c_int
    return lib


def installation_status():
    try:
        code = load_library().rh_device_status()
        return code, MESSAGES.get(code, "设备组件状态未知，请重新安装")
    except (OSError, RuntimeError) as exc:
        return 4, str(exc)


def open_installer(remove=False):
    """Only called from an explicit UI action; Installer asks for admin consent."""
    if sys.platform != "darwin":
        raise RuntimeError("设备组件仅用于 macOS")
    code, message = installation_status()
    if code in (2, 4):
        raise RuntimeError(message)
    path = resources() / "components" / ("RemoteHubDevice-Uninstall.pkg" if remove else "RemoteHubDevice.pkg")
    if not path.is_file():
        raise RuntimeError("设备组件安装包缺失，请更新完整签名版 App")
    open_package(path)


class MacDeviceHelper(QObject):
    line = Signal(bytes)
    failed = Signal(str)

    def __init__(self, parent=None, *, library=None, clock=time.monotonic):
        super().__init__(parent)
        self.lib = library if library is not None else load_library()
        self.clock = clock
        self.active = False
        self.confirmed = False
        self.poller = QTimer(self)
        self.poller.setInterval(30)
        self.poller.timeout.connect(self.poll)
        self.buffer = ctypes.create_string_buffer(4097)

    def start(self):
        code = self.lib.rh_device_connect()
        if code:
            raise RuntimeError(MESSAGES.get(code, "设备组件无法连接，请重新安装"))
        self.active = True
        self.confirmed = False
        self.deadline = self.clock() + 12
        self.poller.start()

    def record(self, active):
        if not self.active or not self.confirmed:
            raise RuntimeError("设备组件尚未连接")
        self.lib.rh_device_record(int(active))

    def poll(self):
        # Bounded work per GUI turn; native queue also has a hard limit.
        for _ in range(64):
            if not self.active:
                return
            result = self.lib.rh_device_next(self.buffer, len(self.buffer))
            if result == 0:
                break
            if result != 1:
                self.failed.emit("设备连接异常，已停止接入，请重新检测")
                self.stop()
                return
            self.line.emit(self.buffer.value)
        if self.active and not self.confirmed and self.clock() > self.deadline:
            self.failed.emit("设备组件连接超时，请在通用设置重新安装设备组件后检测")
            self.stop()

    def stop(self):
        self.poller.stop()
        was_active, self.active = self.active, False
        return not was_active or self.lib.rh_device_disconnect() == 0
