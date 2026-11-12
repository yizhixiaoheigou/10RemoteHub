"""Regressions from the pre-open-source audit. All input and COM calls are fake."""
import io
import json
from pathlib import Path
import pytest
from remotehub.controller import AppController
from remotehub.model import Action

@pytest.fixture
def controller(qapp, tmp_path):
    c = AppController(tmp_path, auto_mapping=False)
    c.keys._send = lambda *args: None
    c.keys.sleeper = lambda _: None
    yield c
    c.shutdown()


def test_delayed_gesture_retains_origin(controller):
    c = controller
    a, b = [x for x in c.configurable_buttons() if x.id in ('tv-number-1', 'tv-number-2')]
    a.action = Action('hold', target='latch', keys=['shift'])
    a.double_action = Action('shortcut', keys=['enter'])
    c.on_key(a.trigger, True); c.on_key(a.trigger, False)
    c.on_key(b.trigger, True); c.on_key(b.trigger, False)
    c.gestures[a.trigger].single_timer.timeout.emit()
    assert c.holds.owned(a.trigger) and not c.holds.owned(b.trigger)


@pytest.mark.parametrize('gesture', ['long', 'double'])
def test_gesture_hold_releases_on_physical_up(controller, gesture):
    c = controller
    a = c.selected
    setattr(a, gesture + '_action', Action('hold', target='hold', keys=['shift']))
    c.on_key(a.trigger, True)
    if gesture == 'long':
        c.gestures[a.trigger].long_timer.timeout.emit()
    else:
        c.on_key(a.trigger, False); c.on_key(a.trigger, True)
    assert c.holds.active
    c.on_key(a.trigger, False)
    assert not c.holds.active


def test_delayed_single_hold_never_latches(controller):
    c = controller
    a = c.selected
    a.action = Action('hold', target='hold', keys=['shift'])
    a.double_action = Action('shortcut', keys=['enter'])
    c.on_key(a.trigger, True); c.on_key(a.trigger, False)
    c.gestures[a.trigger].single_timer.timeout.emit()
    assert not c.holds.active


def test_remapping_releases_old_hold(controller):
    c = controller
    a = c.selected
    a.action = Action('hold', target='hold', keys=['shift'])
    c.on_key(a.trigger, True)
    assert c.assign(Action())
    c.on_key(a.trigger, False)
    assert not c.holds.active


def test_device_stop_cancels_pending_gesture(controller):
    c = controller
    a = c.selected
    a.double_action = Action('shortcut', keys=['enter'])
    c.on_key(a.trigger, True); c.on_key(a.trigger, False)
    g = c.gestures[a.trigger]
    c._device_stopped(c.device.generation)
    assert not g.single_timer.isActive() and not c.gestures



def test_logs_reject_keys_paths_and_unknown_events(controller):
    c = controller
    c.voice.trigger_keys = ['alt', 'q']
    c.voice.start('trigger'); c.voice.finish('trigger')
    c.keys.log('injected_key', key='q', flags=['alt','q'], system_flags=123)
    c.diagnostics.write('win_collector', message='/private/marker hid:7:99')
    c.diagnostics.write('/private/marker', message='secret')
    c.diagnostics.write('capture_failed', message='/private/marker', attempt=3)
    c.diagnostics.handler.flush()
    data = (c.store.directory/'logs/connection.log').read_text()
    assert 'recognition_chord' not in data and 'injected_key' not in data
    assert '/private/marker' not in data and 'hid:7:99' not in data
    assert '"attempt": 3' in data

