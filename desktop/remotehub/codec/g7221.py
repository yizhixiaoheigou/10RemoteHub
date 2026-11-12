# SPDX-License-Identifier: LGPL-2.1-or-later
# G.722.1 decoder adapted from FFmpeg n8.0 libavcodec/siren.c.
# Copyright (c) 2012 Youness Alaoui; 2018 Paul B Mahol; 2019 Lynne.
# Python port and receiver compatibility changes: 10RemoteHub contributors.
# See COPYING.LGPLv2.1 and NOTICE.md. No vendor library or reference core used.
"""Stateful 16 kbit/s, 16 kHz receiver decoder using floating-point synthesis.

The output is compatible audio, not a bit-exact emulation of the vendor's
fixed-point rounding/dither. Only one complete 40-byte payload is accepted.
"""

import math
import struct

import numpy as np

from .tables import (
    INDEX_TABLE, VECTOR_DIMENSION, NUMBER_OF_VECTORS, EXPECTED_BITS_TABLE,
    DIFFERENTIAL_DECODER_TREE, MLT_QUANT,
    DECODER_TREE0, DECODER_TREE1, DECODER_TREE2, DECODER_TREE3,
    DECODER_TREE4, DECODER_TREE5, DECODER_TREE6,
)

TREES = (DECODER_TREE0, DECODER_TREE1, DECODER_TREE2, DECODER_TREE3,
         DECODER_TREE4, DECODER_TREE5, DECODER_TREE6)
_K = np.arange(320, dtype=np.float64) + 0.5
# Analytical DCT-IV and sine window; no transform table from a vendor binary.
# The fixed-point profile's energy scale is sqrt(512).
_TRANSFORM = np.cos(np.pi / 320 * np.outer(_K, _K)) * math.sqrt(512 * 2 / 320)
_WINDOW = np.sin(_K * np.pi / 640)
_TRANSFORM.flags.writeable = False
_WINDOW.flags.writeable = False


class InvalidFrame(ValueError):
    pass


class BitBudgetExhausted(InvalidFrame):
    pass


class Bits:
    def __init__(self, data):
        self.value = int.from_bytes(data, "big")
        self.left = len(data) * 8

    def read(self, width=1):
        if self.left < width:
            raise BitBudgetExhausted("G.722.1 bitstream exhausted")
        self.left -= width
        return (self.value >> self.left) & ((1 << width) - 1)


def categorize(powers, available):
    # Port of FFmpeg's bounded category search; ties depend on scan direction.
    offset = -32
    delta = 32
    while delta:
        estimate = sum(EXPECTED_BITS_TABLE[min(7, max(0, (delta + offset - p) >> 1))]
                       for p in powers)
        if estimate >= available - 32:
            offset += delta
        delta //= 2
    high = [min(7, max(0, (offset - p) >> 1)) for p in powers]
    low = high.copy()
    minimum = maximum = sum(EXPECTED_BITS_TABLE[c] for c in high)
    before, after = [], []
    for _ in range(15):
        if minimum + maximum > available * 2:
            choices = [r for r in reversed(range(14)) if low[r] < 7]
            if not choices:
                raise InvalidFrame("invalid low-rate categories")
            r = max(choices, key=lambda r: offset - powers[r] - 2 * low[r])
            after.append(r)
            minimum += EXPECTED_BITS_TABLE[low[r] + 1] - EXPECTED_BITS_TABLE[low[r]]
            low[r] += 1
        else:
            choices = [r for r in range(14) if high[r] > 0]
            if not choices:
                raise InvalidFrame("invalid high-rate categories")
            r = min(choices, key=lambda r: offset - powers[r] - 2 * high[r])
            before.append(r)
            maximum += EXPECTED_BITS_TABLE[high[r] - 1] - EXPECTED_BITS_TABLE[high[r]]
            high[r] -= 1
    return high, list(reversed(before)) + after


