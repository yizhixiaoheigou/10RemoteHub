"""Bounded connection diagnostics; never record keys, PCM or recognition text."""
import json
import logging
import math
from logging.handlers import RotatingFileHandler


# Default logs accept only known lifecycle events and scalar diagnostic metrics.
# Unknown call sites and free-form text are dropped, never persisted verbatim.
EVENTS = frozenset("""app_started app_stopping error connection_retry capture_start
capture_stop capture_ready capture_stopped capture_failed capture_transient_io
capture_waiting_for_receiver capture_transient_retry usb_inventory default_input_route
update_check update_result update_download audio_channel_disconnected voice_edge_failed
voice_open voice_seq_gap voice_audio voice_audio_progress voice_inactivity
voice_max_duration audio_start autostart_upgraded autostart_upgrade_failed
window_error window_result""".split())
NUMERIC_FIELDS = frozenset("""attempt generation milliseconds count bytes frames seconds
rate channels buffer_size buffer_bytes winerror""".split())
BOOLEAN_FIELDS = frozenset(('manual', 'success'))
ENUM_FIELDS = {
    'kind': {'application'},
    'operation': {'acquire', 'release', 'show', 'hide'},
    'state': {'present', 'absent', 'unsupported', 'unadapted', 'checking', 'error'},
    'arch': {'arm64', 'x86_64'},
    'reason': {'window_closed', 'confirmed', 'state_timeout'},
}


def public_fields(event, fields):
    if event not in EVENTS:
        return None
    clean = {'event': event}
    for name, value in fields.items():
        if name in NUMERIC_FIELDS and type(value) in (int, float) and math.isfinite(value):
            clean[name] = value
        elif name in BOOLEAN_FIELDS and type(value) is bool:
            clean[name] = value
        elif name in ENUM_FIELDS and isinstance(value, str) and value in ENUM_FIELDS[name]:
            clean[name] = value
    return clean


class Diagnostics:
    def __init__(self, directory):
        self.handler = None
        try:
            directory.mkdir(parents=True, exist_ok=True)
            self.handler = RotatingFileHandler(
                directory / "connection.log", maxBytes=512 * 1024,
                backupCount=2, encoding="utf-8", delay=True)
            self.handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        except OSError:
            pass  # A logging failure must never prevent device recovery.

    def write(self, event, **fields):
        if self.handler is None:
            return
        data = public_fields(event, fields)
        if data is None:
            return
        record = logging.LogRecord("remotehub.connection", logging.INFO, "", 0,
                                   json.dumps(data, ensure_ascii=False), (), None)
        try:
            self.handler.handle(record)
        except OSError:
            pass

    def close(self):
        if self.handler is not None:
            self.handler.close()
            self.handler = None
