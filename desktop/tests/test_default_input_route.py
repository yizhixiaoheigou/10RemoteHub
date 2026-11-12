"""No real audio settings are changed: model HAL notifications and failure races."""
import threading
import pytest
from PySide6.QtCore import QObject, Signal, QTimer
from remotehub.mac_input import InputLease, MacInputRoute, MIC_UID
from remotehub.session import VoiceSession
from test_ui import FakeAudio, FakeKeys


class HAL:
    def __init__(self, current=1):
        self.current = current
        self.devices = {"original": 1, MIC_UID: 2, "manual": 3}
        self.writes = []
        self.callback = None
    def resolve(self, uid): return self.devices.get(uid, 0)
    def uid(self, device): return next(k for k, v in self.devices.items() if v == device)
    def default(self): return self.current
    def listen(self, callback): self.callback = callback
    def unlisten(self): self.callback = None
    def set_default(self, device):
        self.writes.append(device)
        self.change(device)
    def change(self, device):
        self.current = device
        if self.callback: self.callback(device)


def test_lease_restores_by_uid_after_device_ids_change():
    hal = HAL(); lease = InputLease(hal)
    lease.acquire()
    hal.devices["original"] = 41
    lease.release()
    assert hal.writes == [2, 41] and hal.callback is None


def test_user_selection_is_preserved_even_if_they_select_virtual_again():
    hal = HAL(); lease = InputLease(hal)
    lease.acquire(); hal.change(3); hal.change(2); lease.release()
    assert hal.writes == [2] and hal.default() == 2


def test_already_default_is_never_changed():
    hal = HAL(2); lease = InputLease(hal)
    lease.acquire(); lease.release()
    assert not hal.writes and hal.callback is None


def test_missing_virtual_does_not_change_original():
    hal = HAL(); del hal.devices[MIC_UID]
    with pytest.raises(RuntimeError, match="尚未就绪"): InputLease(hal).acquire()
    assert hal.default() == 1 and not hal.writes


def test_missing_original_reports_failure_and_removes_listener():
    hal = HAL(); lease = InputLease(hal)
    lease.acquire(); del hal.devices["original"]
    with pytest.raises(RuntimeError, match="原麦克风已断开"): lease.release()
    assert hal.callback is None


def test_unconfirmed_set_does_not_pretend_success():
    hal = HAL(); hal.set_default = lambda device: hal.writes.append(device)
    lease = InputLease(hal, timeout=0.01)
    with pytest.raises(RuntimeError, match="未及时完成"): lease.acquire()
    lease.release()
    assert hal.current == 1 and hal.writes == [2, 1]


def test_delayed_notification_wakes_switch_without_fixed_delay():
    hal = HAL()
    def later(device):
        threading.Timer(0.01, lambda: hal.change(device)).start()
    hal.set_default = later
    lease = InputLease(hal)
    lease.acquire(); assert hal.default() == 2
    lease.release(); assert hal.default() == 1


class Route(QObject):
    ready = Signal(); failed = Signal(str); released = Signal()
    def __init__(self): super().__init__(); self.events = []
    def acquire(self): self.events.append("switch")
    def release(self): self.events.append("restore")
    def close(self): self.events.append("close")


def session():
    audio, keys, route = FakeAudio(), FakeKeys(), Route()
    return VoiceSession(audio, keys, route=route), audio, keys, route


def test_confirm_before_recognition_buffer_first_pcm_and_restore_after_tail(qapp):
    voice, audio, keys, route = session()
    voice.start("usb"); voice.feed("usb", b"\x01\x00")
    assert route.events == ["switch"] and not keys.events and not audio.events
    route.ready.emit()
    assert audio.events == ["start", b"\x01\x00"] and keys.events == ["down"]
    voice.finish("usb")
    assert route.events == ["switch"]
    audio.ended.emit()
    assert keys.events == ["down", "up"] and route.events == ["switch", "restore"]
    assert voice.owner == "usb"  # No new session may race the restoration.
    route.released.emit()
    assert voice.owner is None


@pytest.mark.parametrize("end", ["cancel", "finish"])
def test_release_during_switch_never_triggers_late_recognition(qapp, end):
    voice, audio, keys, route = session()
    voice.start("usb")
    voice.finish("usb") if end == "finish" else voice.cancel()
    route.ready.emit(); route.released.emit()
    assert not keys.events and "start" not in audio.events and voice.owner is None


