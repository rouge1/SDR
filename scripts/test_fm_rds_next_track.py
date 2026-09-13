#!/usr/bin/env python3
"""Next Track must not glitch the pilot or RDS.

Runs the real FM + RDS Transmitter flowgraph - with a stand-in for the radio,
so no hardware and no media folder - records the multiplex across two Next
Track presses (stereo into stereo, then into mono) and decodes it the way the
RDS Receiver does: symbol timing measured once at the start, then kept.

Rebuilding the flowgraph on Next Track used to drop the samples in transit.
The pilot jumped 139 degrees, and a receiver that had measured its timing went
from 100% blocks good to about 40% - off air, to nothing at all.

    python scripts/test_fm_rds_next_track.py
"""
import os
import sys
import tempfile
import time
import wave

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import numpy as np  # noqa: E402
from PyQt5 import Qt  # noqa: E402

app = Qt.QApplication(sys.argv[:1])
from gnuradio import blocks, gr  # noqa: E402

import apps.vsg_sink as vsg  # noqa: E402


class stand_in_radio(gr.sync_block):
    """Takes the modulated samples at about the rate a radio would."""

    def __init__(self, center_freq=0, sample_rate=0, level_dbm=0, serial=None):
        gr.sync_block.__init__(self, name='stand_in_radio',
                               in_sig=[np.complex64], out_sig=None)

    def work(self, input_items, output_items):
        time.sleep(len(input_items[0]) / 2e6)
        return len(input_items[0])

    def set_level(self, *args):
        pass

    def set_frequency(self, *args):
        pass

    def set_gain(self, *args):
        pass


vsg.vsg_sink = stand_in_radio
from apps import fmRdsTransmitter as fx  # noqa: E402
from apps.rds_core import RdsDemod, RdsProtocol, software_pilot_pll  # noqa: E402

SECONDS_PER_TRACK = 5
failures = []


def check(name, got, ok):
    print(f"  {'ok  ' if ok else 'FAIL'} {name}: {got}")
    if not ok:
        failures.append(name)


def write_wav(path, seconds, left_hz, right_hz=None):
    t = np.arange(int(seconds * fx.AUDIO_RATE)) / fx.AUDIO_RATE
    chans = [0.5 * np.sin(2 * np.pi * left_hz * t)]
    if right_hz is not None:
        chans.append(0.3 * np.sin(2 * np.pi * right_hz * t))
    data = (np.stack(chans, axis=1) * 32767).astype('<i2')
    with wave.open(path, 'wb') as w:
        w.setnchannels(len(chans))
        w.setsampwidth(2)
        w.setframerate(fx.AUDIO_RATE)
        w.writeframes(data.tobytes())


media = tempfile.mkdtemp(prefix='fm_rds_next_track_')
playlist = [os.path.join(media, name) for name in
            ('Stereo-A.wav', 'Stereo-B.wav', 'Mono-C.wav')]
write_wav(playlist[0], 3, 1000, 400)
write_wav(playlist[1], 3, 600, 1500)
write_wav(playlist[2], 3, 440)

values = {'radio_type': 'vsg', 'frequency_mhz': 102.1, 'power_percent': 0,
          'call': 'KTST', 'ps': 'NEXTTRAK', 'radiotext': '', 'pty': 5,
          'track_in_rt': True, 'audio': playlist[0], 'audio_list': playlist}
tb = fx.fmRdsTransmitter(values)
tap = blocks.vector_sink_f()
tb.disconnect(tb.mpx_sum, tb.mpx_sink)
tb.mpx_sink = tap                 # so a flowgraph rebuild reconnects the tap too
tb.connect(tb.mpx_sum, tap)
tb.start()
presses = []
for _ in range(2):
    time.sleep(SECONDS_PER_TRACK)
    presses.append(len(tap.data()))
    tb.next_track()
time.sleep(SECONDS_PER_TRACK)
tb.stop()
tb.wait()

FS = fx.MPX_RATE
mpx = np.array(tap.data(), dtype=np.float64)
print(f"recorded {len(mpx) / FS:.1f} s of multiplex, Next Track at "
      + ", ".join(f"{p / FS:.1f} s" for p in presses))

print("\nthe pilot carries straight on")
ref = software_pilot_pll(mpx, FS)
residual = np.unwrap(np.angle(ref)) - 2 * np.pi * 19000.0 * np.arange(len(mpx)) / FS
for i, p in enumerate(presses):
    before = np.median(residual[p - int(0.5 * FS):p - int(0.1 * FS)])
    after = np.median(residual[p + int(0.3 * FS):p + int(0.8 * FS)])
    jump = np.degrees(after - before)
    check(f"pilot phase jump at press {i + 1}", f"{jump:.1f} degrees", abs(jump) < 5)

print("\na receiver with its timing measured once keeps decoding")
demod, proto = RdsDemod(FS), RdsProtocol()
rates, titles = [], []
for s in range(0, len(mpx), int(FS)):
    ok0, seen0 = proto.blocks_ok, proto.blocks_seen
    for i in range(s, min(s + int(FS), len(mpx)), 8192):
        j = min(i + 8192, s + int(FS), len(mpx))
        bits = demod.feed(mpx[i:j], ref[i:j])
        if len(bits):
            proto.feed(bits)
    seen = proto.blocks_seen - seen0
    rates.append(100 * (proto.blocks_ok - ok0) / seen if seen else None)
    titles.append(proto.snapshot()['title'])
after_start = [r for r in rates[2:] if r is not None]
check("blocks good per second after the first two",
      " ".join(f"{r:.0f}" for r in after_start),
      after_start and min(after_start) >= 95)
order = [t for k, t in enumerate(titles) if t and (k == 0 or t != titles[k - 1])]
check("Now Playing follows each track", order,
      order == ['Stereo A', 'Stereo B', 'Mono C'])

print("\nthe stereo difference signal is there for stereo files only")


def band_db(segment, lo, hi):
    spec = np.abs(np.fft.rfft(segment * np.hanning(len(segment)))) ** 2
    f = np.fft.rfftfreq(len(segment), 1 / FS)
    return 10 * np.log10(spec[(f > lo) & (f < hi)].sum() + 1e-30)


edges = [0] + presses + [len(mpx)]
for name, (a, b) in zip(('Stereo A', 'Stereo B', 'Mono C'), zip(edges, edges[1:])):
    # The last 2.5 s of each track: the samples already inside the filters at
    # a press still belong to the track before, and play out rather than
    # being thrown away.
    seg = mpx[max(a, b - int(2.5 * FS)):b]
    side = band_db(seg, 36000, 40000) - band_db(seg, 18500, 19500)
    stereo = name.startswith('Stereo')
    check(f"{name}: 36-40 kHz against the pilot", f"{side:.1f} dB",
          side > -30 if stereo else side < -60)

print()
print("RESULT:", "PASS" if not failures else f"FAIL ({', '.join(failures)})")
raise SystemExit(1 if failures else 0)
