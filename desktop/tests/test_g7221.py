"""Signal-quality and lifecycle checks against an external synthetic oracle.

The implementation is floating point: these checks do not claim bit equality
with the fixed-point oracle. The old exact-reference verifier remains unchanged.
"""
import base64
import json
from pathlib import Path

import numpy as np
import pytest

from remotehub.codec.g7221 import Decoder, InvalidFrame


@pytest.fixture
def golden():
    fixture = json.loads((Path(__file__).parent / "fixtures/g7221-synthetic.json").read_text())
    return ([bytes.fromhex(h) for h in fixture["payloads"]],
            base64.b64decode(fixture["expected_pcm_s16le_base64"]))


def test_synthetic_golden_audio(golden):
    frames, pcm = golden
    decoder = Decoder()
    decoded = b"".join(decoder.decode(f) for f in frames)
    assert len(decoded) == len(pcm) == len(frames) * 640
    actual = np.frombuffer(decoded, dtype="<i2").astype(float)
    expected = np.frombuffer(pcm, dtype="<i2").astype(float)
    error = actual - expected
    # 40 dB means error energy < 1/10,000 of the signal energy. Fixed-point
    # rounding/dither is intentionally not reproduced by the floating core.
    snr = 10 * np.log10(np.sum(expected ** 2) / np.sum(error ** 2))
    assert snr > 40, snr
    assert np.max(np.abs(error)) < 128
    assert np.sqrt(np.mean(error ** 2)) < 16
    assert decoder.frames == len(frames) and decoder.concealed == 0


def test_restart_and_two_independent_recordings(golden):
    frames, _ = golden
    first, second = Decoder(), Decoder()
    expected = [first.decode(frame) for frame in frames]
    for frame, pcm in zip(frames, expected):
        assert second.decode(frame) == pcm
    first.reset()
    assert first.frames == first.concealed == 0
    assert [first.decode(frame) for frame in frames] == expected


@pytest.mark.parametrize("size", [0, 1, 39, 41, 64, 4096])
def test_partial_frames_rejected_without_changing_state(golden, size):
    decoder = Decoder()
    with pytest.raises(ValueError, match="40"):
        decoder.decode(bytes(size))
    assert decoder.frames == 0
    assert decoder.decode(golden[0][0]) == Decoder().decode(golden[0][0])


def test_corrupt_input_is_bounded_and_finite():
    rng = np.random.default_rng(4160602)
    decoder = Decoder()
    for _ in range(200):
        try:
            pcm = decoder.decode(rng.bytes(40))
        except InvalidFrame:
            continue
        assert len(pcm) == 640
        assert np.isfinite(np.frombuffer(pcm, dtype="<i2")).all()
