"""User-facing text for actions and keys. Pure functions, no Qt widgets."""
from __future__ import annotations

from pathlib import Path
import sys

from .model import KINDS

# Short labels for the inspector and canvas callouts; KINDS keeps the
# longer names used in older exports.
KIND_TITLES = {
    "text": "输入文本",
    "hold": "按住 Command / Shift 等键",
    "latch": "保持 Command / Shift 等键",
    "shortcut": "按键 / 组合键",
    "app": "打开 App",            # legacy "open only"; no longer offered
    "toggle_app": "打开 / 收起 App",
    "file": "打开文件",
    "minimize_window": "收起当前窗口",
    "close_window": "关闭当前窗口",
    "quit_app": "退出当前应用",
    "voice": "语音输入",
}

KIND_HINTS = {
    "text": "保存后，按遥控器键粘贴到当前光标位置。会更新剪贴板，不额外按回车发送。",
    "none": "这个键还没有动作。从下面选一个，点一下即保存。",
    "shortcut": "点录制框，按下一个键或组合键；松手后自动保存。",
    "app": "旧配置：每次按下都打开这个应用。改用「打开 / 收起 App」可在前台时收起。",
    "toggle_app": "未运行时启动；在后台时显示；已在前台时收起。",
    "file": "用系统默认应用打开，也可以指定打开方式。",
    "minimize_window": "只收起按下时的当前窗口，不关闭它，也不收起应用的其他窗口。",
    "close_window": "关闭按下时的前台窗口，保留应用自己的保存提示。",
    "quit_app": "请求退出按下时的前台应用，不强制结束进程。",
    "voice": "录音方式与识别快捷键在「语音设置」页设置。",
    "common": "使用本机系统默认快捷键；若已自行更改，请改用「按键 / 组合键」。",
    "common:switch_app": "按系统最近使用顺序切换应用；不按 Dock 图标顺序逐个启动。",
    "common:app_switcher": "按一次显示所有应用；继续按切换下一个，停顿 1 秒打开。左右键选择，确定打开，返回取消。",
    "hold": "例如按住 Shift 再按方向键选择文字；松开遥控器按键就放开它。",
    "latch": "例如保持 Command 后按 Tab 选择应用；再按一次取消保持。断连或退出也会取消。",
    "common:previous_app": "按系统应用切换器的反向顺序切换。",
    "common:dock": "把键盘焦点移到 Dock / 任务栏，再用方向键选择、回车打开。",
    "common:system_settings": "打开本机的系统设置。",
    "common:screenshot": "使用本机截图工具；按键可能因系统或应用版本不同。",
}

# Right-hand action palette: every entry is one click. Only shortcut, app and
# file/text need a value afterwards. Common operations resolve per platform.
PALETTE = (
    ("按键与应用", ("shortcut", "text", "toggle_app", "file", "voice")),

    ("窗口", ("minimize_window", "close_window", "quit_app")),
    ("滚动与翻页", ("common:scroll_up", "common:scroll_down", "common:page_up", "common:page_down")),
    ("媒体", ("common:volume_up", "common:volume_down", "common:mute", "common:play_pause",
             "common:previous_track", "common:next_track")),
    ("编辑", ("common:copy", "common:paste", "common:cut", "common:undo",
              "common:select_all", "common:find", "common:save")),
    ("切换与浏览", ("common:app_switcher", "common:switch_app", "common:previous_app", "common:next_window", "common:previous_window",
                   "common:next_tab", "common:previous_tab")),
    ("桌面与窗口总览", ("common:overview", "common:app_overview", "common:show_desktop", "common:space_left", "common:space_right")),
    ("导航与搜索", ("common:dock", "common:toggle_dock", "common:menu_bar", "common:status_menu", "common:system_search", "common:finder_search")),
    ("输入法", ("common:previous_input", "common:next_input")),
    ("截图与录屏", ("common:screenshot_region", "common:screenshot", "common:screenshot_full", "common:screenshot_region_clipboard", "common:screenshot_full_clipboard")),
    ("高级导航", ("common:focus_next_window", "common:focus_toolbar", "common:focus_floating")),
    ("系统", ("common:system_settings", "common:lock_screen", "common:fullscreen", "common:hide_current_app")),
)


def chip_id(action):
    """Palette entry that represents a saved action."""
    if action.kind == "hold":
        return action.target
    return "common:" + action.target if action.kind == "common" else action.kind


def palette(platform=sys.platform):
    """[(group, [(chip id, title)])] for this platform; empty groups dropped."""
    from .common_actions import available_actions
    common = available_actions(platform)
    groups = []
    for group, ids in PALETTE:
        items = []
        for ident in ids:
            if ident.startswith("common:"):
                key = ident.split(":", 1)[1]
                if key in common:
                    items.append((ident, common[key]))
            else:
                items.append((ident, KIND_TITLES[ident]))
        if items:
            groups.append((group, items))
    return groups


