"""Platform actions. File paths never pass through a shell."""
from __future__ import annotations
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from .model import Action, MODIFIERS, validate_keys
from .branding import APP_NAME
from .launch import LaunchRequest


REPEATABLE_COMMON = {"scroll_up", "scroll_down", "page_up", "page_down", "volume_up", "volume_down"}
REPEATABLE_KEYS = {"up", "down", "left", "right", "pageup", "pagedown"}


def is_repeatable(action):
    if action.kind == "common":
        return action.target in REPEATABLE_COMMON
    if action.kind != "shortcut":
        return False
    main = [key for key in action.keys if key not in MODIFIERS]
    return len(main) == 1 and main[0] in REPEATABLE_KEYS


def launch_command(action: Action, platform=sys.platform):
    action.validate()
    target = Path(action.target).expanduser().absolute()
    if not target.exists():
        raise FileNotFoundError(f"找不到：{target}。文件可能已移动，或磁盘尚未连接。")
    application = Path(action.application).expanduser().absolute() if action.application else None
    if application and not application.exists():
        raise FileNotFoundError(f"指定的打开方式不存在：{application}")
    if platform == "darwin":
        if action.kind == "app":
            return ["/usr/bin/open", "-a", str(target)]
        return ["/usr/bin/open", "-a", str(application), str(target)] if application else ["/usr/bin/open", str(target)]
    if action.kind == "app" or application:
        app = application or target
        return [str(app), str(target)] if application else [str(app)]
    if platform == "win32":
        return None  # ShellExecute through os.startfile, not cmd.exe
    raise RuntimeError("当前版本只支持 macOS 与 Windows")


