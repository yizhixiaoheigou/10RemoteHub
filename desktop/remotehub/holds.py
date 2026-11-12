"""Owned, bounded modifier holds shared by mappings and voice input."""
from PySide6.QtCore import QObject, QTimer, Signal


class InputHolds(QObject):
    changed = Signal()

    def __init__(self, keys, parent=None):
        super().__init__(parent)
        self.keys = keys
        self.timers = {}
        self.timeouts = {}

    @property
    def active(self):
        return bool(self.keys.owned_modifiers())

    def owned(self, owner):
        return bool(self.keys.owned_modifiers(owner))

    def hold(self, owner, keys, timeout=60_000, on_timeout=None):
        self.keys.hold(owner, keys)
        self.timeouts[owner] = on_timeout
        timer = self.timers.get(owner)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda: self._expire(owner))
            self.timers[owner] = timer
        timer.start(timeout)
        self.changed.emit()

    def _expire(self, owner):
        callback = self.timeouts.pop(owner, None)
        if callback is not None:
            callback()
        else:
            self.release(owner)

    def release(self, owner):
        self.timeouts.pop(owner, None)
        timer = self.timers.pop(owner, None)
        if timer is not None:
            timer.stop()
        self.keys.release_owned(owner)
        self.changed.emit()

    def toggle(self, owner, keys):
        if self.owned(owner):
            self.release(owner)
        else:
            self.hold(owner, keys)

    def close(self):
        errors = []
        for owner in list(self.timers):
            try:
                self.release(owner)
            except Exception as exc:
                errors.append(exc)
        try:
            self.keys.release_all_owned()
        except Exception as exc:
            errors.append(exc)
        self.changed.emit()
        if errors:
            raise errors[0]
