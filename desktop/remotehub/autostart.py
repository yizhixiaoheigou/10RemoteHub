"""Opt-in, per-user login startup. Nothing is written until set_enabled()."""
from pathlib import Path
import plistlib
import subprocess
import sys
from .model import atomic_write

IDENTIFIER = "org.remotehub.desktop"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def launch_arguments():
    # Preserve a virtualenv interpreter symlink in source mode: resolving it
    # would launch the base Python without this project's dependencies.
    executable = Path(sys.executable).absolute()
    if getattr(sys, "frozen", False):
        if sys.platform == "darwin":
            bundle = next((p for p in executable.parents if p.suffix == ".app"), None)
            if bundle is not None:
                # Run the bundle's own signed executable: macOS names a login
                # item after the program it runs, so /usr/bin/open showed "Open".
                return [str(bundle / "Contents/MacOS" / executable.name), "--start-hidden"]
        return [str(executable), "--start-hidden"]
    return [str(executable), str(Path(__file__).resolve().parent.parent / "entry.py"), "--start-hidden"]


def startup_path(platform=None, home=None):
    platform = platform or sys.platform
    home = Path(home) if home is not None else Path.home()
    if platform == "darwin":
        return home / "Library/LaunchAgents" / (IDENTIFIER + ".plist")
    raise ValueError("此平台使用注册表启动项")


def is_enabled(platform=None, home=None, registry=None):
    platform = platform or sys.platform
    if platform == "win32":
        if registry is None:
            import winreg as registry
        try:
            with registry.OpenKey(registry.HKEY_CURRENT_USER, RUN_KEY) as key:
                value, _ = registry.QueryValueEx(key, IDENTIFIER)
                return bool(value)
        except FileNotFoundError:
            return False
    path = startup_path(platform, home)
    if not path.exists():
        return False
    data = plistlib.loads(path.read_bytes())
    return data.get("Label") == IDENTIFIER and data.get("RunAtLoad") is True


def mac_job(arguments):
    # AssociatedBundleIdentifiers lets Login Items show this app's name and
    # icon (same signing team) instead of the program or developer name.
    return {"Label": IDENTIFIER, "ProgramArguments": arguments, "RunAtLoad": True,
            "LimitLoadToSessionType": "Aqua", "AssociatedBundleIdentifiers": [IDENTIFIER]}


def refresh(*, platform=None, home=None, arguments=None):
    """Rewrite an enabled macOS login item made by an older version. Returns True if rewritten."""
    platform = platform or sys.platform
    if platform != "darwin" or not is_enabled(platform, home):
        return False
    arguments = arguments if arguments is not None else launch_arguments()
    path = startup_path(platform, home)
    if plistlib.loads(path.read_bytes()) == mac_job(arguments):
        return False
    atomic_write(path, plistlib.dumps(mac_job(arguments)).decode())
    return True


def set_enabled(enabled, *, platform=None, home=None, arguments=None, registry=None):
    platform = platform or sys.platform
    arguments = arguments if arguments is not None else launch_arguments()
    if platform == "win32":
        if registry is None:
            import winreg as registry
        if enabled:
            command = subprocess.list2cmdline(arguments)
            if len(command) > 260:
                raise ValueError("程序路径过长，Windows 登录启动项限制为 260 字符；请将应用放在较短路径后重试")
            with registry.CreateKey(registry.HKEY_CURRENT_USER, RUN_KEY) as key:
                registry.SetValueEx(key, IDENTIFIER, 0, registry.REG_SZ, command)
        else:
            try:
                with registry.OpenKey(registry.HKEY_CURRENT_USER, RUN_KEY, 0, registry.KEY_SET_VALUE) as key:
                    registry.DeleteValue(key, IDENTIFIER)
            except FileNotFoundError:
                pass
        return
    path = startup_path(platform, home)
    if not enabled:
        path.unlink(missing_ok=True)
        return
    content = plistlib.dumps(mac_job(arguments)).decode()
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, content)
