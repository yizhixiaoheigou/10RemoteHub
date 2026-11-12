import ctypes as c
import pytest
from remotehub.input_codes import windows_keyboard
from remotehub.photo_template import KEYMAP, television_profile
from remotehub.windows_hid import ConsumerReports, Caps, U32, SUCCESS


@pytest.mark.parametrize('scan,flags,key', [(2, 0, 'tv-number-1'), (11, 0, 'tv-number-0'),
    (0x48, 2, 'tv-up'), (0x4b, 2, 'tv-left'), (0x4d, 2, 'tv-right'), (0x50, 2, 'tv-down'),
    (0x5d, 2, 'tv-menu'), (0x3f, 0, 'tv-voice'), (0x49, 2, 'tv-channel-up'),
    (0x51, 2, 'tv-channel-down'), (0x37, 0, 'tv-number-*')])
def test_windows_scans_match_fixed_table(scan, flags, key):
    assert windows_keyboard(scan, flags) == KEYMAP['keys'][key]['trigger']
    assert windows_keyboard(scan, flags | 1) == KEYMAP['keys'][key]['trigger']


def test_windows_unknown_and_extended_scans_are_not_guessed():
    assert windows_keyboard(2, 2) is None
    assert windows_keyboard(0xcc, 0) is None


class FakeUser:
    def GetRawInputDeviceInfoW(self, handle, command, buffer, size):
        assert handle == 42 and command == 0x20000005
        c.cast(size, c.POINTER(U32))[0] = 64
        return 64 if buffer is not None else 0


class FakeHid:
    """Simulate HidP ABI using a report-ID byte followed by one consumer usage."""
    def HidP_GetCaps(self, preparsed, caps):
        c.cast(caps, c.POINTER(Caps)).contents.input_length = 3
        return SUCCESS

    def HidP_MaxUsageListLength(self, kind, page, preparsed):
        assert kind == 0 and page == 12
        return 8

    def HidP_GetUsages(self, kind, page, collection, usages, count, preparsed, packet, length):
        assert kind == 0 and page == 12 and collection == 0 and length == 3
        raw = c.string_at(packet, length)
        usage = int.from_bytes(raw[1:], 'little')
        c.cast(count, c.POINTER(U32))[0] = bool(usage)
        usages[0] = usage
        return SUCCESS


def test_windows_consumer_descriptor_api_matches_all_fixed_media_keys():
    decoder = ConsumerReports(FakeUser(), 42, hid=FakeHid())
    for button in television_profile().buttons:
        if not button.trigger.startswith('hid:12:'):
            continue
        packet = b'\0' + int(button.trigger.split(':')[2]).to_bytes(2, 'little')
        assert decoder.decode(packet) == [(button.trigger, True)]
        assert decoder.decode(packet) == []
        with pytest.raises(ValueError):
            decoder.decode(packet[:2])
        assert decoder.decode(bytes(3)) == [(button.trigger, False)]


def test_windows_consumer_report_ids_and_disconnect_keep_independent_state():
    decoder = ConsumerReports(FakeUser(), 42, hid=FakeHid())
    assert decoder.decode(b'\x01\xe9\0') == [('hid:12:233', True)]
    assert decoder.decode(b'\x02\xea\0') == [('hid:12:234', True)]
    assert decoder.decode(b'\x02\0\0') == [('hid:12:234', False)]
    assert decoder.release() == [('hid:12:233', False)]
    assert decoder.release() == []


def test_windows_raw_input_adapter_emits_canonical_keys(qapp, monkeypatch):
    from types import SimpleNamespace
    from remotehub import windows_input as win
    from remotehub.model import Profile
    packet = [b'']
    def raw_data(handle, command, buffer, size, header_size):
        size._obj.value = len(packet[0])
        if buffer is None:
            return 0
        c.memmove(buffer, packet[0], len(packet[0]))
        return len(packet[0])
    def device_info(handle, command, buffer, size):
        path = r'\\?\hid#vid_0416&pid_0602#receiver'
        size._obj.value = len(path) + 1
        if buffer is not None:
            buffer.value = path
        return len(path)
    user = SimpleNamespace(GetRawInputData=raw_data, GetRawInputDeviceInfoW=device_info,
                           RegisterRawInputDevices=lambda *args: True)
    monkeypatch.setattr(win.c, 'WinDLL', lambda *args, **kwargs: user, raising=False)
    monkeypatch.setattr(win, 'ConsumerReports', lambda *args: ConsumerReports(FakeUser(), 42, hid=FakeHid()))
    events, errors = [], []
    adapter = win.WindowsInput(Profile(), lambda *args: events.append(args), errors.append, None)
    msg = win.w.MSG()
    msg.message = 0xff
    def send(kind, body):
        header = win.HEADER(kind, c.sizeof(win.HEADER) + len(body), 42, 0)
        packet[0] = bytes(header) + body
        assert adapter.nativeEventFilter(None, c.addressof(msg)) == (False, 0)
    assert c.sizeof(win.KEYBOARD) == 16
    send(1, bytes(win.KEYBOARD(2, 0, 0, 0x31, 0, 0)))
    send(1, bytes(win.KEYBOARD(2, 0, 0, 0x31, 0, 0)))
    send(1, bytes(win.KEYBOARD(2, 1, 0, 0x31, 0, 0)))
    for report in (b'\0\xe9\0', bytes(3)):
        send(2, (3).to_bytes(4, 'little') + (1).to_bytes(4, 'little') + report)
    assert not errors
    assert events == [('hid:7:30', True), ('hid:7:30', False), ('hid:12:233', True), ('hid:12:233', False)]
    adapter._release(42)
    assert not adapter.cache and not adapter.held and not adapter.consumers
