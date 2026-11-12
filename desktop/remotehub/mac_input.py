"""Temporary default-input routing; all CoreAudio work stays off the GUI thread.

Uses the HAL property listener, not a fixed sleep or a subprocess. Only the
default INPUT is writable here. Device UIDs survive CoreAudio re-enumeration.
"""
import ctypes as C
import queue
import threading
import time

from PySide6.QtCore import QObject, Signal, Qt

MIC_UID = "RemoteHubAudioDevice_UID"
# A native registration must keep its ctypes callback alive even if removing
# the listener fails during an audio-service restart. The worker retries cleanup
# before accepting another lease, so failed registrations cannot accumulate.
_listeners = {}


def fourcc(value):
    return int.from_bytes(value.encode("ascii"), "big")


class Address(C.Structure):
    _fields_ = [("selector", C.c_uint32), ("scope", C.c_uint32), ("element", C.c_uint32)]


class CoreAudioInput:
    def __init__(self):
        self.ca = C.CDLL("/System/Library/Frameworks/CoreAudio.framework/CoreAudio")
        self.cf = C.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        self.ca.AudioObjectGetPropertyData.argtypes = [C.c_uint32, C.POINTER(Address),
            C.c_uint32, C.c_void_p, C.POINTER(C.c_uint32), C.c_void_p]
        self.ca.AudioObjectGetPropertyData.restype = C.c_int32
        self.ca.AudioObjectSetPropertyData.argtypes = [C.c_uint32, C.POINTER(Address),
            C.c_uint32, C.c_void_p, C.c_uint32, C.c_void_p]
        self.ca.AudioObjectSetPropertyData.restype = C.c_int32
        self.callback_type = C.CFUNCTYPE(C.c_int32, C.c_uint32, C.c_uint32,
                                        C.POINTER(Address), C.c_void_p)
        for name in ("AudioObjectAddPropertyListener", "AudioObjectRemovePropertyListener"):
            fn = getattr(self.ca, name)
            fn.argtypes = [C.c_uint32, C.POINTER(Address), self.callback_type, C.c_void_p]
            fn.restype = C.c_int32
        self.cf.CFStringCreateWithCString.argtypes = [C.c_void_p, C.c_char_p, C.c_uint32]
        self.cf.CFStringCreateWithCString.restype = C.c_void_p
        self.cf.CFStringGetCString.argtypes = [C.c_void_p, C.c_void_p, C.c_long, C.c_uint32]
        self.cf.CFStringGetCString.restype = C.c_bool
        self.cf.CFRelease.argtypes = [C.c_void_p]
        self.cf.CFRelease.restype = None
        self.callback = None

    @staticmethod
    def address(selector):
        return Address(fourcc(selector), fourcc("glob"), 0)

    @staticmethod
    def check(status):
        if status:
            raise RuntimeError(f"系统麦克风切换失败（{status}）")

    def get(self, device, selector, result, qualifier=None):
        size = C.c_uint32(C.sizeof(result))
        address = self.address(selector)
        self.check(self.ca.AudioObjectGetPropertyData(device, C.byref(address),
            C.sizeof(qualifier) if qualifier is not None else 0,
            C.byref(qualifier) if qualifier is not None else None, C.byref(size), C.byref(result)))
        return result.value

    def default(self):
        return self.get(1, "dIn ", C.c_uint32())

    def uid(self, device):
        if not device:
            raise RuntimeError("没有可恢复的默认麦克风，请先在系统设置中选择麦克风")
        value = self.get(device, "uid ", C.c_void_p())
        try:
            buffer = C.create_string_buffer(4096)
            if not self.cf.CFStringGetCString(value, buffer, len(buffer), 0x08000100):
                raise RuntimeError("无法读取原麦克风标识")
            return buffer.value.decode("utf-8")
        finally:
            if value:
                self.cf.CFRelease(value)

    def resolve(self, uid):
        value = self.cf.CFStringCreateWithCString(None, uid.encode("utf-8"), 0x08000100)
        if not value:
            raise RuntimeError("无法读取麦克风标识")
        try:
            return self.get(1, "uidd", C.c_uint32(), C.c_void_p(value))
        finally:
            self.cf.CFRelease(value)

    def set_default(self, device):
        value, address = C.c_uint32(device), self.address("dIn ")
        self.check(self.ca.AudioObjectSetPropertyData(1, C.byref(address), 0, None,
                                                     C.sizeof(value), C.byref(value)))

    def listen(self, changed):
        def callback(*_):
            try:
                changed(self.default())
            except Exception:
                changed(0)  # Device removal/service restart: relinquish ownership.
            return 0
        self.callback = self.callback_type(callback)
        address = self.address("dIn ")
        self.check(self.ca.AudioObjectAddPropertyListener(1, C.byref(address), self.callback, None))
        _listeners[id(self)] = self

    def unlisten(self):
        if self.callback is not None:
            address = self.address("dIn ")
            self.check(self.ca.AudioObjectRemovePropertyListener(1, C.byref(address), self.callback, None))
            _listeners.pop(id(self), None)
            # Keep the callback alive until this backend is destroyed.


