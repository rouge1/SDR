#!/usr/bin/env python3
"""The NTSC transmit chain, with no radio: a picture there and back.

``test_ntsc_loopback.py`` checks the composite encoder against the decoder.
This checks everything between them and the antenna - the modulator - by
putting a picture through it, detecting the envelope the way a television
does, and decoding what comes out.

    python scripts/test_ntsc_transmit.py
    python scripts/test_ntsc_transmit.py --video clip.mp4

Three things this is really here to pin down, all of which were wrong:

- **the ``.dat`` captures are 18 MS/s** and were played at 10, which makes
  every timing in them wrong by 1.8 and the line rate 8741 Hz where NTSC
  needs 15734.266;
- **the modulation polarity** defaulted to positive, which is not a US
  standard and drove the carrier to 1.79 against a radio that clips at 1.0;
- **saturated colour drives composite below sync level**, where a receiver
  cannot tell picture from sync at all, unless the encoder legalises it.
"""
import argparse
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gnuradio import blocks, gr  # noqa: E402

from apps.ntsc_encode import (FH, IRE_PEAK, IRE_TROUGH, LINE,  # noqa: E402
                              NtscEncoder, ire_to_unit)
from apps.ntsc_decode import NtscDecoder  # noqa: E402
from apps.ntsc_source import (TestPattern, VideoFile, colour_bars,  # noqa: E402
                              dat_resample_ratio, have_ffmpeg, ntsc_source)
from apps.ntscAnalogVideoRecorded import (  # noqa: E402
    AURAL_CARRIER, AURAL_SPACING, CARRIER_AT_SYNC, CARRIER_AT_WHITE,
    LO_OFFSET, NtscModulator, VISUAL_CARRIER)

RATE = 10e6
#: How far the vestigial sideband extends either side of the visual carrier,
#: and therefore how wide a receiver's Nyquist slope is.
VESTIGIAL_SLOPE = 0.75e6
failures = []


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


class Modulate(gr.top_block):
    """Composite samples in, modulated RF baseband out. No radio."""

    def __init__(self, composite, polarity='negative'):
        gr.top_block.__init__(self, "modulate", catch_exceptions=True)
        self.src = blocks.vector_source_f(composite.astype(np.float32).tolist())
        self.mod = NtscModulator(RATE, polarity)
        self.sink = blocks.vector_sink_c()
        self.connect(self.src, self.mod, self.sink)

    def result(self):
        return np.array(self.sink.data(), dtype=np.complex64)


def envelope(rf):
    """Detect it the way a television does - including the Nyquist slope.

    Envelope detection is what System M receivers use: the visual carrier
    is left in the signal at full strength precisely so that they can. But
    a receiver does not rectify the signal as it arrives. Its IF has a
    **Nyquist slope** across the visual carrier - half response at the
    carrier, rising to full 0.75 MHz above and falling to nothing 0.75 MHz
    below - and without it the result is wrong in a specific, recognisable
    way. Below 0.75 MHz both sidebands survive and add; above it only one
    does. So luma comes back twice as strong as chroma: whites too bright,
    colours washed out toward grey. Leaving this out reads as a broken
    modulator and is not one.
    """
    n = rf.size
    base = rf * np.exp(-2j * np.pi * VISUAL_CARRIER * np.arange(n) / RATE)
    freqs = np.fft.fftfreq(n, 1.0 / RATE)
    slope = np.clip(0.5 + freqs / (2 * VESTIGIAL_SLOPE), 0.0, 1.0)
    # x2 puts the halved carrier back where it started.
    return 2.0 * np.abs(np.fft.ifft(np.fft.fft(base) * slope))


