"""Read Raw Input consumer usages with Windows' own descriptor parser.

RIDI_PREPARSEDDATA + HidP_GetUsages; the report ID byte is retained. Never
interpret report bytes as usage numbers without the device's descriptor.
"""
import ctypes as c

U16, U32 = c.c_uint16, c.c_uint32
SUCCESS = 0x00110000


class Caps(c.Structure):
    _fields_ = [(name, U16) for name in ('usage', 'page', 'input_length', 'output_length', 'feature_length')]
    _fields_ += [('reserved', U16 * 17)]
    _fields_ += [(name, U16) for name in ('links', 'input_buttons', 'input_values', 'input_indices',
                                        'output_buttons', 'output_values', 'output_indices',
                                        'feature_buttons', 'feature_values', 'feature_indices')]


class ConsumerReports:
    def __init__(self, user, handle, hid=None):
        self.hid = hid if hid is not None else c.WinDLL('hid', use_last_error=True)
        if hid is None:
            self.hid.HidP_GetCaps.argtypes = [c.c_void_p, c.POINTER(Caps)]
            self.hid.HidP_GetCaps.restype = U32
            self.hid.HidP_MaxUsageListLength.argtypes = [c.c_int, U16, c.c_void_p]
            self.hid.HidP_MaxUsageListLength.restype = U32
            self.hid.HidP_GetUsages.argtypes = [c.c_int, U16, U16, c.POINTER(U16), c.POINTER(U32),
                                              c.c_void_p, c.c_void_p, U32]
            self.hid.HidP_GetUsages.restype = U32
        size = U32()
        rc = user.GetRawInputDeviceInfoW(handle, 0x20000005, None, c.byref(size))
        if rc == 0xffffffff or not 0 < size.value <= 65536:
            raise ValueError('无法读取按键描述符')
        self.preparsed = c.create_string_buffer(size.value)
        rc = user.GetRawInputDeviceInfoW(handle, 0x20000005, self.preparsed, c.byref(size))
        if rc == 0xffffffff:
            raise ValueError('无法读取按键描述符')
        self.caps = Caps()
        if self.hid.HidP_GetCaps(self.preparsed, c.byref(self.caps)) != SUCCESS:
            raise ValueError('按键描述符无效')
        self.maximum = self.hid.HidP_MaxUsageListLength(0, 12, self.preparsed)
        if not 0 < self.maximum <= 128 or not 0 < self.caps.input_length <= 4096:
            raise ValueError('不支持此按键报告布局')
        self.previous = {}  # independent state per report ID

    def decode(self, data):
        if len(data) != self.caps.input_length:
            raise ValueError('按键报文长度不完整')
        usages = (U16 * self.maximum)()
        length = U32(self.maximum)
        packet = c.create_string_buffer(data)
        rc = self.hid.HidP_GetUsages(0, 12, 0, usages, c.byref(length),
                                    self.preparsed, packet, len(data))
        if rc == 0xc011000a:  # HIDP_STATUS_INCOMPATIBLE_REPORT_ID
            return []
        if rc != SUCCESS or length.value > self.maximum:
            raise ValueError('无法解析按键报文')
        current = {f'hid:12:{usage}' for usage in usages[:length.value] if usage}
        previous = self.previous.get(data[0], set())
        self.previous[data[0]] = current
        return [(key, False) for key in sorted(previous - current)] + [(key, True) for key in sorted(current - previous)]

    def release(self):
        events = [(key, False) for state in self.previous.values() for key in sorted(state)]
        self.previous.clear()
        return events
