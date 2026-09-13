#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Signal Hound BB60D as a live GNU Radio source.

The BB60D is a SoapySDR device, but it cannot be driven through
``gr-soapy``: ``soapy.source(...)`` constructs, and then *every* setter -
``set_frequency``, ``set_gain``, ``set_sample_rate`` - fails with
``setupStream: Invalid format ''``. So this wraps the raw SoapySDR Python
binding as a ``gr.sync_block`` instead, in the same spirit as
``apps/vsg_sink.py`` wrapping the VSG's vendor C API.

Four things about this device that are not like the others:

- **``setupStream`` comes before configuration, not after.** Set the rate or
  the frequency on a device whose stream has not been set up and the module
  reports the format as empty and nothing works afterwards.
- **It is opened by driver name alone.** ``driver=SignalHoundBB60`` opens
  it; the same arguments ``enumerate()`` hands back - serial, label,
  device_id - are refused, one with "no match" and one with "device_id is
  not a number".
- **Its module is a system one.** It lives in ``/usr/local/lib/SoapySDR``
  rather than inside the conda environment, so ``SOAPY_SDR_PLUGIN_PATH``
  has to point at it. The ABI matches (both 0.8), so the conda binding
  loads the system module quite happily once it can find it.
- **Its rates are a ladder**: 40, 20, 10, 5, 2.5 MS/s and on down in
  halves. Nothing in between, so a flowgraph picks one off the ladder and
  resamples. At 10 MS/s the analog filter is 8 MHz, which is what makes it
  usable for a 6 MHz television channel.

Gain is two elements, an attenuator and an RF stage, presented as one
0-100% control like every other radio here.
"""

import glob
import os
import sys
import threading

import numpy as np
from gnuradio import gr  # type: ignore

DRIVER = 'SignalHoundBB60'
#: The rates the hardware actually has. Anything else is refused.
SAMPLE_RATES = [40e6, 20e6, 10e6, 5e6, 2.5e6, 1.25e6, 625e3, 312.5e3]
#: Gain elements, in the order the slider should open them up: take the
#: attenuator off first, because attenuation costs noise figure outright,
#: and only then start adding RF gain.
GAIN_STAGES = [('ATT', -30.0, 0.0), ('RF', 0.0, 20.0)]
GAIN_SPAN = sum(high - low for _, low, high in GAIN_STAGES)   # 50 dB

# Messages the vendor module prints on every ordinary retune. They are
# logged at ERROR, which they are not - the frequency reads back correctly
# afterwards - and they scroll a terminal several lines per second.
_EXPECTED_CHATTER = ('ConfigureIQCenter', 'ConfigureIO', 'Using format',
                     'set decimation', 'deprecrated')
_overflows = [0]
_last_message = ['']


def _log_handler(level, text):
    """Count real problems, drop the noise, pass anything else on.

    The ADC overflowing is the one message that matters and the only sign
    of it: the samples that come back are filtered and decimated, so a
    front end being driven into the converter does *not* show up as
    clipping in what the flowgraph sees. Without this it is an ERROR line
    in a terminal nobody is looking at.
    """
    message = str(text).strip()
    if 'overflow' in message.lower():
        _overflows[0] += 1
        _last_message[0] = message
        return
    if any(k in message for k in _EXPECTED_CHATTER):
        return
    print(f"BB60: {message}", file=sys.stderr)


def install_log_handler():
    try:
        import SoapySDR  # type: ignore
        SoapySDR.registerLogHandler(_log_handler)
        return True
    except Exception:
        return False


def overflow_count():
    """How many times the converter has been overdriven since reset."""
    return _overflows[0]


def reset_overflows():
    _overflows[0] = 0
    _last_message[0] = ''

_MODULE_DIRS = [
    '/usr/local/lib/SoapySDR/modules0.8',
    '/usr/lib/x86_64-linux-gnu/SoapySDR/modules0.8',
    '/usr/local/lib/SoapySDR/modules*',
    '/usr/lib/*/SoapySDR/modules*',
]


def ensure_plugin_path():
    """Put the system SoapySDR module directory on the plugin path.

    SoapySDR reads ``SOAPY_SDR_PLUGIN_PATH`` when it first loads modules,
    which is on the first enumerate, so setting it here is in time even
    though ``SoapySDR`` may already be imported. Whatever is already in the
    variable is kept ahead of what we add.
    """
    paths = [p for p in os.environ.get('SOAPY_SDR_PLUGIN_PATH', '').split(':')
             if p]
    for pattern in _MODULE_DIRS:
        for path in sorted(glob.glob(pattern), reverse=True):
            # The patterns deliberately overlap - an exact directory and a
            # glob that also matches it - so duplicates have to be dropped
            # here, or the variable grows every time this is called.
            if (path not in paths and os.path.isdir(path)
                    and glob.glob(os.path.join(path, '*BB60*'))):
                paths.append(path)
    if paths:
        os.environ['SOAPY_SDR_PLUGIN_PATH'] = ':'.join(paths)
    return paths


def gain_plan(percent):
    """Map 0-100% onto the attenuator and the RF stage, in that order.

    **The level falls as this rises, and that is correct.** Measured on a
    real broadcaster against an empty channel, which is the only way to see
    it - raw level says the opposite:

    ======  ====  ==========  ==========
    ATT     RF    level       SNR
    ======  ====  ==========  ==========
    -30     0     -56.5 dBFS   -0.1 dB
    -20     0     -61.4 dBFS    0.0 dB
    -10     0     -69.9 dBFS    1.2 dB
      0     0     -74.0 dBFS    4.7 dB
      0    20     -74.5 dBFS    6.6 dB
    ======  ====  ==========  ==========

    Winding the attenuator stage negative adds 18 dB of level and *all* of
    it is noise. So the slider opens the attenuator toward 0 first and only
    then adds RF, which makes it monotone in signal-to-noise even though
    the input level meter goes the other way.

    The last 20 dB of RF is worth under 2 dB of SNR and is front-end
    amplification, which is what overdrives the converter on a strong local
    signal - so a high setting is the first thing to wind back if
    ``overflow_count()`` starts climbing, and it costs almost nothing.
    """
    percent = min(max(float(percent), 0.0), 100.0)
    budget = percent / 100.0 * GAIN_SPAN
    plan = {}
    for name, low, high in GAIN_STAGES:
        take = min(high - low, budget)
        plan[name] = low + take
        budget -= take
    return plan


def nearest_rate(rate):
    """The rate on the hardware's ladder closest to what was asked for."""
    return min(SAMPLE_RATES, key=lambda r: abs(r - float(rate)))


