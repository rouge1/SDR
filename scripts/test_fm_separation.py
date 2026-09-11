#!/usr/bin/env python3
"""Measure FM stereo channel separation with a one-channel-at-a-time tone.

A side/mid level ratio proves difference content survived, but not that it is
the *right* difference content - swapped channels, crosstalk and noise all pass
that check. This drives one channel with a tone while the other is silent, then
measures how much of the tone lands in the silent channel.

Two properties make it trustworthy where a level ratio is not:

* The measurement is taken **at the tone frequency only**, by projecting onto a
  complex exponential, so broadband noise cannot flatter the result. That
  matters because FM noise rises with baseband frequency and inflates any
  wideband reading of the difference signal.
* Windows are classified by **which channel actually carries the tone**, so no
  alignment with the source is needed and swapped channels are obvious.

    python scripts/test_fm_separation.py              # transmitter chain only
    python scripts/test_fm_separation.py capture      # an off-air .cfile + .json

For reference: good FM stereo reaches 30-40 dB of separation, and above about
20 dB sounds properly separated.
"""
import json
import os
import sys
import wave

import numpy as np
from gnuradio import analog, blocks, filter, gr  # type: ignore
from gnuradio.filter import firdes  # type: ignore
from scipy import signal as sig  # type: ignore

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from apps.fmRdsTransmitter import (  # noqa: E402
    AUDIO_LEVEL, MAX_DEVIATION, MPX_RATE, TX_RATE, call_to_pi, rds_source,
)
from apps.rds_core import fm_demodulate, software_pilot_pll  # noqa: E402
from apps.rds_encode import RdsEncoder  # noqa: E402

TEST_WAV = '/tmp/fm_stereo_separation.wav'
TONE_HZ = 1000.0
SEGMENT_S = 4.0          # how long each channel is driven before swapping
SECONDS = 24             # a few segments each way


def make_test_wav(path, fs=48000, cycles=3):
    """Alternate a tone in left-only and right-only segments."""
    n = int(fs * SEGMENT_S)
    t = np.arange(n) / fs
    tone = (0.6 * np.sin(2 * np.pi * TONE_HZ * t) * 32767).astype('<i2')
    quiet = np.zeros(n, dtype='<i2')
    left = np.empty(n * 2, dtype='<i2')
    right = np.empty(n * 2, dtype='<i2')
    left[0::2], left[1::2] = tone, quiet          # left driven
    right[0::2], right[1::2] = quiet, tone        # right driven
    frames = np.concatenate([left, right] * cycles)
    w = wave.open(path, 'wb')
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(fs)
    w.writeframes(frames.tobytes())
    w.close()
    return path


