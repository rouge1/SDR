#!/usr/bin/env python3
"""Check the stereo multiplex: is the 38 kHz subcarrier there, and is L-R on it?

Runs the transmitter's modulation chain on a stereo WAV into a file, then
demodulates it and measures the multiplex: pilot, the 38 kHz difference
subcarrier and RDS. The side/mid ratio recovered is compared against the ratio
measured in the source file, which is a delay-independent way of proving the
difference signal survived the round trip at the right level.

    python scripts/test_fm_stereo.py /data/python/media/<stereo>.wav
"""
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
    wav_channels,
)
from apps.rds_core import (  # noqa: E402
    RdsDemod, RdsProtocol, fm_demodulate, software_pilot_pll,
)
from apps.rds_encode import RdsEncoder  # noqa: E402

SECONDS = 10


def source_side_mid(path, seconds):
    """The side/mid ratio actually present in the file, in dB."""
    w = wave.open(path)
    raw = np.frombuffer(w.readframes(min(w.getnframes(),
                                         w.getframerate() * seconds)),
                        dtype='<i2').astype(np.float64)
    fr = w.getframerate()
    w.close()
    left, right = raw[0::2], raw[1::2]
    # Band-limit to the 15 kHz the transmitter passes, for a fair comparison.
    taps = sig.firwin(201, 15e3, fs=fr)
    mid = sig.lfilter(taps, 1.0, (left + right) / 2)
    side = sig.lfilter(taps, 1.0, (left - right) / 2)
    return 20 * np.log10(side.std() / (mid.std() + 1e-12))


def build(encoder, path, out_path):
    tb = gr.top_block()
    src = blocks.wavfile_source(path, True)
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
    head = blocks.head(gr.sizeof_gr_complex, int(TX_RATE * SECONDS))
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
    # Locals would be garbage collected while the scheduler still holds them.
    tb.keepalive = (src, rds, rl, rr, add, sub, midh, sideh, mpre, mlpf,
                    spre, slpf, mix, asum, mpx, up, mod, head, sink)
    return tb


def band_db(f, p, lo, hi, floor):
    m = (f >= lo) & (f < hi)
    return 10 * np.log10(float(np.sum(p[m]) * (f[1] - f[0])) / floor)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else None
    if not path or wav_channels(path) != 2:
        print("give me a 2-channel WAV")
        return 1
    out = '/tmp/fm_stereo_tx.cfile'
    want = source_side_mid(path, SECONDS)
    print(f"source {os.path.basename(path)}: side/mid = {want:.1f} dB")

    enc = RdsEncoder(pi=call_to_pi('KTST'), ps='STEREOFM', pty=5)
    enc.set_now_playing('Bench', 'Stereo Test')
    print(f"modulating {SECONDS}s ...")
    build(enc, path, out).run()

    iq = np.fromfile(out, dtype=np.complex64)
    mpx, fs = fm_demodulate(iq, TX_RATE, 0.0, 250e3)
    del iq
    centred = mpx - np.median(mpx)
    dev = np.percentile(np.abs(centred), 99.99) * fs / (2 * np.pi)
    print(f"peak deviation ~{dev/1e3:.1f} kHz (limit 75)")

    f, p = sig.welch(centred, fs=fs, nperseg=1 << 14)
    floor = float(np.median(p[(f >= 100e3) & (f < 120e3)])) * 1e3
    print(f"  pilot   19 kHz : {band_db(f, p, 18.9e3, 19.1e3, floor):6.1f} dB")
    print(f"  stereo  38 kHz : {band_db(f, p, 23e3, 53e3, floor):6.1f} dB")
    print(f"  RDS     57 kHz : {band_db(f, p, 54.6e3, 59.4e3, floor):6.1f} dB")

    # Coherently demodulate the difference subcarrier at twice the pilot phase.
    ref = software_pilot_pll(mpx, fs)
    phase = np.unwrap(np.angle(ref))
    lp = sig.firwin(301, 15e3, fs=fs)
    mid = sig.lfilter(lp, 1.0, centred)
    side = sig.lfilter(lp, 1.0, centred * 2 * np.cos(2 * phase))
    got = 20 * np.log10(side.std() / (mid.std() + 1e-12))
    print(f"\nrecovered side/mid = {got:.1f} dB   (source {want:.1f} dB, "
          f"difference {abs(got - want):.1f} dB)")

    demod, proto = RdsDemod(fs), RdsProtocol(region='RBDS')
    for i in range(0, len(mpx), 8192):
        bits = demod.feed(mpx[i:i + 8192], ref[i:i + 8192])
        if len(bits):
            proto.feed(bits)
    snap = proto.snapshot()
    print(f"RDS still fine: PS={snap['ps']!r} title={snap['title']!r} "
          f"blocks {snap['blocks_ok']}/{snap['blocks_seen']}")

    ok = abs(got - want) < 3.0 and dev < 80e3 and snap['blocks_seen'] > 0
    print("\nSTEREO MULTIPLEX:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
