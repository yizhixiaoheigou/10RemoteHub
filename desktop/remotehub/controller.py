"""Application state and rules, kept apart from widget layout.

The window builds widgets and forwards user intent here. It never mutates a
Profile or talks to a device itself. Everything below runs without showing a
window; see tests/test_controller.py. Data flow and invariants: ARCHITECTURE.md.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
import sys
import time
import uuid
import wave

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, QTimer, Qt, Signal
from PySide6.QtGui import QImage
from PySide6.QtMultimedia import QMediaDevices

from .actions import ActionRunner, KeyOutput
from .branding import BRAND
from .audio import AudioBridge
from .devices import DeviceInput
from .inventory import USBMonitor, receiver_name, receiver_state
from .model import Action, Button, Profile, atomic_write
from . import autostart, permissions
from .photo_template import apply_fixed_keys, is_fixed_model, is_voice_button
from .presentation import action_text
from .session import VoiceSession
from .store import MAX_PROFILES, ConfigStore, validate_settings
from .usb_bridge import USBBridge
from .virtual_mic import VirtualMic, is_windows_cable, is_voice_output
from .windows import PendingHide
from .launch import Launcher, LaunchRequest
from .diagnostics import Diagnostics

TEST_DELAY = 3  # seconds between "测试" and running the action


@dataclass(frozen=True)
class StatusView:
    """What a status pill shows. tone: neutral | ready | busy | ok | error."""
    title: str
    detail: str = ""
    tone: str = "neutral"
    diagnostic: str = ""
    settings_link: bool = False


def _b64(raw):
    return base64.b64encode(raw).decode()


class AppController(QObject):
    # A dongle that briefly re-enumerates (voice key, hub power event) must not
    # tear down a working capture; only a persistent absence counts as unplugged.
    ABSENCE_GRACE = 3.0
    message = Signal(str, bool)       # text, is_error
    profiles_changed = Signal()       # list or current index changed
    mapping_changed = Signal()        # selection, action, name, rect or photo changed
    physical_key = Signal(str, bool)  # verified key event for first-run feedback
    device_changed = Signal()         # receiver state / enabled / ready changed
    learning_changed = Signal(bool)
    voice_changed = Signal()          # settings, outputs, USB link or session owner changed
    level = Signal(float)
    test_pending = Signal(int)        # seconds left; 0 = idle
    permission_opened = Signal(str)   # Show the companion guide only on user request.
    update_found = Signal(object)     # updates.Update
    update_none = Signal()
    update_error = Signal(str)
    update_downloaded = Signal(str)

    def __init__(self, directory, parent=None, *, auto_mapping=True):
        super().__init__(parent)
        self.store = ConfigStore(Path(directory))
        self.store.load()
        self.diagnostics = Diagnostics(self.store.directory / "logs")
        self.diagnostics.write("app_started")
        self._connection_feedback = False
        self._inventory_signature = None
        self.message.connect(self._feedback_replaced)
        self.index = 0
        self.selected_id = ""
        self.action_undo = None
        self.enabled = False
        self.keys_ready = False
        self.learning = False
        self.pressed = set()
        self.switcher_pressed = set()
        self.gestures = {}
        self.learned_release = None
        self.shutting_down = False
        self.host = None  # widget whose winId() Windows raw input registers on
        # Key input starts by itself when a supported receiver appears. A failed
        # attempt is not retried on every 2 s scan; retry_connection() re-arms it.
        self.auto_mapping = auto_mapping
        self.mapping_attempted = False
        self.mapping_error = ""
        self.transient_error = ""
        self.recovery_attempts = 0
        self.helper_missing = False
        self._absent_since = None
        self.usb_connecting = False
        self.recording_requested = False   # remote key asked for a recording
        self.voice_auto_pending = False    # audio arrived before its physical key
        self.voice_trigger = None          # physical trigger that started it
        self.outputs = []  # [(description, id bytes)]
        self.keys = KeyOutput()
        self.launcher = Launcher(self)
        self.launcher.finished.connect(self.message)
        self.audio = AudioBridge(self)
        route = None
        if auto_mapping and sys.platform == "darwin":
            from .mac_input import MacInputRoute
            route = MacInputRoute(self)
            route.measured.connect(lambda operation, elapsed: self.diagnostics.write(
                "default_input_route", operation=operation, milliseconds=round(elapsed, 1)))
        elif auto_mapping and sys.platform == "win32":
            from .win_audio_route import WindowsInputRoute
            route = WindowsInputRoute(self)
            route.measured.connect(lambda operation, elapsed: self.diagnostics.write(
                "default_input_route", operation=operation, milliseconds=round(elapsed, 1)))
            route.failed.connect(self.fail)
        self.voice = VoiceSession(self.audio, self.keys, self, route=route)
        self.voice.log = self.diagnostics.write
        self.keys.log = self.diagnostics.write
        self.audio.log = self.diagnostics.write
        self.runner = ActionRunner(self.keys, self.voice_button)
        self.runner.windows.log = self.diagnostics.write
        self.switcher = self.runner.switcher
        self.switcher.log = self.diagnostics.write
        self.holds = self.runner.holds
        self.pending_hide = None
        self.hide_timer = QTimer(self)
        self.hide_timer.setInterval(50)
        self.hide_timer.timeout.connect(self._check_hide_result)
        self.device = DeviceInput(self)
        # Both collectors hand decoded frames to the same bridge; Windows no
        # longer needs its separate USB worker once the collector owns the device.
        self.usb = USBBridge(self.voice, self.store.directory / "runtime", self,
                             collector=self.device if sys.platform in ("darwin", "win32") else None,
                             log=self.diagnostics.write)
        self.monitor = USBMonitor(self)
        self.virtual_mic = VirtualMic(self)
        self.microphone_installed = self.virtual_mic.installed()
        self.microphone_watch = QTimer(self)
        self.microphone_watch.setInterval(2000)
        self.microphone_watch.timeout.connect(self._check_microphone_installation)
        if sys.platform == "darwin":
            self.microphone_watch.start()
        self.media_devices = QMediaDevices(self)
        self.media_devices.audioOutputsChanged.connect(self.refresh_outputs)
        self.wav = None
        self.wav_timer = QTimer(self)
        self.wav_timer.setInterval(20)
        self.wav_timer.timeout.connect(self._wav_tick)
        self.test_action = None
        self.test_left = 0
        self.test_timer = QTimer(self)
        self.test_timer.setInterval(1000)
        self.test_timer.timeout.connect(self._test_tick)
        self.recovery_timer = QTimer(self)
        self.recovery_timer.setSingleShot(True)
        self.recovery_timer.setInterval(750)
        self.recovery_timer.timeout.connect(self._recover_transient)

        self.device.key.connect(self.on_key)
        self.usb.key.connect(self.on_key)
        self.device.stopped.connect(self._device_stopped)
        self.device.ready.connect(self.input_ready)
        self.monitor.changed.connect(self._inventory_changed)
        self.usb.changed.connect(self.refresh_device)
        self.usb.changed.connect(self.voice_changed)
        self.usb.started.connect(self._usb_ready)
        self.usb.disconnected.connect(self._usb_released)
        self.usb.recording_stopped.connect(self._recording_stopped)
        self.usb.recording_started.connect(self._recording_started)
        self.device.failed.connect(self._device_failed)
        self.device.log.connect(lambda message: self.diagnostics.write("win_collector", message=message))
        for source in (self.device, self.usb, self.virtual_mic):
            source.status.connect(self.tell)
            if source is not self.device:
                source.failed.connect(self.fail)
        self.audio.changed.connect(self.tell)
        self.audio.level.connect(self.level)
        self.voice.failed.connect(self.fail)
        self.voice.expired.connect(self._voice_expired)
        self.voice.changed.connect(self.voice_changed)
        self.voice.finished.connect(self._voice_finished)

        self._apply_voice_settings()
        self.refresh_outputs()
        self.selected_id = self._default_selection()

    # -- read-only views -----------------------------------------------------

    @property
    def profiles(self):
        return self.store.profiles

    @property
    def settings(self):
        return self.store.settings

    @property
    def load_error(self):
        return self.store.load_error

    @property
    def profile(self) -> Profile:
        return self.profiles[min(max(0, self.index), len(self.profiles) - 1)]

    @property
    def fixed_model(self):
        return is_fixed_model(self.profile)

    @property
    def selected(self) -> Button | None:
        return next((b for b in self.profile.buttons if b.id == self.selected_id and b.configurable), None)

    def configurable_buttons(self):
        return [b for b in self.profile.buttons if b.configurable]

    @property
    def selected_voice_key(self):
        return is_voice_button(self.profile, self.selected)

    def assigned_count(self):
        keys = [b for b in self.configurable_buttons() if not is_voice_button(self.profile, b)]
        return sum(any(action.kind != "none" for action in (b.action, b.double_action, b.long_action))
                   for b in keys), len(keys)

    def profile_names(self):
        return [receiver_name(p, self.monitor.devices) for p in self.profiles]

    # -- feedback & persistence ----------------------------------------------

    def _feedback_replaced(self, text, error):
        self._connection_feedback = False

    def tell(self, text):
        self.message.emit(text, False)

    def fail(self, text):
        self.diagnostics.write("error", kind="application")
        self.message.emit(str(text), True)

    def _cancel_hide_result(self):
        self.hide_timer.stop()
        self.pending_hide = None

    def _action_feedback(self, result):
        if isinstance(result, LaunchRequest):
            self.launcher.start(result)
        elif isinstance(result, PendingHide):
            self.pending_hide = result
            self.hide_deadline = time.monotonic() + 1.0
            self.tell(getattr(result, "request_message", "已请求收起应用"))
            self.hide_timer.start()
        elif isinstance(result, str):
            self.tell(result)

    def _check_hide_result(self):
        if self.pending_hide is None:
            return
        try:
            result = self.pending_hide.poll(expired=time.monotonic() >= self.hide_deadline)
        except Exception as exc:
            result = (f"无法检查收起结果：{exc}", True)
        if result is not None:
            self._cancel_hide_result()
            self.message.emit(*result)

    def save(self):
        try:
            self.store.save()
            return True
        except Exception as exc:
            self.fail(str(exc))
            return False

    # -- profiles --------------------------------------------------------------

    def select_profile(self, index):
        if not 0 <= index < len(self.profiles):
            return
        # Switching devices always drops live input: a mapping must never keep
        # running against a profile the user is no longer looking at.
        self.voice.cancel()
        if self.usb.authenticated:
            self.usb.stop()
        self.set_enabled(False)
        self.set_learning(False)
        self.mapping_attempted = False
        self._clear_gestures()
        self.action_undo = None
        self.index = index
        self.selected_id = self._default_selection(self.selected_id)
        self.profiles_changed.emit()
        self.mapping_changed.emit()
        self.refresh_device()

    def _default_selection(self, preferred=""):
        keys = self.configurable_buttons()
        ids = [b.id for b in keys]
        for candidate in (preferred, "tv-number-1"):
            if candidate in ids:
                return candidate
        return ids[0] if ids else ""

    def _unique_profile_name(self, name):
        names = {p.name for p in self.profiles}
        if name not in names:
            return name
        number = 2
        base = name[:95]
        while f"{base} {number}" in names:
            number += 1
        return f"{base} {number}"

    def import_profile(self, path, replace=False):
        try:
            path = Path(path)
            if path.stat().st_size > 14_000_000:
                raise ValueError("配置文件过大")
            profile = Profile.loads(path.read_text(encoding="utf-8"))
            apply_fixed_keys(profile)
            profile.validate()
            if replace:
                profile.id = self.profile.id
                previous = self.profile
                self.profiles[self.index] = profile
                if not self.save():
                    self.profiles[self.index] = previous
                    return False
                self.select_profile(self.index)
            else:
                profile.id = uuid.uuid4().hex
                profile.name = self._unique_profile_name(profile.name)
                if len(self.profiles) >= MAX_PROFILES:
                    raise ValueError(f"最多保存 {MAX_PROFILES} 个设备配置")
                self.profiles.append(profile)
                if not self.save():
                    self.profiles.pop()
                    return False
                self.select_profile(len(self.profiles) - 1)
            self.tell("按键配置已导入；不会自动启用或执行动作。")
            return True
        except Exception as exc:
            self.fail(str(exc))
            return False

    def rename_profile(self, name):
        name = name.strip()
        if not name or len(name) > 100:
            self.fail("配置名称应为 1–100 字")
            return False
        if name == self.profile.name:
            return True
        previous = self.profile.name
        self.profile.name = name
        if not self.save():
            self.profile.name = previous
            return False
        self.profiles_changed.emit()
        self.tell("配置已重命名。")
        return True

    def delete_profile(self):
        if len(self.profiles) <= 1:
            self.fail("至少需要保留一个按键配置")
            return False
        index = self.index
        removed = self.profiles.pop(index)
        if not self.save():
            self.profiles.insert(index, removed)
            return False
        self.select_profile(min(index, len(self.profiles) - 1))
        self.tell("按键配置已删除。")
        return True

    def export_profile(self, path):
        try:
            atomic_write(Path(path), self.profile.dumps())
            self.tell("按键配置已导出，包含图片与按键动作，不包含语音设置。")
        except Exception as exc:
            self.fail(str(exc))

    # -- mapping ---------------------------------------------------------------

    def select(self, ident):
        """Select a configurable key. Blocked keys (电源/TV) are ignored."""
        button = next((b for b in self.profile.buttons if b.id == ident), None)
        if button is None or not button.configurable or ident == self.selected_id:
            return
        self.selected_id = ident
        self.mapping_changed.emit()

    def assign(self, action: Action, gesture="single"):
        button = self.selected
        fields = {"single": "action", "double": "double_action", "long": "long_action"}
        if gesture not in fields:
            raise ValueError("未知按键手势")
        if button is None:
            self.fail("请先在图上选择一个按键")
            return False
        if self.selected_voice_key and (gesture != "single" or action != Action("voice")):
            self.fail("这个实体语音键固定用于开始和结束语音输入，请在右侧设置麦克风、唤起键和说话方式。")
            return False
        if gesture != "single" and action.kind == "voice":
            self.fail("双击和长按不支持语音动作")
            return False
        try:
            action.validate(sys.platform)
        except ValueError as exc:
            self.fail(str(exc))
            return False
        field = fields[gesture]
        previous = getattr(button, field)
        if action == previous:
            return True
        self._cancel_button_actions(button.trigger)
        setattr(button, field, action)
        if not self.save():
            setattr(button, field, previous)
            self.mapping_changed.emit()
            return False
        self.action_undo = (self.profile.id, button.id, gesture, previous)
        self.mapping_changed.emit()
        prefix = "「" + button.name + "」" + {"single": "", "double": "双击", "long": "长按"}[gesture]
        self.tell(prefix + "已清除动作。" if action.kind == "none"
                  else prefix + " → " + action_text(action) + "，已保存。")
        return True

    def clear_action(self, gesture="single"):
        return self.assign(Action(), gesture)

    def undo_action(self):
        if self.action_undo is None:
            return False
        profile_id, button_id, gesture, previous = self.action_undo
        if self.profile.id != profile_id:
            return False
        button = next((b for b in self.profile.buttons if b.id == button_id), None)
        if button is None:
            self.action_undo = None
            self.mapping_changed.emit()
            return False
        field = {"single": "action", "double": "double_action", "long": "long_action"}[gesture]
        current = getattr(button, field)
        self._cancel_button_actions(button.trigger)
        setattr(button, field, previous)
        if not self.save():
            setattr(button, field, current)
            return False
        self.action_undo = None
        self.selected_id = button.id
        self.mapping_changed.emit()
        self.tell(f"已撤销「{button.name}」的上一次动作修改。")
        return True

    def rename(self, name):
        button = self.selected
        name = name.strip()
        if button is None or name == button.name:
            return
        if not name or len(name) > 100:
            self.fail("按键名称应为 1–100 字")
            self.mapping_changed.emit()  # put the old name back in the field
            return
        previous = button.name
        button.name = name
        if not self.save():
            button.name = previous
        self.mapping_changed.emit()

    def set_rect(self, rect):
        button = self.selected
        if button is None:
            return
        x = min(max(0.0, rect[0]), .99)
        y = min(max(0.0, rect[1]), .99)
        w = max(.01, min(rect[2], 1 - x))
        h = max(.01, min(rect[3], 1 - y))
        rect = [x, y, w, h]
        if rect == button.rect:
            return
        previous = button.rect
        button.rect = rect
        if not self.save():
            button.rect = previous
        self.mapping_changed.emit()

    def add_button(self):
        if len(self.profile.buttons) >= 128:
            self.fail("每个设备最多 128 个按键")
            return None
        button = Button(name=f"按键 {len(self.profile.buttons) + 1}")
        self.profile.buttons.append(button)
        if not self.save():
            self.profile.buttons.pop()
            return None
        self.selected_id = button.id
        self.mapping_changed.emit()
        return button

    def remove_button(self):
        button = self.selected
        if button is None:
            return
        previous = self.profile.buttons
        self.profile.buttons = [b for b in previous if b.id != button.id]
        if not self.save():
            self.profile.buttons = previous
            return
        self.selected_id = self._default_selection()
        self.mapping_changed.emit()

    def replace_photo(self, path):
        try:
            if Path(path).stat().st_size > 20_000_000:
                raise ValueError("请选择小于 20 MB 的照片")
            image = QImage(str(path))
            if image.isNull():
                raise ValueError("图片无法读取")
            if max(image.width(), image.height()) > 1600:
                image = image.scaled(1600, 1600, Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation)
            data = QByteArray()
            buffer = QBuffer(data)
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            image.save(buffer, "PNG")
            previous = self.profile.image
            self.profile.image = _b64(bytes(data))
            if not self.save():
                self.profile.image = previous
                return
        except Exception as exc:
            self.fail(str(exc))
            return
        self.mapping_changed.emit()
        self.tell("照片已替换。请检查按键位置，必要时在「名称与位置」里重新框选。")

    # -- device state ------------------------------------------------------------

    def _state(self):
        return receiver_state(self.profile, self.monitor.devices, checked=self.monitor.checked,
                              error=self.monitor.error, keys_ready=self.keys_ready, voice_ready=self.usb.ready)

    def _collector_missing(self):
        if sys.platform != "darwin":
            return False
        try:
            from .mac_device_helper import installation_status
            return installation_status()[0] == 1
        except Exception:
            return False

    def device_view(self) -> StatusView:
        state = self._state()
        if not state.usable:
            if self.monitor.error:
                return StatusView(state.title, "无法读取系统 USB 设备清单，请点「重新检测」。详情见通用设置。",
                                  "error", self.monitor.error, True)
            return StatusView(state.title, state.detail)
        if self.transient_error:
            return StatusView("正在重新连接", "USB 读取暂时中断，正在恢复按键映射。", "busy")
        if self.helper_missing and not self.enabled and not self.mapping_error:
            return StatusView("遥控器已接入，采集组件未安装",
                              "安装读取组件后才能读取按键和声音。",
                              "ready")
        if self.mapping_error and not self.usb.ready:
            return StatusView("设备连接出错", self.mapping_error, "error", self.mapping_error, True)
        if state.usable and self.enabled and not self.keys_ready and not self.usb.ready:
            return StatusView("正在接入遥控器按键", "USB 已识别，正在启动按键监听。", "busy")
        tone = "ok" if self.keys_ready or self.usb.ready else "ready"
        return StatusView(state.title, state.detail, tone)

    def _usb_holds_receiver(self):
        # macOS shares a single collector for keys and audio, so the receiver is
        # never held twice. Windows keeps Raw Input for keys and libusb for audio.
        return False

    def refresh_device(self):
        if self.shutting_down:
            return
        state = self._state()
        if state.code in ("absent", "unsupported"):
            if self.voice.owner == "trigger":
                # The receiver is gone; never leave a recognition shortcut held.
                self.voice.cancel()
            now = time.monotonic()
            if self._absent_since is None:
                self._absent_since = now
            if state.code == "unsupported" or now - self._absent_since >= self.ABSENCE_GRACE:
                # Unplugged for real: drop live input and retry on replug.
                self.mapping_attempted = False
                self.mapping_error = ""
                if self.enabled:
                    self.set_enabled(False)
                if self.usb.ready:
                    self.usb.stop()
        else:
            self._absent_since = None
        if self._connection_feedback:
            view = self.device_view()
            self.message.emit(view.detail, view.tone == "error")
            self._connection_feedback = True
        self.device_changed.emit()

    def _inventory_changed(self):
        state = self._state()
        receivers = [(d.connection, d.serial) for d in self.monitor.devices
                     if (d.vendor, d.product) == (self.profile.vendor, self.profile.product)]
        signature = (state.code if not state.usable else "present", self.monitor.error, receivers)
        if signature != self._inventory_signature:
            self.diagnostics.write("usb_inventory", state=signature[0], error=self.monitor.error[:1000])
            self._inventory_signature = signature
        self.refresh_device()
        if state.usable and self.transient_error and not self.recovery_timer.isActive():
            self.recovery_timer.start()
        self.ensure_mapping()

    def ensure_mapping(self):
        """Start key input once per plug-in / retry. Never in safe (smoke) mode."""
        if (self.shutting_down or not self.auto_mapping or self.enabled or self.mapping_attempted
                or self.usb_connecting or self._usb_holds_receiver()):
            return
        if not self._state().usable:
            return
        if self._collector_missing():
            # Fresh install: nothing to read keys with yet. This is a state, not
            # a failure, so the first launch must not open with a red error.
            self.mapping_attempted = True
            self.helper_missing = True
            self.device_changed.emit()
            return
        self.helper_missing = False
        self.mapping_attempted = True
        self.set_enabled(True)

    def retry_connection(self):
        self.diagnostics.write("connection_retry")
        self.recovery_timer.stop()
        self.transient_error = ""
        self.recovery_attempts = 0
        self.mapping_attempted = False
        self.mapping_error = ""
        self.helper_missing = False
        self.monitor.refresh()
        self.device_changed.emit()

    def _require_receiver(self, profile=None):
        if not self.monitor.checked or time.monotonic() - self.monitor.updated > 6:
            self.monitor.refresh()
            raise RuntimeError("请等待 USB 检测完成后再接入")
        state = receiver_state(profile or self.profile, self.monitor.devices,
                               checked=self.monitor.checked, error=self.monitor.error)
        if not state.usable:
            raise RuntimeError(state.title + "：" + state.detail)

    def set_enabled(self, on):
        on = bool(on)
        if on == self.enabled:
            self.device_changed.emit()
            return
        self.pressed.clear()
        self._clear_gestures()
        self.keys_ready = False
        try:
            if on:
                self._require_receiver()
                # The collector uses USB directly, not a GUI IOHID open. It
                # preflights its signed installation without requesting TCC.
                self.mapping_error = ""
                self.helper_missing = False
                self.enabled = True
                self.diagnostics.write("capture_start")
                self.device.start(self.profile, self.host)
            else:
                self.enabled = False
                self.diagnostics.write("capture_stop")
                if self.voice.owner == "trigger":
                    self.voice.cancel()  # release a held recognition shortcut
                self.device.stop()
                self.set_learning(False)
        except Exception as exc:
            self.enabled = False
            if on:
                self._device_failed(str(exc))
                self.device.stop()
            else:
                self.fail(str(exc))
        self.refresh_device()

    def input_ready(self, generation):
        if generation == self.device.generation and self.enabled:
            self.diagnostics.write("capture_ready", generation=generation)
            self.recovery_timer.stop()
            self.transient_error = ""
            self.recovery_attempts = 0
            self.keys_ready = True
            self.mapping_error = ""
            self.refresh_device()
            self.ensure_remote_audio()

    def _device_stopped(self, generation):
        if generation != self.device.generation:
            return
        self.diagnostics.write("capture_stopped", generation=generation)
        self.enabled = False
        self.keys_ready = False
        self.pressed.clear()
        self._clear_gestures()
        if not self.mapping_error and not self.transient_error:
            self._device_failed("按键监听意外停止，组件未提供详细原因。请重新检测；若仍失败，请退出后重新打开应用。")
        if self.voice.owner == "trigger":
            self.voice.cancel()
        self.set_learning(False)
        self.refresh_device()

    def _device_failed(self, error):
        text = str(error).strip() or "按键组件返回了空错误。"
        disconnected = any(code in text for code in ("LIBUSB_ERROR_IO", "LIBUSB_ERROR_NO_DEVICE"))
        if disconnected and self.auto_mapping and not self.shutting_down and self.recovery_attempts < 1:
            self.transient_error = text
            self.mapping_error = ""
            self.mapping_attempted = False
            self.diagnostics.write("capture_transient_io", reason=text)
            self.recovery_timer.start()
            self.device_changed.emit()
            return
        self.recovery_timer.stop()
        self.transient_error = ""
        self.mapping_error = text
        self.diagnostics.write("capture_failed")
        self.fail(self.device_view().detail)
        self._connection_feedback = True
        self.device_changed.emit()

    def _recover_transient(self):
        if not self.transient_error:
            return
        if not self._state().usable:
            # Re-enumeration can take longer than the retry delay. The next
            # inventory update restarts recovery; do not abandon it here.
            self.diagnostics.write("capture_waiting_for_receiver")
            self.device_changed.emit()
            return
        self.transient_error = ""
        self.recovery_attempts = 1
        self.mapping_attempted = False
        self.mapping_error = ""
        self.diagnostics.write("capture_transient_retry")
        self.monitor.refresh()
        self.ensure_mapping()

    # -- permissions & login startup (read-only until the user clicks) -----------

    def permission_status(self):
        return permissions.permission_status()

    def local_version(self):
        """(version, build) of the running App; source runs report the file version."""
        import plistlib
        from pathlib import Path
        if getattr(sys, "frozen", False):
            bundle = next((p for p in Path(sys.executable).parents if p.suffix == ".app"), None)
            if bundle is not None:
                info = plistlib.loads((bundle / "Contents/Info.plist").read_bytes())
                return info.get("CFBundleShortVersionString", "0"), info.get("CFBundleVersion", "0")
        for candidate in (Path(__file__).resolve().parents[1] / "VERSION",
                          Path(getattr(sys, "_MEIPASS", "")) / "VERSION"):
            try:
                if candidate.is_file():
                    return candidate.read_text(encoding="utf-8").strip(), "0"
            except OSError:
                pass
        return "0", "0"

    def check_updates(self, manual=False):
        import platform, threading
        if sys.platform != "darwin":
            # Windows 版没有 .app 更新器；调试阶段用整包替换，不假装能自动更新。
            self.update_error.emit("当前平台暂不支持自动更新；请替换整个程序目录。")
            return
        from . import updates
        version, build = self.local_version()
        arch = "arm64" if platform.machine() == "arm64" else "x86_64"
        self.diagnostics.write("update_check", manual=manual, version=version, build=build)

        def work():
            try:
                found = updates.check(local_version=version, local_build=build, arch=arch)
            except updates.UpdateError as exc:
                self.update_error.emit(str(exc))
                return
            except Exception as exc:
                self.update_error.emit("检查更新失败：" + str(exc))
                return
            self.diagnostics.write("update_result", found=found.version if found else "")
            if found is None:
                self.update_none.emit()
            else:
                self.update_found.emit(found)
        threading.Thread(target=work, daemon=True, name="remotehub-update-check").start()

    def download_update(self, update):
        import platform, tempfile, threading
        from . import updates
        arch = "arm64" if platform.machine() == "arm64" else "x86_64"
        asset = update.assets.get(arch)
        if asset is None:
            self.update_error.emit("这个版本没有本机架构的安装包")
            return
        target = Path.home() / "Library/Caches/RemoteHub/updates" / asset.name
        self.diagnostics.write("update_download", version=update.version, arch=arch)

        def work():
            try:
                updates.download(asset, target)
            except Exception as exc:
                self.update_error.emit("下载更新失败：" + str(exc))
                return
            self.update_downloaded.emit(str(target))
        threading.Thread(target=work, daemon=True, name="remotehub-update-download").start()

    def onboarding_needed(self):
        return not self.settings.get("onboarded")

    def finish_onboarding(self):
        if self.settings.get("onboarded"):
            return
        self.settings["onboarded"] = "1"
        self.save()

    def install_collector(self, remove=False):
        from .mac_device_helper import open_installer
        if remove:
            self.set_enabled(False)
        open_installer(remove)

    def open_permission(self, name):
        try:
            permissions.open_permission_settings(name)
            self.permission_opened.emit(name)
        except Exception as exc:
            self.fail(str(exc))

    def autostart_enabled(self):
        return autostart.is_enabled()

    def set_autostart(self, enabled):
        """Raises on failure so the caller can put the checkbox back."""
        autostart.set_enabled(enabled)

    # -- learning & key dispatch ---------------------------------------------------

    def set_learning(self, on):
        on = bool(on)
        if on != self.learning:
            self.learning = on
            self.learning_changed.emit(on)

    def toggle_learning(self):
        if self.learning:
            self.set_learning(False)
            return
        if self.selected is None:
            self.fail("请先选择一个按键")
            return
        if not self.enabled and not self.usb.authenticated:
            self.fail("请先启用按键映射，或接入 USB 音频")
            return
        self.set_learning(True)
        self.tell("现在按一次遥控器上要绑定的实体键。学习期间不执行映射动作。")

    def _voice_key(self, trigger):
        """The dedicated voice key bound to this trigger, if any."""
        for button in self.profile.buttons:
            if button.configurable and button.trigger == trigger and (
                    is_voice_button(self.profile, button) or button.action.kind == "voice"):
                return button
        return None

    def _clear_gestures(self):
        self.switcher.close()
        self.holds.close()
        self.switcher_pressed.clear()
        for gesture in self.gestures.values():
            gesture.cancel()
            gesture.deleteLater()
        self.gestures.clear()

    def _run_action(self, action, down, owner):
        if action.kind == "hold" or (action.kind == "common" and action.target == "app_switcher"):
            return self.runner.run(action, down, owner=owner)
        return self.runner.run(action, down)

    def _cancel_button_actions(self, trigger):
        pending = self.gestures.pop(trigger, None)
        if pending is not None:
            pending.cancel()
            pending.deleteLater()
        self.holds.release(trigger)
        if self.switcher.owner == trigger:
            self.switcher.close()

    def _run_gesture_action(self, action, trigger, down=True):
        try:
            self._action_feedback(self._run_action(action, down, trigger))
        except Exception as exc:
            self.fail(str(exc))

    def _switcher_controls(self):
        return {button.trigger: button.id for button in self.configurable_buttons() if button.trigger}

    def on_key(self, trigger, down):
        if trigger and not self.learning and (self.switcher.active or trigger in self.switcher_pressed):
            controls = self._switcher_controls()
            role = controls.get(trigger)
            try:
                if down:
                    self.pressed.add(trigger)
                else:
                    self.pressed.discard(trigger)
                    self.switcher_pressed.discard(trigger)
                if down and trigger in self.switcher_pressed:
                    if self.switcher.active and role in ("tv-left", "tv-right"):
                        self.switcher.handle_key(trigger, True, controls)
                    return
                if down:
                    self.switcher_pressed.add(trigger)
                else:
                    self.switcher_pressed.discard(trigger)
                if self.switcher.active:
                    self.switcher.handle_key(trigger, down, controls)
            except Exception as exc:
                self.switcher.close()
                self.fail(str(exc))
            return
        # The collector session follows the physical key, not the mapping: it must
        # also close when voice is disabled or was remapped while the key was down.
        if trigger and not self.learning and self._voice_key(trigger) is not None:
            if not down or trigger not in self.pressed:
                self.diagnostics.write("voice_key", down=down)
            self._voice_edge(down)
        if not down and trigger == self.voice_trigger:
            # The key that started a recording always ends it, even if its
            # mapping was changed while it was held.
            self.voice_trigger = None
            self.pressed.discard(trigger)
            try:
                self.voice_button(False)
            except Exception as exc:
                self.fail(str(exc))
            return
        if not down and trigger == self.learned_release:
            # Release of the key that was just learned must not fire its action.
            self.learned_release = None
            self.pressed.discard(trigger)
            return
        if down:
            if trigger in self.pressed:
                button = next((b for b in self.profile.buttons if b.configurable and b.trigger == trigger), None)
                if button is not None and not self.learning:
                    from .actions import is_repeatable
                    from .gestures import KeyGesture
                    action = button.action
                    if not KeyGesture.needed(button) and is_repeatable(action):
                        try:
                            self._action_feedback(self.runner.run(action, True))
                        except Exception as exc:
                            self.fail(str(exc))
                return
            self.pressed.add(trigger)
        else:
            self.pressed.discard(trigger)
        if self.learning:
            button = self.selected
            if down and button:
                if any(b.trigger == trigger and b.id != button.id for b in self.profile.buttons):
                    self.fail("这个实体键已绑定其他按键，请先解除旧绑定")
                    return
                button.trigger = trigger
                self.learned_release = trigger
                self.set_learning(False)
                self.mapping_changed.emit()
                self.save()
                self.tell("实体按键已绑定")
            return
        if not trigger:
            return
        button = next((b for b in self.profile.buttons if b.configurable and b.trigger == trigger), None)
        if button is None:
            return
        self.physical_key.emit(trigger, down)
        self.select(button.id)
        from .gestures import KeyGesture
        if KeyGesture.needed(button):
            gesture = self.gestures.get(trigger)
            if gesture is None:
                gesture = KeyGesture(button, self)
                gesture.triggered.connect(lambda action, origin=trigger:
                                          self._run_gesture_action(action, origin))
                gesture.released.connect(lambda action, origin=trigger:
                                         self._run_gesture_action(action, origin, False))
                self.gestures[trigger] = gesture
            gesture.handle(down)
            return
        action = Action("voice") if is_voice_button(self.profile, button) else button.action
        voice = action.kind == "voice"
        if down:
            # A later press can show the same app again; don't report stale results.
            self._cancel_hide_result()
        try:
            if voice and down:
                if self.recording_requested:
                    if (self.voice_auto_pending and self.remote_audio
                            and self.usb.voice.owner == "usb" and not self.usb.cancelled):
                        self.voice_auto_pending = False
                        self.voice_trigger = trigger
                        self.diagnostics.write("voice_key_adopted")
                        return
                    if self.settings.get("record_mode", "hold") == "hold":
                        return
                self.voice_trigger = trigger
            message = self._run_action(action, down, trigger)
            self._action_feedback(message)
        except Exception as exc:
            if voice:
                self.voice_trigger = None
            self.fail(str(exc))

    # -- delayed test ----------------------------------------------------------------

    def schedule_test(self):
        button = self.selected
        if button is None or button.action.kind == "none":
            return
        if button.action.kind == "voice":
            self.fail("语音动作需要先接入音频来源；可在「语音设置」页用录音文件验证通路。")
            return
        self.test_action = button.action
        self.test_left = TEST_DELAY
        self.test_timer.start()
        self.test_pending.emit(self.test_left)
        self.tell(f"{TEST_DELAY} 秒后执行「{action_text(self.test_action)}」，请切换到目标应用。")

    def cancel_test(self):
        if self.test_timer.isActive():
            self.test_timer.stop()
            self.test_action = None
            self.test_pending.emit(0)
            self.tell("已取消测试。")

    def _test_tick(self):
        self.test_left -= 1
        if self.test_left > 0:
            self.test_pending.emit(self.test_left)
            return
        self.test_timer.stop()
        action, self.test_action = self.test_action, None
        self.test_pending.emit(0)
        self._cancel_hide_result()
        try:
            result = self.runner.run(action)
            if result is None:
                self.tell("测试动作已执行。")
            else:
                self._action_feedback(result)
        except Exception as exc:
            self.fail(str(exc))

    # -- voice settings ----------------------------------------------------------------

    def voice_settings(self):
        s = self.settings
        return {"voice_source": s.get("voice_source", "disabled"), "record_mode": s.get("record_mode", "hold"),
                "voice_keys": s.get("voice_keys", "alt"), "voice_mode": s.get("voice_mode", "hold"),
                "input_routing": s.get("input_routing", "automatic"),
                "gain": s.get("gain", 12), "codec": s.get("codec", ""), "output": s.get("output", "")}

    @property
    def remote_audio(self):
        return self.settings.get("voice_source", "disabled") == "remote"

    @property
    def voice_enabled(self):
        return self.settings.get("voice_source", "disabled") != "disabled"

    def _apply_voice_settings(self):
        s = self.voice_settings()
        self.voice.trigger_keys = [k for k in s["voice_keys"].split("+") if k]
        self.voice.trigger_mode = s["voice_mode"]
        self.voice.gain = s["gain"]
        self.voice.switch_input = s["input_routing"] == "automatic"

    def update_voice(self, **changes):
        """Validate, apply and persist voice fields. Returns False if rejected."""
        if self.voice.owner is not None or self.recording_requested:
            self.fail("请先停止语音，再修改语音设置")
            self.voice_changed.emit()  # put the fields back
            return False
        if "voice_keys" in changes:
            changes["voice_keys"] = "+".join(k.strip().lower() for k in changes["voice_keys"].split("+") if k.strip())
        candidate = {**self.settings, **changes}
        try:
            validate_settings(candidate)
            from .model import validate_keys
            validate_keys(candidate.get("voice_keys", "alt").split("+"), allow_modifier=True, platform=sys.platform)
            if self.fixed_model and candidate.get("voice_mode", "hold") == "manual":
                raise ValueError("实体语音键需要发送唤起键，请选择按住或切换方式")
            if candidate.get("voice_source", "disabled") == "trigger" and candidate.get("voice_mode", "hold") == "manual":
                raise ValueError("仅触发识别时需要发送识别快捷键，请选择按住或切换方式")
        except ValueError as exc:
            self.fail("语音设置未保存：" + str(exc))
            self.voice_changed.emit()
            return False
        previous = dict(self.settings)
        self.settings.update(changes)
        if not self.save():
            # Keep runtime and memory in step with what is on disk.
            self.settings.clear()
            self.settings.update(previous)
            self.voice_changed.emit()
            return False
        self._apply_voice_settings()
        if not self.remote_audio and (self.usb.ready or self.usb_connecting):
            self.stop_usb()
        self.ensure_remote_audio()
        self.voice_changed.emit()
        return True

    def refresh_outputs(self):
        devices = list(self.audio.outputs())
        if sys.platform == "win32":
            self.microphone_installed = any(is_windows_cable(d) for d in devices)
        else:
            self.microphone_installed = self.virtual_mic.installed()
        self.outputs = [(d.description(), bytes(d.id())) for d in devices if is_voice_output(d)]
        wanted = self.settings.get("output", "")
        self.voice.output_id = next((ident for _, ident in self.outputs if _b64(ident) == wanted),
                                    self.outputs[0][1] if self.outputs else b"")
        self.ensure_remote_audio()
        self.voice_changed.emit()

    def _check_microphone_installation(self):
        if self.virtual_mic.installed() != self.microphone_installed:
            self.refresh_outputs()

    def microphone_view(self):
        if self.voice.output_id:
            return StatusView("已就绪", "可以接收遥控器音频。", "ok")
        if sys.platform == "win32":
            if self.microphone_installed:
                return StatusView("已安装，尚未选择", "在下方选择虚拟声卡的播放端；识别软件那边选对应的录音端。", "neutral")
            return StatusView("还没有虚拟声卡", "安装一次 VB-CABLE 即可使用遥控器麦克风。", "neutral")
        if self.microphone_installed:
            return StatusView("已安装，尚未生效", "点击「完成设置」启用麦克风；若安装器提示未能启用，请保存工作后重启 Mac。", "neutral")
        return StatusView("尚未就绪", "请先安装虚拟麦克风。", "neutral")

    def check_microphone(self):
        self.refresh_outputs()
        state = self.microphone_view()
        self.tell(f"{state.title}。{state.detail}")

    def set_output(self, ident: bytes):
        ident = bytes(ident or b"")
        if self.update_voice(output=_b64(ident)):
            self.voice.output_id = ident
            self.voice_changed.emit()

    def setup_virtual_mic(self):
        try:
            if sys.platform == "darwin":
                from .devices import resources
                from .installers import open_package
                pkg = resources() / "components" / "RemoteHubAudio.pkg"
                if not pkg.exists():
                    pkg = resources() / "build" / "RemoteHubAudio.pkg"
                if not pkg.exists():
                    raise FileNotFoundError("虚拟麦克风安装文件缺失，请重新安装 10RemoteHub。")
                open_package(pkg)
                self.tell("已打开安装器。安装结束会自动启用麦克风，声音和录音将短暂中断，请先暂停通话与录音。")
            elif sys.platform == "win32":
                # The voice page explains the step inline and owns the download
                # link; never open a browser from here.
                self.tell("请在语音设置页按提示安装 VB-CABLE，装完点「重新检测」。")
            else:
                raise RuntimeError("此版本尚不支持当前系统的遥控器麦克风，请选择电脑麦克风。")
        except Exception as exc:
            self.fail(str(exc))

    # -- USB voice link ------------------------------------------------------------------

    def ensure_remote_audio(self):
        if (self.usb.collector is not None and self.auto_mapping and not self.shutting_down
                and self.keys_ready and self.device.capture_ready and self.remote_audio
                and self.voice.output_id and not self.usb.ready and not self.usb_connecting):
            self.start_usb(self.profile)

    def usb_view(self) -> StatusView:
        if not self.voice_enabled:
            return StatusView("未启用", "选择麦克风后启用语音输入。", "neutral")
        if not self.remote_audio:
            return StatusView("不需要", "仅触发识别时不连接遥控器音频。", "neutral")
        if self.usb.ready:
            return StatusView("已连接", "按遥控器语音键开始说话。", "ok")
        if self.usb_connecting or self.usb.authenticated or self.usb.server.isListening():
            return StatusView("正在连接", "正在准备遥控器音频通路。", "busy")
        if not self.voice.output_id:
            return StatusView("未连接", "请先完成虚拟麦克风设置。", "neutral")
        return StatusView("未连接", "确认接收器已插好。" if self.usb.collector is not None else
                          "点击「连接遥控器音频」后即可使用。", "neutral")

    def voice_view(self) -> StatusView:
        if not self.voice_enabled:
            return StatusView("未启用", "选择麦克风后启用语音输入。", "neutral")
        owner = self.voice.owner
        if self.voice.routing:
            return StatusView("正在准备麦克风", "", "busy")
        if self.voice.ending:
            return StatusView("正在结束语音", "", "busy")
        if owner == "usb":
            return StatusView("正在录音", "", "ok")
        if owner == "trigger":
            return StatusView("识别中", "", "ok")
        if owner == "wav":
            return StatusView("正在播放测试录音", "", "ok")
        if self.recording_requested:
            return StatusView("正在开始录音", "", "busy")
        if self.remote_audio and not self.voice.output_id:
            return StatusView("虚拟麦克风尚未就绪", "", "neutral")
        return StatusView("空闲", "", "ready")

    def usb_preflight(self):
        """Every check that can fail before asking the user to hand over the receiver."""
        if not self.remote_audio:
            raise RuntimeError("当前语音设置不需要连接遥控器音频")
        if self.voice.owner is not None or self.recording_requested:
            raise RuntimeError("请先停止当前语音")
        if not self.voice.output_id:
            raise RuntimeError("虚拟麦克风尚未就绪，请到语音设置查看处理方法。")
        profile = next((p for p in self.profiles if is_fixed_model(p)), None)
        if profile is None:
            raise RuntimeError("未找到适配型号的遥控器配置")
        self._require_receiver(profile)
        return profile

    def start_usb(self, profile):
        """Attach audio to the Mac collector, or start the confirmed legacy worker."""
        self.usb_connecting = True
        if self.usb.collector is None:
            self.set_enabled(False)
            if self.device.stop() is False:
                self.usb_connecting = False
                self.fail("遥控器暂时无法连接音频，请重新检测后再试。")
                self.voice_changed.emit()
                return
        if self.profile is not profile:
            self.select_profile(self.profiles.index(profile))
        try:
            if sys.platform == "win32" and self.usb.collector is None:
                self.set_enabled(True)   # legacy worker path only
            self.usb.start()
        except Exception as exc:
            self.usb_connecting = False
            self.mapping_attempted = False
            self.ensure_mapping()
            self.fail(str(exc))
        self.voice_changed.emit()

    def stop_usb(self):
        self.usb_connecting = False
        self.recording_requested = False
        self.usb.stop()
        if self.usb.collector is None:
            self.mapping_attempted = False
            # Only the separate worker needs to hand the receiver back to HID.
            QTimer.singleShot(1000, self.ensure_mapping)
        self.voice_changed.emit()

    def _usb_ready(self):
        self.usb_connecting = False
        self.mapping_error = ""
        self.tell("遥控器音频已就绪，按语音键开始说话。")
        self.voice_changed.emit()

    def _usb_released(self):
        self.diagnostics.write("audio_channel_disconnected")
        self.usb_connecting = False
        self.recording_requested = False
        self.voice_auto_pending = False
        self.voice_trigger = None
        if self.usb.collector is None:
            self.mapping_attempted = False
            QTimer.singleShot(1000, self.ensure_mapping)
        self.voice_changed.emit()

    def _recording_started(self):
        self.recording_requested = True
        self.voice_auto_pending = self.voice_trigger is None
        self.voice_changed.emit()

    def _recording_stopped(self):
        self.recording_requested = False
        self.voice_auto_pending = False
        self.voice_changed.emit()

    def _voice_expired(self):
        self.tell("本次语音已到 60 秒，自动结束；松开语音键后可重新开始。")

    def _voice_finished(self):
        self.recording_requested = False
        self.voice_auto_pending = False
        self.voice_trigger = None
        if self.usb.recording_requested:
            self.usb.stop_audio()
        self.voice_changed.emit()

    def _voice_edge(self, down):
        """Windows keeps the receiver's voice session open across the key."""
        if sys.platform != "win32":
            return
        try:
            self.device.voice_edge(down)
        except Exception as exc:
            self.diagnostics.write("voice_edge_failed", error=str(exc)[:300])

    def voice_button(self, down):
        """ActionRunner callback for keys mapped to 语音输入.

        record_mode hold: press starts, release stops. toggle: press starts,
        next press stops. Source trigger: only the recognition shortcut is sent.
        """
        if not self.voice_enabled:
            self.voice_trigger = None
            if down:
                self.tell("语音未启用，请先选择麦克风。")
            return
        mode = self.settings.get("record_mode", "hold")
        if not down:
            if mode == "hold":
                self.stop_voice()
            return
        if self.recording_requested:
            if mode == "toggle":
                self.stop_voice()
            return
        if self.voice.owner is not None:
            raise RuntimeError("上一段语音尚未结束，请稍后再按")
        if self.remote_audio:
            if not self.usb.ready:
                self.ensure_remote_audio()   # collector may have just come up
            self.usb.start_audio()
        else:
            self.voice.start("trigger")
        self.recording_requested = True
        self.voice_changed.emit()

    # -- WAV path test ---------------------------------------------------------------------

    def play_wav(self, path):
        try:
            if self.voice.owner is not None or self.recording_requested:
                raise RuntimeError("请先停止当前语音")
            if not self.voice.output_id:
                raise RuntimeError("虚拟麦克风尚未就绪，请到语音设置查看处理方法。")
            wav = wave.open(str(path), "rb")
            if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (16000, 1, 2) \
                    or wav.getnframes() > 16000 * 120:
                wav.close()
                raise ValueError("请选择不超过两分钟的 16 kHz 单声道 16-bit WAV")
            try:
                self.voice.start("wav")
            except Exception:
                wav.close()
                raise
            self.wav = wav
            self.wav_timer.start()
        except Exception as exc:
            self.fail(str(exc))

    def _wav_tick(self):
        try:
            pcm = self.wav.readframes(320)
            if pcm:
                self.voice.feed("wav", pcm)
            else:
                self.wav.close()
                self.wav = None
                self.wav_timer.stop()
                self.voice.finish("wav")
        except Exception as exc:
            self.stop_voice()
            self.fail(str(exc))

    def stop_voice(self):
        """Also the emergency stop in 通用设置 and the tray."""
        self.recording_requested = False
        self.wav_timer.stop()
        if self.wav:
            self.wav.close()
            self.wav = None
        self.usb.stop_audio()  # USB recording ends when the worker sends its tail
        if self.voice.owner is not None and self.voice.owner != "usb":
            self.voice.finish(self.voice.owner)
        self.voice_changed.emit()

    # -- lifecycle -------------------------------------------------------------------------

    def start(self):
        """Begin read-only USB inventory polling. Not called in --smoke runs."""
        self.monitor.start()
        try:
            # Only an already-enabled login item is upgraded; never enables one.
            if getattr(sys, "frozen", False) and autostart.refresh():
                self.diagnostics.write("autostart_upgraded")
        except Exception as exc:
            self.diagnostics.write("autostart_upgrade_failed", error=str(exc))

    def shutdown(self):
        if self.shutting_down:
            return
        self.shutting_down = True
        self.diagnostics.write("app_stopping")
        self.launcher.stop()
        self.microphone_watch.stop()
        self._cancel_hide_result()
        self.test_timer.stop()
        self.recovery_timer.stop()
        self._clear_gestures()
        self.monitor.stop()
        self.device.stop()
        self.usb.stop()
        self.virtual_mic.stop()
        self.wav_timer.stop()
        if self.wav:
            self.wav.close()
            self.wav = None
        self.voice.cancel()
        try:
            self.keys.release()
        except Exception:
            pass
        self.voice.close()
        self.diagnostics.close()
