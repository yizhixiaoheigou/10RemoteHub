import os
import subprocess
from types import SimpleNamespace
import pytest
from remotehub.windows import Window,WindowController
from remotehub.model import Action,Profile,Button
from remotehub.actions import ActionRunner


def test_mac_hide_false_return_waits_for_actual_state():
    from remotehub.windows import MacWindows, PendingHide
    state = {'hidden': False}
    app = SimpleNamespace(hide=lambda: False, isHidden=lambda: state['hidden'],
                          isTerminated=lambda: False)
    result = MacWindows.__new__(MacWindows).hide(Window(app, 123, '/Example.app'))
    assert isinstance(result, PendingHide)
    assert result.poll() is None  # macOS has not delivered the state update yet
    state['hidden'] = True
    assert result.poll() == ('已收起应用', False)


@pytest.mark.parametrize('terminated,expected', [(False, '未确认应用已收起'), (True, '目标应用已退出')])
def test_mac_hide_does_not_claim_success_when_still_visible(terminated, expected):
    from remotehub.windows import MacWindows
    app = SimpleNamespace(hide=lambda: False, isHidden=lambda: False,
                          isTerminated=lambda: terminated)
    result = MacWindows.__new__(MacWindows).hide(Window(app, 123, '/Example.app'))
    message, error = result.poll(expired=True)
    assert error and expected in message


def test_mac_show_reopens_running_app_without_windows(tmp_path, monkeypatch):
    from remotehub.windows import MacWindows
    app = tmp_path / 'Example App.app'
    app.mkdir()
    from remotehub.launch import LaunchRequest
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: pytest.fail('must not block GUI'))
    backend = MacWindows.__new__(MacWindows)
    result = backend.show(Window(None, 123, str(app)))
    assert isinstance(result, LaunchRequest)
    assert result.command == ['/usr/bin/open', '-a', str(app)]


class Backend:
    def __init__(self):self.matches=[];self.active=None;self.calls=[]
    def find(self,path):return self.matches
    def foreground(self):return self.active
    def hide(self,w):self.calls.append(("hide",w.pid))
    def show(self,w):self.calls.append(("show",w.pid))
    def close(self,w):self.calls.append(("close",w.pid))
    def quit(self,w):self.calls.append(("quit",w.pid))
    def minimize(self,w):self.calls.append(("minimize",w.handle))


def test_app_button_launch_show_hide_and_restore(tmp_path):
    app=tmp_path/"Edge.app";app.mkdir();backend=Backend();controller=WindowController(backend);launch=[]
    controller.toggle(str(app),lambda:launch.append(True));assert launch==[True]
    backend.matches=[Window(1,123,str(app))];backend.active=Window(2,456,"Other.app")
    controller.toggle(str(app),lambda:launch.append(True));assert backend.calls[-1]==("show",123)
    backend.active=backend.matches[0]
    controller.toggle(str(app),lambda:launch.append(True));assert backend.calls[-1]==("hide",123)
    backend.active=Window(2,456,"Other.app")
    controller.toggle(str(app),lambda:launch.append(True));assert backend.calls[-1]==("show",123)
    assert launch==[True]


def test_close_targets_foreground_at_invocation_not_configuration():
    backend=Backend();controller=WindowController(backend)
    backend.active=Window(1,123,"One");controller.close_current()
    backend.active=Window(2,456,"Two");controller.close_current(whole_app=True)
    assert backend.calls==[("close",123),("quit",456)]


def test_no_foreground_and_self_are_not_closed():
    backend=Backend();controller=WindowController(backend)
    with pytest.raises(RuntimeError):controller.close_current()
    backend.active=Window(1,os.getpid(),"RemoteHub")
    with pytest.raises(RuntimeError):controller.close_current(True)
    assert backend.calls==[]


def test_toggle_profile_export_and_import():
    p=Profile(buttons=[Button(action=Action("toggle_app",target="/Applications/Microsoft Edge.app"))])
    assert Profile.loads(p.dumps())==p


def test_window_action_only_on_key_down():
    runner=ActionRunner();backend=Backend();backend.active=Window(1,123,"Edge")
    runner.windows=WindowController(backend)
    runner.run(Action("quit_app"),True);runner.run(Action("quit_app"),False)
    assert backend.calls==[("quit",123)]


def test_minimize_targets_only_current_window_not_other_windows_of_app():
    runner=ActionRunner();backend=Backend()
    backend.matches=[Window(1,123,"Edge"),Window(2,123,"Edge")]
    backend.active=backend.matches[1]
    runner.windows=WindowController(backend)
    runner.run(Action("minimize_window"),True);runner.run(Action("minimize_window"),False)
    assert backend.calls==[("minimize",2)]
