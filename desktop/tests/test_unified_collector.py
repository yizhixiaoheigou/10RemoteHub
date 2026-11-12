"""One collection connection carries keys and encoded audio; no native access."""
import json
from PySide6.QtCore import QObject, Signal
from remotehub.devices import DeviceInput
from remotehub.usb_bridge import USBBridge
from remotehub.session import VoiceSession
from test_ui import FakeAudio, FakeKeys


class Collector(QObject):
    collected = Signal(object)
    capture_stopped = Signal()
    def __init__(self):
        super().__init__()
        self.capture_ready = True
        self.commands = []
    def record(self, active):
        self.commands.append(active)


def test_one_collector_streams_audio_and_disconnect_does_not_drop_keys(qapp, tmp_path):
    source = Collector()
    audio, keys = FakeAudio(), FakeKeys()
    voice = VoiceSession(audio, keys)
    bridge = USBBridge(voice, tmp_path, collector=source)
    bridge.start()
    decoded = []
    class Decoder:
        def reset(self): decoded.append('reset')
        def decode(self, data): decoded.append(data); return b'\0\0'
    bridge.decoder = Decoder()
    bridge.start_audio()
    source.collected.emit({'type': 'start'})
    packet = bytearray(64); packet[:2] = b'\x01\x81'
    packet[6:46] = b'x' * 40
    source.collected.emit({'type': 'audio', 'hex': packet.hex()})
    bridge.stop_audio()
    assert voice.owner == 'usb'  # End event and sink drain release the shortcut.
    packet[46:50] = packet[50:54] = (1).to_bytes(4, 'little')
    source.collected.emit({'type': 'audio', 'hex': packet.hex()})
    source.collected.emit({'type': 'end'})
    audio.ended.emit()
    assert source.commands == [True, False]
    assert decoded == ['reset', b'x'*40, b'x'*40]
    assert audio.events == ['start', b'\0\0', b'\0\0', 'finish']
    assert keys.events == ['down', 'up']
    bridge.stop()
    assert source.capture_ready and not bridge.ready


def test_new_press_after_completed_stop_does_not_cancel_again(qapp, tmp_path):
    source = Collector()
    audio, keys = FakeAudio(), FakeKeys()
    voice = VoiceSession(audio, keys)
    bridge = USBBridge(voice, tmp_path, collector=source)
    bridge.start()
    bridge.start_audio()
    source.collected.emit({"type": "start"})
    bridge.stop_audio()
    assert bridge.cancelled
    source.collected.emit({"type": "end"})
    audio.ended.emit()
    source.collected.emit({"type": "start"})
    assert source.commands == [True, False]
    assert voice.owner == "usb"
    assert not bridge.cancelled
    bridge.stop_audio()
    source.collected.emit({"type": "end"})
    audio.ended.emit()


def test_cancel_before_audio_start_never_triggers_recognition(qapp, tmp_path):
    source = Collector(); audio, keys = FakeAudio(), FakeKeys()
    bridge = USBBridge(VoiceSession(audio, keys), tmp_path, collector=source)
    bridge.start(); bridge.start_audio(); bridge.stop_audio()
    source.collected.emit({'type': 'start'})
    source.collected.emit({'type': 'end'})
    assert not audio.events and not keys.events
    source.capture_ready = False
    source.capture_stopped.emit()
    assert not bridge.ready


def test_sequence_gap_is_resynced_but_a_burst_stops_recording(qapp, tmp_path):
    """One dropped frame must not kill the take; a run of them must."""
    source = Collector(); audio, keys = FakeAudio(), FakeKeys()
    bridge = USBBridge(VoiceSession(audio, keys), tmp_path, collector=source)
    bridge.start(); bridge.start_audio(); source.collected.emit({'type': 'start'})
    bridge.last_seq = (1, 1)
    errors = []; bridge.failed.connect(errors.append)
    packet = bytearray(64); packet[:2] = b'\x01\x81'
    packet[46:50] = packet[50:54] = (3).to_bytes(4, 'little')
    source.collected.emit({'type': 'audio', 'hex': packet.hex()})
    assert not errors and bridge.gaps == 1          # tolerated, session alive
    assert bridge.last_seq == (3, 3)                # resynced to the new frame
    for _ in range(6):
        bridge.last_seq = (1, 1)
        source.collected.emit({'type': 'audio', 'hex': packet.hex()})
    assert errors and '不连续' in errors[0]
    bridge.stop()


def test_raw_hid_descriptor_and_report_share_collector(qapp):
    d = DeviceInput(); keys = []
    d.key.connect(lambda *args: keys.append(args))
    # Synthetic 8-bit array with the real receiver's declared usage maximum FF.
    descriptor = bytes.fromhex('0507190029ff150025ff750895018100')
    for event in ({'type':'descriptor','interface':1,'hex':descriptor.hex()},
                  {'type':'report','interface':1,'hex':'cc'},
                  {'type':'report','interface':1,'hex':'00'}):
        d._event(json.dumps(event).encode(), d.generation)
    assert keys == [('hid:7:204', True), ('hid:7:204', False)]
    d.stop()


