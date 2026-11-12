"""Config file ownership: load, validate, migrate and save. No Qt or device/system integration.

The on-disk format is unchanged from the pre-refactor UI:
``{"version": 1, "profiles": [...], "settings": {...}}``.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import uuid

from .model import Profile, atomic_write, default_profiles, validate_keys

MAX_FILE = 30_000_000
MAX_PROFILES = 24
VOICE_MODES = ("hold", "toggle", "manual")      # how the recognition shortcut is sent
VOICE_SOURCES = ("disabled", "remote", "trigger")
RECORD_MODES = ("hold", "toggle")                # how the remote key controls recording
INPUT_ROUTING = ("automatic", "fixed")
LEGACY_M5 = (0x620A, 0x0407)


def validate_settings(settings):
    if not isinstance(settings, dict):
        raise ValueError("设置格式无效")
    if any(not isinstance(settings.get(k, ""), str)
           for k in ("voice_keys", "voice_mode", "voice_source", "record_mode", "input_routing", "output", "codec")):
        raise ValueError("设置字段类型无效")
    gain = settings.get("gain", 12)
    if type(gain) not in (float, int) or not 0 <= gain <= 24:
        raise ValueError("语音增益无效")
    if settings.get("voice_mode", "hold") not in VOICE_MODES:
        raise ValueError("识别模式无效")
    if settings.get("voice_source", "disabled") not in VOICE_SOURCES:
        raise ValueError("语音来源无效")
    if settings.get("record_mode", "hold") not in RECORD_MODES:
        raise ValueError("遥控器录音操作无效")
    if settings.get("input_routing", "automatic") not in INPUT_ROUTING:
        raise ValueError("麦克风连接方式无效")
    validate_keys(settings.get("voice_keys", "alt").split("+"), allow_modifier=True)


def migrate(profiles):
    """Drop retired M5 profiles and refresh the fixed key table.

    Returns (profiles, changed). Only the dedicated voice key's action is fixed.
    """
    from .photo_template import apply_fixed_keys, television_profile
    original = list(profiles)
    profiles = [p for p in profiles if (p.vendor, p.product) != LEGACY_M5]
    keymap_changed = False
    for i, p in enumerate(profiles):
        if (p.vendor, p.product) == (0x0416, 0x0602) and not p.image and not p.buttons:
            replacement = television_profile()
            replacement.id, replacement.serial = p.id, p.serial
            profiles[i] = replacement
        if (p.vendor, p.product) == (0x0416, 0x0602) and p.name == "USB 0416-0602":
            profiles[i].name = "USB 0416:0602"
            keymap_changed = True
        keymap_changed = apply_fixed_keys(profiles[i]) or keymap_changed
    if not profiles:
        profiles = [television_profile()]
    return profiles, profiles != original or keymap_changed


@dataclass
class ConfigStore:
    directory: Path
    profiles: list = field(default_factory=default_profiles)
    settings: dict = field(default_factory=dict)
    load_error: str = ""
    legacy_backup: str | None = None

    @property
    def path(self):
        return self.directory / "profiles.json"

    def load(self):
        """Transactional: on any error keep defaults and refuse later saves."""
        if not self.path.exists():
            return
        try:
            if self.path.stat().st_size > MAX_FILE:
                raise ValueError("配置文件过大")
            text = self.path.read_text(encoding="utf-8")
            data = json.loads(text)
            profiles = [Profile.loads(json.dumps(p)) for p in data["profiles"]]
            if not 1 <= len(profiles) <= MAX_PROFILES:
                raise ValueError("设备配置数量无效")
            settings = data.get("settings", {})
            validate_settings(settings)
            profiles, changed = migrate(profiles)
            from .photo_template import is_fixed_model
            if settings.get("voice_mode") == "manual" and any(is_fixed_model(p) for p in profiles):
                settings["voice_mode"] = "hold"
                changed = True
            if changed:
                self.legacy_backup = text
            self.profiles, self.settings = profiles, settings
        except (json.JSONDecodeError, UnicodeError, KeyError, TypeError, AttributeError):
            self.load_error = "原配置格式不完整或已损坏，未覆盖原文件；请恢复备份或导入有效配置。"
        except OSError:
            self.load_error = "无法读取原配置，未覆盖原文件；请检查文件访问权限和存储空间。"
        except ValueError:
            self.load_error = "原配置内容无效，未覆盖原文件；请恢复备份或导入有效配置。"

    def serialize(self):
        for p in self.profiles:
            p.validate()
        validate_settings(self.settings)
        text = json.dumps({"version": 1, "profiles": [asdict(p) for p in self.profiles],
                           "settings": self.settings}, ensure_ascii=False, indent=2)
        if len(text.encode("utf-8")) > MAX_FILE:
            raise ValueError("配置总量超过 30 MB，请减少图片大小")
        return text

    def save(self):
        """Raises ValueError with a user-facing message; never half-writes."""
        if self.load_error:
            raise ValueError("原配置读取失败，请先导出当前配置并检查原文件；本次不会覆盖")
        text = self.serialize()
        if self.legacy_backup is not None:
            atomic_write(self.directory / ("profiles-before-standalone-" + uuid.uuid4().hex[:8] + ".json"),
                         self.legacy_backup)
            self.legacy_backup = None
        atomic_write(self.path, text)
