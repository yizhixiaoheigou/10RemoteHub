"""AppController rules without a window. No device, USB or OS action runs."""
import json
import pytest
from remotehub.controller import AppController
from remotehub.model import Action
from remotehub.presentation import action_text, key_label
from remotehub.store import ConfigStore


@pytest.fixture
def ctl(qapp, tmp_path):
    c = AppController(tmp_path)
    yield c
    c.shutdown()


def test_store_round_trip_keeps_file_format(tmp_path):
    store = ConfigStore(tmp_path)
    store.load()
    store.profiles[0].buttons[5].action = Action("shortcut", ["cmd", "c"])
    store.settings["voice_keys"] = "alt"
    store.save()
    data = json.loads((tmp_path / "profiles.json").read_text())
    assert set(data) == {"version", "profiles", "settings"} and data["version"] == 1
    again = ConfigStore(tmp_path)
    again.load()
    assert not again.load_error and again.profiles == store.profiles


def test_blocked_keys_cannot_be_selected_and_messages_report_saves(ctl):
    seen = []
    ctl.message.connect(lambda text, error: seen.append((text, error)))
    first = ctl.selected_id
    ctl.select("tv-power")
    assert ctl.selected_id == first
    assert ctl.assign(Action("close_window"))
    assert seen[-1][1] is False and "已保存" in seen[-1][0]
    assert not ctl.assign(Action("shortcut", []))
    assert seen[-1][1] is True and ctl.selected.action.kind == "close_window"


def test_rename_and_rect_are_validated(ctl):
    name = ctl.selected.name
    ctl.rename("   ")
    assert ctl.selected.name == name
    ctl.rename("  确认  ")
    assert ctl.selected.name == "确认"
    ctl.set_rect([1.2, -0.5, 0.5, 2])
    x, y, w, h = ctl.selected.rect
    assert x == .99 and y == 0 and w == pytest.approx(.01) and h == 1
    ctl.profile.validate()


def test_failed_mapping_save_keeps_previous_action_and_can_retry(ctl, monkeypatch):
    assert ctl.assign(Action("close_window"))
    original = ctl.selected.action
    saved = ctl.store.path.read_bytes()
    messages = []
    ctl.message.connect(lambda text, error: messages.append((text, error)))
    with monkeypatch.context() as patch:
        def disk_full():
            raise OSError("disk full")
        patch.setattr(ctl.store, "save", disk_full)
        assert not ctl.clear_action()
        assert ctl.selected.action == original
        assert ctl.store.path.read_bytes() == saved
        assert messages[-1] == ("disk full", True)
    assert ctl.clear_action()
    again = ConfigStore(ctl.store.directory)
    again.load()
    assert again.profiles[0].buttons == ctl.profile.buttons


def test_delayed_test_counts_down_runs_once_and_can_cancel(ctl, monkeypatch):
    runs, ticks = [], []
    monkeypatch.setattr(ctl.runner, "run", lambda action, down=True: runs.append(action))
    ctl.test_pending.connect(ticks.append)
    ctl.assign(Action("shortcut", ["ctrl", "a"]))
    ctl.schedule_test()
    for _ in range(3):
        ctl._test_tick()
    assert ticks == [3, 2, 1, 0] and len(runs) == 1 and not ctl.test_timer.isActive()
    ctl.schedule_test()
    ctl.cancel_test()
    assert not ctl.test_timer.isActive() and ticks[-1] == 0 and len(runs) == 1


def test_voice_actions_are_not_run_by_delayed_test(ctl, monkeypatch):
    runs = []
    monkeypatch.setattr(ctl.runner, "run", lambda *a: runs.append(a))
    ctl.assign(Action("voice"))
    ctl.schedule_test()
    assert not ctl.test_timer.isActive() and not runs


@pytest.mark.parametrize('hidden,terminated,expired,expected', [
    (True, False, False, ('已收起应用', False)),
    (False, False, True, ('未确认应用已收起，请检查目标窗口', True)),
    (False, True, False, ('目标应用已退出，无法确认收起结果', True)),
])
def test_hide_feedback_waits_for_state_and_cleans_up(ctl, monkeypatch, hidden, terminated, expired, expected):
    from types import SimpleNamespace
    from remotehub.windows import MacWindows
    from remotehub.windows import Window
    state = {'hidden': False, 'terminated': False}
    app = SimpleNamespace(hide=lambda: False, isHidden=lambda: state['hidden'],
                          isTerminated=lambda: state['terminated'])
    result = MacWindows.__new__(MacWindows).hide(Window(app, 123, '/Example.app'))
    monkeypatch.setattr(ctl.runner, 'run', lambda action, down=True: result if down else None)
    button = next(b for b in ctl.profile.buttons if b.id == 'tv-number-1')
    seen = []
    ctl.message.connect(lambda text, error: seen.append((text, error)))
    ctl.on_key(button.trigger, True)
    ctl.on_key(button.trigger, False)
    assert seen == [('已请求收起应用', False)]
    assert ctl.hide_timer.isActive()
    state.update(hidden=hidden, terminated=terminated)
    if expired:
        ctl.hide_deadline = 0
    ctl._check_hide_result()
    assert seen[-1] == expected
    assert ctl.pending_hide is None and not ctl.hide_timer.isActive()


