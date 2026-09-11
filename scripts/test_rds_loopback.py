#!/usr/bin/env python3
"""Encode RDS, decode it straight back, and check it survived the round trip.

Pure software - no radio involved. This is the cheap gate to run before
transmitting anything: if the encoder and decoder disagree here, they will
disagree on the air too, and off the air it is far harder to tell which end is
at fault.

    python scripts/test_rds_loopback.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from apps.rds_core import (  # noqa: E402
    RdsDemod, RdsProtocol, pi_to_callsign, software_pilot_pll,
)
from apps.rds_encode import RdsEncoder, RdsSubcarrier  # noqa: E402

FS = 200e3
SECONDS = 15
PI = 0x4413            # K + T,S,T -> KTST
PS = 'GNURADIO'
ARTIST = 'Claude Test'
TITLE = 'Loopback Tune'
PTY = 5                # Rock, in the RBDS table


def main():
    enc = RdsEncoder(pi=PI, ps=PS, pty=PTY)
    enc.set_now_playing(ARTIST, TITLE)
    sub = RdsSubcarrier(enc, FS)

    chunks = int(FS * SECONDS) // 8192
    mpx = np.concatenate([sub.generate(8192) for _ in range(chunks)])
    mpx = mpx.astype(np.float64)
    print(f"encoded {len(mpx)/FS:.1f} s of pilot + RDS subcarrier "
          f"(rms {mpx.std():.4f})")

    ref = software_pilot_pll(mpx, FS)
    demod, proto = RdsDemod(FS), RdsProtocol(region='RBDS')
    for i in range(0, len(mpx), 8192):
        bits = demod.feed(mpx[i:i + 8192], ref[i:i + 8192])
        if len(bits):
            proto.feed(bits)

    snap = proto.snapshot()
    good = 100 * (1 - (snap['block_error_rate'] or 0))
    print(f"decoded back: {snap['groups']} groups, "
          f"{snap['blocks_ok']}/{snap['blocks_seen']} blocks ({good:.1f}% good)")
    print()
    checks = [
        ('PI', snap['pi'], PI, f"{snap['pi_hex']} -> "
                               f"{pi_to_callsign(snap['pi']) if snap['pi'] else None}"),
        ('PS', snap['ps'].strip(), PS, repr(snap['ps'])),
        ('artist', snap['artist'], ARTIST, repr(snap['artist'])),
        ('title', snap['title'], TITLE, repr(snap['title'])),
        ('PTY', snap['pty'], 'Rock', repr(snap['pty'])),
    ]
    ok = True
    for name, got, want, shown in checks:
        hit = got == want
        ok &= hit
        print(f"  {'ok  ' if hit else 'FAIL'} {name:7s} {shown}"
              + ('' if hit else f"   (expected {want!r})"))
    print(f"  RadioText {snap['radiotext']!r}")

    # A noiseless loopback should be essentially perfect; anything much below
    # this means a structural bug rather than a marginal signal.
    if good < 95:
        ok = False
        print(f"\n  FAIL block quality {good:.1f}% - too low for a clean signal")
    print("\nLOOPBACK:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
