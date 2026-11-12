import pytest
import sys
from remotehub import system_hotkeys as sh


def test_reads_live_custom_binding_each_time(monkeypatch):
    bindings = iter([(65, 0, 0x120000, True), (65535, 103, 0x800000, True)])
    monkeypatch.setattr(sh, '_query', lambda ident: next(bindings))
    assert sh.resolve('show_desktop') == (0, 0x120000)
    assert sh.resolve('show_desktop') == (103, 0x800000)


@pytest.mark.parametrize('binding', [(65535, 65535, 0, True), (65535, 0, 0, True), (65535, 103, 0, False)])
def test_unset_or_disabled_is_not_sent(monkeypatch, binding):
    monkeypatch.setattr(sh, '_query', lambda ident: binding)
    with pytest.raises(RuntimeError): sh.resolve('show_desktop')


def test_correct_system_ids_and_function_flag(monkeypatch):
    calls = []
    def query(ident):
        calls.append(ident)
        return 65535, 99, 0x840000, True
    monkeypatch.setattr(sh, '_query', query)
    for operation in ('dock', 'overview', 'show_desktop'):
        assert sh.resolve(operation) == (99, 0x840000)
    assert calls == [8, 32, 36]


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS integration")
def test_native_events_keep_function_flag_and_release_modifiers(monkeypatch):
    import Quartz as q
    import ApplicationServices as ax
    monkeypatch.setattr(ax, 'AXIsProcessTrusted', lambda: True)
    events = []
    monkeypatch.setattr(q, 'CGEventPost', lambda tap, event: events.append((q.CGEventGetType(event), q.CGEventGetIntegerValueField(event,q.kCGKeyboardEventKeycode), q.CGEventGetFlags(event))))
    sh.post((99, 0x840000), sleeper=lambda delay: None)
    main = [e for e in events if e[1] == 99]
    assert [e[0] for e in main] == [q.kCGEventKeyDown,q.kCGEventKeyUp]
    assert all(e[2] == 0x840000 for e in main)
    assert events[-1][0] == q.kCGEventFlagsChanged
    assert events[-1][2] == 0


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS integration")
def test_runner_routes_system_actions(qapp, monkeypatch):
    from remotehub.actions import ActionRunner
    from remotehub.model import Action
    calls=[]
    monkeypatch.setattr(sh.SystemHotkeys, 'execute', lambda self, operation, **kwargs: calls.append(operation))
    runner=ActionRunner()
    for operation in sh.OPERATIONS:
        runner.run(Action('common',target=operation))
    assert calls == list(sh.OPERATIONS)
    runner.switcher.close()


def test_cache_reads_only_at_startup_and_explicit_refresh(monkeypatch):
    calls=[]
    def reader(operation):
        calls.append(operation)
        return (103, 0x800000)
    cache=sh.SystemHotkeys(reader)
    monkeypatch.setattr(sh, 'post', lambda binding: None)
    cache.execute('show_desktop')
    cache.execute('show_desktop')
    assert len(calls)==len(sh.OPERATIONS)
    cache.refresh()
    assert len(calls)==2*len(sh.OPERATIONS)


def test_refresh_failure_clears_stale_binding():
    cache=sh.SystemHotkeys(lambda operation: (103, 0x800000))
    def fail(operation): raise RuntimeError('read failed')
    cache.reader=fail
    cache.refresh()
    assert not cache.bindings
    with pytest.raises(RuntimeError, match='read failed'):
        cache.execute('show_desktop')


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS integration")
def test_general_refresh_updates_cache_without_sending_keys(qtbot, tmp_path, monkeypatch):
    from remotehub.ui import MainWindow
    w=MainWindow(tmp_path,safe=True)
    qtbot.addWidget(w)
    calls=[]
    monkeypatch.setattr(sh, 'post', lambda binding: pytest.fail('refresh must not execute actions'))
    cache=w.controller.runner.system_hotkeys
    cache.reader=lambda operation: (calls.append(operation) or (103,0x800000))
    w.general.hotkeys_reload.click()
    assert len(calls)==len(sh.OPERATIONS)
    assert w.general.hotkey_labels['show_desktop'].text()=='F11'
    def disabled(operation): raise RuntimeError('系统快捷键已关闭')
    cache.reader=disabled
    w.general.hotkeys_reload.click()
    assert '已关闭' in w.general.hotkey_labels['show_desktop'].text()
    assert not cache.bindings
    w.shutdown()