def test_later_action_cancels_stale_hide_feedback(ctl, monkeypatch):
    from types import SimpleNamespace
    from remotehub.windows import PendingHide
    pending = PendingHide(SimpleNamespace(isHidden=lambda: False, isTerminated=lambda: False))
    ctl._action_feedback(pending)
    seen = []
    ctl.message.connect(lambda text, error: seen.append((text, error)))
    monkeypatch.setattr(ctl.runner, 'run', lambda *args: '已请求显示应用')
    button = next(b for b in ctl.profile.buttons if b.id == 'tv-number-1')
    ctl.on_key(button.trigger, True)
    ctl._check_hide_result()
    assert seen == [('已请求显示应用', False)]
    assert ctl.pending_hide is None and not ctl.hide_timer.isActive()


def test_trigger_only_cannot_be_combined_with_manual_shortcut(qapp, tmp_path):
    from remotehub.ui import MainWindow
    w = MainWindow(tmp_path, safe=True)
    c = w.controller
    c.profile.product = 1  # generic profiles retain the legacy manual mode
    assert c.update_voice(voice_mode="manual")
    assert not c.update_voice(voice_source="trigger")
    w.voice_page.source.setCurrentIndex(w.voice_page.source.findData("trigger"))
    w.voice_page.source_chosen()  # the page switches the mode for the user
    assert c.settings["voice_source"] == "trigger" and c.settings["voice_mode"] == "hold"
    w.shutdown()


def test_voice_settings_reject_bad_values_and_active_session(ctl):
    assert not ctl.update_voice(voice_keys="ctrl+ctrl")
    assert ctl.settings.get("voice_keys", "alt") == "alt"
    assert not ctl.update_voice(gain=99)
    ctl.voice.owner = "usb"
    assert not ctl.update_voice(voice_mode="toggle")
    ctl.voice.owner = None
    assert ctl.update_voice(voice_mode="toggle") and ctl.voice.trigger_mode == "toggle"


def test_usb_preflight_reports_missing_pieces_before_any_takeover(ctl, monkeypatch):
    # This case explicitly models a missing mic, even when one is installed on the test Mac.
    ctl.voice.output_id = b""
    started = []
    monkeypatch.setattr(ctl.usb, "start", lambda: started.append(True))
    ctl.settings["voice_source"] = "trigger"
    with pytest.raises(RuntimeError, match="不需要"):
        ctl.usb_preflight()
    ctl.settings["voice_source"] = "remote"
    with pytest.raises(RuntimeError, match="虚拟麦克风"):
        ctl.usb_preflight()
    assert not started


def test_switching_profile_drops_live_input(ctl, monkeypatch, tmp_path):
    exported = tmp_path / "copy.json"
    ctl.export_profile(exported)
    ctl.import_profile(exported)
    assert len(ctl.profiles) == 2 and ctl.index == 1
    ctl.enabled = True
    stops = []
    monkeypatch.setattr(ctl.device, "stop", lambda: stops.append(1))
    ctl.select_profile(0)
    assert not ctl.enabled and stops and ctl.index == 0


@pytest.mark.parametrize("platform,keys,text", [
    ("darwin", ["cmd", "shift", "4"], "⇧⌘4"),
    ("darwin", ["ctrl", "alt", "left"], "⌃⌥←"),
    ("win32", ["ctrl", "shift", "a"], "Ctrl + Shift + A"),
    ("win32", ["cmd", "e"], "Win + E"),
])
def test_shortcut_labels_follow_host_conventions(platform, keys, text):
    assert key_label(keys, platform) == text


def test_action_text_names_apps_without_bundle_suffix():
    assert action_text(Action("toggle_app", target="/Applications/Safari.app")) == "打开 / 收起 App · Safari"
    assert action_text(Action("common", target="copy"), "darwin") == "复制"
    assert action_text(Action()) == "未设置"


def test_undo_restores_previous_action_and_persists(ctl):
    original = Action("text", text="keep me")
    assert ctl.assign(original)
    assert ctl.clear_action()
    assert ctl.action_undo is not None
    assert ctl.undo_action()
    assert ctl.selected.action == original
    assert ctl.action_undo is None
    again = ConfigStore(ctl.store.directory)
    again.load()
    assert again.profiles[0].buttons == ctl.profile.buttons


def test_profile_import_replace_rename_and_delete(ctl, tmp_path):
    exported = tmp_path / "keys.json"
    ctl.export_profile(exported)
    original_name = ctl.profile.name
    assert ctl.import_profile(exported)
    assert len(ctl.profiles) == 2
    assert ctl.profile.name == original_name + " 2"
    assert ctl.rename_profile("工作布局")
    assert ctl.profile.name == "工作布局"
    current_id = ctl.profile.id
    assert ctl.import_profile(exported, replace=True)
    assert len(ctl.profiles) == 2 and ctl.profile.id == current_id
    assert ctl.profile.name == original_name
    assert ctl.delete_profile()
    assert len(ctl.profiles) == 1
    assert not ctl.delete_profile()
    again = ConfigStore(ctl.store.directory)
    again.load()
    assert len(again.profiles) == 1