class KeyOutput:
    def __init__(self, *, sleeper=time.sleep):
        self.sleeper = sleeper
        self.held = []
        self._owners = {}
        self.controller = None
        self.event_source = None

        self.log = lambda event, **fields: None

    def _backend(self):
        if self.controller is None:
            from pynput.keyboard import Controller, Key
            self.controller = Controller()
            self.key_enum = Key
        return self.controller

    def _key(self, name):
        aliases = {"pageup": "page_up", "pagedown": "page_down"}
        return getattr(self.key_enum, aliases.get(name, name), name)

    def _mac(self, name, down, keys):
        import Quartz as q
        from ApplicationServices import AXIsProcessTrusted
        codes = dict(zip("asdfhgzxcvbqwerty", [0,1,2,3,4,5,6,7,8,9,11,12,13,14,15,17,16]))
        codes.update(dict(zip("123465=97-80]ou[ip\nlj'k;\\,/nm.", [18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47])))
        codes.update({"enter":36,"tab":48,"space":49,"`":50,"backspace":51,"esc":53,"cmd":55,"shift":56,"alt":58,"ctrl":59,"delete":117,"insert":114,"home":115,"end":119,"pageup":116,"pagedown":121,"left":123,"right":124,"down":125,"up":126})
        codes.update(dict(zip([f"f{i}" for i in range(1,21)], [122,120,99,118,96,97,98,100,101,109,103,111,105,107,113,106,64,79,80,90])))
        if name not in codes:
            raise ValueError(f"macOS 不支持此键：{name}")
        if not AXIsProcessTrusted():
            raise PermissionError(f"请在系统设置中允许 {APP_NAME} 的辅助功能权限")
        flags = 0
        for k, mask in {"cmd":q.kCGEventFlagMaskCommand,"shift":q.kCGEventFlagMaskShift,"alt":q.kCGEventFlagMaskAlternate,"ctrl":q.kCGEventFlagMaskControl}.items():
            if k in keys:
                flags |= mask
        if self.event_source is None:
            self.event_source = q.CGEventSourceCreate(q.kCGEventSourceStateHIDSystemState)
        event = q.CGEventCreateKeyboardEvent(self.event_source, codes[name], down)
        q.CGEventSetFlags(event, flags)
        q.CGEventSetIntegerValueField(event, q.kCGEventSourceUserData, 0x52485542)
        if name in MODIFIERS:
            q.CGEventSetType(event, q.kCGEventFlagsChanged)
        q.CGEventPost(q.kCGHIDEventTap, event)
        if name in MODIFIERS or name == "tab":
            self.log("injected_key", key=name, down=down, flags=list(keys),
                     system_flags=int(q.CGEventSourceFlagsState(q.kCGEventSourceStateHIDSystemState)))

    def _send(self, key, down, flags):
        if sys.platform == "darwin":
            return self._mac(key, down, flags)
        backend = self._backend()
        if down:
            backend.press(self._key(key))
        else:
            backend.release(self._key(key))

    def owned_modifiers(self, owner=None):
        if owner is not None:
            return set(self._owners.get(owner, set()))
        return {key for keys in self._owners.values() for key in keys}

    def _modifiers(self):
        owned = self.owned_modifiers()
        return [key for key in MODIFIERS if key in owned or key in self.held]

    def hold(self, owner, keys):
        validate_keys(keys, allow_modifier=True, platform=sys.platform)
        if not owner or any(key not in MODIFIERS for key in keys):
            raise ValueError("只能按住修饰键")
        for key in keys:
            if key in self.held or any(key in owned and name != owner for name, owned in self._owners.items()):
                raise RuntimeError("这个修饰键正被另一个动作按住，请先释放")
        for key in list(self._owners.get(owner, set()) - set(keys)):
            self._release_owned_key(owner, key)
        owner_keys = self._owners.setdefault(owner, set())
        for key in keys:
            if key not in owner_keys:
                self._send(key, True, [*self._modifiers(), key])
                owner_keys.add(key)

    def _release_owned_key(self, owner, key):
        owner_keys = self._owners.get(owner, set())
        owner_keys.discard(key)
        if not owner_keys:
            self._owners.pop(owner, None)
        if key not in self.held and not any(key in owned for owned in self._owners.values()):
            self._send(key, False, self._modifiers())

    def release_owned(self, owner):
        errors = []
        for key in list(self._owners.get(owner, set())):
            try:
                self._release_owned_key(owner, key)
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise errors[0]

    def release_all_owned(self):
        errors = []
        for owner in list(self._owners):
            try:
                self.release_owned(owner)
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise errors[0]

    def chord(self, keys, hold_ms=0):
        validate_keys(keys, allow_modifier=True, platform=sys.platform)
        held = self._modifiers()
        flags = held + [key for key in keys if key not in held]
        sent = []
        try:
            for key in keys:
                if key in held:
                    continue
                sent.append(key)
                self._send(key, True, flags)
            if hold_ms:
                self.sleeper(hold_ms / 1000)
        finally:
            for key in reversed(sent):
                sent.remove(key)
                remaining = [flag for flag in held + sent if flag in MODIFIERS]
                self._send(key, False, remaining)

    def press(self, keys):
        validate_keys(keys, allow_modifier=True, platform=sys.platform)
        if self.held or any(key in self.owned_modifiers() for key in keys):
            raise RuntimeError("另一个按键动作尚未释放")
        try:
            for key in keys:
                self.held.append(key)
                self._send(key, True, self._modifiers())
        except Exception:
            self.release()
            raise

    def release(self):
        errors = []
        while self.held:
            key = self.held.pop()
            try:
                self._send(key, False, self._modifiers())
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise errors[0]

    def shortcut(self, keys):
        validate_keys(keys)
        if self.held:
            raise RuntimeError("另一个按键动作尚未释放")
        self.chord(keys)

    def media(self, operation):
        from .common_actions import MEDIA_ACTIONS
        if operation not in MEDIA_ACTIONS:
            raise ValueError("未知媒体操作")
        if sys.platform == "darwin":
            from ApplicationServices import AXIsProcessTrusted
            if not AXIsProcessTrusted():
                raise PermissionError(f"请在系统设置中允许 {APP_NAME} 的辅助功能权限")
        names = {"volume_up": "media_volume_up", "volume_down": "media_volume_down",
                 "mute": "media_volume_mute", "play_pause": "media_play_pause",
                 "previous_track": "media_previous", "next_track": "media_next"}
        backend = self._backend()
        key = getattr(self.key_enum, names[operation])
        backend.press(key)
        backend.release(key)

    def scroll(self, operation, with_held=False):
        if operation not in ("scroll_up", "scroll_down"):
            raise ValueError("未知滚动操作")
        amount = 3 if operation == "scroll_up" else -3
        if sys.platform == "darwin":
            import Quartz as q
            from ApplicationServices import AXIsProcessTrusted
            if not AXIsProcessTrusted():
                raise PermissionError(f"请在系统设置中允许 {APP_NAME} 的辅助功能权限")
            event = q.CGEventCreateScrollWheelEvent(None, q.kCGScrollEventUnitLine, 1, amount)
            if with_held:
                flags = 0
                for key, mask in {"cmd": q.kCGEventFlagMaskCommand, "shift": q.kCGEventFlagMaskShift,
                                  "alt": q.kCGEventFlagMaskAlternate, "ctrl": q.kCGEventFlagMaskControl}.items():
                    if key in self._modifiers():
                        flags |= mask
                q.CGEventSetFlags(event, flags)
            q.CGEventSetIntegerValueField(event, q.kCGEventSourceUserData, 0x52485542)
            q.CGEventPost(q.kCGHIDEventTap, event)
            return
        self._backend().scroll(0, amount)

    def input_text(self, text):
        # One plain-text paste handles Unicode and line breaks across backends.
        # Keep it on the clipboard: timed restoration can race the receiving app.
        from PySide6.QtWidgets import QApplication
        Action("text", text=text).validate()
        if self.held:
            raise RuntimeError("请先结束当前语音输入或按键动作，再输入文本")
        app = QApplication.instance()
        if app is None:
            raise RuntimeError("文本输入需要运行桌面应用")
        app.clipboard().setText(text)
        self.shortcut(["cmd" if sys.platform == "darwin" else "ctrl", "v"])
        return "已请求输入文本"


