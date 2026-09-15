#!/usr/bin/env python3
"""PAL encoder -> decoder, no radio at all.

    python scripts/test_pal_loopback.py

The PAL half of ``test_ntsc_loopback.py``: builds frames, encodes them as
625-line PAL composite, decodes them back and compares. The structural
checks are against ITU-R BT.1700 Part B (docs/1700-e.pdf) - Table 1 for the
frequencies, Table 2 for line timing and levels, Table 3 and Figs. 3-5 for
the field-sync blocks.

Beyond what the NTSC test covers, two things are PAL's own:

- **the V switch** - the V component and the burst's V half change sign
  every line, and a decoder that reads the switch wrongly swaps red for
  cyan and magenta for green;
- **where each field's picture starts**, which a single bright band decoded
  from buffers that begin at different points in the frame pins to the row.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from apps.ntsc_decode import CompositeDecoder, VERTICAL_RUN  # noqa: E402
from apps.ntsc_encode import (PAL, PAL_FH, PAL_FSC, BROAD,  # noqa: E402
                              CompositeEncoder, EQUALIZING)

failures = []
W, H = PAL.width, PAL.height


def check(name, ok, detail=''):
    print(f"  {'ok  ' if ok else 'FAIL'} {name}{'  ' + detail if detail else ''}")
    if not ok:
        failures.append(name)


def close(name, got, want, tol):
    ok = abs(got - want) <= tol
    print(f"  {'ok  ' if ok else 'FAIL'} {name}: {got:.6g}")
    if not ok:
        print(f"       wanted {want:.6g} +/- {tol:g}")
        failures.append(name)


def colour_bars(width=W, height=H, level=0.75):
    bars = [(1, 1, 1), (1, 1, 0), (0, 1, 1), (0, 1, 0), (1, 0, 1), (1, 0, 0), (0, 0, 1)]
    img = np.zeros((height, width, 3))
    for k, rgb in enumerate(bars):
        img[:, k * width // 7:(k + 1) * width // 7] = np.array(rgb) * level
    return img


def bar_error(out, src):
    worst = 0.0
    for k in range(7):
        col = (k * src.shape[1] // 7 + (k + 1) * src.shape[1] // 7) // 2
        got = out[120:170, col - 10:col + 10].mean(axis=(0, 1))
        worst = max(worst, float(np.abs(got - src[120, col]).max()))
    return worst


print("the frequencies (BT.1700 Table 1)")
close("line rate, Hz", PAL_FH, 15625.0, 1e-9)
close("subcarrier, Hz", PAL_FSC, 4433618.75, 1e-6)
close("subcarrier is (1135/4 + 1/625) line rates", PAL_FSC / PAL_FH, 1135 / 4 + 1 / 625, 1e-12)
close("line period, microseconds", PAL.line * 1e6, 64.0, 1e-9)
close("frame period, milliseconds", PAL.frame * 1e3, 40.0, 1e-9)
close("active line, microseconds (Table 2: 64 - 12)", PAL.active_len * 1e6, 52.0, 1e-9)

print("\nlevels (Table 2), scaled so sync tip is 0 and white is 1")
close("blanking", PAL.blank, 0.3, 1e-12)
close("black - PAL has no set-up", PAL.black, 0.3, 1e-12)
close("burst, peak to peak", 2 * PAL.burst_amplitude / PAL.span, 0.3, 1e-12)

print("\nthe structure of a frame, found the way the decoder finds it")
fs = 4 * PAL_FSC
enc = CompositeEncoder(fs, standard=PAL)
frames = [enc.encode_frame(colour_bars()) for _ in range(3)]
close("samples in a frame at 4x subcarrier", frames[1].size, PAL.frame * fs, 1.0)
signal = np.concatenate(frames)
dec = CompositeDecoder(fs, standard=PAL)
sync, blank = dec.levels(signal)
starts, widths = dec.find_pulses(signal, sync, blank)
# Count the middle frame's: a buffer that opens on a broad pulse has no
# leading edge for the slicer to find, which is a fact about the buffer.
middle = (starts >= frames[0].size) & (starts < frames[0].size + frames[1].size)
widths = widths[middle]
w = widths * 1e6
check("five equalizing pulses either side of each field-sync block - 20",
      int(((w > 1.8) & (w < 3.0)).sum()) == 20, str(int(((w > 1.8) & (w < 3.0)).sum())))
check("five broad pulses in each block - 10", int((widths > VERTICAL_RUN).sum()) == 10,
      str(int((widths > VERTICAL_RUN).sum())))
check("and a line sync on every other line - 610",
      int(((w > 4.0) & (w < 5.5)).sum()) == 610, str(int(((w > 4.0) & (w < 5.5)).sum())))
table = PAL.half_line_types()
check("the half-line table agrees: 20 equalizing, 10 broad",
      int((table == EQUALIZING).sum()) == 20 and int((table == BROAD).sum()) == 10)
check("the burst is left off the field-sync lines only - 609 lines carry it",
      int(PAL.burst_lines().sum()) == 609, str(int(PAL.burst_lines().sum())))
check("the decoder counts 17 lines to the picture in both fields",
      dec.field_offsets == (17, 17), str(dec.field_offsets))

print("\ncolour bars at 4x subcarrier")
enc = CompositeEncoder(fs, standard=PAL)
src = colour_bars()
sig = np.concatenate([enc.encode_frame(src) for _ in range(3)])
dec = CompositeDecoder(fs, standard=PAL)
sync, blank = dec.levels(sig)
# The first estimates are only that - PAL's burst and colour bars put the
# 20th percentile a little under blanking - and what the picture is scaled
# by is what the porches and the pulses say.
check("the first estimates are the right way round and inside the step",
      0.0 <= sync < 0.05 and 0.15 < blank <= 0.31, f"sync {sync:.3f}, blanking {blank:.3f}")
starts, widths = dec.find_pulses(sig, sync, blank)
close("decoder reads the sync tip off the pulses",
      dec.sync_tip_level(sig, starts, widths, sync), 0.0, 0.002)
close("decoder reads blanking off the porches",
      dec.back_porch_level(sig, starts, widths, blank), 0.3, 0.002)
out = dec.decode_frame(sig)
check("a full 576-line frame comes back", out.shape == (H, W, 3), str(out.shape))
names = ['white', 'yellow', 'cyan', 'green', 'magenta', 'red', 'blue']
for k, name in enumerate(names):
    col = (k * W // 7 + (k + 1) * W // 7) // 2
    got = out[120:170, col - 10:col + 10].mean(axis=(0, 1))
    print(f"  {name:8s} sent {np.round(src[120, col], 2)}  back {np.round(got, 3)}")
close("worst colour error across all seven bars", bar_error(out, src), 0.0, 0.01)

print("\nthe V switch is read the right way round")
# Magenta and green differ only in the sign of V against U; so do red and
# cyan. Flip every line's V and they swap.
reference = CompositeDecoder(fs, standard=PAL)
wrong = CompositeDecoder(fs, standard=PAL)
real_axes = wrong._pal_axes
wrong._pal_axes = lambda z, zb, found, gain, window=4: (
    lambda u, v: (u, -v))(*real_axes(z, zb, found, gain, window))
flipped = wrong.decode_frame(sig)
check("reading the switch backwards turns green magenta, which is how a "
      "wrong switch would look", bar_error(flipped, src) > 0.3,
      f"worst {bar_error(flipped, src):.2f} backwards against "
      f"{bar_error(reference.decode_frame(sig), src):.4f} as decoded")

print("\ncolour from any starting sample, at 12.5 MS/s")
fs = 12.5e6
enc = CompositeEncoder(fs, standard=PAL)
sig = np.concatenate([enc.encode_frame(src) for _ in range(2)])
dec = CompositeDecoder(fs, standard=PAL)
errors = [bar_error(dec.decode_frame(sig[start:]), src) for start in range(12)]
print(f"       starting on samples 0-11: {min(errors):.4f} to {max(errors):.4f}")
close("worst colour error from any of them", max(errors), 0.0, 0.03)

print("\nluma on its own")
enc = CompositeEncoder(fs, color=False, standard=PAL)
grey = np.repeat(np.repeat(np.linspace(0, 1, W)[None, :, None], H, 0), 3, 2)
sig = np.concatenate([enc.encode_frame(grey) for _ in range(2)])
out = CompositeDecoder(fs, standard=PAL).decode_frame(sig, color=False)
ramp = float(np.abs(out[100:140, 40:W - 40, 0].mean(axis=0) - grey[100, 40:W - 40, 0]).max())
close("a full-scale grey ramp comes back", ramp, 0.0, 0.01)

print("\nevery row lands where it was sent, whichever field the buffer opens on")
# A single bright band: a field in the wrong order puts it a row out, and a
# wrong count from field sync to picture moves it by two.
band = np.zeros((H, W, 3))
band[300:306] = 0.8
enc = CompositeEncoder(fs, color=False, standard=PAL)
sig = np.concatenate([enc.encode_frame(band) for _ in range(3)])
worst_shift = 0
for start in (0, int(PAL.frame * fs * 0.25), int(PAL.frame * fs * 0.5),
              int(PAL.frame * fs * 0.8)):
    out = CompositeDecoder(fs, standard=PAL).decode_frame(sig[start:], color=False)
    profile = out[:, 100:600, 0].mean(axis=1)
    lit = np.flatnonzero(profile > 0.4)
    got = (int(lit.min()), int(lit.max())) if lit.size else (-1, -1)
    shift = max(abs(got[0] - 300), abs(got[1] - 305))
    worst_shift = max(worst_shift, shift)
    print(f"       buffer starting {start / (PAL.frame * fs):.2f} of a frame in: "
          f"band on rows {got[0]}-{got[1]}")
check("the band comes back on exactly rows 300-305 every time", worst_shift == 0,
      f"worst {worst_shift} rows out")

print("\nthrough noise")
enc = CompositeEncoder(fs, standard=PAL)
clean = np.concatenate([enc.encode_frame(src) for _ in range(2)])
noisy = clean + np.random.RandomState(1).normal(0, 0.05, clean.size)
dec = CompositeDecoder(fs, standard=PAL)
sync, blank = dec.levels(noisy)
starts, widths = dec.find_pulses(noisy, sync, blank)
close("blanking through noise", dec.back_porch_level(noisy, starts, widths, blank), 0.3, 0.01)
close("sync tip through noise", dec.sync_tip_level(noisy, starts, widths, sync), 0.0, 0.01)
err = float(np.abs(dec.decode_frame(noisy) - dec.decode_frame(clean)).mean())
close("the picture through noise, against the clean decode", err, 0.0, 0.06)

print()
if failures:
    print(f"{len(failures)} FAILED: {', '.join(failures)}")
    sys.exit(1)
print("all checks passed")
