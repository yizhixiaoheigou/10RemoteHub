from PySide6.QtCore import QObject, QTimer, Signal


class KeyGesture(QObject):
    triggered = Signal(object)
    released = Signal(object)

    DOUBLE_INTERVAL = 280
    LONG_PRESS = 550

    def __init__(self, button, parent=None):
        super().__init__(parent)
        self.single_action = button.action
        self.double_action = button.double_action
        self.long_action = button.long_action
        self.holding = False
        self.awaiting_second = False
        self.long_fired = False
        self.active_hold = None
        self.single_timer = QTimer(self)
        self.single_timer.setSingleShot(True)
        self.single_timer.setInterval(self.DOUBLE_INTERVAL)
        self.single_timer.timeout.connect(self._single)
        self.long_timer = QTimer(self)
        self.long_timer.setSingleShot(True)
        self.long_timer.setInterval(self.LONG_PRESS)
        self.long_timer.timeout.connect(self._long)

    @staticmethod
    def needed(button):
        return button.double_action.kind != "none" or button.long_action.kind != "none"

    def handle(self, down):
        if down:
            if self.awaiting_second:
                action = self.double_action
                self._reset()
                self.holding = True
                self.long_fired = True  # second down already consumed this click
                self._fire(action)
                return
            if self.holding:
                return
            self.holding = True
            if self.long_action.kind != "none":
                self.long_timer.start()
            return
        if not self.holding:
            return
        self.holding = False
        self._release_hold()
        self.long_timer.stop()
        if self.long_fired:
            self._reset()
        elif self.double_action.kind != "none":
            self.awaiting_second = True
            self.single_timer.start()
        else:
            action = self.single_action
            self._reset()
            self._fire(action)

    def _single(self):
        action = self.single_action
        self._reset()
        self._fire(action)

    def _long(self):
        self.long_fired = True
        self.awaiting_second = False
        self.single_timer.stop()
        self._fire(self.long_action)

    def _fire(self, action):
        held = action.kind == "hold" and action.target == "hold"
        if held:
            self.active_hold = action
        self.triggered.emit(action)
        # A delayed single fires after physical release: pair its down immediately.
        if held and not self.holding:
            self._release_hold()

    def _release_hold(self):
        action, self.active_hold = self.active_hold, None
        if action is not None:
            self.released.emit(action)

    def _reset(self):
        self._release_hold()
        self.single_timer.stop()
        self.long_timer.stop()
        self.holding = False
        self.awaiting_second = False
        self.long_fired = False

    def cancel(self):
        self._reset()
