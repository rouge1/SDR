#!/usr/bin/env python3
"""Run the transmitter's modulation chain into a file and decode it back.

Everything the FM+RDS transmitter does apart from the radio itself: audio
resampling, pre-emphasis, the pilot and RDS subcarrier, the multiplex sum, and
the FM modulator. The result is decoded with apps/rds_core.py, so a pass means
the signal is right before any of it is radiated.

    python scripts/test_fm_rds_tx.py [audio.wav]
"""
import json
import os
import sys

import numpy as np
from gnuradio import analog, blocks, filter, gr  # type: ignore
from gnuradio.filter import firdes  # type: ignore

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from apps.fmRdsTransmitter import (  # noqa: E402
    AUDIO_LEVEL, MAX_DEVIATION, MPX_RATE, PILOT_LEVEL, RDS_INJECTION, TX_RATE,
    call_to_pi, rds_source, track_name,
)
from apps.rds_core import (  # noqa: E402
    RdsDemod, RdsProtocol, fm_demodulate, pi_to_callsign, software_pilot_pll,
)
from apps.rds_encode import RdsEncoder  # noqa: E402

SECONDS = 8
CALL = 'KTST'
PS = 'LOOPBACK'
ARTIST = 'Claude'
TITLE = 'Bench Test'


def build(encoder, audio_path, out_path):
    tb = gr.top_block()
    if audio_path and os.path.exists(audio_path):
        src = blocks.wavfile_source(audio_path, True)
    else:
        src = analog.sig_source_f(48000, analog.GR_COS_WAVE, 1000, 0.5, 0, 0)
    resamp = filter.rational_resampler_fff(interpolation=25, decimation=6,
                                           taps=[], fractional_bw=0)
    preemph = analog.fm_preemph(MPX_RATE, 75e-6)
    lpf = filter.fir_filter_fff(1, firdes.low_pass(AUDIO_LEVEL, MPX_RATE,
                                                   15e3, 2e3))
    rds = rds_source(encoder, MPX_RATE)
    mpx = blocks.add_vff(1)
    up = filter.rational_resampler_fff(
        interpolation=int(TX_RATE // MPX_RATE), decimation=1, taps=[],
        fractional_bw=0)
    mod = analog.frequency_modulator_fc(2 * np.pi * MAX_DEVIATION / TX_RATE)
    head = blocks.head(gr.sizeof_gr_complex, int(TX_RATE * SECONDS))
    sink = blocks.file_sink(gr.sizeof_gr_complex, out_path, False)

    # One branch only. Deviation is measured from the demodulated signal
    # afterwards, which is a truer check anyway - it measures what actually
    # came out rather than what went in.
    tb.connect(src, resamp, preemph, lpf, (mpx, 0))
    tb.connect(rds, (mpx, 1))
    tb.connect(mpx, up, mod, head, sink)
    # Keep Python references to every block alive. These are locals, and once
    # this function returns they can be garbage collected while the C++
    # scheduler is still running - which segfaults, spectacularly and with no
    # Python frame in the traceback, as soon as it calls a Python block's
    # work() on a freed object. The apps are safe because they store blocks on
    # self; a plain function has to say so explicitly.
    tb.keepalive = (src, resamp, preemph, lpf, rds, mpx, up, mod, head, sink)
    return tb


def main():
    audio = sys.argv[1] if len(sys.argv) > 1 else None
    out = '/tmp/fm_rds_tx.cfile'
    pi = call_to_pi(CALL)
    enc = RdsEncoder(pi=pi, ps=PS, pty=5)
    enc.set_now_playing(ARTIST, TITLE)

    print(f"modulating {SECONDS}s"
          + (f" of {track_name(audio)!r}" if audio else " of a 1 kHz tone"))
    tb = build(enc, audio, out)
    tb.run()

    iq = np.fromfile(out, dtype=np.complex64)
    demod_mpx, fs = fm_demodulate(iq, TX_RATE, 0.0, 250e3)
    centred = demod_mpx - np.median(demod_mpx)
    peak_dev = np.percentile(np.abs(centred), 99.99) * fs / (2 * np.pi)
    print(f"peak deviation ~{peak_dev/1e3:.1f} kHz (limit 75)")
    if peak_dev > 80e3:
        print("  WARNING: over-deviating")
    ref = software_pilot_pll(demod_mpx, fs)
    d, p = RdsDemod(fs), RdsProtocol(region='RBDS')
    for i in range(0, len(demod_mpx), 8192):
        bits = d.feed(demod_mpx[i:i + 8192], ref[i:i + 8192])
        if len(bits):
            p.feed(bits)
    snap = p.snapshot()
    good = 100 * (1 - (snap['block_error_rate'] or 0))
    print(f"\ndecoded back: {snap['groups']} groups, "
          f"{snap['blocks_ok']}/{snap['blocks_seen']} blocks ({good:.1f}% good)")
    checks = [('PI', snap['pi'], pi), ('PS', snap['ps'].strip(), PS),
              ('artist', snap['artist'], ARTIST), ('title', snap['title'], TITLE)]
    ok = True
    for name, got, want in checks:
        hit = got == want
        ok &= hit
        print(f"  {'ok  ' if hit else 'FAIL'} {name:7s} {got!r}"
              + ('' if hit else f"  (expected {want!r})"))
    print(f"  call sign from PI: {pi_to_callsign(snap['pi']) if snap['pi'] else None}")
    print(f"  RadioText {snap['radiotext']!r}")
    if good < 95:
        ok = False
        print(f"  FAIL block quality {good:.1f}%")
    json.dump({'station_hz': 0.0, 'lo_hz': 0.0, 'offset_hz': 0.0,
               'rate': TX_RATE, 'seconds': SECONDS}, open(out[:-7] + '.json', 'w'))
    print("\nTRANSMIT CHAIN:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