def build(encoder, wav_path, out_path, seconds):
    """The transmitter's stereo multiplex chain, into a file."""
    tb = gr.top_block()
    src = blocks.wavfile_source(wav_path, True)
    rds = rds_source(encoder, MPX_RATE)

    def resampler():
        return filter.rational_resampler_fff(interpolation=25, decimation=6,
                                             taps=[], fractional_bw=0)

    def shaping():
        return (analog.fm_preemph(MPX_RATE, 75e-6),
                filter.fir_filter_fff(1, firdes.low_pass(
                    AUDIO_LEVEL, MPX_RATE, 15e3, 2e3)))

    rl, rr = resampler(), resampler()
    add, sub = blocks.add_ff(1), blocks.sub_ff(1)
    midh, sideh = blocks.multiply_const_ff(0.5), blocks.multiply_const_ff(0.5)
    mpre, mlpf = shaping()
    spre, slpf = shaping()
    mix = blocks.multiply_ff(1)
    asum, mpx = blocks.add_vff(1), blocks.add_vff(1)
    up = filter.rational_resampler_fff(
        interpolation=int(TX_RATE // MPX_RATE), decimation=1, taps=[],
        fractional_bw=0)
    mod = analog.frequency_modulator_fc(2 * np.pi * MAX_DEVIATION / TX_RATE)
    head = blocks.head(gr.sizeof_gr_complex, int(TX_RATE * seconds))
    sink = blocks.file_sink(gr.sizeof_gr_complex, out_path, False)

    tb.connect((src, 0), rl)
    tb.connect((src, 1), rr)
    tb.connect(rl, (add, 0))
    tb.connect(rr, (add, 1))
    tb.connect(rl, (sub, 0))
    tb.connect(rr, (sub, 1))
    tb.connect(add, midh, mpre, mlpf, (asum, 0))
    tb.connect(sub, sideh, spre, slpf, (mix, 0))
    tb.connect((rds, 1), (mix, 1))
    tb.connect(mix, (asum, 1))
    tb.connect(asum, (mpx, 0))
    tb.connect((rds, 0), (mpx, 1))
    tb.connect(mpx, up, mod, head, sink)
    tb.keepalive = (src, rds, rl, rr, add, sub, midh, sideh, mpre, mlpf,
                    spre, slpf, mix, asum, mpx, up, mod, head, sink)
    return tb


def tone_amplitude(x, fs, f0):
    """Amplitude of f0 in x, measured at that frequency alone."""
    n = np.arange(len(x))
    return 2.0 * abs(np.mean(x * np.exp(-2j * np.pi * f0 * n / fs)))


def recover_lr(iq, rate, offset_hz, phase_deg=None):
    """IQ -> (left, right, mpx rate, phase used), demodulating the 38 kHz side.

    The regenerated subcarrier must be phase-aligned with the multiplex, and
    the offset is emphatically not zero: the pilot reaches the PLL through a
    band-pass whose group delay the multiplex does not share. Assuming zero
    reads 18 dB of separation where 34 dB is actually available - it looks like
    a broken transmitter and is not. A real stereo decoder locks this phase, so
    fit it here rather than assume it.

    The delay arithmetic predicts the answer, which is a useful cross-check: a
    401-tap band-pass delays 200 samples, at 19 kHz and 250 kHz that is 0.2 of
    a cycle or 72 degrees of pilot phase, doubled to ~144 degrees at 38 kHz.
    """
    mpx, fs = fm_demodulate(iq, rate, offset_hz, 250e3)
    centred = mpx - np.median(mpx)
    ref = software_pilot_pll(mpx, fs)
    phase = np.unwrap(np.angle(ref))
    lp = sig.firwin(301, 15e3, fs=fs)
    mid = sig.lfilter(lp, 1.0, centred)

    def demod(deg):
        # The difference signal rides on a subcarrier at twice the pilot.
        return sig.lfilter(lp, 1.0,
                           centred * 2 * np.cos(2 * phase + np.deg2rad(deg)))

    if phase_deg is None:
        best = (-1e9, 0.0)
        for deg in range(0, 180, 10):            # coarse
            side = demod(deg)
            score = _score(mid + side, mid - side, fs)
            if score > best[0]:
                best = (score, float(deg))
        for deg in np.arange(best[1] - 10, best[1] + 10.1, 2.0):   # fine
            side = demod(float(deg))
            score = _score(mid + side, mid - side, fs)
            if score > best[0]:
                best = (score, float(deg))
        phase_deg = best[1]
    side = demod(phase_deg)
    return mid + side, mid - side, fs, phase_deg


def separation(left, right, fs):
    """Median separation per direction, from half-second windows."""
    win = int(fs * 0.5)
    results = {'left driven': [], 'right driven': []}
    for i in range(0, len(left) - win, win):
        a_l = tone_amplitude(left[i:i + win], fs, TONE_HZ)
        a_r = tone_amplitude(right[i:i + win], fs, TONE_HZ)
        if max(a_l, a_r) < 1e-6:
            continue
        ratio = 20 * np.log10(max(a_l, a_r) / (min(a_l, a_r) + 1e-12))
        results['left driven' if a_l > a_r else 'right driven'].append(ratio)
    return results


def _score(left, right, fs):
    """Worst-direction separation, used to fit the demodulation phase."""
    res = separation(left, right, fs)
    medians = [float(np.median(v)) for v in res.values() if v]
    return min(medians) if medians else -1e9


def main():
    if len(sys.argv) > 1:                      # measure an off-air capture
        base = sys.argv[1]
        meta = json.load(open(base + '.json'))
        iq = np.fromfile(base + '.cfile', dtype=np.complex64)
        print(f"measuring capture {os.path.basename(base)}")
        left, right, fs, fitted = recover_lr(iq, meta['rate'],
                                             meta['offset_hz'])
    else:
        make_test_wav(TEST_WAV)
        print(f"test signal: {TONE_HZ:.0f} Hz tone, {SEGMENT_S:g}s per channel"
              f" -> {TEST_WAV}")
        out = '/tmp/fm_separation_tx.cfile'
        enc = RdsEncoder(pi=call_to_pi('KTST'), ps='SEPTEST', pty=5)
        print(f"modulating {SECONDS}s through the transmitter chain ...")
        build(enc, TEST_WAV, out, SECONDS).run()
        iq = np.fromfile(out, dtype=np.complex64)
        left, right, fs, fitted = recover_lr(iq, TX_RATE, 0.0)

    res = separation(left, right, fs)
    print(f"\n38 kHz demodulation phase fitted to {fitted:.0f} deg "
          f"(filter delay predicts ~144)")
    ok = True
    for label, values in res.items():
        if not values:
            print(f"  {label:13s} no windows measured")
            ok = False
            continue
        med = float(np.median(values))
        print(f"  {label:13s} separation {med:5.1f} dB   "
              f"(min {min(values):5.1f}, max {max(values):5.1f}, "
              f"{len(values)} windows)")
        ok &= med > 20.0
    print(f"\nSEPARATION: {'PASS' if ok else 'FAIL'}"
          " (>20 dB in both directions sounds properly separated)")
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
