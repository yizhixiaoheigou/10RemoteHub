"""Model-only connection regressions; all native input and USB calls are fake."""
import sys
from types import SimpleNamespace
import pytest
from remotehub import devices, usb_bridge, windows_input
from remotehub.model import Profile
from remotehub.inventory import USBDevice
from remotehub.ui import MainWindow


@pytest.mark.parametrize("serial", ["", "old-receiver"])
def test_mac_helper_receives_only_model(qapp, monkeypatch, tmp_path, serial):
    from PySide6.QtCore import QObject, Signal
    from remotehub import mac_device_helper
    calls=[]
    class Helper(QObject):
        line = Signal(bytes)
        failed = Signal(str)
        def start(self): calls.append("connect fixed receiver")
        def stop(self): return True
    monkeypatch.setattr(devices,"sys",SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(mac_device_helper,"MacDeviceHelper",Helper)
    adapter=devices.DeviceInput();adapter.start(Profile(serial=serial))
    assert calls == ["connect fixed receiver"]  # no serial/path/command in XPC
    adapter.stop()
    with pytest.raises(RuntimeError, match="只支持 USB"):
        adapter.start(Profile(vendor=0x1234))
    assert calls == ["connect fixed receiver"]


def test_windows_uses_vid_pid_without_hid_serial_lookup(qapp,monkeypatch):
    paths={1:r"\\?\hid#vid_0416&pid_0602#new-receiver",2:r"\\?\hid#vid_1234&pid_0602#keyboard"}
    def info(handle,command,buffer,size):
        if buffer is None:size._obj.value=len(paths[handle])+1
        else:buffer.value=paths[handle]
        return len(paths[handle])
    user=SimpleNamespace(RegisterRawInputDevices=lambda *args:True,GetRawInputData=lambda *args:0,GetRawInputDeviceInfoW=info)
    monkeypatch.setattr(windows_input.c,"WinDLL",lambda *args,**kwargs:user,raising=False)
    # Reading HID strings is unnecessary for model matching and may need permissions.
    monkeypatch.setitem(sys.modules,"hid",SimpleNamespace(enumerate=lambda *args:pytest.fail("Unexpected serial lookup")))
    adapter=windows_input.WindowsInput(Profile(serial="old-receiver"),lambda *args:None,lambda *args:None,SimpleNamespace(winId=lambda:123))
    adapter.start()
    try:
        assert adapter._matches(1)
        assert not adapter._matches(2)
    finally:adapter.stop()


def test_usb_bridge_launches_worker_without_serial_or_vendor_library(qapp,monkeypatch,tmp_path):
    calls=[]
    monkeypatch.setattr(usb_bridge,"sys",SimpleNamespace(platform="win32",executable="python"))
    monkeypatch.setattr(usb_bridge.subprocess,"Popen",lambda args,**kwargs:(calls.append(args) or SimpleNamespace(poll=lambda:0)))
    bridge=usb_bridge.USBBridge(SimpleNamespace(owner=None),tmp_path/"runtime")
    try:
        bridge.start()
        assert len(calls)==1 and "--serial" not in calls[0]
        assert "--library" not in calls[0]
    finally:bridge.stop()


def test_voice_ui_accepts_unbound_receiver(qtbot,monkeypatch,tmp_path):
    from PySide6.QtWidgets import QMessageBox
    window=MainWindow(tmp_path,safe=True);qtbot.addWidget(window);c=window.controller
    c.settings['voice_source'] = 'remote'
    c.profile.serial="old-receiver"
    c.monitor.apply([USBDevice(0x0416,0x0602,"","Receiver","port")])
    c.voice.output_id=b"test-output"
    assert not c.settings.get("codec")
    asked=[]
    monkeypatch.setattr(QMessageBox,"question",lambda *args:asked.append(args) or QMessageBox.StandardButton.Yes)
    calls=[];monkeypatch.setattr(c.usb,"start",lambda:calls.append(True))
    monkeypatch.setattr(c.device,"start",lambda *args:None)
    window.voice_page.start_usb()
    assert calls==[True] and len(asked)==(0 if c.usb.collector is not None else 1)
    window.shutdown()
