import sys
import pytest
from remotehub.actions import ActionRunner, KeyOutput
from remotehub.app_switcher import AppSwitcher
from remotehub.controller import AppController
from remotehub.holds import InputHolds
from remotehub.model import Action, Button, Profile


@pytest.fixture
def output(qapp):
    keys = KeyOutput()
    events = []
    keys._send = lambda key, down, flags: events.append((key, down, list(flags)))
    keys.sleeper = lambda _: None
    return keys, events


def test_hold_shift_then_direction_preserves_modifier_until_release(output):
    keys, events = output
    runner = ActionRunner(keys)
    action = Action("hold", target="hold", keys=["shift"])
    runner.run(action, True, owner="number-1")
    assert runner.holds.active
    keys.shortcut(["right"])
    assert ("right", True, ["shift", "right"]) in events
    assert ("right", False, ["shift"]) in events
    assert not any(key == "shift" and not down for key, down, _ in events)
    runner.run(action, False, owner="number-1")
    assert events[-1] == ("shift", False, [])
    assert not runner.holds.active


def test_latched_command_survives_physical_release_and_next_press_cancels(output):
    keys, events = output
    runner = ActionRunner(keys)
    action = Action("hold", target="latch", keys=["cmd"])
    runner.run(action, True, owner="number-1")
    runner.run(action, False, owner="number-1")
    assert runner.holds.active
    keys.shortcut(["tab"])
    assert ("tab", True, ["cmd", "tab"]) in events
    runner.run(action, True, owner="number-1")
    assert not runner.holds.active
    assert events[-1] == ("cmd", False, [])


def test_voice_and_mapping_have_independent_modifier_ownership(output):
    keys, events = output
    holds = InputHolds(keys)
    keys.press(["alt"])
    with pytest.raises(RuntimeError, match="另一个动作"):
        holds.hold("number-1", ["alt"])
    holds.hold("number-1", ["cmd"])
    keys.chord(["tab"])
    assert ("tab", True, ["alt", "cmd", "tab"]) in events
    keys.release()
    assert holds.owned("number-1")
    holds.close()
    assert not holds.active and not keys.held


def test_hold_timeout_and_release_cleanup_are_idempotent(output):
    keys, events = output
    holds = InputHolds(keys)
    holds.hold("number-1", ["shift"])
    holds.timers["number-1"].timeout.emit()
    holds.release("number-1")
    holds.close()
    assert not holds.active
    assert events == [("shift", True, ["shift"]), ("shift", False, [])]


def test_owner_can_replace_modifier_without_losing_ownership(output):
    keys, events = output
    holds = InputHolds(keys)
    holds.hold("number-1", ["cmd"])
    holds.hold("number-1", ["shift"])
    assert keys.owned_modifiers("number-1") == {"shift"}
    assert keys.owned_modifiers() == {"shift"}
    holds.close()
    assert not keys.owned_modifiers()


def test_app_switcher_cycles_selects_and_cancels(output):
    keys, events = output
    holds = InputHolds(keys)
    dock = {"count": 0}
    switcher = AppSwitcher(holds, window_counter=lambda: dock["count"], sleeper=lambda _: None)
    switcher.advance("tv-number-3")
    dock["count"] = 1
    switcher.advance("tv-number-3")
    switcher.handle_key("tv-left")
    assert switcher.active
    assert ("tab", True, [switcher.modifier, "shift", "tab"]) in events
    assert not any(key == switcher.modifier and not down for key, down, _ in events)
    assert switcher.handle_key("tv-ok")
    assert not switcher.active
    assert events[-1] == ("alt", False, [])
    if sys.platform == "darwin":
        assert ("alt", True, ["cmd", "alt"]) in events
    dock["count"] = 0
    switcher.advance("tv-number-3")
    dock["count"] = 1
    switcher.handle_key("tv-back")
    assert ("esc", True, [switcher.modifier, "esc"]) in events
    assert ("esc", False, [switcher.modifier]) in events
    assert not switcher.active


