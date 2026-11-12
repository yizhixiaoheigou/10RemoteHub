import sys
import pytest

pytestmark=pytest.mark.skipif(sys.platform!="darwin",reason="native macOS API verification")


@pytest.mark.parametrize('key,code', [('t', 0x11), ('y', 0x10)])
def test_native_key_events_have_modifiers_without_posting(monkeypatch, key, code):
    import Quartz as q
    import ApplicationServices as ax
    from remotehub.actions import KeyOutput
    events=[]
    monkeypatch.setattr(ax,"AXIsProcessTrusted",lambda:True)
    monkeypatch.setattr(q,"CGEventPost",lambda tap,event:events.append((q.CGEventGetType(event),q.CGEventGetIntegerValueField(event,q.kCGKeyboardEventKeycode),q.CGEventGetFlags(event))))
    # Apple's Events.h defines kVK_ANSI_T=0x11 and kVK_ANSI_Y=0x10.
    output=KeyOutput();output.shortcut(["cmd","shift",key])
    letter=[e for e in events if e[1]==code]
    assert len(letter)==2
    assert all(e[2] & q.kCGEventFlagMaskCommand and e[2] & q.kCGEventFlagMaskShift for e in letter)
    assert events[-1][2]==0 and not output.held


def test_foreground_query_does_not_activate_apps():
    from remotehub.windows import MacWindows
    window=MacWindows().foreground()
    assert window is None or window.pid>0


def test_minimize_sets_only_focused_window_attribute(monkeypatch):
    import ApplicationServices as ax
    from remotehub.windows import MacWindows, Window
    calls=[]
    monkeypatch.setattr(ax,"AXIsProcessTrusted",lambda:True)
    monkeypatch.setattr(ax,"AXUIElementCreateApplication",lambda pid:("app",pid))
    monkeypatch.setattr(ax,"AXUIElementSetMessagingTimeout",lambda *args:0)
    monkeypatch.setattr(ax,"AXUIElementCopyAttributeValue",lambda *args:(0,"focused-window"))
    monkeypatch.setattr(ax,"AXUIElementSetAttributeValue",lambda *args:calls.append(args) or 0)
    MacWindows().minimize(Window(None,123,"example"))
    assert calls==[("focused-window",ax.kAXMinimizedAttribute,True)]


def test_scroll_event_has_expected_direction_without_posting(monkeypatch):
    import Quartz as q
    import ApplicationServices as ax
    from remotehub.actions import KeyOutput
    events = []
    monkeypatch.setattr(ax, 'AXIsProcessTrusted', lambda: True)
    monkeypatch.setattr(q, 'CGEventPost', lambda tap, event: events.append(event))
    KeyOutput().scroll('scroll_up')
    assert len(events) == 1
    assert q.CGEventGetIntegerValueField(events[0], q.kCGScrollWheelEventDeltaAxis1) == 3
