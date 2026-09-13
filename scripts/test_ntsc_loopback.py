#!/usr/bin/env python3
"""NTSC encoder -> decoder, no radio at all.

Builds a frame, encodes it as composite baseband, decodes it back and
compares the picture. A timing or subcarrier-phase mistake shows up as a
number here rather than as "the TV looked wrong" later.

    python scripts/test_ntsc_loopback.py

The structural checks are against SMPTE 170M directly - line period, samples
per line, sync levels - and against the instructor's own capture geometry:
at 18 MS/s a frame is 600600 samples of 1144, which is exactly what the
``*-18M0FS.dat`` files in the media folder contain.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from apps.ntsc_encode import (FH, FRAME, FSC, IRE_BLANK, IRE_SYNC,  # noqa: E402
                              IRE_WHITE, LINE, NtscEncoder, ire_to_unit)
from apps.ntsc_decode import NtscDecoder  # noqa: E402

failures = []


def check(name, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {name}: {got!r}")
    if not ok:
        print(f"       wanted {want!r}")
        failures.append(name)


def close(name, got, want, tol):
    ok = abs(got - want) <= tol
    print(f"  {'ok  ' if ok else 'FAIL'} {name}: {got:.6g}")
    if not ok:
        print(f"       wanted {want:.6g} +/- {tol:g}")
        failures.append(name)


BARS = [(1, 1, 1), (1, 1, 0), (0, 1, 1), (0, 1, 0),
        (1, 0, 1), (1, 0, 0), (0, 0, 1)]
NAMES = ['white', 'yellow', 'cyan', 'green', 'magenta', 'red', 'blue']


def colour_bars(width=640, height=480, level=0.75):
    img = np.zeros((height, width, 3))
    for k, rgb in enumerate(BARS):
        img[:, k * width // 7:(k + 1) * width // 7] = np.array(rgb) * level
    return img


print("the frequencies everything else descends from (clause 11)")
close("subcarrier", FSC, 3579545.4545, 1e-3)
close("line rate", FH, 15734.2657, 1e-3)
close("line period, microseconds", LINE * 1e6, 63.5556, 1e-3)
close("frame period, milliseconds", FRAME * 1e3, 33.3667, 1e-3)

print("\nlevels (table 1), scaled so sync tip is 0 and white is 1")
close("sync", ire_to_unit(IRE_SYNC), 0.0, 1e-9)
close("blanking", ire_to_unit(IRE_BLANK), 0.285714, 1e-6)
close("white", ire_to_unit(IRE_WHITE), 1.0, 1e-9)

print("\na frame at 18 MS/s has the geometry of the instructor's captures")
enc = NtscEncoder(18e6, color=True)
frame = enc.encode_frame(colour_bars())
check("600600 samples, as in the *-18M0FS.dat files", frame.size, 600600)
check("1144 samples a line", frame.size // 525, 1144)
close("lowest sample is sync tip", float(frame.min()), 0.0, 1e-6)

# Sync structure: full lines 1144 apart, half-lines 572 apart in the two
# vertical intervals.
low = frame < 0.1
starts = np.flatnonzero(np.diff(low.astype(np.int8)) == 1) + 1
gaps = np.diff(starts)
check("most sync pulses are a whole line apart",
      int(np.bincount(gaps)[1144]) > 490, True)
check("and some are a half line apart, in the vertical intervals",
      int(np.bincount(gaps)[572]) > 25, True)

print("\nencode and decode a colour frame at 4x subcarrier")
fs = 4 * FSC
enc = NtscEncoder(fs, color=True)
src = colour_bars()
sig = np.concatenate([enc.encode_frame(src) for _ in range(3)])
dec = NtscDecoder(fs, width=src.shape[1], active_lines=240)
sync, blank = dec.levels(sig)
close("decoder reads the sync tip off the signal", sync, 0.0, 0.01)
close("decoder reads blanking off the signal", blank, 0.285714, 0.01)

out = dec.decode_frame(sig, color=True)
check("a full frame comes back", out.shape, (480, src.shape[1], 3))

worst = 0.0
for k, name in enumerate(NAMES):
    col = (k * src.shape[1] // 7 + (k + 1) * src.shape[1] // 7) // 2
    got = out[100:140, col - 10:col + 10].mean(axis=(0, 1))
    want = src[100, col]
    err = float(np.abs(got - want).max())
    worst = max(worst, err)
    print(f"  {name:8s} sent {np.round(want, 2)}  back {np.round(got, 2)}  "
          f"error {err:.4f}")
close("worst colour error across all seven bars", worst, 0.0, 0.02)

print("\nluma survives on its own, with colour switched off")
enc = NtscEncoder(fs, color=False)
grey = np.repeat(np.linspace(0, 1, 640)[None, :, None], 480, axis=0)
grey = np.repeat(grey, 3, axis=2)
sig = np.concatenate([enc.encode_frame(grey) for _ in range(3)])
out = NtscDecoder(fs, width=640, active_lines=240).decode_frame(sig, color=False)
ramp_err = float(np.abs(out[100:140, 40:600, 0].mean(axis=0)
                        - grey[100, 40:600, 0]).max())
close("a full-scale grey ramp comes back", ramp_err, 0.0, 0.03)

print()
if failures:
    print(f"{len(failures)} FAILED: {', '.join(failures)}")
    sys.exit(1)
print("all checks passed")