class ActionRunner:
    def __init__(self, keys=None, voice=None, *, holds=None, switcher=None):
        self.keys = keys or KeyOutput()
        self.voice = voice
        from .holds import InputHolds
        from .app_switcher import AppSwitcher
        self.holds = holds or InputHolds(self.keys)
        self.switcher = switcher or AppSwitcher(self.holds)
        from .windows import WindowController
        self.windows=WindowController()
        self.system_hotkeys = None
        if sys.platform == "darwin":
            from .system_hotkeys import SystemHotkeys
            self.system_hotkeys = SystemHotkeys()

    def run(self, action: Action, down=True, owner="mapping"):
        action.validate(sys.platform)
        if action.kind == "voice":
            if self.voice is None:
                raise RuntimeError("请先配置语音输入")
            return self.voice(down)
        if action.kind == "hold":
            if action.target == "latch":
                if down:
                    self.holds.toggle(owner, action.keys)
            elif down:
                self.holds.hold(owner, action.keys)
            else:
                self.holds.release(owner)
            return
        if not down or action.kind == "none":
            return
        if action.kind == "shortcut":
            return self.keys.shortcut(action.keys)
        if action.kind == "text":
            return self.keys.input_text(action.text)
        if action.kind == "common":
            from .common_actions import MEDIA_ACTIONS, SCROLL_ACTIONS, common_keys, open_system_settings
            if self.system_hotkeys is not None and action.target in self.system_hotkeys.bindings.keys() | self.system_hotkeys.errors.keys():
                if self.keys.held or self.holds.active:
                    raise RuntimeError("请先结束语音输入或释放修饰键，再执行系统快捷键")
                return self.system_hotkeys.execute(action.target, log=self.keys.log)
            if action.target == "app_switcher":
                return self.switcher.advance(owner)
            if action.target == "system_settings":
                return open_system_settings()
            if action.target in MEDIA_ACTIONS:
                return self.keys.media(action.target)
            if action.target in SCROLL_ACTIONS:
                return self.keys.scroll(action.target, with_held=self.holds.active)
            return self.keys.shortcut(common_keys(action.target))
        if action.kind == "minimize_window":
            return self.windows.minimize_current()
        if action.kind == "toggle_app":
            return self.windows.toggle(action.target,lambda:self.run(Action("app",target=action.target)))
        if action.kind in ("close_window","quit_app"):
            return self.windows.close_current(action.kind=="quit_app")
        cmd = launch_command(action)
        if cmd is None:
            os.startfile(str(Path(action.target).expanduser().absolute()))
            return
        if not Path(cmd[0]).is_absolute() and not shutil.which(cmd[0]):
            raise RuntimeError(f"本系统缺少打开工具：{cmd[0]}")
        if sys.platform == "darwin":
            return LaunchRequest(cmd)
        else:
            subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
