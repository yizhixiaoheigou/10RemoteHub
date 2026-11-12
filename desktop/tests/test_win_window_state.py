from types import SimpleNamespace
from remotehub.windows import WinWindows, Window


def backend(*, iconic=False, zoomed=False, foreground=0, accept=True):
    b = WinWindows.__new__(WinWindows)
    calls = []
    state = {'iconic': iconic, 'zoomed': zoomed, 'foreground': foreground}
    def activate(hwnd):
        calls.append(('activate', hwnd))
        if accept: state['foreground'] = hwnd
        return int(accept)
    def show(hwnd, mode):
        calls.append(('show', hwnd, mode))
        state['iconic'] = mode == 6
        return 1
    b.user = SimpleNamespace(IsIconic=lambda h: state['iconic'], IsZoomed=lambda h: state['zoomed'],
        IsWindow=lambda h: True, ShowWindowAsync=show, SetForegroundWindow=activate,
        GetForegroundWindow=lambda: state['foreground'])
    b.saved_states = {}
    b.log = lambda *a, **k: None
    b._info = lambda h: Window(h, 10, 'app.exe') if h else None
    b._all = lambda: [Window(100, 10, 'app.exe')]
    b._restore_maximized = lambda w: False
    b._activate_attached = lambda h: False
    return b, calls, state


def test_show_does_not_restore_visible_maximized_window():
    b, calls, state = backend(zoomed=True)
    b.show(Window(100, 10, 'app.exe'))
    assert not any(c[0] == 'show' for c in calls)
    assert state['zoomed']


def test_hide_and_show_remembers_maximized_state():
    b, calls, state = backend(zoomed=True, foreground=100)
    result = b.hide(Window(100, 10, 'app.exe'))
    assert result.poll() == ('已收起应用', False)
    b.show(Window(100, 10, 'app.exe'))
    assert ('show', 100, 3) in calls
    assert ('show', 100, 9) not in calls


def test_show_rejection_is_pending_until_real_foreground_matches():
    b, calls, state = backend(accept=False)
    result = b.show(Window(100, 10, 'app.exe'))
    assert result.poll() is None
    message, failed = result.poll(expired=True)
    assert failed and '前台' in message


def test_hide_does_not_claim_success_when_target_remains_visible():
    b, calls, state = backend(foreground=100)
    b.user.ShowWindowAsync = lambda *a: 1
    result = b.hide(Window(100, 10, 'app.exe'))
    assert result.poll() is None
    assert result.poll(expired=True)[1]


def test_show_restores_previously_maximized_external_window():
    b, calls, state = backend(iconic=True)
    b._restore_maximized = lambda w: True
    b.show(Window(100, 10, 'app.exe'))
    assert ('show', 100, 3) in calls


def test_hide_covers_main_windows_in_separate_processes_of_same_app():
    b, calls, state = backend(foreground=100)
    b._all = lambda: [Window(100, 10, 'app.exe'), Window(200, 11, 'app.exe'), Window(300, 12, 'other.exe')]
    b.user.IsIconic = lambda h: False
    result = b.hide(Window(100, 10, 'app.exe'))
    assert [x.handle for x in result.targets] == [100, 200]
    assert ('show', 300, 6) not in calls


def test_verified_foreground_is_success_even_if_api_returned_false():
    b, calls, state = backend(accept=False, foreground=100)
    result = b.show(Window(100, 10, 'app.exe'))
    assert result.poll() == ('已调出应用', False)


def test_attached_activation_always_detaches():
    b, calls, state = backend(accept=False)
    b.c = SimpleNamespace(get_last_error=lambda: 0)
    b.kernel = SimpleNamespace(GetCurrentThreadId=lambda: 1)
    b.user.GetAsyncKeyState = lambda k: 0
    b.user.GetForegroundWindow = lambda: 200
    b.user.GetWindowThreadProcessId = lambda h, p: 2
    b.user.AttachThreadInput = lambda a, c, attach: calls.append(('attach', attach)) or 1
    def fail(h): raise RuntimeError('native call failed')
    b.user.SetForegroundWindow = fail
    import pytest
    with pytest.raises(RuntimeError): WinWindows._activate_attached(b, 100)
    assert calls[-2:] == [('attach', True), ('attach', False)]


def test_attached_activation_does_not_disturb_held_modifier():
    b, calls, state = backend()
    b.user.GetAsyncKeyState = lambda k: 0x8000 if k == 0x12 else 0
    assert not WinWindows._activate_attached(b, 100)
    assert not calls