class Decoder:
    def __init__(self):
        self.reset()

    def reset(self):
        """Start a new recording with fresh overlap, concealment and noise state."""
        self.seeds = [1, 1, 1, 1]
        self.previous = np.zeros(160)
        self.backup = np.zeros(320)
        self.frames = 0
        self.concealed = 0
        self.last_powers = []
        self.last_categories = []

    def random_word(self):
        value = (self.seeds[0] + self.seeds[3]) & 0xFFFF
        if value & 0x8000:
            value = (value + 1) & 0xFFFF
        self.seeds = [value, *self.seeds[:3]]
        return value

    def coefficients(self, data):
        bits = Bits(data)
        powers = [bits.read(5) - 7]
        for region in range(1, 14):
            tree = DIFFERENTIAL_DECODER_TREE[region - 1]
            index = 0
            while True:
                if bits.left < 4 + 14 - region:
                    raise InvalidFrame("truncated envelope")
                if not 0 <= index < len(tree):
                    raise InvalidFrame("invalid envelope node")
                index = tree[index][bits.read()]
                if index <= 0:
                    break
            powers.append(powers[-1] - index - 12)
        control = bits.read(4)
        categories, balance = categorize(powers, bits.left)
        for region in balance[:control]:
            categories[region] += 1
        self.last_powers, self.last_categories = powers, categories.copy()
        coefs = np.zeros(320)
        exhausted = False
        for region, category in enumerate(categories):
            base = region * 20
            stddev = 2.0 ** (max(-24, min(39, powers[region])) / 2)
            if category < 7 and not exhausted:
                tree = TREES[category]
                dim = VECTOR_DIMENSION[category]
                shift = INDEX_TABLE[category]
                try:
                    for vector in range(NUMBER_OF_VECTORS[category]):
                        index = 0
                        while not index & 1:
                            node = index + bits.read()
                            if node >= len(tree):
                                raise InvalidFrame("invalid vector node")
                            index = tree[node]
                        index >>= 1
                        bins = [(index >> (shift * j)) & ((1 << shift) - 1) for j in range(dim)]
                        if sum(b != 0 for b in bins) > bits.left:
                            raise BitBudgetExhausted("truncated signs")
                        for j, bin_index in enumerate(bins):
                            if bin_index > (13, 9, 6, 4, 3, 2, 1)[category]:
                                raise InvalidFrame("invalid quantizer bin")
                            value = MLT_QUANT[category][bin_index] * stddev
                            if value and not bits.read():
                                value = -value
                            coefs[base + vector * dim + j] = value
                except BitBudgetExhausted:
                    exhausted = True
            if exhausted:
                category = 7
            if category >= 5:
                # Fixed-point profile uses constant fill amplitudes and two
                # consecutive groups of ten. Consume a bit only for a filled bin.
                noise = stddev * (0.17678, 0.25, 0.70711)[category - 5]
                for group in range(2):
                    word = self.random_word()
                    for j in range(10):
                        position = base + group * 10 + j
                        if category == 7 or coefs[position] == 0:
                            coefs[position] = noise if word & 1 else -noise
                            word >>= 1
        error = exhausted and control != 15
        if not exhausted and bits.left:
            remaining = bits.left
            error |= bits.read(remaining) != (1 << remaining) - 1
        error |= any(p < -15 or p > 24 for p in powers)
        if error:
            coefs = self.backup.copy()
            self.backup.fill(0)
            self.concealed += 1
        else:
            self.backup = coefs.copy()
        return coefs

    def decode(self, payload):
        if len(payload) != 40:
            raise ValueError("expected exactly 40 payload bytes")
        words = list(struct.unpack("<20H", payload))
        for a, b, c in ((4, 16, 9), (8, 3, 11), (2, 6, 18), (7, 13, 17)):
            words[a], words[b], words[c] = words[c], words[a], words[b]
        data = struct.pack(">20H", *(word ^ 0x0416 for word in words))
        coefs = self.coefficients(data)
        current = np.einsum("ij,j->i", _TRANSFORM, coefs, optimize=False)
        output = np.empty(320)
        output[:160] = _WINDOW[:160] * current[159::-1] + _WINDOW[:159:-1] * self.previous
        output[160:] = _WINDOW[160:] * current[:160] - _WINDOW[159::-1] * self.previous[::-1]
        self.previous = current[160:].copy()
        self.frames += 1
        return (np.clip(np.rint(output), -32768, 32767).astype("<i2") & -4).tobytes()