def to_composite(env, polarity='negative'):
    """Undo the carrier mapping, back to sync 0 / white 1."""
    span = CARRIER_AT_SYNC - CARRIER_AT_WHITE
    if polarity == 'negative':
        return (CARRIER_AT_SYNC - env) / span
    return (env - CARRIER_AT_WHITE) / span


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--video', help='a video file to send instead of bars')
    args = ap.parse_args()

    print("where the carriers sit, relative to the channel centre")
    close("visual carrier, MHz", VISUAL_CARRIER / 1e6, -1.75, 1e-9)
    close("aural carrier, MHz", AURAL_CARRIER / 1e6, 2.75, 1e-9)
    close("aural above visual, MHz", AURAL_SPACING / 1e6, 4.5, 1e-9)
    # A 6 MHz channel puts the visual carrier 1.25 MHz above the lower edge.
    close("visual above the lower channel edge, MHz",
          (VISUAL_CARRIER + 3e6) / 1e6, 1.25, 1e-9)
    check("the radio is tuned clear of the channel so its DC leak misses it",
          LO_OFFSET > 3e6, f"{LO_OFFSET/1e6:g} MHz above centre")

    print("\nplaying an 18 MS/s .dat capture at the flowgraph's rate")
    for rate, want in ((10e6, (5, 9)), (12e6, (2, 3)), (18e6, (1, 1))):
        got = dat_resample_ratio(rate)
        check(f"{rate/1e6:g} MS/s needs {want[0]}/{want[1]}", got == want, str(got))
    # What the app used to do: play it out untouched at 10 MS/s.
    naive = 10e6 / 1144
    close("unresampled, a .dat gives this line rate", naive, 8741.26, 1.0)
    close("resampled, it gives the right one", 10e6 / (1144 * 5 / 9), FH, 1.0)

    print("\nthe composite legalizer")
    close("legal composite floor, in units", ire_to_unit(IRE_TROUGH), 0.142857, 1e-5)
    close("legal composite ceiling, in units", ire_to_unit(IRE_PEAK), 1.142857, 1e-5)
    saturated = np.zeros((480, 640, 3))
    for k, rgb in enumerate([(1, 1, 1), (1, 1, 0), (0, 1, 1), (0, 1, 0),
                             (1, 0, 1), (1, 0, 0), (0, 0, 1)]):
        saturated[:, k * 640 // 7:(k + 1) * 640 // 7] = rgb
    raw = NtscEncoder(RATE, legalize=False).encode_frame(saturated)
    legal = NtscEncoder(RATE, legalize=True).encode_frame(saturated)
    print(f"       100% bars reach {raw.max():.3f} unlegalised, "
          f"{legal.max():.3f} after")
    check("100% saturated colour overshoots past what a carrier can hold",
          raw.max() > ire_to_unit(IRE_PEAK), f"{raw.max():.3f}")
    check("and the legalizer brings it back inside",
          legal.max() <= ire_to_unit(IRE_PEAK) + 1e-9, f"{legal.max():.3f}")
    # 75% bars are the standard test signal precisely because they fit.
    bars = colour_bars()
    check("75% bars are untouched by it",
          np.array_equal(NtscEncoder(RATE, legalize=False).encode_frame(bars),
                         NtscEncoder(RATE, legalize=True).encode_frame(bars)))

    print("\nmodulating: sync, blanking and white onto the carrier")
    # A flat frame of each level, so the envelope can be read directly.
    enc = NtscEncoder(RATE, color=False)
    composite = np.concatenate([enc.encode_frame(np.full((480, 640, 3), v))
                                for v in (0.0, 1.0)])
    tb = Modulate(composite)
    tb.run()
    rf = tb.result()
    env = envelope(rf)
    # Skip the filter's start-up, then read the three levels back.
    body = slice(len(env) // 4, None)
    at_sync = np.percentile(env[body], 99.9)
    at_white = np.percentile(env[body], 0.1)
    print(f"       carrier runs {at_white:.3f} .. {at_sync:.3f}")
    close("sync tip sits at 100% of peak carrier", at_sync, CARRIER_AT_SYNC, 0.03)
    close("peak white sits at 12.5%", at_white, CARRIER_AT_WHITE, 0.03)
    check("so it is negative modulation, as System M requires",
          at_sync > at_white)

    print("\nand the other polarity, which used to be the default")
    tb = Modulate(composite, polarity='positive')
    tb.run()
    env_p = envelope(tb.result())[body]
    print(f"       carrier runs {np.percentile(env_p, 0.1):.3f} .. "
          f"{np.percentile(env_p, 99.9):.3f}")
    check("positive modulation puts white at peak carrier instead",
          np.percentile(env_p, 99.9) > CARRIER_AT_SYNC - 0.1
          and np.percentile(env_p, 0.1) < 0.3)
    # The vestigial filter rings on sync's sharp edges, and it rings hardest
    # in *negative* modulation because there the sync pulse is the peak of
    # the carrier - the fastest, largest excursion in the whole signal. That
    # is inherent to System M and real transmitters carry the same overshoot,
    # which is why the number that matters is not this one but the level
    # reaching the radio, after the app scales the sum of vision and sound.
    scale = 0.85 / (CARRIER_AT_SYNC + 0.316)
    print(f"       ringing on sync: negative {env.max():.3f}, "
          f"positive {env_p.max():.3f} of peak carrier")
    check("both polarities stay within the filter's ringing",
          env.max() < 1.30 and env_p.max() < 1.30)
    check("after the app's own scaling both are well inside full scale",
          max(env.max(), env_p.max()) * scale < 0.9,
          f"{max(env.max(), env_p.max()) * scale:.3f} of full scale")

    print("\na picture, all the way through the modulator and back")
    frame = colour_bars()
    if args.video:
        if not have_ffmpeg():
            print("       (--video needs ffmpeg; using bars)")
        else:
            src = VideoFile(args.video)
            frame = src.next_frame()
            src.close()
    enc = NtscEncoder(RATE)
    composite = np.concatenate([enc.encode_frame(frame) for _ in range(3)])
    tb = Modulate(composite)
    tb.run()
    recovered = to_composite(envelope(tb.result()))
    # The filter delays the signal; decode from safely inside it.
    recovered = recovered[len(recovered) // 6:]
    dec = NtscDecoder(RATE, width=frame.shape[1], active_lines=240)
    out = dec.decode_frame(recovered)
    check("a frame comes back", out.shape == frame.shape, str(out.shape))
    worst = 0.0
    names = ['white', 'yellow', 'cyan', 'green', 'magenta', 'red', 'blue']
    if not args.video:
        for k, name in enumerate(names):
            col = (k * 640 // 7 + (k + 1) * 640 // 7) // 2
            got = out[100:140, col - 10:col + 10].mean(axis=(0, 1))
            want = frame[100, col]
            err = float(np.abs(got - want).max())
            worst = max(worst, err)
            print(f"  {name:8s} sent {np.round(want, 2)}  back {np.round(got, 2)}"
                  f"  error {err:.4f}")
        # An order of magnitude looser than the 0.01 the composite-only
        # loopback requires, and it should be: chroma sits at 3.58 MHz,
        # which is outside the vestigial region, so only one of its
        # sidebands is transmitted. A television recovers it with the same
        # inaccuracy - this is what vestigial sideband costs, not a fault
        # in the modulator.
        close("worst colour error through the whole transmit chain", worst,
              0.0, 0.15)
    else:
        err = float(np.abs(out - frame).mean())
        close("mean error through the whole transmit chain", err, 0.0, 0.15)

    print("\nthe live source keeps up with the air")
    for label, frames in (("colour bars", TestPattern()),):
        src = ntsc_source(frames, RATE)
        tb = gr.top_block("speed", catch_exceptions=True)
        head = blocks.head(gr.sizeof_float, int(RATE * 0.5))
        sink = blocks.null_sink(gr.sizeof_float)
        tb.connect(src, head, sink)
        import time
        t0 = time.time()
        tb.run()
        wall = time.time() - t0
        print(f"       {label}: {0.5 / wall:.2f}x real time, "
              f"{src.frames_encoded} frames, {src.starved} samples starved")
        check(f"{label} encodes faster than real time", 0.5 / wall > 1.0,
              f"{0.5 / wall:.2f}x")
        check(f"{label} never starved the output", src.starved == 0)

    print()
    if failures:
        print(f"{len(failures)} FAILED: {', '.join(failures)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
