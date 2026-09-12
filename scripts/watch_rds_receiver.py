#!/usr/bin/env python3
"""Run the RDS receiver for a long stretch and log why decode quality moves.

The receiver window shows a lifetime blocks-good figure, which lags: a falling
number means the current rate is below the average, not where it is now. This
logs the windowed rate beside it, plus what would explain a decline:

  win%    blocks good in this window only
  drops%  samples the decoder never saw - elapsed x 250 kHz minus what the RDS
          block actually consumed. Nonzero means the radio overran.
  cpu     cores this whole process used during the window (os.times, so it
          works on Windows as well as Linux)
  dtau    (--timing only) where the best symbol timing sits now, relative to
          the offset measured once at startup
  coh     (--timing only) BPSK eye quality, 1.0 is perfect - the best single
          reading of how much signal the decoder is getting
  rf dBFS mean power of the raw radio samples; near 0 means the gain is
          driving the ADC to full scale. There is deliberately no pilot-level
          column: measured after FM demodulation it is flat whatever the gain,
          because demodulation normalises amplitude.

    python scripts/watch_rds_receiver.py --minutes 15
    python scripts/watch_rds_receiver.py --minutes 15 --gui --rt 1

The timing probe scores sixteen offsets on every chunk inside the flowgraph's
own thread, so it is off by default: on a slow machine the probe could cause
the very overruns being measured. --gui runs the real window with a real event
loop, which is how a user runs it; headless, the spectrum plot never paints.
Close any launcher first - it holds the HackRF even while sitting on a dialog.
"""
import argparse
import json
import os
import platform
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ap = argparse.ArgumentParser()
ap.add_argument('--minutes', type=float, default=15.0)
ap.add_argument('--every', type=float, default=15.0, help='seconds per window')
ap.add_argument('--audio', choices=['on', 'off'], default=None,
                help='default: as saved in the receiver config')
ap.add_argument('--gui', action='store_true')
ap.add_argument('--freq', type=float, default=None, help='MHz')
ap.add_argument('--gain', type=float, default=None, help='percent')
ap.add_argument('--timing', action='store_true')
ap.add_argument('--rt', type=float, default=0.0,
                help='also log RadioText/RT+ and clock changes this often, '
                     'in seconds')
ap.add_argument('--gains', default='',
                help='comma-separated gain percents to step through, one per '
                     '--reset-every segment, e.g. 30,40,55,70')
ap.add_argument('--reset-every', type=float, default=0.0,
                help='clear decoded data and re-measure symbol timing this often, '
                     'in seconds - what the Clear Decoded Data button does')
a = ap.parse_args()

if not a.gui:
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from PyQt5 import Qt                      # noqa: E402
app = Qt.QApplication(sys.argv[:1])       # before any QWidget

from apps import rdsReceiver as R         # noqa: E402
from apps.rds_core import RdsDemod, clock_text  # noqa: E402

cfg = {'radio_type': 'hackrf', 'frequency_mhz': 98.7, 'gain_percent': 40,
       'region': 'RBDS', 'audio': True}
try:
    with open(os.path.join(ROOT, 'config', 'rdsReceiver_config.json')) as f:
        cfg.update(json.load(f))
except (OSError, ValueError):
    pass
if a.audio:
    cfg['audio'] = a.audio == 'on'
if a.freq:
    cfg['frequency_mhz'] = a.freq
if a.gain is not None:
    cfg['gain_percent'] = a.gain
GAINS = [float(g) for g in a.gains.split(',') if g.strip()]
if GAINS:
    if not a.reset_every:
        ap.error('--gains needs --reset-every to say how long each step lasts')
    cfg['gain_percent'] = GAINS[0]

