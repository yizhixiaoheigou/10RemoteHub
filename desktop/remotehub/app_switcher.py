"""Full application switcher built on the shared modifier-hold state."""
import sys
import time
from PySide6.QtCore import QObject, QTimer


def dock_window_count():
    if sys.platform != "darwin":
        return None
    from AppKit import NSRunningApplication
    from Quartz import CGWindowListCopyWindowInfo, kCGWindowListOptionAll, kCGNullWindowID
    dock = NSRunningApplication.runningApplicationsWithBundleIdentifier_("com.apple.dock").firstObject()
    if dock is None:
        return None
    windows = CGWindowListCopyWindowInfo(kCGWindowListOptionAll, kCGNullWindowID) or []
    pid = dock.processIdentifier()
    return sum(window.get("kCGWindowOwnerPID") == pid for window in windows)


class AppSwitcher(QObject):
    OWNER = "app_switcher"

    def __init__(self, holds, parent=None, *, window_counter=dock_window_count, sleeper=time.sleep):
        super().__init__(parent)
        self.holds = holds
        self.keys = holds.keys
        self.window_counter = window_counter
        self.sleep = sleeper
        self.log = lambda event, **fields: None
        self.owner = None
        self.baseline = None
        self.opened = False
        self.navigated = False
        self.option_held = False
        self.open_timer = QTimer(self)
        self.open_timer.setSingleShot(True)
        self.open_timer.setInterval(320)
        self.open_timer.timeout.connect(self._verify_open)
        self.watch = QTimer(self)
        self.watch.setInterval(500)
        self.watch.timeout.connect(self._external_check)
        holds.changed.connect(self._sync)

    @property
    def active(self):
        return self.owner is not None

    @property
    def modifier(self):
        return "cmd" if sys.platform == "darwin" else "alt"

    def _sync(self):
        if not self.holds.owned(self.OWNER):
            if self.active:
                self.log("switcher_sync_lost", owner=self.owner)
            self.owner = None
            self.baseline = None
            self.opened = False
            self.navigated = False
            self.open_timer.stop()
            self.watch.stop()

    def _externally_closed(self):
        if self.baseline is None:
            return False
        count = self.window_counter()
        if count is not None and count > self.baseline:
            self.opened = True
        return self.opened and count is not None and count <= self.baseline

    def _external_check(self):
        if self._externally_closed():
            self._release_only("window_closed")

    def _verify_open(self):
        if not self.active:
            return
        count = self.window_counter()
        if count is not None and self.baseline is not None and count > self.baseline:
            self.opened = True
        self.log("switcher_open", dock_windows=count, baseline=self.baseline, opened=self.opened)
        if not self.opened:
            self.keys.chord([self.modifier, "tab"], hold_ms=25)

    def advance(self, owner, direction=1):
        if self.active and self._externally_closed():
            self._release_only("window_closed")
        if self.active and self.owner != owner:
            self.finish("new_owner")
        if self.keys.held:
            raise RuntimeError("请先结束语音输入，再打开应用切换器")
        first = self.baseline is None
        self.log("switcher_advance", trigger=owner, direction=direction, first=first)
        if first:
            self.baseline = self.window_counter()
            self.opened = False
            self.navigated = False
        self.owner = owner
        try:
            self.holds.hold(self.OWNER, [self.modifier], timeout=1000,
                            on_timeout=lambda: self.finish("idle"))
            self.log("switcher_hold", held=self.holds.owned(self.OWNER),
                     modifiers=sorted(self.keys.owned_modifiers(self.OWNER)))
            if first:
                self.sleep(0.08)
            self.keys.chord([self.modifier, "tab"] if direction > 0
                            else [self.modifier, "shift", "tab"], hold_ms=25)
            if first:
                if sys.platform == "win32":
                    # Windows has no Dock window counter. Treat the sent
                    # Alt-Tab as open; retrying would select a second item,
                    # and cancellation must still send Escape.
                    self.opened = True
                else:
                    self.open_timer.start()
                    self.watch.start()
            else:
                self.navigated = True
        except Exception:
            self.close()
            raise

    def finish(self, reason="idle"):
        if not self.active:
            return
        self.open_timer.stop()
        self.watch.stop()
        externally_closed = self._externally_closed()
        self.log("switcher_finish", reason=reason, opened=self.opened, externally_closed=externally_closed)
        try:
            if sys.platform == "darwin" and self.opened and not externally_closed:
                self.keys._send("alt", True, ["cmd", "alt"])
                self.option_held = True
                self.sleep(0.06)
                self._release_only(reason)
                self.sleep(0.10)
            else:
                self._release_only(reason)
        finally:
            if self.holds.owned(self.OWNER):
                self._release_only(reason)
            self._release_option()

    def _release_only(self, reason):
        if self.active:
            self.log("switcher_release", reason=reason, owner=self.owner,
                     held=self.holds.owned(self.OWNER))
        self.open_timer.stop()
        self.watch.stop()
        self.holds.release(self.OWNER)

    def cancel(self, reason="cancel"):
        if self.active:
            try:
                if not self._externally_closed() and self.opened:
                    self.keys.chord([self.modifier, "esc"], hold_ms=25)
            finally:
                self._release_only(reason)

    def _release_option(self):
        if self.option_held:
            self.option_held = False
            self.keys._send("alt", False, [])

    def close(self):
        self._release_option()
        try:
            self.cancel("close")
        except Exception:
            self._release_only("close")

    def handle_key(self, trigger, down=True, controls=None):
        role = controls.get(trigger, trigger) if controls else trigger
        self.log("switcher_key", trigger=trigger, role=role, down=down)
        if not down:
            return True
        if trigger == self.owner:
            self.advance(trigger)
        elif role == "tv-left":
            self.advance(self.owner, -1)
        elif role == "tv-right":
            self.advance(self.owner, 1)
        elif role == "tv-ok":
            self.finish("confirm")
        elif role == "tv-back":
            self.cancel("back")
        else:
            self.finish("other_key")
        return True