def test_switch_failure_restores_and_reports_without_triggering(qapp):
    voice, audio, keys, route = session(); errors = []
    voice.failed.connect(errors.append)
    voice.start("usb"); route.failed.emit("failed")
    assert route.events == ["switch", "restore"] and not keys.events
    route.released.emit()
    assert errors == ["failed"] and voice.owner is None


def test_sink_failure_after_switch_restores(qapp):
    voice, audio, keys, route = session()
    def fail(*_): raise RuntimeError("sink failed")
    audio.start = fail
    voice.start("usb"); route.ready.emit()
    assert route.events == ["switch", "restore"] and not keys.events
    route.released.emit(); assert voice.owner is None


def test_buffer_is_bounded_on_stalled_audio_service(qapp):
    voice, audio, keys, route = session()
    voice.start("usb"); voice.feed("usb", b"\0"*32000)
    with pytest.raises(RuntimeError, match="耗时过长"): voice.feed("usb", b"\0\0")
    assert not voice.pending and not keys.events and route.events[-1] == "restore"
    route.released.emit()


def test_switch_watchdog_cancels_even_when_no_audio_arrives(qapp):
    voice, audio, keys, route = session()
    voice.start("usb"); voice.route_timeout.timeout.emit()
    route.ready.emit(); route.released.emit()
    assert not keys.events and voice.owner is None and not voice.route_timeout.isActive()


@pytest.mark.parametrize("owner", ["trigger", "wav"])
def test_computer_mic_and_file_diagnostics_do_not_switch(qapp, owner):
    voice, audio, keys, route = session()
    voice.start(owner); voice.cancel()
    assert not route.events and keys.events == ["down", "up"]


def test_async_worker_does_not_block_gui_and_cancel_restores(qtbot):
    hal = HAL(); gate = threading.Event(); entered = threading.Event()
    write = hal.set_default
    def blocked(device):
        if device == 2:
            entered.set(); gate.wait(2)
        write(device)
    hal.set_default = blocked
    route = MacInputRoute(backend_factory=lambda: hal)
    ready, ticks = [], []
    route.ready.connect(lambda: ready.append(True))
    timer = QTimer(); timer.setInterval(5); timer.timeout.connect(lambda: ticks.append(1))
    timer.start()
    try:
        route.acquire()
        qtbot.waitUntil(entered.is_set)
        qtbot.waitUntil(lambda: len(ticks) >= 3)
        route.release(); gate.set()
        qtbot.waitUntil(lambda: route.state == "idle")
        assert not ready and hal.current == 1 and hal.writes == [2, 1]
    finally:
        gate.set(); timer.stop(); route.close()


def test_exit_restores_without_processing_qt_events(qapp):
    hal = HAL(); route = MacInputRoute(backend_factory=lambda: hal)
    route.acquire(); route.close()
    assert hal.current == 1 and hal.writes == [2, 1]


def test_restore_error_still_ends_session_and_reports(qtbot):
    hal = HAL(); route = MacInputRoute(backend_factory=lambda: hal)
    voice = VoiceSession(FakeAudio(), FakeKeys(), route=route)
    errors = []; voice.failed.connect(errors.append)
    try:
        voice.start("usb")
        qtbot.waitUntil(lambda: voice.recognition_started)
        del hal.devices["original"]
        voice.cancel()
        qtbot.waitUntil(lambda: voice.owner is None)
        assert any("恢复原麦克风失败" in e for e in errors)
    finally:
        voice.close()


def test_failed_listener_cleanup_is_retried_before_next_registration(qtbot):
    hal = HAL(); attempts = []
    def remove():
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("audio service unavailable")
        hal.callback = None
    hal.unlisten = remove
    route = MacInputRoute(backend_factory=lambda: hal)
    try:
        route.acquire(); qtbot.waitUntil(lambda: route.state == "active")
        route.release(); qtbot.waitUntil(lambda: route.state == "idle")
        route.acquire(); qtbot.waitUntil(lambda: route.state == "active")
        assert len(attempts) == 2 and hal.current == 2
        route.release(); qtbot.waitUntil(lambda: route.state == "idle")
        assert hal.current == 1 and hal.callback is None
    finally:
        route.close()