def find_devices():
    """Every BB60 the machine can see, as dicts. Empty if none or no module.

    ``enumerate`` hands back ``SoapySDRKwargs``, a SWIG map proxy with no
    ``get`` - it has to be turned into a dict before it can be read like
    one. Getting that wrong once cost an afternoon, because the exception
    it raises looks exactly like no device being plugged in.
    """
    ensure_plugin_path()
    try:
        import SoapySDR  # type: ignore
        devices = [dict(d) for d in SoapySDR.Device.enumerate()]
    except Exception as exc:
        print(f"BB60: could not enumerate SoapySDR devices: {exc}",
              file=sys.stderr)
        return []
    return [d for d in devices
            if DRIVER.lower() in str(d.get('driver', '')).lower()]


def is_available():
    """True if the SoapySDR module for this device can be found at all."""
    ensure_plugin_path()
    try:
        import SoapySDR  # type: ignore
        return any('BB60' in m for m in SoapySDR.listModules())
    except Exception:
        return False


class bb60_source(gr.sync_block):
    """Complex baseband from a BB60D.

    The device is opened in ``start()`` and closed in ``stop()``, so the
    block can be built before anything is plugged in and so the device is
    released the moment the flowgraph ends.

    **Every call into the vendor module is made from the work thread.**
    ``set_center_freq`` and ``set_gain_percent`` are called from the Qt
    thread while ``work`` is parked inside ``readStream``; rather than
    serialise on a lock and make the GUI wait up to a read timeout, they
    leave the new value behind and ``work`` applies it before its next
    read. Nothing else touches the device, so there is nothing to race.
    """

    #: How long readStream may wait. Long enough that an idle flowgraph is
    #: not a spin loop, short enough that a pending retune lands promptly.
    TIMEOUT_US = 200000

    def __init__(self, center_freq, sample_rate, gain_percent=60.0):
        gr.sync_block.__init__(self, name='bb60_source', in_sig=None,
                               out_sig=[np.complex64])
        self.center_freq = float(center_freq)
        self.sample_rate = nearest_rate(sample_rate)
        self.gain_percent = float(gain_percent)
        self.overflows = 0
        self._sdr = None
        self._stream = None
        self._lock = threading.Lock()
        self._pending = {}

    # -- lifecycle -------------------------------------------------------

    def start(self):
        ensure_plugin_path()
        install_log_handler()
        reset_overflows()
        import SoapySDR  # type: ignore
        from SoapySDR import SOAPY_SDR_RX, SOAPY_SDR_CF32  # type: ignore

        if not find_devices():
            raise RuntimeError(
                "No Signal Hound BB60 was found on USB. Check it is "
                "connected, and that no other application - Sceptre, or "
                "another flowgraph - already has it open.")
        # Opened by driver name alone: the arguments enumerate() returns
        # are refused, serial with "no match" and the whole dict with
        # "device_id is not a number".
        self._sdr = SoapySDR.Device(f"driver={DRIVER}")
        # Before configuration, not after - see the module docstring.
        self._stream = self._sdr.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32)
        self._configure(center_freq=self.center_freq,
                        sample_rate=self.sample_rate,
                        gain_percent=self.gain_percent)
        self._sdr.activateStream(self._stream)
        return True

    def stop(self):
        sdr, stream, self._sdr, self._stream = self._sdr, self._stream, None, None
        if sdr is not None and stream is not None:
            try:
                sdr.deactivateStream(stream)
                sdr.closeStream(stream)
            except Exception as exc:
                print(f"BB60 source: error closing the stream: {exc}",
                      file=sys.stderr)
        return True

    # -- settings --------------------------------------------------------

    def set_center_freq(self, hz):
        self.center_freq = float(hz)
        with self._lock:
            self._pending['center_freq'] = self.center_freq

    def set_gain_percent(self, percent):
        self.gain_percent = float(percent)
        with self._lock:
            self._pending['gain_percent'] = self.gain_percent

    def set_sample_rate(self, rate):
        self.sample_rate = nearest_rate(rate)
        with self._lock:
            self._pending['sample_rate'] = self.sample_rate

    # The UHD and Soapy setter idioms, so this drops into an app that
    # branches on radio type without a fourth branch everywhere.
    def set_frequency(self, _chan, hz):
        self.set_center_freq(hz)

    def set_samp_rate(self, rate):
        self.set_sample_rate(rate)

    def _configure(self, **values):
        from SoapySDR import SOAPY_SDR_RX  # type: ignore
        if 'sample_rate' in values:
            self._sdr.setSampleRate(SOAPY_SDR_RX, 0, values['sample_rate'])
        if 'center_freq' in values:
            # The module logs "ERROR ConfigureIQCenter: <hz>" for every
            # successful retune; the frequency reads back correctly after
            # it. It is a log level, not a failure.
            self._sdr.setFrequency(SOAPY_SDR_RX, 0, values['center_freq'])
        if 'gain_percent' in values:
            for name, value in gain_plan(values['gain_percent']).items():
                self._sdr.setGain(SOAPY_SDR_RX, 0, name, value)

    # -- streaming -------------------------------------------------------

    def work(self, input_items, output_items):
        if self._sdr is None or self._stream is None:
            return -1                      # nothing to read from; end cleanly

        with self._lock:
            pending, self._pending = self._pending, {}
        if pending:
            try:
                self._configure(**pending)
            except Exception as exc:
                print(f"BB60 source: could not apply {sorted(pending)}: {exc}",
                      file=sys.stderr)

        out = output_items[0]
        status = self._sdr.readStream(self._stream, [out], len(out),
                                      timeoutUs=self.TIMEOUT_US)
        if status.ret > 0:
            return status.ret
        if status.ret == -4:               # SOAPY_SDR_OVERFLOW - samples lost
            self.overflows += 1
        return 0

    def adc_overflows(self):
        """Times the converter has been overdriven - a gain problem, not a
        dropped-sample one, and invisible in the samples themselves."""
        return overflow_count()
