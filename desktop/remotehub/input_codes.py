"""Normalize Windows input identities to the HID identities in the fixed key table.

RAWKEYBOARD scan codes cover standard keyboard keys only; unknown codes are never
guessed. Linux 归一化在 `linux/remotehub_linux/keys.py`，不在发布范围内。
"""

WINDOWS_KEYS = {**{(i + 2, 0): i + 30 for i in range(10)},
                (0x1c, 0): 40, (1, 0): 41, (0x3f, 0): 62, (0x37, 0): 85,
                (0x48, 2): 82, (0x4b, 2): 80, (0x4d, 2): 79,
                (0x50, 2): 81, (0x5d, 2): 101,
                (0x49, 2): 75, (0x51, 2): 78}


def windows_keyboard(scan, flags):
    usage = WINDOWS_KEYS.get((scan, flags & 6))
    return f"hid:7:{usage}" if usage is not None else None
