"""Startup registrations stay in temporary directories or a fake registry."""
import sys
import plistlib
import os
import subprocess
from types import SimpleNamespace
import pytest
from remotehub import autostart


def test_registration_is_opt_in_and_disable_preserves_unrelated_files(tmp_path):
    platform="darwin"
    unrelated=tmp_path/"unrelated";unrelated.write_text("keep")
    assert not autostart.is_enabled(platform,tmp_path)
    args=["/applications/test folder/10RemoteHub","--start-hidden"]
    autostart.set_enabled(True,platform=platform,home=tmp_path,arguments=args)
    assert autostart.is_enabled(platform,tmp_path)
    path=autostart.startup_path(platform,tmp_path)
    data=plistlib.loads(path.read_bytes())
    assert data["ProgramArguments"]==args and data["RunAtLoad"]
    assert "KeepAlive" not in data
    autostart.set_enabled(False,platform=platform,home=tmp_path,arguments=args)
    assert not autostart.is_enabled(platform,tmp_path) and unrelated.read_text()=="keep"


@pytest.mark.skipif(sys.platform != "darwin", reason="frozen .app launch path is macOS-only")
def test_frozen_mac_uses_bundle_launch_without_current_cli_flags(monkeypatch):
    monkeypatch.setattr(autostart,"sys",SimpleNamespace(platform="darwin",frozen=True,executable="/Applications/10RemoteHub.app/Contents/MacOS/10RemoteHub"))
    # Not /usr/bin/open: macOS would list the login item as "Open".
    assert autostart.launch_arguments()==["/Applications/10RemoteHub.app/Contents/MacOS/10RemoteHub","--start-hidden"]


def test_mac_login_item_is_attributed_to_the_app(tmp_path):
    args=["/Applications/10RemoteHub.app/Contents/MacOS/10RemoteHub","--start-hidden"]
    autostart.set_enabled(True,platform="darwin",home=tmp_path,arguments=args)
    data=plistlib.loads(autostart.startup_path("darwin",tmp_path).read_bytes())
    assert data["AssociatedBundleIdentifiers"]==["org.remotehub.desktop"]


def test_refresh_upgrades_only_an_enabled_legacy_open_item(tmp_path):
    args=["/Applications/10RemoteHub.app/Contents/MacOS/10RemoteHub","--start-hidden"]
    path=autostart.startup_path("darwin",tmp_path)
    assert not autostart.refresh(platform="darwin",home=tmp_path,arguments=args) and not path.exists()
    legacy={"Label":autostart.IDENTIFIER,"RunAtLoad":True,"LimitLoadToSessionType":"Aqua",
            "ProgramArguments":["/usr/bin/open","-g","-a","/Applications/10RemoteHub.app","--args","--start-hidden"]}
    path.parent.mkdir(parents=True);path.write_bytes(plistlib.dumps(legacy))
    assert autostart.refresh(platform="darwin",home=tmp_path,arguments=args)
    data=plistlib.loads(path.read_bytes())
    assert data["ProgramArguments"]==args and data["AssociatedBundleIdentifiers"]==["org.remotehub.desktop"]
    assert not autostart.refresh(platform="darwin",home=tmp_path,arguments=args)


@pytest.mark.skipif(os.name=="nt",reason="POSIX virtualenv symlinks; Windows venvs use executable copies")
def test_source_startup_keeps_virtualenv_interpreter(monkeypatch,tmp_path):
    base=tmp_path/"base-python";base.touch()
    executable=tmp_path/"venv/bin/python";executable.parent.mkdir(parents=True);executable.symlink_to(base)
    monkeypatch.setattr(autostart,"sys",SimpleNamespace(platform="darwin",executable=str(executable)))
    args=autostart.launch_arguments()
    assert args[0]==str(executable) and args[-1]=="--start-hidden"
    assert args[1].endswith("desktop/entry.py")


class Registry:
    HKEY_CURRENT_USER=1;REG_SZ=1;KEY_SET_VALUE=2
    def __init__(self):self.values={"unrelated":("keep",1)}
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def OpenKey(self,hive,path,*args):
        assert hive==self.HKEY_CURRENT_USER and path==autostart.RUN_KEY
        return self
    CreateKey=OpenKey
    def QueryValueEx(self,key,name):
        if name not in self.values:raise FileNotFoundError(name)
        return self.values[name]
    def SetValueEx(self,key,name,reserved,kind,value):self.values[name]=(value,kind)
    def DeleteValue(self,key,name):self.values.pop(name,None)


def test_windows_changes_only_this_apps_per_user_run_value():
    registry=Registry();args=[r"C:\Program Files\10RemoteHub\10RemoteHub.exe","--start-hidden"]
    assert not autostart.is_enabled("win32",registry=registry)
    autostart.set_enabled(True,platform="win32",arguments=args,registry=registry)
    assert autostart.is_enabled("win32",registry=registry)
    assert registry.values[autostart.IDENTIFIER][0]==subprocess.list2cmdline(args)
    autostart.set_enabled(False,platform="win32",registry=registry)
    assert registry.values=={"unrelated":("keep",1)}


def test_startup_ui_never_enables_on_load_and_reverts_failed_change(qtbot,tmp_path,monkeypatch):
    from remotehub.ui import MainWindow
    calls=[]
    monkeypatch.setattr(autostart,"is_enabled",lambda:False)
    def fail(enabled):calls.append(enabled);raise PermissionError("denied")
    monkeypatch.setattr(autostart,"set_enabled",fail)
    window=MainWindow(tmp_path,safe=True);qtbot.addWidget(window)
    page=window.general
    assert not calls and not page.start_at_login.isChecked()
    page.start_at_login.click()
    assert calls==[True] and not page.start_at_login.isChecked()
    assert "失败" in page.startup_status.text()
    window.shutdown()
