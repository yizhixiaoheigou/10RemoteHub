"""Windows voice-interface driver state and the guided binding entry.

Interface 3 must be bound to WinUSB before the collector can claim it. Release
builds will install a Microsoft-signed INF; until then the app detects the state
and can open the bundled Zadig helper, which performs the same libwdi install.
"""
import sys
from pathlib import Path

ENUM_KEY = r"SYSTEM\CurrentControlSet\Enum\USB\VID_0416&PID_0602&MI_03"


def binding_state():
    """'winusb' | 'other' | 'missing' for the receiver's vendor interface."""
    if sys.platform != "win32":
        return "other"
    try:
        import winreg
    except ImportError:
        return "other"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, ENUM_KEY) as key:
            for index in range(winreg.QueryInfoKey(key)[0]):
                instance = winreg.EnumKey(key, index)
                with winreg.OpenKey(key, instance) as sub:
                    try:
                        service = str(winreg.QueryValueEx(sub, "Service")[0])
                    except FileNotFoundError:
                        continue
                    if service:
                        return "winusb" if service.lower() == "winusb" else "other"
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "other"
    return "missing"


def helper_path():
    """Bundled Zadig next to the app (debug builds only)."""
    for base in (Path(sys.executable).parent, Path(__file__).resolve().parent.parent):
        candidate = base / "zadig-2.9.exe"
        if candidate.is_file():
            return candidate
    return None


def launch_helper():
    """Open the binding helper, or the download page when it is not bundled.

    Zadig is GPLv3 and is never redistributed with this project, so most users
    start from the download page and follow the two-step binding in the guide.
    """
    path = helper_path()
    if path is None:
        import webbrowser
        webbrowser.open("https://zadig.akeo.ie/")
        return ("已打开 Zadig 下载页。装好后把 Interface 3 和 Interface 4 都绑定到 WinUSB；"
                "详细步骤见 INSTALL-Windows.md。")
    import ctypes
    result = ctypes.windll.shell32.ShellExecuteW(None, "runas", str(path), None, None, 1)
    if result <= 32:
        raise RuntimeError("无法以管理员身份启动绑定工具")
    return "已打开绑定工具：选 Interface 3，驱动选 WinUSB，点 Replace Driver。"
