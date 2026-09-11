#!/usr/bin/env python3
"""Exercise apps/rds_core.py against a recorded FM capture.

Feeds the capture through the demodulator in small chunks, the way the live
flowgraph does, so the cross-chunk state (pilot phase continuity, the partial
bit carried between calls, differential-decode carry) is actually tested.

    python scripts/test_rds_core.py /path/to/capture   # no .cfile extension

The capture is raw complex float32 plus a JSON sidecar from the recording
script (keys: rate, offset_hz, station_hz).
"""
import argparse
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from apps.rds_core import (  # noqa: E402
    RdsDemod, RdsProtocol, fm_demodulate, software_pilot_pll,
)

MPX_RATE = 250e3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('base', help='capture path without extension')
    ap.add_argument('--seconds', type=float, default=20.0)
    ap.add_argument('--chunk', type=int, default=8192)
    ap.add_argument('--region', default='RBDS')
    a = ap.parse_args()

    with open(a.base + '.json') as f:
        meta = json.load(f)
    iq = np.fromfile(a.base + '.cfile', dtype=np.complex64,
                     count=int(meta['rate'] * a.seconds))
    print(f"capture: {meta['station_hz']/1e6:.1f} MHz, "
          f"{len(iq)/meta['rate']:.1f} s at {meta['rate']/1e6:g} MS/s")

    t0 = time.time()
    mpx, fs = fm_demodulate(iq, meta['rate'], meta['offset_hz'], MPX_RATE)
    del iq
    ref = software_pilot_pll(mpx, fs)
    print(f"FM demod + pilot PLL: {time.time()-t0:.1f} s")

    demod = RdsDemod(fs)
    proto = RdsProtocol(region=a.region)
    t0 = time.time()
    nbits = 0
    for i in range(0, len(mpx), a.chunk):
        bits = demod.feed(mpx[i:i + a.chunk], ref[i:i + a.chunk])
        if len(bits):
            nbits += len(bits)
            proto.feed(bits)
    dt = time.time() - t0
    audio_s = len(mpx) / fs
    print(f"streamed {nbits} bits in {dt:.1f} s "
          f"({audio_s/dt:.1f}x real time, chunk={a.chunk})")

    snap = proto.snapshot()
    print()
    call = snap['callsign_confirmed']
    print(f"  PI            {snap['pi_hex']}   " + (
        f"call sign {call} (confirmed against the station's own text)" if call
        else f"(unconfirmed call-sign hint: {snap['callsign']})"))
    print(f"  station name  {snap['station_name']!r}")
    print(f"  PS (live)     {snap['ps']!r}")
    print(f"  RadioText     {snap['radiotext']!r}")
    if snap['rtplus']:
        print(f"  RT+ tags      {snap['rtplus']}")
    if snap['oda']:
        print(f"  ODA apps      {snap['oda']}"
              + ("   (carries TMC traffic data)" if snap['has_tmc'] else ""))
    print(f"  PTY           {snap['pty']}")
    print(f"  TP / TA       {snap['tp']} / {snap['ta']}")
    print(f"  clock         {snap['clock']}")
    print(f"  groups        {snap['groups']}")
    print(f"  blocks        {snap['blocks_ok']}/{snap['blocks_seen']} ok "
          f"({100*(snap['block_error_rate'] or 0):.1f}% bad)")
    print(f"  group types   {snap['group_counts']}")

    ber = snap['block_error_rate']
    # Test for None explicitly: a flawless decode gives 0.0, and `ber or 1`
    # would treat that falsy zero as a failure.
    ok = (snap['pi'] is not None and snap['groups'] > 50
          and ber is not None and ber < 0.35)
    print()
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