def test_switcher_key_release_does_not_advance_again(output):
    keys, events = output
    dock = {"count": 0}
    switcher = AppSwitcher(InputHolds(keys), window_counter=lambda: dock["count"], sleeper=lambda _: None)
    switcher.advance("tv-number-3")
    dock["count"] = 1
    switcher.handle_key("tv-number-3", True)
    switcher.handle_key("tv-number-3", False)
    switcher.handle_key("tv-left", True)
    switcher.handle_key("tv-left", False)
    assert sum(key == "tab" and down for key, down, _ in events) == 3
    switcher.close()


def test_app_switcher_idle_confirms_current_app(output):
    keys, events = output
    switcher = AppSwitcher(InputHolds(keys), window_counter=lambda count=iter([0, 1]): next(count, 1), sleeper=lambda _: None)
    switcher.advance("tv-number-3")
    switcher.holds.timers[switcher.OWNER].timeout.emit()
    assert not switcher.active
    assert events[-1] == ("alt", False, [])
    assert (switcher.modifier, False, []) in events


def test_switcher_does_not_start_during_voice_modifier_hold(output):
    keys, events = output
    switcher = AppSwitcher(InputHolds(keys), window_counter=lambda: 0, sleeper=lambda _: None)
    keys.press(["alt"])
    with pytest.raises(RuntimeError, match="结束语音"):
        switcher.advance("tv-number-3")
    assert not switcher.active
    assert not any(key == "cmd" for key, _, _ in events)
    keys.release()


def test_cancel_does_not_release_unowned_option(output):
    keys, events = output
    switcher = AppSwitcher(InputHolds(keys), window_counter=lambda: 0, sleeper=lambda _: None)
    switcher.advance("tv-number-3")
    switcher.close()
    if sys.platform == "darwin":
        assert not any(key == "alt" and not down for key, down, _ in events)
    else:
        assert events[-1] == ("alt", False, [])


