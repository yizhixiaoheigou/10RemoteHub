from dataclasses import asdict
import json
from pathlib import Path
import plistlib
from remotehub.inventory import USBDevice,USBMonitor,receiver_name,receiver_state,mac_inventory,windows_inventory
from remotehub.model import Profile,Button,Action,default_profiles
from remotehub.ui import MainWindow

A=USBDevice(0x0416,0x0602,"receiver-1","Receiver","port-1")
B=USBDevice(0x0416,0x0602,"receiver-2","Receiver","port-2")


def test_receiver_name_is_model_id_without_serial_or_promotional_text():
    profile=Profile(serial=A.serial,name="电视语音遥控器")
    actual=USBDevice(A.vendor,A.product,A.serial,"深圳讯飞互动出品 仿冒必究",A.connection)
    assert receiver_name(profile,[actual])=="USB 0416:0602"
    assert receiver_name(profile,[B])=="USB 0416:0602"
    assert receiver_name(profile,[])=="USB 0416:0602"


def test_name_refresh_does_not_interrupt_mapping_or_rewrite_profile(qtbot,tmp_path,monkeypatch):
    w=MainWindow(tmp_path,safe=True);qtbot.addWidget(w);c=w.controller
    monkeypatch.setattr(c,"permission_status",lambda:{"input":"已授权"})
    c.profile.serial=A.serial;c.profile.name="电视语音遥控器"
    calls=[]
    monkeypatch.setattr(c.device,"start",lambda *args:calls.append("start"))
    monkeypatch.setattr(c.device,"stop",lambda:calls.append("stop"))
    c.auto_mapping=True;c.monitor.apply([A]);c.input_ready(c.device.generation)
    c.monitor.apply([A])
    assert w.sidebar.device_name.text()=="USB 0416:0602" and w.sidebar.profile_box.isHidden()
    assert c.profile.name=="电视语音遥控器"
    assert c.enabled and c.keys_ready and calls==["start"]
    assert w.sidebar.status.property("tone")=="ok"
    assert A.serial not in w.sidebar.detail.text()+w.sidebar.device_name.text()+w.inspector.trigger.text()
    from PySide6.QtWidgets import QPushButton
    assert not any("选择接收器" in b.text() for b in w.findChildren(QPushButton))
    w.shutdown()


def test_any_supported_model_works_despite_old_saved_serial():
    profile=Profile(serial="old-disconnected-receiver")
    for devices in ([A],[B],[A,B],[USBDevice(A.vendor,A.product,"","Receiver","port-3")]):
        state=receiver_state(profile,devices,checked=True)
        assert state.code=="detected" and state.usable
        assert "序列号" not in state.detail
    assert receiver_state(profile,[],checked=True).code=="absent"


def test_unsupported_models_and_scan_errors_are_not_enabled():
    other=USBDevice(1,2,"","Other","port-4")
    assert not receiver_state(Profile(),[other],checked=True).usable
    assert receiver_state(Profile(vendor=1,product=2),[other],checked=True).code=="unsupported"
    assert not receiver_state(Profile(),[A],checked=True,error="permission denied").usable


def test_detection_is_not_capture_readiness():
    assert receiver_state(Profile(),[A],checked=True).code=="detected"
    assert receiver_state(Profile(),[A],checked=True,keys_ready=True).code=="keys_ready"
    assert receiver_state(Profile(),[A],checked=True,voice_ready=True).code=="voice_ready"


def test_mac_physical_devices_not_hid_interface_count():
    first={"idVendor":A.vendor,"idProduct":A.product,"USB Serial Number":A.serial,"IORegistryEntryID":10,
        "IORegistryEntryChildren":[{"IORegistryEntryName":"HID interface 1"},{"IORegistryEntryName":"HID interface 2"}]}
    second={**first,"IORegistryEntryID":11}
    devices=mac_inventory(plistlib.dumps([first,second]))
    assert len(devices)==2 and devices[0].connection!=devices[1].connection
    assert receiver_state(Profile(serial=A.serial),devices,checked=True).usable


def test_windows_generated_instance_suffix_is_not_a_serial():
    rows=[{"InstanceId":r"USB\VID_0416&PID_0602\receiver-1"},{"InstanceId":r"USB\VID_0416&PID_0602\6&generated&0&1"},
        {"InstanceId":r"USB\VID_0416&PID_0602&MI_03\6&child"}]
    hid=[{"vendor_id":A.vendor,"product_id":A.product,"serial_number":A.serial}]
    devices=windows_inventory(json.dumps(rows),hid)
    assert len(devices)==2 and devices[0].serial==A.serial and devices[1].serial==""


def test_monitor_scans_in_background_and_stops(qtbot):
    monitor=USBMonitor(enumerate_devices=lambda:[A]); monitor.start()
    qtbot.waitUntil(lambda:monitor.checked)
    assert monitor.devices==[A] and not monitor.error
    monitor.stop(); monitor.apply([B]); assert monitor.devices==[A]


def test_ui_unplug_stops_input_and_replacement_model_needs_no_binding(qtbot,tmp_path,monkeypatch):
    w=MainWindow(tmp_path,safe=True);qtbot.addWidget(w);c=w.controller;c.profile.serial=A.serial
    monkeypatch.setattr(c,"permission_status",lambda:{"input":"已授权"})
    calls=[];monkeypatch.setattr(c.device,"start",lambda *args:calls.append("start"));monkeypatch.setattr(c.device,"stop",lambda:calls.append("stop"))
    c.auto_mapping=True;c.monitor.apply([A]);c.input_ready(c.device.generation)
    assert c.keys_ready and "已接入" in w.sidebar.status.text()
    c.monitor.apply([])
    # A short re-enumeration (voice key, hub reset) must not tear down capture.
    assert c.enabled and calls==["start"]
    c.ABSENCE_GRACE = 0
    c.refresh_device()
    assert not c.enabled and not hasattr(w,"enable") and not hasattr(w.sidebar,"enable")
    assert calls==["start","stop"]
    c.monitor.apply([B]);assert c.enabled
    assert c.profile.serial==A.serial  # Legacy config is harmless and preserved.
    assert calls==["start","stop","start"]
    w.shutdown()


def test_old_m5_configuration_is_backed_up_before_removal(qtbot,tmp_path):
    old=Profile(id="m5",vendor=0x620A,product=0x0407,buttons=[Button(action=Action("shortcut",["ctrl","a"]))])
    original=json.dumps({"profiles":[asdict(old)],"settings":{}})
    path=tmp_path/"profiles.json";path.write_text(original)
    w=MainWindow(tmp_path,safe=True);qtbot.addWidget(w);c=w.controller
    assert len(c.profiles)==1 and c.profile.product==0x0602 and c.profile.image
    assert path.read_text()==original
    c.save();assert next(tmp_path.glob("profiles-before-standalone-*.json")).read_text()==original
    assert len(default_profiles())==1
    w.shutdown()


def test_generated_icons_have_transparency_and_distinct_roles(qapp):
    from remotehub.icons import app_icon,tray_icon,ASSETS
    from PySide6.QtGui import QImage
    import sys
    assert not app_icon().isNull() and not tray_icon().isNull()
    assert tray_icon().isMask()==(sys.platform=="darwin")
    for name in ("app-icon.png","tray-icon.png"):
        image=QImage(str(ASSETS/name))
        assert image.hasAlphaChannel() and image.pixelColor(0,0).alpha()==0
