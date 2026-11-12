"""Bounded PCM stream, gain/filter, and explicit virtual-output routing."""
from __future__ import annotations
from collections import deque
import math
import threading
import time
import numpy as np
from PySide6.QtCore import QIODevice, QObject, QTimer, Signal, Slot
from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices, QtAudio


class PCMProcessor:
    """16 kHz mono s16 input; state persists across packet boundaries.

    Conservative high-pass + gain + limiter, no destructive fixed lead trim.
    Linear interpolation is stateful; hardware rate is selected explicitly.
    """
    def __init__(self, output_rate=48000, channels=2, gain_db=12.0, highpass=100):
        if output_rate < 16000 or channels not in (1, 2):
            raise ValueError("输出需要至少 16 kHz、单声道或双声道")
        self.rate, self.channels = output_rate, channels
        self.gain = 10 ** (gain_db/20)
        self.alpha = math.exp(-2*math.pi*highpass/16000)
        self.last_x = self.last_y = 0.0
        self.tail = np.empty(0, dtype=np.float32)
        # Rational phase in units of output-rate: avoids floating point packet
        # boundary drift (e.g. 16 kHz -> 48 kHz yielding an extra sample per block).
        self.phase = 0
        self.level = 0.0

    def process(self, pcm: bytes):
        if len(pcm) % 2:
            raise ValueError("PCM 音频必须按 16-bit 样本对齐")
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
        if not len(samples):
            return np.empty((0, self.channels), dtype=np.float32)
        out = np.empty_like(samples)
        for i, value in enumerate(samples):
            self.last_y = self.alpha * (self.last_y + float(value) - self.last_x)
            self.last_x = float(value)
            out[i] = self.last_y
        out = np.clip(out*self.gain, -0.8913, 0.8913)
        self.level = float(np.sqrt(np.mean(out*out)))
        values = np.concatenate((self.tail, out))
        phases = np.arange(self.phase, (len(values)-1)*self.rate, 16000, dtype=np.int64)
        positions = phases/self.rate
        resampled = np.interp(positions, np.arange(len(values)), values).astype(np.float32)
        end = int(phases[-1])+16000 if len(phases) else self.phase
        keep = max(0, len(values)-1)
        self.tail = values[keep:]
        self.phase = end-keep*self.rate
        return np.repeat(resampled[:, None], self.channels, axis=1)

    def flush(self):
        if not len(self.tail):
            return np.empty((0,self.channels),dtype=np.float32)
        phases=np.arange(self.phase,len(self.tail)*self.rate,16000,dtype=np.int64)
        out=np.repeat(self.tail[-1:],len(phases))
        self.tail=np.empty(0,dtype=np.float32); self.phase=0
        return np.repeat(out[:,None],self.channels,axis=1)


class PCMQueue(QIODevice):
    def __init__(self, bytes_per_second, parent=None):
        super().__init__(parent)
        self.chunks = deque()
        self.size = 0
        self.limit = bytes_per_second * 2
        self.lock = threading.Lock()
        self.open(QIODevice.OpenModeFlag.ReadOnly)

    def isSequential(self):
        return True

    def bytesAvailable(self):
        # Always produce silence during input jitter; never re-play old samples.
        return max(16384, self.size) + super().bytesAvailable()

    def push(self, data):
        with self.lock:
            if self.size + len(data) > self.limit:
                raise BufferError("音频输出积压超过两秒，已停止本次语音")
            if data:
                self.chunks.append(data)
                self.size += len(data)

    def readData(self, maximum):
        out = bytearray()
        with self.lock:
            while self.chunks and len(out) < maximum:
                block = self.chunks.popleft()
                take = min(len(block), maximum-len(out))
                out.extend(block[:take]); self.size -= take
                if take < len(block):
                    self.chunks.appendleft(block[take:])
        out.extend(b"\0"*(maximum-len(out)))
        return bytes(out)

    def writeData(self, data):
        return -1


