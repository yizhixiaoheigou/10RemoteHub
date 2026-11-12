"""Windows Raw Input with VID/PID filtering. No administrator driver changes.

Raw Input identifies the source device but cannot suppress its legacy events
system-wide. This adapter intentionally does not block the user's main keyboard.
"""
import ctypes as c
from ctypes import wintypes as w
import re
from PySide6.QtCore import QAbstractNativeEventFilter
from PySide6.QtWidgets import QApplication
from .input_codes import windows_keyboard
from .photo_template import is_fixed_model
from .windows_hid import ConsumerReports


class RID(c.Structure):
    _fields_=[("page",c.c_uint16),("usage",c.c_uint16),("flags",c.c_uint32),("target",c.c_void_p)]
class HEADER(c.Structure):
    _fields_=[("kind",c.c_uint32),("size",c.c_uint32),("device",c.c_void_p),("param",c.c_size_t)]
class KEYBOARD(c.Structure):
    _fields_=[("scan",c.c_uint16),("flags",c.c_uint16),("reserved",c.c_uint16),("vk",c.c_uint16),("message",c.c_uint32),("extra",c.c_uint32)]


class WindowsInput(QAbstractNativeEventFilter):
    def __init__(self, profile, emit, status, window, unmapped=None):
        super().__init__()
        self.profile,self.emit,self.status,self.window=profile,emit,status,window
        self.unmapped=unmapped
        self.keyboard_muted=False
        self.user=c.WinDLL("user32",use_last_error=True)
        self.user.RegisterRawInputDevices.argtypes=[c.POINTER(RID),w.UINT,w.UINT]
        self.user.GetRawInputData.argtypes=[w.HANDLE,w.UINT,c.c_void_p,c.POINTER(w.UINT),w.UINT]
        self.user.GetRawInputData.restype=w.UINT
        self.user.GetRawInputDeviceInfoW.argtypes=[w.HANDLE,w.UINT,c.c_void_p,c.POINTER(w.UINT)]
        self.user.GetRawInputDeviceInfoW.restype=w.UINT
        self.cache={}
        self.previous={}
        self.consumers={}
        self.held={}

    def start(self):
        if self.window is None:
            raise RuntimeError("Windows 设备接入需要桌面窗口")
        self.reg=(RID*2)(RID(1,6,0x2100,int(self.window.winId())),RID(12,1,0x2100,int(self.window.winId())))
        if not self.user.RegisterRawInputDevices(self.reg,2,c.sizeof(RID)):
            raise c.WinError(c.get_last_error())
        QApplication.instance().installNativeEventFilter(self)
        self.status("Windows 已监听适配型号；系统原按键仍保留")

    def _matches(self, handle):
        if handle not in self.cache:
            size=w.UINT(0)
            rc=self.user.GetRawInputDeviceInfoW(handle,0x20000007,None,c.byref(size))
            if rc==0xffffffff or not 0<size.value<=32768:
                return False
            buf=c.create_unicode_buffer(size.value+1)
            rc=self.user.GetRawInputDeviceInfoW(handle,0x20000007,buf,c.byref(size))
            path=buf.value.lower() if rc!=0xffffffff else ""
            self.cache[handle]=bool(re.search(f"vid_{self.profile.vendor:04x}&pid_{self.profile.product:04x}",path))
        return self.cache[handle]

    def nativeEventFilter(self, kind, message):
        try:
            msg=w.MSG.from_address(int(message))
            if msg.message==0x00fe and msg.wParam==2:  # device removed; handles may be reused
                self._release(msg.lParam)
                return False,0
            if msg.message!=0x00ff: return False,0
            size=w.UINT(0)
            self.user.GetRawInputData(msg.lParam,0x10000003,None,c.byref(size),c.sizeof(HEADER))
            if not c.sizeof(HEADER)<=size.value<=4096: return False,0
            raw=c.create_string_buffer(size.value)
            n=self.user.GetRawInputData(msg.lParam,0x10000003,raw,c.byref(size),c.sizeof(HEADER))
            if n==0xffffffff or n!=size.value: return False,0
            header=HEADER.from_buffer(raw)
            if not self._matches(header.device): return False,0
            offset=c.sizeof(HEADER)
            if self.unmapped is not None and header.kind not in (1, 2):
                self.unmapped(-header.kind, 0, 0)  # unexpected report kind
            if header.kind==1 and self.keyboard_muted:
                return False, 0
            if header.kind==1 and size.value>=offset+c.sizeof(KEYBOARD):
                k=KEYBOARD.from_buffer(raw,offset)
                if k.vk==255 and self.unmapped is not None:
                    self.unmapped(k.scan, k.flags, 255)
                if k.vk!=255:
                    trigger = (windows_keyboard(k.scan,k.flags) if is_fixed_model(self.profile)
                               else f"win:{k.scan}:{k.flags & 6}")
                    if trigger:
                        down = not bool(k.flags & 1)
                        held = self.held.setdefault(header.device, set())
                        if down and trigger not in held:
                            held.add(trigger); self.emit(trigger,True)
                        elif not down and trigger in held:
                            held.remove(trigger); self.emit(trigger,False)
                    elif self.unmapped is not None:
                        self.unmapped(k.scan, k.flags, k.vk)
            elif header.kind==2 and size.value>=offset+8:
                width=c.c_uint32.from_buffer(raw,offset).value
                count=c.c_uint32.from_buffer(raw,offset+4).value
                if width and width*count<=size.value-offset-8:
                    for i in range(count):
                        data=bytes(raw[offset+8+i*width:offset+8+(i+1)*width])
                        if is_fixed_model(self.profile):
                            if header.device not in self.consumers:
                                self.consumers[header.device]=ConsumerReports(self.user,header.device)
                            events=self.consumers[header.device].decode(data)
                            for trigger,down in events:
                                self.emit(trigger,down)
                            if not events and self.unmapped is not None and any(data[1:]):
                                self.unmapped(1000 + data[0], data[1] if len(data) > 1 else 0, data[2] if len(data) > 2 else 0)
                            continue
                        trigger="raw:"+data.hex()
                        old=self.previous.get(header.device)
                        if old and old!=trigger: self.emit(old,False)
                        if any(data[1:]) and old!=trigger:
                            self.emit(trigger,True); self.previous[header.device]=trigger
                        elif not any(data[1:]): self.previous.pop(header.device,None)
        except Exception as exc:
            self.status(f"设备事件读取失败：{exc}")
        return False,0

    def _release(self, handle):
        for trigger in self.held.pop(handle, set()): self.emit(trigger,False)
        consumer=self.consumers.pop(handle,None)
        if consumer:
            for trigger,down in consumer.release(): self.emit(trigger,down)
        old=self.previous.pop(handle,None)
        if old: self.emit(old,False)
        self.cache.pop(handle,None)

    def stop(self):
        QApplication.instance().removeNativeEventFilter(self)
        reg=(RID*2)(RID(1,6,1,None),RID(12,1,1,None))
        self.user.RegisterRawInputDevices(reg,2,c.sizeof(RID))
        for handle in set(self.held) | set(self.consumers) | set(self.previous) | set(self.cache):
            self._release(handle)
