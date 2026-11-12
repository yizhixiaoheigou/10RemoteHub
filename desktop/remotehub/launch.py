"""Run desktop opener commands without blocking input, audio or the GUI."""
from dataclasses import dataclass
from PySide6.QtCore import QObject, QProcess, QTimer, Signal


@dataclass
class LaunchRequest:
    command: list[str]
    success: str = "已请求打开"


class Launcher(QObject):
    finished = Signal(str, bool)

    def __init__(self, parent=None, timeout_ms=15000):
        super().__init__(parent)
        self.jobs = set()
        self.timeout_ms = timeout_ms

    def start(self, request):
        if len(self.jobs) >= 8:
            self.finished.emit("打开操作过多，请稍后再试", True)
            return
        process = QProcess(self)
        timer = QTimer(process)
        timer.setSingleShot(True)
        errors = bytearray()
        self.jobs.add(process)
        process.setStandardOutputFile(QProcess.nullDevice())

        def read_error():
            data = bytes(process.readAllStandardError())
            errors.extend(data[:max(0, 4096 - len(errors))])

        def complete(message, failed):
            if process not in self.jobs:
                return
            self.jobs.remove(process)
            timer.stop()
            self.finished.emit(message, failed)
            if process.state() != QProcess.ProcessState.NotRunning:
                process.finished.connect(process.deleteLater)
                process.kill()
            else:
                process.deleteLater()

        def done(code, status):
            read_error()
            failed = bool(code) or status != QProcess.ExitStatus.NormalExit
            complete(errors.decode('utf-8', 'replace').strip() or "打开失败" if failed else request.success, failed)

        process.readyReadStandardError.connect(read_error)
        process.finished.connect(done)
        process.errorOccurred.connect(lambda error: complete("无法启动打开程序，请检查应用或文件路径", True)
                                      if error == QProcess.ProcessError.FailedToStart else None)
        timer.timeout.connect(lambda: complete("打开操作超时，请检查目标应用或磁盘后重试", True))
        timer.start(self.timeout_ms)
        process.start(request.command[0], request.command[1:])

    def stop(self):
        # Kill only opener utilities, never the application they opened.
        for process in list(self.jobs):
            self.jobs.discard(process)
            process.blockSignals(True)
            process.kill()
            process.waitForFinished(100)
            process.deleteLater()