def test_screenshot_modes_keep_legacy_toolbar_and_separate_region(monkeypatch):
    calls=[]
    def query(ident):
        calls.append(ident)
        return 65535, ident % 100, 0x120000, True
    monkeypatch.setattr(sh, '_query', query)
    for operation in ('screenshot', 'screenshot_region', 'screenshot_full', 'screenshot_region_clipboard', 'screenshot_full_clipboard'):
        sh.resolve(operation)
    assert calls == [184,30,28,31,29]


def test_expanded_actions_use_custom_settings_and_preserve_native_flags(monkeypatch):
    expected={'system_search':64,'next_window':27,'app_overview':33,
              'space_left':79,'space_right':81,'menu_bar':7,'status_menu':57,
              'toggle_dock':52,'previous_input':60,'next_input':61}
    seen=[]
    monkeypatch.setattr(sh, '_query', lambda ident: (seen.append(ident) or (65,0,0x940000,True)))
    for operation in expected:
        assert sh.resolve(operation)==(0,0x940000)
    assert seen==list(expected.values())


def test_reverse_window_uses_custom_base_and_shift(monkeypatch):
    monkeypatch.setattr(sh,'_query',lambda ident:(65,0,0x140000,True))
    assert sh.resolve('previous_window')==(0,0x160000)


def test_windows_palette_excludes_mac_only_and_preserves_screenshot():
    from remotehub.common_actions import available_actions
    mac, win=available_actions('darwin'),available_actions('win32')
    assert mac['screenshot']=='截图与录屏工具栏'
    assert mac['screenshot_region']=='区域截图'
    assert win['screenshot']=='截图选区'
    assert win['overview']=='任务视图'
    assert win['hide_current_app']=='还原 / 最小化当前窗口'
    for name in ('space_left','app_overview','menu_bar','screenshot_region'):
        assert name in mac and name not in win


def test_every_supported_action_is_visible_once():
    from remotehub.common_actions import available_actions
    from remotehub.presentation import palette
    for platform in ('darwin','win32'):
        ids=[ident for _,items in palette(platform) for ident,_ in items]
        assert len(ids)==len(set(ids))
        assert {x[7:] for x in ids if x.startswith('common:')}==set(available_actions(platform))


def test_legacy_screenshot_profile_keeps_toolbar_behavior():
    from remotehub.model import Action,Button,Profile
    profile=Profile(buttons=[Button(action=Action('common',target='screenshot'))])
    restored=Profile.loads(profile.dumps())
    assert restored.buttons[0].action.target=='screenshot'
    assert sh.OPERATIONS[restored.buttons[0].action.target][0]==184


def test_ambiguous_reverse_window_is_reported_not_guessed(monkeypatch):
    monkeypatch.setattr(sh,'_query',lambda ident:(65,0,0x120000,True))
    assert sh.resolve('next_window')==(0,0x120000)
    with pytest.raises(RuntimeError,match='Shift'):
        sh.resolve('previous_window')


def test_disabled_region_does_not_fallback_to_toolbar(monkeypatch):
    def query(ident):return (65535,21,0x120000,ident!=30)
    monkeypatch.setattr(sh,'_query',query)
    monkeypatch.setattr(sh,'post',lambda binding:pytest.fail('disabled action must not send keys'))
    cache=sh.SystemHotkeys()
    with pytest.raises(RuntimeError,match='已关闭'):
        cache.execute('screenshot_region')
    assert 'screenshot' in cache.bindings


def test_settings_groups_cover_every_cached_action_once():
    ids=[op for _,ops in sh.GROUPS for op in ops]
    assert len(ids)==len(set(ids))
    assert set(ids)==set(sh.OPERATIONS)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows settings UI")
def test_windows_has_no_mac_hotkey_reload(qtbot, tmp_path):
    from remotehub.ui import MainWindow
    w = MainWindow(tmp_path, safe=True)
    qtbot.addWidget(w)
    assert w.controller.runner.system_hotkeys is None
    assert w.general.hotkey_labels == {}
    assert not hasattr(w.general, 'hotkeys_reload')
    w.shutdown()
