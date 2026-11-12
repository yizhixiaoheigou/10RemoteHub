"""Versioned, validated profiles. No OS calls while importing or editing."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import base64
import json
import math
from pathlib import Path
import uuid

KINDS = {"none": "无操作", "shortcut": "按键 / 组合键", "common": "常见操作", "hold": "按住 / 锁定修饰键", "app": "仅打开 App（旧配置）", "toggle_app": "打开 / 收起 App", "file": "打开文件", "minimize_window": "收起当前窗口", "close_window": "关闭当前窗口", "quit_app": "退出当前应用", "voice": "语音输入"}
KINDS["text"] = "输入文本"
MAX_TEXT_LENGTH = 10_000
MODIFIERS = ("ctrl", "alt", "shift", "cmd")
SPECIAL_KEYS = {"enter", "esc", "tab", "space", "backspace", "delete", "insert", "home", "end", "pageup", "pagedown", "up", "down", "left", "right", "print_screen"}
KEYS = set("abcdefghijklmnopqrstuvwxyz0123456789-=[]\\;',./`") | SPECIAL_KEYS | {f"f{i}" for i in range(1, 25)}


def validate_keys(keys: list[str], *, allow_modifier=False, platform=None):
    if not isinstance(keys, list) or not 1 <= len(keys) <= 5 or any(not isinstance(k, str) for k in keys):
        raise ValueError("请选择一个按键或组合键")
    if len(set(keys)) != len(keys) or any(k not in KEYS and k not in MODIFIERS for k in keys):
        raise ValueError("组合键包含重复或不支持的按键")
    main = [k for k in keys if k not in MODIFIERS]
    if len(main) != 1 and not (allow_modifier and not main):
        raise ValueError("组合键需要一个主键；语音触发允许单独修饰键")
    if platform == 'darwin' and any(k in {'f21', 'f22', 'f23', 'f24', 'print_screen'} for k in keys):
        raise ValueError("macOS 不支持这个按键，请选择 F1–F20 或其他按键；截图可使用「截图」动作")


@dataclass
class Action:
    kind: str = "none"
    keys: list[str] = field(default_factory=list)
    target: str = ""
    application: str = ""  # optional app for a file
    text: str = ""  # literal plain text; never interpreted as keys or a command

    def validate(self, platform=None):
        if self.kind not in KINDS:
            raise ValueError("未知动作类型")
        if self.kind == "shortcut":
            validate_keys(self.keys, platform=platform)
        if self.kind == "hold":
            if self.target not in ("hold", "latch"):
                raise ValueError("修饰键保持方式无效")
            if len(self.keys) != 1 or self.keys[0] not in MODIFIERS:
                raise ValueError("只能选择一个修饰键")
            validate_keys(self.keys, allow_modifier=True, platform=platform)
        if self.kind == "text":
            if not isinstance(self.text, str) or not 1 <= len(self.text) <= MAX_TEXT_LENGTH:
                raise ValueError("请输入 1–10000 个字符")
            if any((ord(c) < 32 and c not in "\n\r\t") or 0xD800 <= ord(c) <= 0xDFFF for c in self.text):
                raise ValueError("文本包含不支持的控制字符")
        if self.kind == "common":
            from .common_actions import COMMON_ACTIONS
            if not isinstance(self.target, str) or self.target not in COMMON_ACTIONS:
                raise ValueError("请选择常见操作")
        if self.kind in ("app", "toggle_app", "file") and (not isinstance(self.target, str) or not self.target or "\x00" in self.target):
            raise ValueError("请选择应用或文件")
        if not isinstance(self.application, str) or "\x00" in self.application:
            raise ValueError("打开方式无效")


@dataclass
class Button:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    name: str = "新按钮"
    trigger: str = ""  # stable source id e.g. hid:7:82 / ev:103
    action: Action = field(default_factory=Action)
    double_action: Action = field(default_factory=Action)
    long_action: Action = field(default_factory=Action)
    # Normalized image rect; portable, independent of window DPI/size.
    rect: list[float] = field(default_factory=lambda: [0.35, 0.4, 0.3, 0.12])

    @property
    def configurable(self):
        # Reserved identities in the fixed TV-remote template. These two
        # physical controls remain visible but are excluded by user request.
        return self.id not in ("tv-power", "tv-tv")


@dataclass
class Profile:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    name: str = "新遥控器"
    vendor: int = 0x0416
    product: int = 0x0602
    serial: str = ""  # Legacy export field; runtime matching uses VID/PID only.
    image: str = ""  # base64 PNG, bounded, self-contained export
    buttons: list[Button] = field(default_factory=list)
    version: int = 1

    def validate(self):
        if self.version != 1:
            raise ValueError("不支持的配置版本")
        if not isinstance(self.name, str) or not self.name.strip() or len(self.name) > 100:
            raise ValueError("设备名称应为 1–100 字")
        if any(type(n) is not int or not 0 <= n <= 65535 for n in (self.vendor, self.product)):
            raise ValueError("设备 VID/PID 无效")
        if not isinstance(self.serial, str) or len(self.serial) > 256:
            raise ValueError("设备序列号无效")
        if len(self.buttons) > 128:
            raise ValueError("每个设备最多 128 个按钮")
        ids, triggers = set(), set()
        for button in self.buttons:
            if not isinstance(button.id, str) or not button.id or button.id in ids:
                raise ValueError("按钮标识重复或无效")
            ids.add(button.id)
            if not isinstance(button.name, str) or not button.name.strip() or len(button.name) > 100:
                raise ValueError("按钮名称无效")
            if not isinstance(button.trigger, str) or len(button.trigger) > 200:
                raise ValueError("实体按键标识无效")
            if button.trigger:
                if button.trigger in triggers:
                    raise ValueError("同一实体键不能绑定两个按钮")
                triggers.add(button.trigger)
            if len(button.rect) != 4 or any(type(x) not in (float, int) or not math.isfinite(x) for x in button.rect):
                raise ValueError("图片按钮区域无效")
            x, y, w, h = button.rect
            if not (0 <= x < 1 and 0 <= y < 1 and 0 < w <= 1-x+1e-9 and 0 < h <= 1-y+1e-9):
                raise ValueError("按钮区域超出图片范围")
            for action in (button.action, button.double_action, button.long_action):
                action.validate()
            if any(action.kind == "voice" for action in (button.double_action, button.long_action)):
                raise ValueError("双击和长按不支持语音动作")
        if not isinstance(self.image, str) or len(self.image) > 12_000_000:
            raise ValueError("设备图片过大")
        if self.image:
            raw = base64.b64decode(self.image, validate=True)
            if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError("设备图片应为 PNG")

    def dumps(self):
        self.validate()
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    @classmethod
    def loads(cls, text: str):
        if len(text) > 14_000_000:
            raise ValueError("配置文件过大")
        try:
            data = json.loads(text)
            if not isinstance(data, dict):
                raise ValueError("配置必须是对象")
            buttons = []
            for raw in data.get("buttons", []):
                values = dict(raw)
                for name in ("action", "double_action", "long_action"):
                    values[name] = Action(**raw.get(name, {}))
                buttons.append(Button(**values))
            data["buttons"] = buttons
            profile = cls(**data)
            profile.validate()
            return profile
        except (TypeError, KeyError, AttributeError) as exc:
            raise ValueError("配置结构不正确") from exc


def atomic_write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink()


def default_profiles():
    # Geometry and physical signal table are fixed for the user's TV remote.
    from .photo_template import television_profile
    return [television_profile()]
