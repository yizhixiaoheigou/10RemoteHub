"""Read-only macOS symbolic shortcuts, cached until startup/manual refresh.

CGS queries are undocumented: fail visibly if unavailable, never rewrite the
user's shortcut preferences or silently substitute a hard-coded combination.
"""
import ctypes
from functools import lru_cache
import time

# Stable operation IDs preserve imported profiles; "screenshot" remains the
# screenshot/recording toolbar (Shift-Command-5), never the region selector.
OPERATIONS = {
    'dock': (8, '聚焦 Dock'), 'overview': (32, '展示所有窗口'),
    'show_desktop': (36, '显示桌面'),
    'system_search': (64, '打开系统搜索'),
    'next_window': (27, '应用下一窗口'), 'previous_window': (27, '应用上一窗口'),
    'app_overview': (33, '展示当前应用窗口'),
    'space_left': (79, '切换到左侧桌面'), 'space_right': (81, '切换到右侧桌面'),
    'menu_bar': (7, '聚焦菜单栏'), 'status_menu': (57, '聚焦状态菜单'),
    'toggle_dock': (52, '显示 / 隐藏 Dock'),
    'previous_input': (60, '切换到上一输入法'), 'next_input': (61, '切换到下一输入法'),
    'finder_search': (65, '在 Finder 中搜索'),
    'focus_next_window': (9, '聚焦下一个活跃窗口'),
    'focus_toolbar': (10, '聚焦窗口工具栏'), 'focus_floating': (11, '聚焦浮动窗口'),
    'screenshot': (184, '截图与录屏工具栏'),
    'screenshot_region': (30, '区域截图'),
    'screenshot_full': (28, '全屏截图'),
    'screenshot_region_clipboard': (31, '区域截图到剪贴板'),
    'screenshot_full_clipboard': (29, '全屏截图到剪贴板'),
}
GROUPS = (
    ('桌面与窗口', ('overview', 'app_overview', 'show_desktop', 'space_left', 'space_right', 'next_window', 'previous_window')),
    ('导航与搜索', ('dock', 'toggle_dock', 'menu_bar', 'status_menu', 'system_search', 'finder_search')),
    ('输入法', ('previous_input', 'next_input')),
    ('截图与录屏', ('screenshot_region', 'screenshot', 'screenshot_full', 'screenshot_region_clipboard', 'screenshot_full_clipboard')),
    ('高级导航', ('focus_next_window', 'focus_toolbar', 'focus_floating')),
)



@lru_cache(maxsize=1)
def _api():
    library = ctypes.CDLL('/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics')
    query = library.CGSGetSymbolicHotKeyValue
    query.argtypes = [ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint16),
                      ctypes.POINTER(ctypes.c_uint16), ctypes.POINTER(ctypes.c_uint32)]
    query.restype = ctypes.c_int32
    enabled = library.CGSIsSymbolicHotKeyEnabled
    enabled.argtypes = [ctypes.c_uint32]
    enabled.restype = ctypes.c_bool
    return query, enabled


def _query(ident):
    query, enabled = _api()
    equivalent, code, flags = ctypes.c_uint16(), ctypes.c_uint16(), ctypes.c_uint32()
    if query(ident, ctypes.byref(equivalent), ctypes.byref(code), ctypes.byref(flags)):
        raise RuntimeError('macOS 未返回快捷键配置')
    return equivalent.value, code.value, flags.value, enabled(ident)


def resolve(operation):
    ident, title = OPERATIONS[operation]
    equivalent, code, flags, enabled = _query(ident)
    if not enabled:
        raise RuntimeError(f'{title}：系统快捷键已关闭')
    if code == 65535 or (code == 0 and equivalent == 65535):
        raise RuntimeError(f'{title}：系统快捷键未设置')
    if not 0 <= code <= 127:
        raise RuntimeError(f'{title}：不支持的系统按键码 {code}')
    if operation == 'previous_window':
        # macOS uses Shift with the configured forward-window shortcut. If
        # that binding already includes Shift, do not invent a reverse chord.
        if flags & (1 << 17):
            raise RuntimeError(f'{title}：下一窗口快捷键已含 Shift，无法自动推导反向组合')
        flags |= 1 << 17
    return code, flags


