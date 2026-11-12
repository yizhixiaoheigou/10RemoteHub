"""GUI-side authenticated loopback link to the explicitly authorized USB worker."""
import base64
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
from PySide6.QtCore import QObject, Signal, QTimer
from PySide6.QtNetwork import QTcpServer, QHostAddress, QNetworkProxy


class USBBridge(QObject):
    status=Signal(str)
    failed=Signal(str)
    key=Signal(str,bool)
    started=Signal()
    recording_started=Signal()
    changed=Signal()
    disconnected=Signal()
    recording_stopped=Signal()
    def __init__(self, voice, directory, parent=None, *, collector=None, log=None):
        super().__init__(parent)
        self.voice,self.directory=voice,Path(directory)
        self.collector = collector
        self.log = log or (lambda event, **fields: None)
        self.decoder = None
        self.last_seq = None
        if collector is not None:
            collector.collected.connect(self._collected)
            collector.capture_stopped.connect(self._collector_stopped)
        self.server=QTcpServer(self)
        self.server.setProxy(QNetworkProxy(QNetworkProxy.ProxyType.NoProxy))
        self.server.newConnection.connect(self._connect)
        self.client=None; self.pending=b""; self.authenticated=False; self.ready=False
        self.process=None; self.auth_file=None; self.script=None
        self.recording_requested=False
        self.cancelled=False   # an explicit stop outranks a late collector start
        self.logged_audio=False
        self.gaps=0
        self.audio_frames=0
        self.auth_timer=QTimer(self); self.auth_timer.setSingleShot(True)
        self.auth_timer.timeout.connect(self._auth_expired)
        self.start_timer=QTimer(self); self.start_timer.setSingleShot(True)
        self.start_timer.timeout.connect(self._start_expired)
        self.inactivity_timer=QTimer(self); self.inactivity_timer.setSingleShot(True)
        self.inactivity_timer.setInterval(1000)
        self.inactivity_timer.timeout.connect(self._inactivity_expired)

    def start(self):
        if self.collector is not None:
            if not self.collector.capture_ready:
                raise RuntimeError("请先在通用设置完成设备采集接入")
            if self.ready:
                raise RuntimeError("遥控器音频已经连接")
            from .codec.g7221 import Decoder
            self.decoder = Decoder()
            self.cancelled = False
            self.ready = self.authenticated = True
            self.changed.emit()
            self.started.emit()
            return
        if sys.platform == "darwin":
            raise RuntimeError("音频组件不完整，请更新 10RemoteHub")
        if self.server.isListening() or self.client: raise RuntimeError("USB 接入已启动")
        if not self.server.listen(QHostAddress.SpecialAddress.LocalHost,0): raise RuntimeError("无法建立本机 USB 通道")
        self.token=secrets.token_hex(32)
        self.directory.mkdir(parents=True,exist_ok=True)
        self.auth_file=self.directory/("worker-"+secrets.token_hex(8)+".auth")
        fd=os.open(self.auth_file,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,"w",encoding="utf-8") as f: f.write(self.token)
        if getattr(sys,"frozen",False):
            args=[sys.executable,"--usb-worker"]
        else:
            args=[sys.executable,"-m","remotehub.usb_worker"]
        args += ["--port",str(self.server.serverPort()),"--auth-file",str(self.auth_file)]
        try:
            self.process=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            self.auth_timer.start(90_000)
            self.status.emit("等待 USB 接入授权；接入期间由本程序处理该接收器")
        except Exception:
            self.stop(); raise

    def _connect(self):
        sock=self.server.nextPendingConnection()
        if self.client is not None:
            sock.abort(); sock.deleteLater(); return
        self.client=sock; self.pending=b""
        sock.readyRead.connect(self._read)
        sock.disconnected.connect(self._disconnect)

    def _read(self):
        self.pending+=bytes(self.client.readAll())
        if len(self.pending)>1_000_000:
            self.failed.emit("USB 通道数据超限"); self.stop(); return
        while b"\n" in self.pending and self.client:
            line,self.pending=self.pending.split(b"\n",1)
            try:
                event=json.loads(line)
                if not self.authenticated:
                    import hmac
                    supplied=event.get("token","")
                    if event.get("type")!="auth" or not isinstance(supplied,str) or not hmac.compare_digest(supplied,self.token):
                        self.client.abort(); return
                    self.authenticated=True; self.auth_timer.stop(); self.server.close()
                    continue
                kind=event.get("type")
                if kind=="ready":
                    self.ready=True; self.changed.emit(); self.status.emit("遥控器音频已就绪"); self.started.emit()
                elif kind=="start":
                    self.start_timer.stop()
                    if self.recording_requested:
                        self.voice.start("usb")
                    else:
                        self.stop_audio()
                elif kind=="pcm" and self.voice.owner=="usb":
                    self.voice.feed("usb",base64.b64decode(event["data"],validate=True))
                elif kind=="end":
                    self.recording_requested=False
                    self.voice.finish("usb")
                    self.recording_stopped.emit()
                elif kind=="key": self.key.emit(event["trigger"],event["down"])
                elif kind=="warning": self.failed.emit(event["message"])
                elif kind=="restored":
                    if event.get("errors"): self.failed.emit("接收器恢复失败，请拔插："+str(event["errors"]))
                    else: self.status.emit("遥控器音频已断开")
            except Exception as exc:
                self.failed.emit(str(exc)); self.stop_audio()

    def _collected(self, event):
        if not self.ready:
            return
        try:
            kind = event["type"]
            if kind == "start":
                self.start_timer.stop()
                self.last_seq = None
                self.logged_audio = False
                self.gaps = 0
                self.audio_frames = 0
                self.decoder.reset()
                # The receiver only streams for the physical voice key, so a
                # start may arrive a few milliseconds before the GUI sees the
                # key. Accept that, but never resurrect a session the user
                # already cancelled.
                if self.cancelled:
                    self.stop_audio()
                else:
                    self.recording_requested = True
                    self.voice.start("usb")
                    self.recording_started.emit()
                    self.log("voice_open")
            elif kind == "audio" and self.voice.owner == "usb":
                packet = bytes.fromhex(event["hex"])
                if len(packet) != 64 or packet[:2] != b"\x01\x81":
                    raise ValueError("遥控器音频包不完整")
                self.inactivity_timer.start()
                seq = tuple(int.from_bytes(packet[n:n+4], "little") for n in (46, 50))
                if self.last_seq and any(b != (a+1) & 0xffffffff for a, b in zip(self.last_seq, seq)):
                    # A single dropped frame is a transport hiccup, not a reason
                    # to end the take: never fabricate samples, just resync and
                    # report. Only a burst of gaps means the link is broken.
                    self.gaps += 1
                    self.log("voice_seq_gap", count=self.gaps)
                    if self.gaps > 5:
                        raise ValueError("遥控器音频包不连续")
                self.last_seq = seq
                pcm = self.decoder.decode(packet[6:46])
                self.audio_frames += 1
                if not self.logged_audio:
                    self.logged_audio = True
                    self.log("voice_audio", bytes=len(pcm))
                elif self.audio_frames % 100 == 0:
                    self.log("voice_audio_progress", frames=self.audio_frames)
                try:
                    self.voice.feed("usb", pcm)
                except RuntimeError:
                    # Tail packets keep arriving while the session is closing;
                    # they are expected, not a failure.
                    pass
            elif kind == "end":
                self.start_timer.stop()
                self.inactivity_timer.stop()
                self.recording_requested = False
                self.cancelled = False
                self.voice.finish("usb")
                self.recording_stopped.emit()
            elif kind == "warning":
                self.failed.emit("遥控器录音启动超时，请松开语音键后重试。" if event["message"] == "voice handshake timeout" else event["message"])
        except Exception as exc:
            self.failed.emit(str(exc))
            self.stop_audio()

    def _collector_stopped(self):
        if self.ready:
            self.stop()

    def start_audio(self):
        self.cancelled = False
        if (self.collector is None and not self.client) or not self.authenticated or not self.ready:
            if self.collector is not None:
                if self.collector.capture_ready:
                    self.collector.record(False)
                raise RuntimeError("虚拟麦克风尚未就绪。请在语音设置安装或完成设置后，再按语音键。")
            raise RuntimeError("请先在语音设置中连接遥控器音频")
        if self.recording_requested or self.voice.owner is not None:
            raise RuntimeError("上一段语音尚未结束")
        self.recording_requested=True
        self.start_timer.start(10_000)
        if self.collector is not None:
            self.collector.record(True)
        else:
            self.client.write(b'{"type":"start"}\n'); self.client.flush()

    def stop_audio(self):
        self.cancelled=True
        self.recording_requested=False
        self.start_timer.stop()
        self.inactivity_timer.stop()
        if self.collector is not None and self.collector.capture_ready:
            self.collector.record(False)
        elif self.client and self.authenticated:
            self.client.write(b'{"type":"stop"}\n'); self.client.flush()
        else:
            self.voice.finish("usb")

    def _inactivity_expired(self):
        if self.voice.owner != "usb":
            return
        self.log("voice_inactivity")
        self.failed.emit("遥控器音频已中断，已自动结束本次语音")
        self.stop_audio()
        self.voice.finish("usb")
        self.recording_stopped.emit()

    def _start_expired(self):
        self.stop_audio()
        self.recording_stopped.emit()
        self.failed.emit("遥控器未能开始传送音频，请检查音频连接后重试")

    def _auth_expired(self):
        self.failed.emit("USB 接入未完成；请查看接入终端中的权限或驱动提示")
        self.stop()
        self.disconnected.emit()

    def _disconnect(self):
        sock,self.client=self.client,None
        if sock: sock.deleteLater()
        self.authenticated=False
        self.recording_requested=False
        self.start_timer.stop()
        self.inactivity_timer.stop()
        self.ready=False; self.changed.emit()
        if self.voice.owner=="usb": self.voice.cancel()
        self._clean_files()
        self.status.emit("USB 接入已断开")
        self.recording_stopped.emit()
        self.disconnected.emit()

    def _clean_files(self):
        for path in (self.auth_file,self.script):
            if path and path.exists(): path.unlink()
        self.auth_file=self.script=None

    def stop(self):
        if self.collector is not None:
            linked = self.ready
            if linked and self.collector.capture_ready:
                self.collector.record(False)
            self.ready = self.authenticated = self.recording_requested = False
            self.start_timer.stop()
            self.inactivity_timer.stop()
            if self.voice.owner == "usb":
                self.voice.cancel()
            self.decoder = None
            self.last_seq = None
            self.changed.emit()
            if linked:
                self.recording_stopped.emit()
                self.disconnected.emit()
            return
        self.recording_requested=False
        self.start_timer.stop()
        self.ready=False; self.changed.emit()
        self.auth_timer.stop(); self.server.close()
        if self.client:
            self.client.write(b'{"type":"exit"}\n'); self.client.flush()
            self.client.disconnectFromHost()
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try: self.process.wait(4)
            except subprocess.TimeoutExpired: self.failed.emit("遥控器连接尚未关闭，请重新检测")
        self.process=None
        if self.voice.owner=="usb": self.voice.cancel()
        self._clean_files()