class AudioBridge(QObject):
    changed = Signal(str)
    level = Signal(float)
    failed = Signal(str)
    ended = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.log = lambda event, **fields: None
        self.pushed = 0
        self.sink = self.buffer = self.processor = None
        self.active = False
        self.starting = False
        self.finishing = False
        self.timer = QTimer(self)
        self.timer.setInterval(20)
        self.timer.timeout.connect(self._drain)
        self.deadline = 0
        self.empty_since = None

    @staticmethod
    def outputs():
        return QMediaDevices.audioOutputs()

    def start(self, device_id: bytes, gain_db=12):
        if self.active:
            raise RuntimeError("已有语音会话，请先结束")
        device = next((d for d in self.outputs() if bytes(d.id()) == device_id), None)
        if device is None:
            raise RuntimeError("选定的虚拟麦克风输出不可用，请重新选择")
        fmt = QAudioFormat()
        fmt.setSampleRate(48000); fmt.setChannelCount(2)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Float)
        if not device.isFormatSupported(fmt):
            fmt = device.preferredFormat()
        if fmt.sampleFormat() not in (QAudioFormat.SampleFormat.Float, QAudioFormat.SampleFormat.Int16, QAudioFormat.SampleFormat.Int32):
            raise RuntimeError("该输出设备的音频格式不受支持")
        self.processor = PCMProcessor(fmt.sampleRate(), fmt.channelCount(), gain_db)
        self.format = fmt
        self.buffer = PCMQueue(fmt.bytesForDuration(1_000_000), self)
        self.sink = QAudioSink(device, fmt, self)
        self.sink.setBufferSize(fmt.bytesForDuration(80_000))
        self.sink.stateChanged.connect(self._state)
        self.active, self.finishing = True, False
        self.starting = True
        try:
            self.sink.start(self.buffer)
        except Exception:
            self.abort()
            raise
        finally:
            self.starting = False
        # QAudio is a legacy Python namespace with distinct enums on Qt 6.12.
        # Compare the QtAudio enums actually returned by QAudioSink, and capture
        # the error before stop() clears it. Synchronous startup signals are
        # handled here so they cannot delete the sink while start() is running.
        error = self.sink.error()
        if error != QtAudio.Error.NoError:
            self.abort()
            raise RuntimeError(f"虚拟麦克风启动失败（{error.name}），请重新检测音频设备")
        self.changed.emit("语音输入已开始")
        name = device.description() if hasattr(device, "description") else str(device)
        self.log("audio_start", device=name, rate=fmt.sampleRate(),
                 channels=fmt.channelCount(), sample_format=fmt.sampleFormat().name)

    def feed(self, pcm):
        if not self.active or self.finishing:
            raise RuntimeError("当前没有接收音频的会话")
        self.pushed += 1
        samples = self.processor.process(pcm)
        self._queue(samples)
        self.level.emit(self.processor.level)

    def _queue(self,samples):
        sf = self.format.sampleFormat()
        if sf == QAudioFormat.SampleFormat.Float:
            data = samples.astype("<f4").tobytes()
        elif sf == QAudioFormat.SampleFormat.Int16:
            data = (samples*32767).astype("<i2").tobytes()
        else:
            data = (samples*2147483647).astype("<i4").tobytes()
        self.buffer.push(data)

    def finish(self):
        if not self.active or self.finishing:
            return
        self._queue(self.processor.flush())
        self.finishing = True
        self.deadline = time.monotonic()+4
        self.empty_since = None
        self.timer.start()

    def _drain(self):
        now = time.monotonic()
        if self.buffer.size == 0:
            if self.empty_since is None:
                self.empty_since = now
            # Drain native sink buffer as well before releasing recognition key.
            latency = self.format.durationForBytes(self.sink.bufferSize())/1_000_000 + 0.1
            if now-self.empty_since >= latency:
                self.abort()
                return
        if now > self.deadline:
            self.failed.emit("音频输出未能及时完成，已停止")
            self.abort()

    @Slot()
    def _state(self):
        # Some PySide versions retain QAudio::State in the signal signature.
        # A no-argument slot reads the actual QtAudio.State from the sink,
        # avoiding conversion through that obsolete signal parameter type.
        if self.starting or not self.sink:
            return
        state = self.sink.state()
        error = self.sink.error()
        if state == QtAudio.State.StoppedState and error != QtAudio.Error.NoError:
            self.failed.emit(f"虚拟麦克风已断开或输出失败（{error.name}），请重新检测音频设备")
            self.abort()

    def abort(self):
        was_active = self.active
        self.active = self.finishing = False
        self.timer.stop()
        sink, self.sink = self.sink, None
        if sink:
            sink.stop(); sink.deleteLater()
        if self.buffer:
            self.buffer.close(); self.buffer.deleteLater(); self.buffer = None
        self.level.emit(0)
        if was_active:
            self.ended.emit()
            self.changed.emit("语音输入已结束")
