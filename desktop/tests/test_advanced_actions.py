from types import SimpleNamespace

import pytest

from remotehub.actions import KeyOutput, is_repeatable
from remotehub.common_actions import common_keys
from remotehub.controller import AppController
from remotehub.gestures import KeyGesture
from remotehub.model import Action, Button, Profile


@pytest.fixture
def controller(qapp, tmp_path):
    c = AppController(tmp_path)
    yield c
    c.shutdown()


def events(controller, monkeypatch):
    calls = []
    monkeypatch.setattr(controller.runner, 'run', lambda action, down=True: calls.append((action, down)))
    return calls


def test_three_action_model_round_trip_and_legacy_default():
    button = Button(action=Action('common', target='copy'),
                    double_action=Action('common', target='play_pause'),
                    long_action=Action('common', target='volume_up'))
    assert Profile.loads(Profile(buttons=[button]).dumps()).buttons[0] == button
    legacy = Button(action=Action('common', target='paste'))
    assert legacy.double_action.kind == legacy.long_action.kind == 'none'
    assert not KeyGesture.needed(legacy)


def test_media_and_scroll_use_platform_backends(monkeypatch):
    calls = []
    output = KeyOutput()
    output.controller = SimpleNamespace(
        press=lambda key: calls.append(('press', key)),
        release=lambda key: calls.append(('release', key)),
        scroll=lambda x, y: calls.append(('scroll', x, y)))
    output.key_enum = SimpleNamespace(media_play_pause='play', media_volume_up='volume')
    monkeypatch.setattr('remotehub.actions.sys.platform', 'win32')
    output.media('play_pause')
    output.scroll('scroll_down')
    assert calls == [('press', 'play'), ('release', 'play'), ('scroll', 0, -3)]


def test_new_common_shortcuts():
    assert common_keys('page_up', 'darwin') == ['pageup']
    assert common_keys('lock_screen', 'darwin') == ['ctrl', 'cmd', 'q']
    assert common_keys('fullscreen', 'win32') == ['f11']
    assert common_keys('hide_current_app', 'win32') == ['cmd', 'down']


def test_repeat_is_limited_to_safe_actions(controller, monkeypatch):
    calls = events(controller, monkeypatch)
    assert controller.assign(Action('common', target='scroll_up'))
    trigger = controller.selected.trigger
    controller.on_key(trigger, True)
    controller.on_key(trigger, True)
    controller.on_key(trigger, False)
    assert [action.target for action, down in calls if down] == ['scroll_up', 'scroll_up']
    assert is_repeatable(Action('shortcut', keys=['down']))
    assert not is_repeatable(Action('close_window'))


def test_dangerous_action_does_not_repeat(controller, monkeypatch):
    calls = events(controller, monkeypatch)
    assert controller.assign(Action('close_window'))
    trigger = controller.selected.trigger
    for down in (True, True, False):
        controller.on_key(trigger, down)
    assert sum(down for _, down in calls) == 1


def test_double_click_waits_for_single_and_suppresses_duplicate_single(controller, monkeypatch):
    calls = events(controller, monkeypatch)
    button = controller.selected
    button.action = Action('common', target='copy')
    button.double_action = Action('common', target='play_pause')
    trigger = button.trigger
    controller.on_key(trigger, True)
    controller.on_key(trigger, False)
    assert calls == []
    controller.gestures[trigger].single_timer.timeout.emit()
    assert [action.target for action, _ in calls] == ['copy']
    controller.on_key(trigger, True)
    controller.on_key(trigger, False)
    controller.on_key(trigger, True)
    controller.on_key(trigger, False)
    assert [action.target for action, _ in calls] == ['copy', 'play_pause']


def test_long_press_fires_once_and_short_release_uses_single(controller, monkeypatch):
    calls = events(controller, monkeypatch)
    button = controller.selected
    button.action = Action('common', target='copy')
    button.long_action = Action('common', target='volume_up')
    trigger = button.trigger
    controller.on_key(trigger, True)
    controller.gestures[trigger].long_timer.timeout.emit()
    controller.on_key(trigger, True)
    controller.on_key(trigger, False)
    assert [action.target for action, _ in calls] == ['volume_up']
    controller.on_key(trigger, True)
    controller.on_key(trigger, False)
    assert [action.target for action, _ in calls] == ['volume_up', 'copy']


def test_inspector_edits_double_and_long_actions(qtbot, tmp_path):
    from remotehub.ui import MainWindow

    window = MainWindow(tmp_path, safe=True)
    qtbot.addWidget(window)
    window.show()
    controller, inspector = window.controller, window.inspector
    inspector.choose_kind('shortcut')
    assert 30 <= inspector.pages.height() < 70
    assert inspector.sequence.isVisible()
    assert '当前编辑：单击动作' in inspector.gesture_hint.text()
    assert inspector.clear_current.text() == '清除单击映射'
    inspector.set_gesture('double')
    assert inspector.clear_current.text() == '清除双击映射'
    inspector.choose_kind('common:play_pause')
    assert controller.selected.action.kind == 'none'
    assert controller.selected.double_action == Action('common', target='play_pause')
    inspector.set_gesture('long')
    inspector.choose_kind('common:volume_up')
    assert controller.selected.long_action == Action('common', target='volume_up')
    assert controller.assigned_count() == (1, 27)
    assert '双击' in window.canvas.callouts[controller.selected_id].toolTip()
    inspector.clear_current.click()
    assert controller.selected.long_action.kind == 'none'
    assert controller.undo_action()
    assert controller.selected.long_action == Action('common', target='volume_up')
    controller.select('tv-voice')
    assert inspector.gesture == 'single'
    assert not inspector.gesture_buttons['double'].isEnabled()
    assert not inspector.gesture_buttons['long'].isEnabled()
    window.shutdown()
