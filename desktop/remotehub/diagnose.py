"""Read-only environment report for remote debugging.

Reports OS/build information and supported receiver model IDs. Personal paths,
device names, serials, connection IDs and exception details stay on the machine.
"""
from __future__ import annotations

import json
import platform
import sys
from pathlib import Path

from .branding import APP_NAME


def _version():
    for candidate in (Path(__file__).resolve().parents[1] / "VERSION",
                      Path(getattr(sys, "_MEIPASS", "")) / "VERSION"):
        try:
            if candidate.is_file():
                return candidate.read_text().strip()
        except OSError:
            pass
    return "0"


def build_report():
    from .inventory import list_usb_devices

    report = {
        "product": APP_NAME,
        "version": _version(),
        "platform": sys.platform,
        "release": platform.release(),
        "version_string": platform.version(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "frozen": bool(getattr(sys, "frozen", False)),
        "usb": [],
        "usb_error": "",
        "note": "只读报告；不包含个人路径、设备名称/序列号、按键、音频或识别文字。",
    }
    try:
        report["usb"] = [
            {"vendor": device.vendor, "product": device.product, "bcd_device": device.bcd_device}
            for device in list_usb_devices()]
    except Exception as exc:  # The report must survive a broken inventory call.
        report["usb_error"] = type(exc).__name__
    return report


def write_report(path):
    path = Path(path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    report = build_report()
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
