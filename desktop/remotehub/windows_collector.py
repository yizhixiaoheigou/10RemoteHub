"""Windows voice collector: keeps the receiver's vendor session alive.

Keys stay on Raw Input. This component claims interface 3 over WinUSB and speaks
the same vendor protocol as the macOS device helper, so the receiver keeps its
USB session: pressing the voice key starts the session, releasing it sends the
stop command instead of leaving the dongle to reset itself.

Requires interface 3 to be bound to WinUSB (see docs/WINDOWS-TESTING.md).
"""
from __future__ import annotations

import queue
import threading
import time

from PySide6.QtCore import QObject, Signal

VOICE_INTERFACE = 3
KEY_INTERFACES = (1, 4)          # consumer control, keyboard
MOUSE_INTERFACE = 2              # claimed only so the pointer stays put
READ_ENDPOINT = 0x84
WRITE_ENDPOINT = 0x05
# Audio stops as soon as the key is released; a short gap ends the session even
# if the GUI never sees the key-up event.
RELEASE_GAP = 0.45


def _frame(*prefix):
    return bytes(prefix) + bytes(64 - len(prefix))


class WindowsCollector(QObject):
    collected = Signal(object)
    status = Signal(str)
    failed = Signal(str)
    ready = Signal()
    log = Signal(str)
    key = Signal(str, bool)
    keys_ready = Signal(bool)   # True when the keyboard interface was taken

    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker = None
        self.halt = threading.Event()
        self.capture_ready = False
        self._lock = threading.Lock()
        self._request = None
        self.frames = queue.Queue()

    # -- public API ------------------------------------------------------

    def start(self):
        self.stop()
        self.halt.clear()
        self.worker = threading.Thread(target=self._supervise, name="remotehub-win-collector", daemon=True)
        self.worker.start()

    def _supervise(self):
        """Reconnect after a re-enumeration; the dongle may reset on its own."""
        quick = 0
        while not self.halt.is_set():
            started = time.monotonic()
            try:
                self._run()
            except Exception as exc:
                self._log(f"worker error: {exc!r}")
                self.failed.emit(f"遥控器语音通道中断：{exc}")
            self.capture_ready = False
            self._clear_session()
            if self.halt.is_set():
                break
            # An instant failure is a real error, not a reset; don't flap the
            # device (and the user's ears) forever.
            quick = quick + 1 if time.monotonic() - started < 2 else 0
            if quick >= 3:
                self._log("collector keeps failing; giving up until restart")
                self.failed.emit("遥控器语音接口反复断开，请拔插接收器后重新检测。")
                break
            self._log(f"collector ended; retry {quick}")
            self.halt.wait(1.5 if quick < 2 else 5)

    def voice_edge(self, down):
        """Voice key pressed/released, from Raw Input."""
        with self._lock:
            self._request = bool(down)

    def record(self, active):
        # The bridge may ask for a recording; the voice key edge already drives
        # the session, so reuse the same request without double-starting.
        with self._lock:
            self._request = bool(active)

    def _clear_session(self):
        with self._lock:
            self._request = None
        while True:
            try:
                self.frames.get_nowait()
            except queue.Empty:
                break

    def stop(self):
        self.halt.set()
        if self.worker:
            self.worker.join(3)
            self.worker = None
        self.capture_ready = False
        self._clear_session()

    # -- worker ----------------------------------------------------------

    def _voice_loop(self, endpoint, stop):
        """Always have a read pending on the voice endpoint.

        An interrupt report is dropped when the next one arrives first, and a
        lost frame breaks the packet sequence the GUI validates, so the reader
        must never wait for the state machine.
        """
        import usb.core
        while not (self.halt.is_set() or stop.is_set()):
            try:
                frame = bytes(endpoint.read(64, timeout=200))
            except usb.core.USBTimeoutError:
                continue
            except Exception as exc:
                if not (self.halt.is_set() or stop.is_set()):
                    self._log(f"voice read stopped: {exc}")
                return
            if frame:
                while self.frames.qsize() > 64:   # never build a backlog
                    self.frames.get_nowait()
                self.frames.put(frame)

    def _key_loop(self, endpoint, parser, stop):
        """Always be waiting on the endpoint.

        A HID interrupt report is overwritten if the host has not read it when
        the next one arrives, so a press shorter than the polling interval would
        vanish. A dedicated blocking read per interface cannot miss one.
        """
        import usb.core
        while not (self.halt.is_set() or stop.is_set()):
            try:
                report = bytes(endpoint.read(64, timeout=200))
            except usb.core.USBTimeoutError:
                continue
            except Exception as exc:
                if not (self.halt.is_set() or stop.is_set()):
                    self._log(f"key read stopped: {exc}")
                return
            if not report:
                continue
            try:
                events = parser.decode(report)
            except ValueError as exc:
                self._log(f"key report rejected: {type(exc).__name__}")
                continue
            for trigger, down in events:
                self.key.emit(trigger, down)

    def _emit(self, payload):
        try:
            self.collected.emit(payload)
        except RuntimeError:
            pass  # window destroyed while the session ends

    def _log(self, message):
        try:
            self.log.emit(message)
        except RuntimeError:
            pass

    def _claim_keys(self, device):
        """Read raw key reports when the key interfaces are bound to WinUSB.

        Windows' keyboard driver drops unknown usages (the remote's # is 0xCC)
        and still delivers the rest to the foreground app, so taking the raw
        stream is the only complete source. Without the binding this returns an
        empty list and Raw Input keeps working unchanged.
        """
        import usb.util
        from .hid_reports import HIDReports
        readers = []
        claimed = []
        configuration = device.get_active_configuration()
        for number in KEY_INTERFACES:
            try:
                interface = configuration[(number, 0)]
                descriptor = bytes(device.ctrl_transfer(0x81, 6, 0x2200, number, 4096, timeout=1000))
                parser = HIDReports(descriptor)
                usb.util.claim_interface(device, number)
                endpoint = next(e for e in interface if e.bEndpointAddress & 0x80)
            except Exception as exc:
                self._log(f"interface {number} stays with Windows: {exc}")
                continue
            readers.append((endpoint, parser))
            claimed.append(number)
            self._log(f"interface {number} claimed")
        try:
            usb.util.claim_interface(device, MOUSE_INTERFACE)
            self._log("interface 2 claimed (pointer parked)")
        except Exception as exc:
            self._log(f"interface 2 stays with Windows: {exc}")
        self._claimed = claimed
        return readers

    def _run(self):
        try:
            import libusb_package
            import usb.core
            import usb.util
            from usb.backend import libusb1
        except Exception as exc:  # dependency problem, not a device failure
            self.failed.emit(f"缺少 USB 运行库：{exc}")
            return

        backend = libusb1.get_backend(find_library=libusb_package.find_library)
        device = None
        try:
            devices = list(usb.core.find(find_all=True, idVendor=0x0416, idProduct=0x0602, backend=backend))
            if not devices:
                raise RuntimeError("未找到适配的 USB 0416:0602 接收器")
            device = devices[0]
            interface = device.get_active_configuration()[(VOICE_INTERFACE, 0)]
            usb.util.claim_interface(device, VOICE_INTERFACE)
            reader = next(e for e in interface if e.bEndpointAddress == READ_ENDPOINT)
            self._log("interface 3 claimed")
            self._claimed = []
            readers = self._claim_keys(device)
        except Exception as exc:
            self._log(f"claim failed: {exc!r}")
            self.failed.emit(f"无法接入遥控器语音接口：{exc}。需要先把接口 3 绑定到 WinUSB。")
            return

        # Frames left over from an earlier session must not open a new one, and
        # only this thread may touch the endpoint until the readers take over.
        drain_until = time.monotonic() + 0.3
        while time.monotonic() < drain_until:
            try:
                reader.read(64, timeout=60)
            except usb.core.USBTimeoutError:
                pass

        stop = threading.Event()
        readers_threads = [
            threading.Thread(target=self._key_loop, args=(endpoint, parser, stop),
                             name=f"remotehub-win-keys-{i}", daemon=True)
            for i, (endpoint, parser) in enumerate(readers)
        ]
        for thread in readers_threads:
            thread.start()
        voice_thread = threading.Thread(target=self._voice_loop, args=(reader, stop),
                                        name="remotehub-win-voice", daemon=True)
        voice_thread.start()
        self.keys_ready.emit(any(number == 4 for number in self._claimed))

        def command(*prefix):
            try:
                device.write(WRITE_ENDPOINT, _frame(*prefix), timeout=1000)
            except Exception as exc:
                self._log(f"command {bytes(prefix).hex()} failed: {exc}")
                raise
            self._log(f"out {bytes(prefix).hex()} phase={phase}")

        phase = 0
        keepalive = 0.0
        deadline = 0.0
        stop_deadline = 0.0
        stop_sent_at = 0.0
        session_start = 0.0
        alternate_sent = False
        last_audio = 0.0
        try:
            command(1, 8, 1, 0)  # ready, same handshake as the macOS worker
            self.capture_ready = True
            self._log("ready handshake sent")
            self.ready.emit()
            self.status.emit("遥控器语音接口已就绪")
            while not self.halt.is_set():
                with self._lock:
                    request, self._request = self._request, None
                now = time.monotonic()
                if request is not None:
                    self._log(f"request {'start' if request else 'stop'} phase={phase}")
                if request is True and phase == 0:
                    command(1, 0x82, 1, 0)
                    command(1, 8, 1, 0)
                    phase = 1
                    deadline = now + 8
                elif request is False and phase:
                    command(1, 0, 0)
                    phase = 4
                    alternate_sent = False
                    stop_deadline = now + 0.4
                    stop_sent_at = now
                    self._emit({"type": "end"})
                try:
                    data = self.frames.get(timeout=0.05)
                except queue.Empty:
                    data = b""
                now = time.monotonic()
                if data and data[:2] != b"\x01\x81":
                    # Audio frames arrive 50 times a second; never log them.
                    self._log(f"in {data[:4].hex()}")
                if data:
                    if data[:2] == b"\x01\x81":
                        last_audio = now
                        if phase == 4 and not alternate_sent and now - stop_sent_at > 0.2:
                            # Audio after a stop means the first command did not
                            # end the session; the older worker used 1,1,0,0.
                            alternate_sent = True
                            self._log("audio after stop; sending alternate stop")
                            command(1, 1, 0, 0)
                        if phase >= 3:
                            self._emit({"type": "audio", "hex": data.hex()})
                    elif data[:2] == b"\x01\x86" and phase == 0:
                        # The receiver announces the voice key itself; this works
                        # even when Raw Input is unavailable to the GUI.
                        self._log("voice key frame from receiver")
                        command(1, 0x82, 1, 0)
                        command(1, 8, 1, 0)
                        phase = 1
                        deadline = now + 8
                    elif data[:4] == b"\x01\x08\x01\x00" and phase == 1:
                        command(1, 1, 1, 0)
                        phase = 2
                    elif data[:4] == b"\x01\x01\x01\x00" and phase == 2:
                        phase = 3
                        session_start = now
                        last_audio = 0.0
                        keepalive = 0
                        deadline = now + 60
                        self._emit({"type": "start"})
                if phase == 4 and now >= stop_deadline:
                    phase = 0
                if phase == 3 and not last_audio and now - session_start > 2.0:
                    self._log("no audio after start; closing session")
                    command(1, 0, 0)
                    phase = 0
                    self._emit({"type": "end"})
                if phase == 3 and last_audio and now - last_audio > RELEASE_GAP:
                    # The receiver stops streaming the moment the key is released.
                    self._log(f"audio stopped {now - last_audio:.2f}s; closing session")
                    command(1, 0, 0)
                    phase = 0
                    self._emit({"type": "end"})
                if phase == 3 and now >= keepalive:
                    command(10, 84, 69)
                    keepalive = now + 1
                if phase and now >= deadline:
                    command(1, 0, 0)
                    handshake = phase < 3
                    phase = 0
                    if handshake:
                        self._emit({"type": "warning", "message": "voice handshake timeout"})
                    self._emit({"type": "end"})
        except Exception as exc:
            self._log(f"session error: {exc!r}")
            self.failed.emit(f"遥控器语音通道中断：{exc}")
        finally:
            stop.set()
            self.capture_ready = False
            if phase:
                # Leaving the receiver mid-session keeps the remote's LED on and
                # blocks the next press; always close it explicitly.
                try:
                    device.write(WRITE_ENDPOINT, _frame(1, 0, 0), timeout=1000)
                except Exception:
                    pass
            try:
                usb.util.release_interface(device, VOICE_INTERFACE)
            except Exception:
                pass