class InputLease:
    """Worker-owned lease; preserve a user's later manual input selection."""
    def __init__(self, backend, timeout=0.8):
        self.backend, self.timeout = backend, timeout
        self.previous = None
        self.target = 0
        self.overridden = False
        self.monitoring = False
        self.listening = False
        self.requested = False
        self.changed = threading.Event()

    def _changed(self, device):
        if self.monitoring and device != self.target:
            self.overridden = True
        self.changed.set()

    def _set(self, device):
        self.changed.clear()
        self.backend.set_default(device)
        deadline = time.monotonic() + self.timeout
        while True:
            # Clear BEFORE reading, so a concurrent notification cannot be lost.
            self.changed.clear()
            if self.backend.default() == device:
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError("系统麦克风切换未及时完成，请重试")
            self.changed.wait(remaining)

    def acquire(self):
        self.target = self.backend.resolve(MIC_UID)
        if not self.target:
            raise RuntimeError("虚拟麦克风尚未就绪，请在语音设置中安装并重新检测")
        current = self.backend.default()
        if current == self.target:
            return  # Already the user's choice; do not restore to another device.
        self.previous = self.backend.uid(current)
        self.backend.listen(self._changed)
        self.listening = True
        # Monitor from the write onward; callbacks may arrive synchronously.
        self.overridden = False
        self.monitoring = True
        self.requested = True
        self._set(self.target)
        if self.overridden:
            raise RuntimeError("默认麦克风已被其他操作更改，请重试语音输入")

    def release(self):
        self.monitoring = False
        try:
            if self.previous and not self.overridden:
                current = self.backend.default()
                original = self.backend.resolve(self.previous)
                if current != self.target and not (self.requested and current == original):
                    return
                if not original:
                    raise RuntimeError("原麦克风已断开，请在系统设置中选择可用麦克风")
                # Reassert the original even after an unconfirmed async write.
                # Otherwise a timed-out request may still be pending in HAL.
                self._set(original)
        finally:
            self.previous = None
            if self.listening:
                self.backend.unlisten()
                self.listening = False


class MacInputRoute(QObject):
    ready = Signal()
    failed = Signal(str)
    released = Signal()
    measured = Signal(str, float)
    _result = Signal(str, int, str, float)

    def __init__(self, parent=None, backend_factory=CoreAudioInput):
        super().__init__(parent)
        self.factory = backend_factory
        self.jobs = queue.Queue()
        self.thread = None
        self.state = "idle"
        self.generation = 0
        self.close_error = ""
        self._result.connect(self._deliver, Qt.ConnectionType.QueuedConnection)

    def acquire(self):
        if self.state != "idle":
            raise RuntimeError("正在恢复麦克风，请稍后再试")
        self.state = "acquiring"
        self.generation += 1
        if self.thread is None:
            self.thread = threading.Thread(target=self._run, name="remotehub-input", daemon=True)
            self.thread.start()
        self.jobs.put(("acquire", self.generation))

    def release(self):
        if self.state in ("idle", "closed"):
            self.released.emit()
        elif self.state != "releasing":
            self.state = "releasing"
            self.jobs.put(("release", self.generation))

    def _run(self):
        lease = None
        while True:
            operation, generation = self.jobs.get()
            started, error = time.monotonic(), ""
            try:
                if operation == "acquire":
                    if lease is not None:
                        lease.release()  # Retry a failed cleanup before registering again.
                        lease = None
                    lease = InputLease(self.factory())
                    lease.acquire()
                elif lease is not None:
                    lease.release()
                    lease = None
            except Exception as exc:
                error = str(exc)
            if operation == "close":
                self.close_error = error
                return
            self._result.emit(operation, generation, error, (time.monotonic()-started)*1000)

    def _deliver(self, operation, generation, error, elapsed):
        if generation != self.generation or self.state == "closed":
            return
        self.measured.emit(operation, elapsed)
        if operation == "acquire" and self.state == "acquiring":
            self.state = "active"
            if error:
                self.failed.emit(error)
            else:
                self.ready.emit()
        elif operation == "release":
            self.state = "idle"
            if error:
                self.failed.emit("恢复原麦克风失败：" + error)
            self.released.emit()

    def close(self):
        if self.state == "closed":
            return
        self.state = "closed"
        if self.thread is not None:
            self.jobs.put(("close", self.generation))
            # Normal exit restores without requiring another GUI event-loop turn.
            self.thread.join(2)
            if self.thread.is_alive():
                self.failed.emit("系统音频服务未响应，请检查默认麦克风是否已恢复")
            elif self.close_error:
                self.failed.emit("恢复原麦克风失败：" + self.close_error)