def test_shared_capture_failure_waits_for_explicit_retry(qtbot, tmp_path, monkeypatch):
    from remotehub.controller import AppController
    from remotehub.inventory import USBDevice
    c = AppController(tmp_path)
    # Wire the shared bridge on every test platform, without opening hardware.
    if c.usb.collector is None:
        c.usb.collector = c.device
        c.device.capture_stopped.connect(c.usb._collector_stopped)
    calls = []
    monkeypatch.setattr(c.device, 'start', lambda *a: calls.append('start'))
    receiver = USBDevice(0x0416, 0x0602, '', 'Receiver', 'port')
    c.monitor.apply([receiver])
    c.input_ready(c.device.generation)
    c.device.capture_ready = True
    c.usb.ready = c.usb.authenticated = True
    c.device._mac_failed('transport failed', c.device.generation)
    assert not c.enabled and not c.usb.ready
    assert c.mapping_attempted
    qtbot.wait(1100)  # Previously _usb_released scheduled a new capture here.
    c.monitor.apply([receiver])
    assert calls == ['start']
    monkeypatch.setattr(c.monitor, 'refresh', lambda: c.monitor.apply([receiver]))
    c.retry_connection()
    assert calls == ['start', 'start']
    c.shutdown()


def test_windows_collector_stop_clears_pending_session(qapp):
    from remotehub.windows_collector import WindowsCollector

    collector = WindowsCollector()
    collector.frames.put(b'\x01\x86-stale')
    collector._request = True
    collector.stop()
    assert collector.frames.empty()
    assert collector._request is None


def test_windows_collector_reconnect_clears_previous_session(qapp):
    from remotehub.windows_collector import WindowsCollector

    collector = WindowsCollector()

    def disconnected():
        collector.capture_ready = True
        collector.frames.put(b'\x01\x86-stale')
        collector._request = True
        collector.halt.set()

    collector._run = disconnected
    collector._supervise()
    assert not collector.capture_ready
    assert collector.frames.empty()
    assert collector._request is None


def test_windows_key_report_bytes_stay_out_of_logs(qapp):
    import threading
    from remotehub.windows_collector import WindowsCollector

    collector = WindowsCollector()
    logs = []
    collector.log.connect(logs.append)
    stop = threading.Event()

    class Endpoint:
        def read(self, *args, **kwargs):
            stop.set()
            return b'\x01\x02\x03\x04'

    class Parser:
        def decode(self, report):
            raise ValueError('invalid synthetic report')

    collector._key_loop(Endpoint(), Parser(), stop)
    assert logs == ['key report rejected: ValueError']
    assert '01020304' not in ''.join(logs)


def test_missing_microphone_closes_vendor_session_without_killing_capture(qapp, tmp_path):
    import pytest
    source = Collector()
    bridge = USBBridge(VoiceSession(FakeAudio(), FakeKeys()), tmp_path, collector=source)
    with pytest.raises(RuntimeError, match='虚拟麦克风尚未就绪'):
        bridge.start_audio()
    assert source.commands == [False]
    assert source.capture_ready


def test_native_debug_trace_is_logged_without_failing_capture(qapp):
    device = DeviceInput()
    logs, failures = [], []
    device.log.connect(logs.append)
    device.failed.connect(failures.append)
    device._event(json.dumps({'type': 'debug', 'event': 'control_stop', 'phase': 3, 'code': 0}).encode(), device.generation)
    assert logs == ['control_stop:phase=3,code=0']
    assert not failures
    device.stop()


def test_receiver_reenumeration_restarts_recovery(qtbot, tmp_path, monkeypatch):
    from remotehub.controller import AppController
    from remotehub.inventory import USBDevice

    c = AppController(tmp_path)
    receiver = USBDevice(0x0416, 0x0602, "serial", "Receiver", "port-a")
    calls = []
    monkeypatch.setattr(c.device, "start", lambda *a: calls.append("start"))
    monkeypatch.setattr(c.monitor, "refresh", lambda: None)
    c._device_failed("collector read receiver: LIBUSB_ERROR_NO_DEVICE (-4)")
    c.monitor.apply([], error="")
    c._recover_transient()
    assert c.transient_error and not calls
    c.monitor.apply([receiver])
    qtbot.waitUntil(lambda: not c.transient_error, timeout=2000)
    assert calls == ["start"]
    c.shutdown()


def test_native_debug_trace_keeps_control_prefix(qapp):
    device = DeviceInput()
    logs = []
    device.log.connect(logs.append)
    device._event(json.dumps({"type": "debug", "event": "voice_packet", "phase": 3,
                             "code": 0, "hex": "01860000"}).encode(), device.generation)
    assert logs == ["voice_packet:phase=3,code=0,hex=01860000"]
    device.stop()


def test_audio_inactivity_releases_recognition_without_key_release(qapp, tmp_path):
    source = Collector()
    audio, keys = FakeAudio(), FakeKeys()
    bridge = USBBridge(VoiceSession(audio, keys), tmp_path, collector=source)
    bridge.start()
    bridge.start_audio()
    source.collected.emit({'type': 'start'})
    packet = bytearray(64)
    packet[:2] = b'\x01\x81'
    packet[6:46] = b'x' * 40
    source.collected.emit({'type': 'audio', 'hex': packet.hex()})
    assert bridge.inactivity_timer.isActive()
    errors = []
    bridge.failed.connect(errors.append)
    bridge.inactivity_timer.timeout.emit()
    assert source.commands == [True, False]
    assert errors == ['遥控器音频已中断，已自动结束本次语音']
    audio.ended.emit()
    assert keys.events == ['down', 'up']
    assert bridge.voice.owner is None
