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
# Was 0.02, and the bars came back at 0.0089. Clamping on the back
# porch rather than a histogram bin made blanking exact, and with it
# the IRE scale, so the error fell to about 1e-11. The tolerance is
# tightened to match: this is now a real tripwire rather than slack.
close("worst colour error across all seven bars", worst, 0.0, 1e-4)

print("\nluma survives on its own, with colour switched off")
enc = NtscEncoder(fs, color=False)
grey = np.repeat(np.linspace(0, 1, 640)[None, :, None], 480, axis=0)
grey = np.repeat(grey, 3, axis=2)
sig = np.concatenate([enc.encode_frame(grey) for _ in range(3)])
out = NtscDecoder(fs, width=640, active_lines=240).decode_frame(sig, color=False)
ramp_err = float(np.abs(out[100:140, 40:600, 0].mean(axis=0)
                        - grey[100, 40:600, 0]).max())
close("a full-scale grey ramp comes back", ramp_err, 0.0, 0.005)

print("\nblanking is found whatever the picture is doing")
# Off air this was one second of lost picture every time a clip reached a
# dark shot: 17 frames in a row raising "could not find two fields", with
# the input level never moving. The decoder read blanking as the commonest
# level in the 10-60% band of sync-to-white, and on a dark scene the top of
# that range collapses toward blanking, which then sits at 89% of what is
# left - outside the window. It landed on dark picture content a thousandth
# above the sync tip and the slicer found no pulses at all.
fs = 4 * FSC
truth = ire_to_unit(IRE_BLANK)
pictures = {
    '75% colour bars': colour_bars(),
    'all white': np.ones((480, 640, 3)),
    'all black': np.zeros((480, 640, 3)),
    'flat mid grey': np.full((480, 640, 3), 0.5),
    'a dark scene': np.clip(np.random.RandomState(0).rand(480, 640, 3) * 0.18,
                            0, 1),
    'nine tenths white': np.concatenate([np.ones((432, 640, 3)),
                                         np.zeros((48, 640, 3))]),
}
decoder = NtscDecoder(fs, width=640, active_lines=240)
worst_level, worst_name = 0.0, ''
for name, picture in pictures.items():
    enc = NtscEncoder(fs)
    sig = np.concatenate([enc.encode_frame(picture) for _ in range(2)])
    sync, blank = decoder.levels(sig)
    starts, widths = decoder.find_pulses(sig, sync, blank)
    porch = decoder.back_porch_level(sig, starts, widths, blank)
    try:
        decoder.decode_frame(sig)
        decoded = "decodes"
    except Exception as exc:
        decoded = f"FAILED: {exc}"
        failures.append(f"decoding {name}")
    print(f"  {name:18s} histogram {blank:.4f}, back porch {porch:.4f}"
          f"  {decoded}")
    if abs(porch - truth) > worst_level:
        worst_level, worst_name = abs(porch - truth), name
close(f"back porch gives blanking to within this of {truth:.4f} "
      f"(worst: {worst_name})", worst_level, 0.0, 0.005)


def bar_error(out, src):
    worst = 0.0
    for k in range(7):
        col = (k * src.shape[1] // 7 + (k + 1) * src.shape[1] // 7) // 2
        got = out[100:140, col - 10:col + 10].mean(axis=(0, 1))
        worst = max(worst, float(np.abs(got - src[100, col]).max()))
    return worst


print("\ncolour does not depend on which sample decoding starts on")
# The decoder rebuilt chroma to subtract it from luma *after* turning its
# envelope to the burst, so the rebuilt chroma was out of phase by that
# rotation - which is set by where the buffer starts. At 4x subcarrier from
# sample 0, as above, the rotation is exactly zero and nothing showed; at
# 10 MS/s colour bars came back anywhere from 0.017 to 0.20 out.
fs = 10e6
enc = NtscEncoder(fs)
sig = np.concatenate([enc.encode_frame(colour_bars()) for _ in range(2)])
dec = NtscDecoder(fs, width=640, active_lines=240)
errors = [bar_error(dec.decode_frame(sig[start:]), colour_bars())
          for start in range(12)]
print(f"       starting on samples 0-11: {min(errors):.4f} to {max(errors):.4f}")
close("worst colour error from any of them, 10 MS/s", max(errors), 0.0, 0.03)

print("\nsync and blanking are found through noise, whatever the picture")
# Blanking was the histogram's commonest level, which is only true of a
# clean signal: with noise the porches spread across many bins and a large
# flat area spreads over more samples. On a white picture it read 2.5 times
# the sync-to-blanking step too high; the slicer then cut at blanking level,
# and the picture came back wrong with no error raised at all.
fs = 10e6
noisy_pictures = {
    '75% colour bars': colour_bars(),
    'all white': np.ones((480, 640, 3)),
    'saturated red/blue': np.concatenate([np.tile([1.0, 0.0, 0.0], (480, 320, 1)),
                                          np.tile([0.0, 0.0, 1.0], (480, 320, 1))],
                                         axis=1),
}
rng = np.random.RandomState(1)
decoder = NtscDecoder(fs, width=640, active_lines=240)
for name, picture in noisy_pictures.items():
    clean = np.concatenate([NtscEncoder(fs).encode_frame(picture) for _ in range(2)])
    sig = clean + rng.normal(0, 0.05, clean.size)
    sync, blank = decoder.levels(sig)
    starts, widths = decoder.find_pulses(sig, sync, blank)
    porch = decoder.back_porch_level(sig, starts, widths, blank)
    tip = decoder.sync_tip_level(sig, starts, widths, sync)
    try:
        err = float(np.abs(decoder.decode_frame(sig) - decoder.decode_frame(clean)).mean())
        detail = f"picture within {err:.3f} of the clean decode"
    except Exception as exc:
        err, detail = 1.0, f"FAILED: {exc}"
    print(f"  {name:20s} noise 0.05: tip {tip:+.4f}, blanking {porch:.4f}; {detail}")
    close(f"{name}: blanking through noise", porch, truth, 0.01)
    close(f"{name}: sync tip through noise", tip, 0.0, 0.01)
    close(f"{name}: the picture through noise", err, 0.0, 0.06)

print()
if failures:
    print(f"{len(failures)} FAILED: {', '.join(failures)}")
    sys.exit(1)
print("all checks passed")
