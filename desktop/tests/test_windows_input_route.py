from remotehub.win_audio_route import WindowsInputRoute


def test_close_restores_saved_roles_and_is_idempotent(qapp, monkeypatch):
    import remotehub.win_audio_route as module
    current = {0: 'cable', 1: 'cable', 2: 'original-communications'}
    writes = []
    monkeypatch.setattr(module, 'current_default', lambda capture, role: current[role])
    def write(endpoint, role):
        writes.append((role, endpoint))
        current[role] = endpoint
    monkeypatch.setattr(module, 'set_endpoint', write)
    route = WindowsInputRoute()
    route.saved = {0: 'original', 1: 'original', 2: 'original-communications'}
    route.targets = {0: 'cable', 1: 'cable', 2: 'original-communications'}
    route.state = 'acquired'
    route.close()
    route.close()
    assert writes == [(0, 'original'), (1, 'original')]
    assert route.state == 'idle' and route.saved == {}


import pytest
from remotehub import win_audio_route as win

@pytest.fixture
def routing(qapp, monkeypatch):
    current = {0:'mic-a', 1:'mic-b', 2:'mic-c'}
    monkeypatch.setattr(win, 'defaults', lambda capture:dict(current))
    monkeypatch.setattr(win, 'current_default', lambda capture, role:current[role])
    monkeypatch.setattr(win, 'set_endpoint', lambda endpoint, role:current.update({role:endpoint}))
    route = win.WindowsInputRoute(find=lambda:'cable')
    yield route, current
    route.close()


def test_com_failure_is_not_success(monkeypatch):
    monkeypatch.setattr(win, '_create', lambda *args:object())
    monkeypatch.setattr(win, '_method', lambda p,i,*args:lambda *a:-2147024891 if i == 13 else 0)
    with pytest.raises(OSError):
        win.set_endpoint('cable', 0)


def test_route_partial_failure_rolls_back_all_changed_roles(routing, monkeypatch):
    route, current = routing
    before = dict(current)
    def set_endpoint(endpoint, role):
        if endpoint == 'cable' and role == 1:
            raise OSError('simulated failure')
        current[role] = endpoint
    monkeypatch.setattr(win, 'set_endpoint', set_endpoint)
    signals=[]
    route.ready.connect(lambda:signals.append('ready'))
    route.failed.connect(lambda _:signals.append('failed'))
    route.acquire()
    assert signals == ['failed'] and current == before and not route.saved


def test_route_requires_readback_confirmation(routing, monkeypatch):
    route, current = routing
    monkeypatch.setattr(win, 'set_endpoint', lambda *args:None)
    ready=[]
    route.ready.connect(lambda:ready.append(True))
    route.acquire()
    assert not ready and route.state != 'acquired'


def test_route_preserves_manual_choice(routing):
    route, current = routing
    route.acquire()
    current[1]='manual-choice'
    route.release()
    assert current == {0:'mic-a', 1:'manual-choice', 2:'mic-c'}


def test_route_restore_failure_is_retryable(routing, monkeypatch):
    route, current = routing
    route.acquire()
    def write(endpoint, role):
        if role == 0:
            raise OSError('restore failed')
        current[role] = endpoint
    monkeypatch.setattr(win, 'set_endpoint', write)
    route.release()
    assert current == {0:'cable', 1:'mic-b', 2:'mic-c'}
    assert route.saved == {0:'mic-a'}
    monkeypatch.setattr(win, 'set_endpoint', lambda e,r:current.update({r:e}))
    route.close()
    assert current[0] == 'mic-a' and not route.saved


def test_route_unreadable_default_does_not_discard_restore_state(routing, monkeypatch):
    route, current = routing
    route.acquire()
    with monkeypatch.context() as patch:
        patch.setattr(win, 'current_default', lambda capture, role:'')
        route.release()
        assert route.saved == {0:'mic-a', 1:'mic-b', 2:'mic-c'}
    route.close()
    assert current == {0:'mic-a', 1:'mic-b', 2:'mic-c'}
