# Built-in receiver audio decoder

This component is licensed under **LGPL-2.1-or-later**; see `COPYING.LGPLv2.1`.
It is an adapted open-source implementation, not an entirely original codec.

`tables.py` contains numerically unchanged decoding tables extracted from
[FFmpeg n8.0 libavcodec/siren.c](https://github.com/FFmpeg/FFmpeg/blob/n8.0/libavcodec/siren.c).
The source file's SHA256 is recorded in `tables.py`.
`g7221.py` ports FFmpeg's envelope, category allocation and vector decoding
algorithms to Python and adds compatibility with this receiver's G.722.1 profile.

Original copyright holders:

- Copyright (c) 2012 Youness Alaoui
- Copyright (c) 2018 Paul B Mahol
- Copyright (c) 2019 Lynne

Python port and receiver compatibility modifications: 10RemoteHub contributors.
The code is provided without warranty, under the terms of the included license.

Changes from FFmpeg:

- Bounded 320-bit reader and fixed 16 kbit/s / 16 kHz profile.
- Receiver word permutation/XOR reversal.
- Fixed-profile noise magnitudes, deterministic 16-bit generator and consecutive
  ten-coefficient noise groups; random bits advance only for filled coefficients.
- Rate-control-15 bit-budget exhaustion uses noise fill; other exhausted frames
  or invalid padding/range use the previous coefficients once, then silence.
- Analytical orthonormal DCT-IV and overlap/add with the profile's sqrt(512)
  amplitude normalization, implemented with NumPy. No copied vendor transform
  tables, machine code or reference-core implementation.
- Saturating little-endian PCM output with the two lowest bits cleared.
- Explicit reset of synthesis, noise and concealment state for every recording.

The floating-point synthesis intentionally does **not** reproduce every rounding
and dither step of the fixed-point reference. Golden comparisons report numerical
error and signal-to-error ratio, not bit-exact compatibility. The earlier exact
reference experiment remains separately reproducible in `research/codec/`.

No `libicocodec.so`, `libg7221`, Unicorn or ARM emulator is used by this component.
The separately downloaded Polycom-derived reference library is only a local test
oracle. It is not copied into this directory or the application package.
This source license does not make a determination about codec patents.

## Modification and rebuilding

The complete corresponding source of this modified component consists of
`__init__.py`, `g7221.py`, `tables.py`, this notice and the license text. These
files are included in frozen builds under `codec-source/remotehub/codec/`.
They require Python 3.10+ and NumPy (the application already depends on NumPy).

In a checkout of 10RemoteHub, replace `desktop/remotehub/codec/` with your modified
copy. From `desktop/`, create a project virtual environment, install `.[dev]`,
then follow `desktop/RELEASE.md` with an exact-version license supplement and
a local signing identity on macOS. This rebuilds the executable on the target OS;
it does not install a driver, alter permissions or publish anything. Tests are in
`desktop/tests/test_g7221.py`, and recorded-audio verification is in
`research/codec/verify_builtin.py`. The standard App build excludes the historical
vendor emulator and includes these modified source files and this license.

Before any public release, the project still needs its complete distribution
license/source offer review (including the rest of the App and supplied artwork).
