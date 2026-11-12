"""Single-owner voice lifecycle shared by USB and local file diagnostics."""
from PySide6.QtCore import QObject, QTimer, Signal
from .model import validate_keys


MAX_RECORD_SECONDS = 60


class VoiceSession(QObject):
    failed = Signal(str)
    expired = Signal()   # normal one-minute end, not a device failure
    changed = Signal()   # owner started or ended; UI enables/disables stop controls
    finished = Signal()  # a session that had an owner ended
    def __init__(self, audio, keys, parent=None, *, route=None):
        super().__init__(parent)
        self.audio, self.keys = audio, keys
        self.owner = None
        self.log = lambda event, **fields: None
        self.trigger_keys = ["alt"]
        self.trigger_mode = "hold"
        self.output_id = b""
        self.gain = 12
        self.recognition_started = False
        self.route = route
        self.routing = False
        self.ending = False
        self.pending = bytearray()
        self.routed = False
        self.switch_input = True
        self.route_timeout = QTimer(self)
        self.route_timeout.setSingleShot(True)
        self.route_timeout.timeout.connect(lambda: self._route_failed(
            "系统麦克风切换耗时过长，已取消本次语音，请重试"))
        if route is not None:
            route.ready.connect(self._route_ready)
            route.failed.connect(self._route_failed)
            route.released.connect(self._complete)
        self.timeout = QTimer(self)
        self.timeout.setSingleShot(True)
        self.timeout.timeout.connect(self._expire)
        audio.ended.connect(self._ended)
        audio.failed.connect(self.failed)

    def _expire(self):
        if self.owner not in ("usb", "trigger"):
            return
        self.log("voice_max_duration", seconds=MAX_RECORD_SECONDS)
        self.expired.emit()
        self.finish(self.owner)

    def start(self, owner):
        if self.owner is not None:
            raise RuntimeError("另一个音频来源正在使用语音输入")
        validate_keys(self.trigger_keys, allow_modifier=True)
        if self.trigger_mode not in ("hold", "toggle", "manual"):
            raise ValueError("识别触发方式无效")
        self.owner = owner
        self.ending = False
        self.routed = owner == "usb" and self.route is not None and self.switch_input
        if owner != "wav":
            self.timeout.start(MAX_RECORD_SECONDS * 1000)
        try:
            if self.routed:
                self.routing = True
                self.route_timeout.start(1000)
                self.route.acquire()
            else:
                self._activate()
            self.changed.emit()
        except Exception:
            self.cancel()
            raise

    def _activate(self):
        if self.owner != "trigger":
            self.audio.start(self.output_id, self.gain)
        self.log("recognition_chord", keys="+".join(self.trigger_keys), mode=self.trigger_mode, down=True)
        if self.trigger_mode == "hold":
            self.keys.press(self.trigger_keys)
        elif self.trigger_mode == "toggle":
            self.keys.press(self.trigger_keys); self.keys.release()
        self.recognition_started = self.trigger_mode != "manual"
        if self.pending:
            self.audio.feed(bytes(self.pending))
            self.pending.clear()

    def _route_ready(self):
        if not self.routing or self.ending:
            return  # The user released the voice key while the switch was pending.
        self.routing = False
        self.route_timeout.stop()
        try:
            self._activate()
            self.changed.emit()
        except Exception as exc:
            self._route_failed(str(exc))

    def _route_failed(self, message):
        self.failed.emit(message)
        if not self.ending:
            self.cancel()

    def feed(self, owner, pcm):
        if owner != self.owner:
            raise ValueError("音频会话不匹配")
        if self.ending:
            return
        if self.routing:
            if len(self.pending) + len(pcm) > 32000:  # one second of mono 16 kHz PCM16
                self.cancel()
                raise RuntimeError("麦克风切换耗时过长，已停止本次语音，请重试")
            self.pending.extend(pcm)
            return
        try:
            self.audio.feed(pcm)
        except Exception:
            self.cancel()
            raise

    def finish(self, owner):
        if owner == self.owner:
            if self.routing:
                self.cancel()
            elif owner == "trigger":
                self._ended()
            else:
                self.audio.finish()

    def cancel(self):
        if self.ending:
            return
        if self.owner != "trigger":
            self.audio.abort()
        # An audio start failure or pending route has no active sink to emit ended.
        if self.owner is not None and not self.ending:
            self._ended()

    def _ended(self):
        if self.ending or self.owner is None:
            return
        self.ending = True
        self.routing = False
        self.route_timeout.stop()
        self.pending.clear()
        self.timeout.stop()
        try:
            if self.recognition_started:
                if self.trigger_mode == "hold":
                    self.keys.release()
                elif self.trigger_mode == "toggle":
                    self.keys.press(self.trigger_keys); self.keys.release()
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.recognition_started = False
            if self.routed:
                self.route.release()
            else:
                self._complete()

    def _complete(self):
        if not self.ending:
            return
        self.owner = None
        self.ending = self.routed = False
        self.changed.emit()
        self.finished.emit()

    def close(self):
        self.cancel()
        if self.route is not None:
            self.route.close()
