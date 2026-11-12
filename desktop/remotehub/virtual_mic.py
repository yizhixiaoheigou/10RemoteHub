"""Managed macOS virtual-microphone component discovery.

Linux 的 PipeWire 版本在 `linux/remotehub_linux/virtual_mic.py`，不在发布范围内。
"""
import sys
from pathlib import Path
from PySide6.QtCore import QObject, Signal
from .branding import BRAND


def is_remotehub_output(device):
    """Only our feed may receive remote audio; never fall back to speakers."""
    return device.description() in {BRAND['microphone_name'], BRAND['audio_feed_name']}


# Windows cannot host a userland virtual microphone (kernel audio drivers need a
# Microsoft signature), so remote audio is played into a signed virtual cable.
WINDOWS_CABLES = ("cable input", "vb-audio", "voicemeeter input", "virtual cable")


def is_windows_cable(device):
    """Render side only: CABLE Output is the capture side the recognizer uses."""
    name = device.description().casefold()
    if "cable output" in name:
        return False
    return any(item in name for item in WINDOWS_CABLES)


def is_voice_output(device):
    """Where remote audio may be played on this platform."""
    return is_windows_cable(device) if sys.platform == "win32" else is_remotehub_output(device)


class VirtualMic(QObject):
    status=Signal(str)
    failed=Signal(str)
    def __init__(self,parent=None):
        super().__init__(parent)

    @staticmethod
    def installed():
        """Installed files are not proof CoreAudio has loaded the device."""
        return sys.platform == "darwin" and Path(
            '/Library/Audio/Plug-Ins/HAL/RemoteHubAudio.driver/Contents/MacOS/RemoteHubAudio'
        ).is_file()

    def stop(self):
        pass
