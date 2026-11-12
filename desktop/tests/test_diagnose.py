"""The remote-debugging report is read-only, bounded and safe to send back."""
import json

import remotehub.inventory as inventory
from remotehub.diagnose import build_report, write_report
from remotehub.inventory import USBDevice


def test_report_does_not_export_personal_paths_or_device_identifiers(monkeypatch):
    import sys
    marker = "private-example-person"
    monkeypatch.setattr(sys, "executable", "/Users/" + marker + "/python")
    monkeypatch.setattr(inventory, "list_usb_devices", lambda: [
        USBDevice(0x0416, 0x0602, marker, marker, marker)])
    report = build_report()
    assert marker not in json.dumps(report)
    assert not {"executable", "config_dir", "log_dir"} & report.keys()


def test_report_does_not_export_exception_details(monkeypatch):
    def broken():
        raise OSError("private-example-person and private device path")
    monkeypatch.setattr(inventory, "list_usb_devices", broken)
    assert build_report()["usb_error"] == "OSError"


def test_report_lists_usb_without_keys_audio_or_text(tmp_path, monkeypatch):
    monkeypatch.setattr(inventory, "list_usb_devices",
                        lambda: [USBDevice(0x0416, 0x0602, "receiver", "Receiver", "1-2")])
    report = build_report()
    assert report["product"] == "10RemoteHub" and report["version"]
    assert report["usb"] == [{"vendor": 0x0416, "product": 0x0602, "bcd_device": None}]
    assert not report["usb_error"] and "只读" in report["note"]
    path = write_report(tmp_path / "nested" / "report.json")
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["platform"] == report["platform"] and "log_dir" not in written


def test_usb_failure_is_reported_instead_of_aborting(tmp_path, monkeypatch):
    def broken():
        raise RuntimeError("ioreg failed")
    monkeypatch.setattr(inventory, "list_usb_devices", broken)
    report = build_report()
    assert report["usb"] == [] and report["usb_error"] == "RuntimeError"
    assert json.loads(write_report(tmp_path / "r.json").read_text(encoding="utf-8"))["usb_error"]