def test_switcher_waits_before_first_tab_and_retries_open(output, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr("remotehub.app_switcher.sys", SimpleNamespace(platform="darwin"))
    keys, events = output
    counts = iter([0, 0, 0])
    sleeps = []
    keys.sleeper = sleeps.append
    switcher = AppSwitcher(InputHolds(keys), window_counter=lambda: next(counts, 0), sleeper=sleeps.append)
    switcher.advance("tv-number-3")
    assert sleeps == [0.08, 0.025]
    switcher.open_timer.timeout.emit()
    assert sleeps == [0.08, 0.025, 0.025]
    assert sum(key == "tab" and down for key, down, _ in events) == 2
    switcher.close()


def test_externally_closed_switcher_releases_without_escape(output):
    keys, events = output
    counts = iter([0, 1, 0])
    switcher = AppSwitcher(InputHolds(keys), window_counter=lambda: next(counts, 0), sleeper=lambda _: None)
    switcher.advance("tv-number-3")
    switcher.open_timer.timeout.emit()
    assert switcher.opened
    switcher.watch.timeout.emit()
    assert not switcher.active
    assert not any(key == "esc" for key, _, _ in events)


def test_only_full_switcher_is_exposed_in_action_palette():
    from remotehub.presentation import palette
    identifiers = {identifier for _, items in palette() for identifier, _ in items}
    assert "common:app_switcher" in identifiers
    assert "hold" not in identifiers and "latch" not in identifiers


def test_hold_configuration_round_trip_and_validation():
    action = Action("hold", target="latch", keys=["cmd"])
    assert Profile.loads(Profile(buttons=[Button(action=action)]).dumps()).buttons[0].action == action
    with pytest.raises(ValueError):
        Action("hold", keys=["right"]).validate()
    with pytest.raises(ValueError):
        Action("hold", target="invalid", keys=["cmd"]).validate()


def test_controller_routes_hold_and_switcher_without_running_other_actions(qtbot, tmp_path):
    c = AppController(tmp_path)
    events = []
    c.keys._send = lambda key, down, flags: events.append((key, down, list(flags)))
    assert c.assign(Action("common", target="app_switcher"))
    trigger = c.selected.trigger
    c.on_key(trigger, True)
    c.on_key(trigger, False)
    assert c.switcher.active
    calls = []
    c.runner.run = lambda *args, **kwargs: calls.append((args, kwargs))
    other = next(b for b in c.configurable_buttons() if b.trigger != trigger)
    c.on_key(other.trigger, True)
    assert not calls and not c.switcher.active
    c.shutdown()


def test_controller_maps_physical_navigation_keys_and_consumes_their_release(qapp, tmp_path):
    c = AppController(tmp_path)
    c.switcher.window_counter = lambda: 0
    c.switcher.sleep = lambda _: None
    events = []
    c.keys.sleeper = lambda _: None
    c.keys._send = lambda key, down, flags: events.append((key, down, list(flags)))
    opener = next(b for b in c.configurable_buttons() if b.id == "tv-number-3")
    c.selected_id = opener.id
    assert c.assign(Action("common", target="app_switcher"))
    right = next(b for b in c.configurable_buttons() if b.id == "tv-right")
    left = next(b for b in c.configurable_buttons() if b.id == "tv-left")
    c.on_key(opener.trigger, True)
    c.on_key(opener.trigger, False)
    c.on_key(right.trigger, True)
    assert c.switcher.active
    assert events[-2:] == [("tab", True, [c.switcher.modifier, "tab"]), ("tab", False, [c.switcher.modifier])]
    c.on_key(right.trigger, True)
    assert sum(key == "tab" and down for key, down, _ in events) == 3
    c.switcher.finish()
    c.on_key(right.trigger, False)
    assert sum(key == "tab" and down for key, down, _ in events) == 3
    c.on_key(opener.trigger, True)
    c.on_key(opener.trigger, False)
    c.on_key(left.trigger, True)
    assert events[-4:] == [("shift", True, [c.switcher.modifier, "shift", "tab"]),
                           ("tab", True, [c.switcher.modifier, "shift", "tab"]),
                           ("tab", False, [c.switcher.modifier, "shift"]),
                           ("shift", False, [c.switcher.modifier])]
    c.on_key(left.trigger, False)
    assert c.switcher.active
    c.shutdown()


def test_plain_language_modifier_editor(qtbot, tmp_path):
    from remotehub.presentation import action_text
    from remotehub.ui import MainWindow

    window = MainWindow(tmp_path, safe=True)
    qtbot.addWidget(window)
    inspector = window.inspector
    inspector.choose_kind("hold")
    index = inspector.modifier.findData("shift")
    inspector.modifier.setCurrentIndex(index)
    inspector.modifier.activated.emit(index)
    assert inspector.current_action == Action("hold", target="hold", keys=["shift"])
    assert "修饰键" not in action_text(inspector.current_action)
    inspector.set_gesture("double")
    inspector.choose_kind("latch")
    index = inspector.modifier.findData("cmd")
    inspector.modifier.setCurrentIndex(index)
    inspector.modifier.activated.emit(index)
    assert inspector.current_action == Action("hold", target="latch", keys=["cmd"])
    assert "再按取消" in action_text(inspector.current_action)
    window.shutdown()


def test_windows_switcher_without_dock_counter_does_not_advance_twice(output, monkeypatch):
    from types import SimpleNamespace
    import remotehub.app_switcher as module
    monkeypatch.setattr(module, 'sys', SimpleNamespace(platform='win32'))
    keys, events = output
    switcher = AppSwitcher(InputHolds(keys), window_counter=lambda: None, sleeper=lambda _: None)
    switcher.advance('menu')
    assert switcher.opened
    assert not switcher.open_timer.isActive()
    assert sum(key == 'tab' and down for key, down, _ in events) == 1
    switcher.cancel()
    assert ('esc', True, ['alt', 'esc']) in events
    assert not switcher.active
