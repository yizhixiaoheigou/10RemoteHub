"""Use native QtAudio enums with simulated sinks; never open real audio devices."""
from types import SimpleNamespace
import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtMultimedia import QtAudio
from remotehub import audio


class FakeSink(QObject):
    stateChanged = Signal(object)
    startup_error = QtAudio.Error.NoError

    def __init__(self, *args):
        super().__init__()
        self.current_error = self.startup_error
        self.current_state = QtAudio.State.StoppedState

    def setBufferSize(self, size): self.size = size
    def bufferSize(self): return self.size
    def error(self): return self.current_error
    def state(self): return self.current_state

    def start(self, buffer):
        self.current_state = (QtAudio.State.ActiveState if self.current_error == QtAudio.Error.NoError
                              else QtAudio.State.StoppedState)
        self.stateChanged.emit(self.current_state)

    def stop(self):
        self.current_error = QtAudio.Error.NoError
        self.current_state = QtAudio.State.StoppedState
        self.stateChanged.emit(self.current_state)


@pytest.fixture
def bridge(qapp, monkeypatch):
    monkeypatch.setattr(audio, 'QAudioSink', FakeSink)
    monkeypatch.setattr(FakeSink, 'startup_error', QtAudio.Error.NoError)
    device = SimpleNamespace(id=lambda: b'virtual', isFormatSupported=lambda fmt: True)
    instance = audio.AudioBridge()
    monkeypatch.setattr(instance, 'outputs', lambda: [device])
    yield instance
    instance.abort()


def test_successful_qt_audio_enum_is_not_treated_as_open_failure(bridge):
    bridge.start(b'virtual')
    assert bridge.active and bridge.sink.state() == QtAudio.State.ActiveState
    bridge.feed(bytes(640))
    assert bridge.buffer.size > 0


def test_open_error_remains_visible_after_sink_stop_resets_it(bridge, monkeypatch):
    monkeypatch.setattr(FakeSink, 'startup_error', QtAudio.Error.OpenError)
    with pytest.raises(RuntimeError, match='OpenError'):
        bridge.start(b'virtual')
    assert not bridge.active and bridge.sink is None and bridge.buffer is None


def test_real_failure_state_aborts_once_and_releases_buffer(bridge):
    ended, failed = [], []
    bridge.ended.connect(lambda: ended.append(True))
    bridge.failed.connect(failed.append)
    bridge.start(b'virtual')
    bridge.sink.current_error = QtAudio.Error.IOError
    bridge.sink.current_state = QtAudio.State.StoppedState
    bridge.sink.stateChanged.emit(QtAudio.State.StoppedState)
    assert len(ended) == 1 and len(failed) == 1
    assert 'IOError' in failed[0]
    assert not bridge.active and bridge.sink is None and bridge.buffer is None
