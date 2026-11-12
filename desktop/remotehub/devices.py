"""Input adapters return device-scoped events, never learn a global keyboard."""
from __future__ import annotations
import json
import logging
from pathlib import Path
import sys
from PySide6.QtCore import QObject, Signal
from .hid_reports import HIDReports


def resources():
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))



class DeviceInput(QObject):
    key = Signal(str, bool)
    status = Signal(str)
    failed = Signal(str)
    stopped = Signal(int)
    ready = Signal(int)
    collected = Signal(object)
    capture_stopped = Signal()
    log = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mac = None
        self.release_confirmed = True
        self.capture_ready = False
        self.reports = {}
        self.windows = None
        self.collector = None
        self.generation = 0
        self.ignored_reports = 0

    def start(self, profile, window=None):
        self.stop()
        generation=self.generation
        if sys.platform == "darwin":
            from .mac_device_helper import MacDeviceHelper
            if (profile.vendor, profile.product) != (0x0416, 0x0602):
                raise RuntimeError("采集程序只支持 USB 0416:0602")
            self.mac = MacDeviceHelper(self)
            self.mac.line.connect(lambda line, g=generation: self._event(line, g))
            self.mac.failed.connect(lambda message, g=generation: self._mac_failed(message, g))
            self.mac.start()
        elif sys.platform == "win32":
            from .windows_input import WindowsInput
            from .windows_collector import WindowsCollector
            self.windows = WindowsInput(profile, self.key.emit, self.status.emit, window,
                                        self._unmapped_key)
            self.windows.start()
            # Keep the receiver's own voice session alive: the dongle re-enumerates
            # on a voice-key release unless the host closes the session itself.
            self.collector = WindowsCollector(self)
            self.collector.collected.connect(self.collected)
            self.collector.status.connect(self.status)
            self.collector.log.connect(self.log)
            self.collector.key.connect(self.key)
            self.collector.keys_ready.connect(self._keys_from_collector)
            self.collector.ready.connect(lambda g=generation: self._win_ready(g))
            self.collector.failed.connect(lambda message, g=generation: self._win_failed(message, g))
            self.collector.start()
            self.ready.emit(generation)
        else:
            raise RuntimeError("当前版本只支持 macOS 与 Windows")

    def _keys_from_collector(self, keyboard_taken):
        """Keyboard reports come from the collector; consumer keys stay on Raw Input."""
        if self.windows is not None:
            self.windows.keyboard_muted = bool(keyboard_taken)
        if keyboard_taken:
            self.status.emit("遥控器按键已由采集程序接管")

    def _unmapped_key(self, scan, flags, vk):
        self.log.emit(f"unmapped keyboard scan={scan} flags={flags} vk={vk}")

    def _win_ready(self, generation):
        if generation != self.generation:
            return
        self.capture_ready = True
        self.status.emit("遥控器语音通道已接入")
        # The collector finishes its handshake after key input is already up, so
        # re-announce readiness; the controller only then can attach audio.
        self.ready.emit(generation)

    def _win_failed(self, message, generation):
        """Voice interface problems must never take key input down with them."""
        if generation != self.generation:
            return
        self.capture_ready = False
        self.status.emit(message)

    def voice_edge(self, down):
        if self.collector is not None:
            self.collector.voice_edge(down)

    def _mac_failed(self, message, generation):
        if generation != self.generation:
            return
        self.capture_ready = False
        self.capture_stopped.emit()
        self.failed.emit(message)
        if self.mac:
            self.release_confirmed = self.mac.stop()
        self.stopped.emit(generation)

    def _event(self, line, generation):
        if generation != self.generation:
            return
        try:
            d = json.loads(line)
            if d["type"] == "descriptor":
                self.reports[d["interface"]] = HIDReports(bytes.fromhex(d["hex"]))
            elif d["type"] == "report":
                try:
                    parser = self.reports[d["interface"]]
                    events = parser.decode(bytes.fromhex(d["hex"]))
                except (ValueError, KeyError, TypeError):
                    # Bad input is not a device/transport failure. Do not clear
                    # parser state or synthesize key releases from partial data.
                    self.ignored_reports += 1
                    if self.ignored_reports == 1 or self.ignored_reports % 100 == 0:
                        logging.getLogger(__name__).warning("Ignored malformed HID reports: %d", self.ignored_reports)
                    return
                for trigger, down in events:
                    self.key.emit(trigger, down)
            elif d["type"] in ("audio", "start", "end", "warning"):
                self.collected.emit(d)
            elif d["type"] == "key":
                self.key.emit(d["trigger"], d["down"])
            elif d["type"] == "debug":
                message = f"{d['event']}:phase={d['phase']},code={d['code']}"
                if "hex" in d:
                    message += f",hex={d['hex']}"
                self.log.emit(message)
            elif d["type"] == "ready" and d["interfaces"] > 0:
                self.release_confirmed = True
                self.capture_ready = True
                if self.mac:
                    self.mac.confirmed = True
                self.status.emit("遥控器按键已连接")
                self.ready.emit(generation)
            elif d["type"] == "error":
                self._mac_failed(d["message"], generation)
            elif d["type"] == "removed":
                self._mac_failed("遥控器已断开，请重新检测", generation)
        except (ValueError, KeyError, TypeError):
            self._mac_failed("采集程序返回了无效数据", generation)

    def record(self, active):
        if self.collector is not None and self.capture_ready:
            self.collector.record(active)
            return
        if not self.mac or not self.capture_ready:
            raise RuntimeError("采集程序尚未连接")
        self.mac.record(active)

    def stop(self):
        self.capture_ready = False
        self.reports = {}
        self.capture_stopped.emit()
        self.generation+=1
        if self.mac:
            if not self.mac.stop():
                self.release_confirmed = False
            self.mac.line.disconnect()
            self.mac.failed.disconnect()
            self.mac.deleteLater()
            self.mac = None
        if self.windows:
            self.windows.stop(); self.windows=None
        if self.collector:
            self.collector.stop(); self.collector.deleteLater(); self.collector=None
        return self.release_confirmed