T_START = time.time()
STEPS = 16
OFFS = (np.arange(STEPS) - STEPS // 2) / STEPS
_orig_symbols = RdsDemod._symbols
from apps.rds_core import count_offset_hits  # noqa: E402


def _pick_tau(self, bb, k):
    """The stock measurement, plus a log line showing how clear the choice was.

    The offset is chosen once and then frozen, so a pick whose winner barely
    beats its neighbours stays wrong for the whole run.
    """
    hits = []
    for i in range(self.TAU_STEPS):
        syms, _ = _orig_symbols(self, bb, k - i / self.TAU_STEPS)
        hits.append(count_offset_hits(self._bits_from(syms)))
    best = int(np.argmax(hits))
    # Same clock as the log windows, once they have started.
    t0 = globals().get('state', {}).get('t0', T_START)
    print(f"# timing measured at {time.time() - t0:.0f} s: tau "
          f"{best / self.TAU_STEPS:.3f}; offset-word hits per candidate "
          f"tau 0..15/16: {hits}", flush=True)
    return best / self.TAU_STEPS


RdsDemod._pick_tau = _pick_tau
# Complex sums over the whole window, magnitude taken only when it is logged.
# The carrier phase is locked to the pilot, so symbols from different chunks add
# coherently; taking each chunk's magnitude instead reads near 1.0 on pure noise
# whenever the driver hands over chunks of only a symbol or two.
score = np.zeros(STEPS, dtype=np.complex128)
coh = [0j, 0.0]
if a.timing:
    def _symbols(self, bb, kt):
        syms, keep = _orig_symbols(self, bb, kt)
        # Any chunk counts: chunk sizes depend on the radio driver and the
        # platform, and a threshold here silently blanks the probe.
        if len(syms):
            for i, d in enumerate(OFFS):
                s = _orig_symbols(self, bb, kt - d)[0] if d else syms
                if len(s):
                    score[i] += np.sum(s ** 2)
            coh[0] += np.sum(syms ** 2)
            coh[1] += float(np.sum(np.abs(syms) ** 2))
        return syms, keep

    RdsDemod._symbols = _symbols

tb = R.rdsReceiver(cfg)
# Mean power of the raw samples, to see how close the radio is to full scale -
# pinned at full scale means the gain is too high. Kept in C++ blocks so it adds
# almost nothing on a slow machine.
from gnuradio import blocks as _blocks        # noqa: E402
_LEVEL_LEN = 400000                           # 0.2 s at 2 MS/s
tb.lvl_mag = _blocks.complex_to_mag_squared(1)
tb.lvl_avg = _blocks.moving_average_ff(_LEVEL_LEN, 1.0 / _LEVEL_LEN, 4000, 1)
tb.lvl_probe = _blocks.probe_signal_f()
tb.connect(tb.radio_source, tb.lvl_mag, tb.lvl_avg, tb.lvl_probe)
tb.start()
tb.apply_gain()
if a.gui:
    tb.show()

print(f"# {platform.system()} {platform.release()}, {os.cpu_count()} cpus, "
      f"{platform.processor() or platform.machine()}", flush=True)
print(f"# {cfg['frequency_mhz']} MHz, gain {cfg['gain_percent']}%, "
      f"audio {'on' if cfg['audio'] else 'off'}, gui {a.gui}, "
      f"timing probe {a.timing}", flush=True)
if GAINS:
    print(f"# gain {GAINS[0]:g}%: {R.rx_gain_plan(GAINS[0], cfg['radio_type'])}",
          flush=True)
print("#    t   cum%   win%  groups  blocks  drops%   cpu    tau   dtau    coh"
      "  rf dBFS  sync  PS / RT", flush=True)

state = {'t0': time.time(), 'blocks_ok': 0, 'blocks_seen': 0, 'groups': 0,
         'items': 0, 'cpu': sum(os.times()[:2]), 'wall': time.time()}


def tick():
    snap = tb.rds.snapshot()
    items = tb.rds.nitems_read(0)
    now_cpu, now_wall = sum(os.times()[:2]), time.time()
    dwall = now_wall - state['wall']
    dok = snap['blocks_ok'] - state['blocks_ok']
    dseen = snap['blocks_seen'] - state['blocks_seen']
    if dseen < 0:              # "Clear Decoded Data" zeroed the counters
        dok, dseen = snap['blocks_ok'], snap['blocks_seen']
    dropped = max(0.0, 1 - (items - state['items']) / (R.MPX_RATE * dwall)) * 100
    cum = 100 * snap['blocks_ok'] / max(1, snap['blocks_seen'])
    win = f"{100 * dok / dseen:5.1f}" if dseen else "   - "
    tau = tb.rds.demod.tau
    if a.timing:
        mag = np.abs(score)
        dtau = f"{OFFS[int(np.argmax(mag))]:+.3f}" if mag.any() else "   -  "
        c = f"{abs(coh[0]) / coh[1]:.3f}" if coh[1] else "  -  "
    else:
        dtau, c = "   -  ", "  -  "
    proto = tb.rds.proto
    lvl = tb.lvl_probe.level()
    rf = f"{10 * np.log10(lvl):7.1f}" if lvl > 0 else "     - "
    print(f"{now_wall - state['t0']:6.0f}  {cum:5.1f}  {win}  {snap['groups']:6d}"
          f"  {snap['blocks_seen']:6d}  {dropped:6.2f}  "
          f"{(now_cpu - state['cpu']) / dwall:4.2f}  "
          f"{('%.3f' % tau) if tau is not None else '  -  '}  {dtau}  {c}  "
          f"{rf}  "
          f"{'Y' if proto._synced else 'n'}{proto._miss}  "
          f"{snap['ps']!r} / {snap['radiotext'][:40]!r}", flush=True)
    state.update({k: snap[k] for k in ('blocks_ok', 'blocks_seen', 'groups')})
    state.update(items=items, cpu=now_cpu, wall=now_wall)
    score[:] = 0
    coh[0], coh[1] = 0j, 0.0


_rt_last = [None]


def rt_tick():
    snap = tb.rds.snapshot()
    now = ' - '.join(x for x in (snap['artist'], snap['title']) if x)
    line = (f"now={now!r} rt={snap['radiotext']!r} "
            f"clock={clock_text(snap['clock'])!r}")
    if line != _rt_last[0]:
        # Wall time too, so a clock change can be read against the real minute.
        print(f"[{time.time() - state['t0']:6.1f} {time.strftime('%H:%M:%S')}] "
              f"{line}", flush=True)
        _rt_last[0] = line


def finish():
    # Timers due at the same instant would otherwise still fire after
    # shutdown and print a window below the final line.
    poll.stop()
    rtpoll.stop()
    resetter.stop()
    tb.stop()
    tb.wait()
    snap = tb.rds.snapshot()
    print(f"# final {100 * snap['blocks_ok'] / max(1, snap['blocks_seen']):.1f}% "
          f"good over {snap['blocks_seen']} blocks", flush=True)


_gain_step = [0]


def reset_timing():
    if GAINS:
        _gain_step[0] += 1
        g = GAINS[_gain_step[0] % len(GAINS)]
        tb.set_gain(g)
        print(f"# gain {g:g}%: {R.rx_gain_plan(g, cfg['radio_type'])}", flush=True)
    tb.rds.reset(R.MPX_RATE, tb.region)
    score[:] = 0
    coh[0], coh[1] = 0j, 0.0
    print(f"# reset at {time.time() - state['t0']:.0f} s: decoded data cleared, "
          f"timing will be re-measured", flush=True)


resetter = Qt.QTimer()
if a.reset_every:
    resetter.timeout.connect(reset_timing)
    resetter.start(int(a.reset_every * 1000))
poll = Qt.QTimer()
poll.timeout.connect(tick)
poll.start(int(a.every * 1000))
rtpoll = Qt.QTimer()
if a.rt:
    rtpoll.timeout.connect(rt_tick)
    rtpoll.start(int(a.rt * 1000))
stop = Qt.QTimer()
stop.setSingleShot(True)
stop.timeout.connect(lambda: (finish(), app.quit()))
stop.start(int(a.minutes * 60 * 1000))
try:
    app.exec_()
except KeyboardInterrupt:
    finish()