def describe(binding):
    code, flags = binding
    keys = {99:'F3', 103:'F11', 126:'↑', 125:'↓', 123:'←', 124:'→',
            49:'Space', 36:'Return', 48:'Tab', 53:'Esc'}
    function_codes = [122,120,99,118,96,97,98,100,101,109,103,111,105,107,113,106,64,79,80,90]
    keys.update({key: f'F{i}' for i,key in enumerate(function_codes,1)})
    if code not in keys:
        # Render the virtual key using the current layout without posting it.
        try:
            import Quartz as q
            from AppKit import NSEvent
            event = q.CGEventCreateKeyboardEvent(None, code, True)
            text = NSEvent.eventWithCGEvent_(event).charactersIgnoringModifiers()
            keys[code] = text.upper() if text and text.isprintable() else f'键码 {code}'
        except Exception:
            keys[code] = f'键码 {code}'
    modifiers = ''.join(symbol for mask,symbol in ((1<<18,'⌃'),(1<<19,'⌥'),(1<<17,'⇧'),(1<<20,'⌘')) if flags & mask)
    return modifiers + keys[code]


class SystemHotkeys:
    def __init__(self, reader=resolve):
        self.reader = reader
        self.bindings = {}
        self.errors = {}
        self.refresh()

    def refresh(self):
        bindings, errors = {}, {}
        for operation in OPERATIONS:
            try:
                bindings[operation] = self.reader(operation)
            except Exception as exc:
                errors[operation] = str(exc)
        self.bindings, self.errors = bindings, errors

    def execute(self, operation, *, log=lambda *args, **kwargs: None):
        if operation in self.errors:
            raise RuntimeError(self.errors[operation] + '；请在系统设置中检查，然后到通用设置重新读取。')
        binding = self.bindings[operation]
        post(binding)
        log('system_hotkey_sent', operation=operation, keycode=binding[0], flags=binding[1])
        return '已请求' + OPERATIONS[operation][1]

    def status(self, operation):
        if operation in self.errors:
            return self.errors[operation]
        return describe(self.bindings[operation])


def post(binding, *, sleeper=time.sleep):
    import Quartz as q
    from ApplicationServices import AXIsProcessTrusted
    if not AXIsProcessTrusted():
        raise PermissionError('请在系统设置中允许本应用的辅助功能权限')
    code, flags = binding
    source = q.CGEventSourceCreate(q.kCGEventSourceStatePrivate)
    def send(key, down, modifiers, modifier=False):
        event = q.CGEventCreateKeyboardEvent(source, key, down)
        if event is None:
            raise RuntimeError('无法创建系统快捷键事件')
        q.CGEventSetFlags(event, modifiers)
        q.CGEventSetIntegerValueField(event, q.kCGEventSourceUserData, 0x52485542)
        if modifier:
            q.CGEventSetType(event, q.kCGEventFlagsChanged)
        q.CGEventPost(q.kCGHIDEventTap, event)
    active = []
    accumulated = 0
    try:
        for mask, key in ((1<<17,56),(1<<18,59),(1<<19,58),(1<<20,55)):
            if flags & mask:
                accumulated |= mask
                active.append((mask,key))
                send(key, True, accumulated, True)
        # Preserve all native flags, notably SecondaryFn (0x800000), on BOTH
        # main-key events. Named-key conversion used to discard this flag.
        send(code, True, flags)
        try:
            sleeper(0.035)
        finally:
            send(code, False, flags)
    finally:
        for mask,key in reversed(active):
            accumulated &= ~mask
            send(key, False, accumulated, True)