def chip_hint(ident):
    if sys.platform == "win32":
        hints = {
            "common:hide_current_app": "发送 Win+↓；最大化窗口先还原，再按可最小化。不是 macOS 的隐藏整个应用。",
            "common:overview": "发送 Win+Tab 打开任务视图。",
            "common:screenshot": "发送 Win+Shift+S 打开截图选区；框选后可粘贴截图。",
            "common:fullscreen": "发送 F11；是否支持全屏由当前应用决定。",
            "quit_app": "请求关闭前台应用同一进程的窗口，保留保存提示；有些应用仍会驻留托盘。",
        }
        if ident in hints:
            return hints[ident]
    from .system_hotkeys import OPERATIONS
    operation = ident.removeprefix("common:")
    if sys.platform == "darwin" and ident.startswith("common:") and operation in OPERATIONS:
        details = {
            "screenshot": "打开截图与录屏工具栏，由你选择截图或录屏，不自动开始录制。",
            "screenshot_region": "进入区域选择，需要鼠标框选；按 Esc 取消。截图保存到系统配置的位置。",
            "screenshot_region_clipboard": "进入区域选择，需要鼠标框选；按 Esc 取消。结果复制到剪贴板。",
            "screenshot_full": "立即截取屏幕，保存到系统配置的位置。",
            "screenshot_full_clipboard": "立即截取屏幕并复制到剪贴板。",
            "dock": "将焦点移到 Dock，方向键选择、回车打开、Esc 退出。",
            "toggle_dock": "切换 Dock 的自动隐藏状态，不是将操作焦点移到 Dock。",
            "space_left": "切换到左侧桌面空间或全屏应用；没有相邻空间时不切换。",
            "space_right": "切换到右侧桌面空间或全屏应用；没有相邻空间时不切换。",
            "app_overview": "只展开前台应用的窗口，不是所有应用的窗口总览。",
            "previous_window": "在已读取的下一窗口组合上加 Shift；无法推导时会显示原因。",
            "previous_input": "切换输入法；需先在 macOS 添加多个输入法。",
            "next_input": "切换输入法；需先在 macOS 添加多个输入法。",
        }
        return details.get(operation, "") + "使用启动时读取的系统快捷键；修改后到「通用设置 → 系统快捷键」重新读取。"
    return KIND_HINTS.get(ident) or (KIND_HINTS["common"] if ident.startswith("common:") else "")


_MAC_GLYPHS = {"cmd": "⌘", "ctrl": "⌃", "alt": "⌥", "shift": "⇧"}
_MAC_ORDER = ("ctrl", "alt", "shift", "cmd")  # Apple HIG modifier order
_PC_NAMES = {"cmd": "Win" if sys.platform == "win32" else "Super", "ctrl": "Ctrl", "alt": "Alt", "shift": "Shift"}
_SPECIAL = {
    "enter": "↩", "esc": "Esc", "tab": "Tab", "space": "Space", "backspace": "⌫",
    "delete": "Del", "insert": "Ins", "home": "Home", "end": "End",
    "pageup": "PgUp", "pagedown": "PgDn", "up": "↑", "down": "↓", "left": "←", "right": "→",
}


def key_label(keys, platform=sys.platform):
    """Render a chord the way the host OS writes it: ⌃⇧A on macOS, Ctrl + Shift + A elsewhere."""
    if not keys:
        return "未录制"
    mods = [k for k in _MAC_ORDER if k in keys]
    rest = [k for k in keys if k not in _MAC_ORDER]
    main = [_SPECIAL.get(k, k.upper()) for k in rest]
    if platform == "darwin":
        return "".join(_MAC_GLYPHS[m] for m in mods) + "".join(main)
    names = {**_PC_NAMES, "cmd": "Win" if platform == "win32" else "Super"}
    return " + ".join([names[m] for m in mods] + main)


def action_text(action, platform=sys.platform):
    if action.kind == "none":
        return "未设置"
    if action.kind == "common":
        from .common_actions import COMMON_ACTIONS, available_actions
        return available_actions(platform).get(action.target, COMMON_ACTIONS.get(action.target, "未选择常见操作"))
    if action.kind == "hold":
        return ("按住 " if action.target == "hold" else "保持 ") + key_label(action.keys, platform) + \
            (" 不放" if action.target == "hold" else "（再按取消）")
    if action.kind == "shortcut":
        return key_label(action.keys, platform)
    if action.kind == "text":
        preview = " ".join(action.text.split())
        return "输入文本 · " + (preview[:32] + "…" if len(preview) > 32 else preview or "空白字符")
    if action.kind in ("app", "toggle_app", "file"):
        name = Path(action.target).name
        if name.endswith(".app"):
            name = name[:-4]
        return KIND_TITLES[action.kind] + " · " + name
    return KIND_TITLES.get(action.kind, KINDS.get(action.kind, "未知动作"))
