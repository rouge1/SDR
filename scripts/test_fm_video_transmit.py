#!/usr/bin/env python3
"""The FM video transmitter with no radio: each standard there and back.

    python scripts/test_fm_video_transmit.py
    python scripts/test_fm_video_transmit.py --video clip.mp4

What this pins down:

- **ITU-R F.405's curves are the ones built.** The recommendation gives its
  pre-emphasis as a formula with three constants per line standard and a
  table of what they produce. The digital filter has to land inside its
  tolerance at the radio's own rate, and 1 V at the crossover frequency
  has to swing the carrier 8 MHz peak to peak, as its note 1 says.
- **The FPV standard matches the RTC6705 datasheet** - subcarrier
  frequencies, their level against the carrier, the audio corner, the
  channel table - since that chip is what nearly every analog FPV
  transmitter is built on.
- **The signal fits the radio's rate**, which FM video, unlike NTSC, only
  just does - in NTSC and in PAL.
- **A picture and its sound survive the whole chain** for each standard and
  each format, decoded by the same decoder the receivers use.
- **FM has a threshold.** Below it the picture does not fade into snow the
  way AM does; it breaks up.
- **It keeps up with the air** at the radio's rate, in both formats.
"""
import argparse
import gc
import os
import subprocess
import sys
import tempfile
import time

import numpy as np
from scipy import signal as sps

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from fractions import Fraction  # noqa: E402

from gnuradio import analog, blocks, gr  # noqa: E402
from gnuradio import filter as gr_filter  # noqa: E402

from apps.fm_video_core import (F405_525, F405_625, FPV, RECEIVE_CUTOFF,  # noqa: E402
                                RELAY, VIDEO_CENTRE, click_threshold_hz,
                                compensation_band,
                                discriminator_compensation_taps,
                                fm_integrator_gain, fpv_channel_items,
                                instantaneous_frequency,
                                integrator_compensation_taps, preemphasis,
                                preemphasis_for, subcarrier_index)
from apps.fmVideoXmitter import (BASEBAND_SCALE, INTERPOLATOR_BW,  # noqa: E402
                                 RF_RATE, VIDEO_RATES, AudioConditioner,
                                 FmVideoModulator)
from apps.ntsc_decode import CompositeDecoder  # noqa: E402
from apps.ntsc_encode import NTSC, PAL, CompositeEncoder  # noqa: E402
from apps.ntsc_source import (AUDIO_RATE, AudioTrack, TestPattern,  # noqa: E402
                              VideoFile, colour_bars, has_audio, have_ffmpeg,
                              ntsc_source)

failures = []
TMP = tempfile.mkdtemp(prefix='fmvideo-')


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


# --- driving the app's own blocks ---------------------------------------------

def modulate(profile, video, n_out, audio48=None, rf_rate=RF_RATE,
             standard=NTSC, **kw):
    """Run ``FmVideoModulator`` on composite (or a constant) and return RF.

    ``audio48`` goes through the app's ``AudioConditioner``; without it the
    subcarriers go out unmodulated, as they do when the app sends silence.
    """
    video_rate = VIDEO_RATES[standard.key]
    path = os.path.join(TMP, 'rf.cf32')
    tb = gr.top_block("fm video", catch_exceptions=True)
    mod = FmVideoModulator(profile, rf_rate, video_rate, standard=standard, **kw)
    if np.isscalar(video):
        vsrc = analog.sig_source_f(video_rate, analog.GR_CONST_WAVE, 0, float(video), 0)
    else:
        vsrc = blocks.vector_source_f(np.asarray(video, np.float32).tolist(), False)
    if audio48 is None:
        asrc = analog.sig_source_f(rf_rate, analog.GR_CONST_WAVE, 0, 0, 0)
        tail = asrc
    else:
        asrc = blocks.vector_source_f(np.asarray(audio48, np.float32).tolist(), False)
        tail = AudioConditioner(profile.audio_tau, AUDIO_RATE, rf_rate)
        tb.connect(asrc, tail)
    head = blocks.head(gr.sizeof_gr_complex, int(n_out))
    sink = blocks.file_sink(gr.sizeof_gr_complex, path, False)
    tb.connect(vsrc, (mod, 0))
    tb.connect(tail, (mod, 1))
    tb.connect(mod, head, sink)
    tb.run()
    sink.close()
    rf = np.fromfile(path, dtype=np.complex64)
    os.remove(path)
    return rf


def lowpass(x, rate, cutoff, edge=0.4e6):
    """Zero-phase, raised-cosine edge - a measuring filter, not a design."""
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(x.size, 1 / rate)
    t = np.clip((f - (cutoff - edge / 2)) / edge, 0, 1)
    return np.fft.irfft(X * 0.5 * (1 + np.cos(np.pi * t)), x.size)


def to_video_rate(x, standard, rf_rate=RF_RATE):
    """From the radio's rate down to the format's video rate."""
    ratio = Fraction(VIDEO_RATES[standard.key] / rf_rate).limit_denominator(64)
    if ratio.numerator == 1:
        return x[::ratio.denominator]
    return sps.resample_poly(x, ratio.numerator, ratio.denominator)


def recover_composite(rf, profile, deviation_pp=None, preemphasis_key=None,
                      rf_rate=RF_RATE, standard=NTSC):
    """What a receiver does: discriminate, de-emphasise, filter, decimate."""
    dev = deviation_pp or profile.deviation_pp
    x = instantaneous_frequency(rf.astype(np.complex128), rf_rate) / dev
    x = np.convolve(x, discriminator_compensation_taps(
        rf_rate, compensation_band(standard.video_band)), mode='same')
    curve = preemphasis(preemphasis_for(
        profile.preemphasis if preemphasis_key is None else preemphasis_key,
        standard.lines))
    if curve is not None:
        b, a = curve.inverse_coefficients(rf_rate)
        x = sps.lfilter(b, a, x)
    x = lowpass(x, rf_rate, RECEIVE_CUTOFF[standard.key]) + VIDEO_CENTRE
    return to_video_rate(x, standard, rf_rate)


def filters_only(composite, standard=NTSC):
    """The composite through the video filters alone, with no FM at all.

    That is the transmitter's interpolator and the receiver's low pass. The
    encoder's colour bars switch from one bar to the next in a single
    sample, so they carry energy right up to the video rate's Nyquist that
    no real video path passes: compared against the untouched original,
    that alone reads 21 dB, and it read as a fault in the modulator until
    this separated the two. Measured against this, what is left is what FM
    does - and for a clean link it is nothing.
    """
    ratio = Fraction(RF_RATE / VIDEO_RATES[standard.key]).limit_denominator(64)
    tb = gr.top_block("filters only", catch_exceptions=True)
    src = blocks.vector_source_f(composite.astype(np.float32).tolist(), False)
    up = gr_filter.rational_resampler_fff(interpolation=ratio.numerator,
                                          decimation=ratio.denominator,
                                          taps=[], fractional_bw=INTERPOLATOR_BW)
    snk = blocks.vector_sink_f()
    tb.connect(src, up, snk)
    tb.run()
    x = lowpass(np.array(snk.data(), np.float64), RF_RATE,
                RECEIVE_CUTOFF[standard.key])
    return to_video_rate(x, standard)


def decode_bars(composite, standard=NTSC):
    dec = CompositeDecoder(VIDEO_RATES[standard.key], standard=standard)
    return dec.decode_frame(composite[composite.size // 6:])


def bar_errors(out, frame):
    width = frame.shape[1]
    worst = 0.0
    for k in range(7):
        col = (k * width // 7 + (k + 1) * width // 7) // 2
        got = out[100:140, col - 10:col + 10].mean(axis=(0, 1))
        worst = max(worst, float(np.abs(got - frame[100, col]).max()))
    return worst


def occupied_bandwidth(rf, rate, fraction=0.99):
    nfft = 1 << 14
    f, p = sps.welch(rf, fs=rate, nperseg=nfft, return_onesided=False)
    order = np.argsort(f)
    f, p = f[order], p[order]
    c = np.cumsum(p) / p.sum()
    lo = f[np.searchsorted(c, (1 - fraction) / 2)]
    hi = f[np.searchsorted(c, 1 - (1 - fraction) / 2)]
    return hi - lo


def _fractional(reference, recovered, lag, rate):
    """Cut both to where they overlap at ``lag``, then move ``recovered``
    the rest of the way by the fraction of a sample its phase says."""
    if lag >= 0:
        a, b = reference, recovered[lag:]
    else:
        a, b = reference[-lag:], recovered
    m = min(a.size, b.size)
    a, b = a[:m], b[:m]
    f = np.fft.rfftfreq(m, 1 / rate)
    A, B = np.fft.rfft(a - a.mean()), np.fft.rfft(b)
    # Low enough that even a sample and a half left over cannot wrap the
    # phase, high enough to hold plenty of the picture's energy.
    sel = (f > 0.2e6) & (f < 3.0e6)
    phase = np.angle(B[sel] * np.conj(A[sel]))
    weight = np.abs(A[sel]) ** 2
    delay = -np.sum(weight * phase * f[sel]) / np.sum(weight * f[sel] ** 2) / (2 * np.pi)
    b = np.fft.irfft(B * np.exp(2j * np.pi * f * delay), m)
    return a, b, lag + delay * rate


def align(reference, recovered, rate=VIDEO_RATES['ntsc'], max_lag=200, line=None):
    """Both signals cut to where they overlap, ``recovered`` moved onto
    ``reference``'s sample grid by whole *and* fractional samples.

    **Compare waveforms, not decoded pictures, to judge the transmitter.**
    The decoder's colour once moved with where in a buffer decoding started,
    and the chain's filters delay the signal by a fraction of a sample, so a
    decoded comparison measures the decoder as much as the link.

    **Find the whole-sample lag on the luma alone.** Colour bars are mostly
    chroma, and at 12.5 MS/s PAL's 4.43 MHz subcarrier is 2.8 samples a
    cycle, so a full-band correlation swings from 0.30 to 0.94 between
    neighbouring lags - and the chain's delay through its 8/5 resampling is
    a fraction of a sample, which no whole lag lands on. The best whole lag
    was then two lines away, and PAL bars read 24 dB where they are 88.
    Below 1.5 MHz the correlation peak is broad and does not swing.

    Luma repeats line after line, though, so in software, where the chain
    delays by tens of samples, only ``max_lag`` either way is searched -
    less than half a line. Off the air, where a capture starts anywhere,
    pass ``max_lag=None`` and the ``line`` length: the luma's best match is
    tried three lines either side too, and whichever leaves the smallest
    residual wins, because only one of them has the chroma the right way up.
    """
    a0 = lowpass(reference - reference.mean(), rate, 1.5e6)
    b0 = lowpass(recovered - recovered.mean(), rate, 1.5e6)
    corr = sps.correlate(b0, a0, mode='full', method='fft')
    lags = np.arange(corr.size) - (a0.size - 1)
    if max_lag is not None:
        near = np.abs(lags) <= max_lag
        lags, corr = lags[near], corr[near]
    coarse = int(lags[np.argmax(corr)])
    candidates = [coarse]
    if line is not None:
        candidates = [coarse + int(round(k * line)) for k in range(-3, 4)]
    best = None
    shorter = min(reference.size, recovered.size)
    for lag in candidates:
        # Skip a lag only if the two would barely overlap there. Off the air
        # a 5 ms segment sits anywhere inside a reference several frames
        # long, so its lag is routinely far bigger than the segment itself.
        overlap = (min(reference.size, recovered.size - lag) if lag >= 0
                   else min(reference.size + lag, recovered.size))
        if overlap < shorter // 2:
            continue
        a, b, where = _fractional(reference, recovered, lag, rate)
        trim = a.size // 20
        err = float(np.sqrt(np.mean((b - a - (b.mean() - a.mean()))[trim:-trim] ** 2)))
        if best is None or err < best[0]:
            best = (err, a, b, where)
    return best[1], best[2], best[3]


def picture_snr(reference, recovered, max_lag=200, standard=NTSC):
    """Peak-to-peak picture over rms error, across the video band, dB.

    A constant offset is taken out first: off the air it is only where the
    two radios' oscillators put the carrier, and the picture does not care.
    """
    rate = VIDEO_RATES[standard.key]
    a, b, _ = align(reference, recovered, rate=rate, max_lag=max_lag,
                    line=None if max_lag is not None else standard.line * rate)
    top = standard.video_band + 0.1e6
    a = lowpass(a, rate, top, edge=0.2e6)
    b = lowpass(b, rate, top, edge=0.2e6)
    b = b - (b.mean() - a.mean())
    trim = a.size // 20
    err = (b - a)[trim:-trim]
    return 20 * np.log10(1.0 / np.sqrt(np.mean(err ** 2))), a, b


# --- the checks -------------------------------------------------------------------

def check_f405():
    for curve, crossover, low, fc in ((F405_525, 0.7616, 2.530, 4.2e6),
                                      (F405_625, 1.512, 2.255, 5.0e6)):
        lines = curve.key.split('-')[1]
        print(f"\nITU-R F.405-1, {lines} lines, against its own Table 1")
        close("crossover frequency, MHz", curve.crossover_hz / 1e6, crossover, 0.0005)
        close("low-frequency deviation for 8 MHz at crossover, MHz p-p",
              8.0 * 10 ** (-curve.A / 20), low, 0.001)
        close("the curve is 0 dB at the crossover",
              float(curve.relative_db(curve.crossover_hz)), 0.0, 0.002)
        print(f"       one zero at {curve.zero_hz / 1e3:.1f} kHz, one pole at "
              f"{curve.pole_hz / 1e3:.1f} kHz")

        b, a = curve.coefficients(RF_RATE)
        f = np.geomspace(0.01e6, fc, 400)
        z = np.exp(-2j * np.pi * f / RF_RATE)
        got = 20 * np.log10(np.abs((b[0] + b[1] * z) / (a[0] + a[1] * z)))
        want = curve.relative_db(f)
        # Section 4 of the recommendation: +-(0.1 + 0.05 f/fc) dB, fc the top
        # of the video band.
        tolerance = 0.1 + 0.05 * f / fc
        worst = float(np.max(np.abs(got - want) / tolerance))
        print(f"       at the radio's rate the worst departure is "
              f"{np.max(np.abs(got - want)):.3f} dB, {worst * 100:.0f}% of what "
              f"F.405 allows there")
        check(f"the filter stays inside F.405's tolerance to {fc / 1e6:g} MHz",
              worst <= 1.0)
        bi, ai = curve.inverse_coefficients(RF_RATE)
        both = sps.lfilter(bi, ai, sps.lfilter(b, a, np.r_[1.0, np.zeros(4095)]))
        check("de-emphasis undoes it exactly",
              np.allclose(both, np.r_[1.0, np.zeros(4095)], atol=1e-9))

    check("choosing PAL turns an F.405 curve into its 625-line one, and back",
          preemphasis_for(F405_525.key, 625) == F405_625.key
          and preemphasis_for(F405_625.key, 525) == F405_525.key
          and preemphasis_for('none', 625) == 'none')

    b, a = F405_525.coefficients(RF_RATE)
    noise = np.random.default_rng(3).standard_normal(20000)
    tb = gr.top_block("iir", catch_exceptions=True)
    src = blocks.vector_source_f(noise.astype(np.float32).tolist(), False)
    iir = gr_filter.iir_filter_ffd(b, a, False)
    snk = blocks.vector_sink_f()
    tb.connect(src, iir, snk)
    tb.run()
    diff = float(np.abs(np.array(snk.data()) - sps.lfilter(b, a, noise)).max())
    check("GNU Radio's IIR block reads the taps the way scipy writes them",
          diff < 1e-4, f"largest difference {diff:.2e}")


def check_second_launch():
    """The clip's sound must survive the app being opened a second time.

    ``AudioTrack`` hands a pipe to ``blocks.file_descriptor_source``, which
    closes what it is given in its destructor - and ``AudioTrack.close``
    closes it too. Two owners, one descriptor, closed twice. The second
    close lands on whatever was opened in between, and what is opened in
    between is the *next* run of the same app: its pipe is handed the
    lowest free number, which is the one just released. So the sequence
    that breaks is launch, close, launch again, and it breaks the moment
    Python collects the first run's flowgraph - ``file_descriptor_source:
    error: [read]: Bad file descriptor``, and the second run goes out
    silent. Reported from TVAdemo, reproduced exactly, fixed by handing out
    a duplicate. The same pattern is in the NTSC and ATSC transmitters.
    """
    print("\nthe clip's sound survives a second launch")
    clip = os.path.join(TMP, 'two-seconds.mp4')
    made = subprocess.run(
        ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
         '-f', 'lavfi', '-i', 'testsrc=size=320x240:rate=30:duration=2',
         '-f', 'lavfi', '-i', 'sine=frequency=1000:duration=2',
         '-c:v', 'mpeg4', '-c:a', 'aac', '-shortest', clip],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if made.returncode != 0 or not has_audio(clip):
        print("  .. skipped: ffmpeg could not make a clip with sound here")
        return

    def one_run():
        track = AudioTrack(clip)
        tb = gr.top_block("second launch", catch_exceptions=True)
        src = blocks.file_descriptor_source(gr.sizeof_float,
                                            track.descriptor())
        head = blocks.head(gr.sizeof_float, AUDIO_RATE // 2)
        snk = blocks.vector_sink_f()
        tb.connect(src, head, snk)
        tb.run()
        return track, tb, (src, head, snk), len(snk.data())

    first, tb1, blocks1, got1 = one_run()
    check("the first launch reads the clip's sound", got1 > 0, f"{got1} samples")
    first.close()                                   # what closeEvent does
    second, tb2, blocks2, _ = AudioTrack(clip), None, None, 0
    # Build the second run's source *before* the first run's blocks are
    # collected, which is the order that used to pull the descriptor.
    tb2 = gr.top_block("second launch", catch_exceptions=True)
    src2 = blocks.file_descriptor_source(gr.sizeof_float, second.descriptor())
    head2 = blocks.head(gr.sizeof_float, AUDIO_RATE // 2)
    snk2 = blocks.vector_sink_f()
    tb2.connect(src2, head2, snk2)
    del tb1, blocks1
    gc.collect()
    time.sleep(0.2)
    tb2.run()
    got2 = len(snk2.data())
    second.close()
    print(f"  first launch {got1} samples, second {got2}")
    check("and so does the second, after the first has been collected",
          got2 > 0, f"{got2} samples - the descriptor was pulled")


def check_fpv_datasheet():
    print("\nthe FPV standard against the RTC6705 and RTC6715 datasheets")
    check("sound on 6.0 and 6.5 MHz", FPV.subcarriers == (6.0e6, 6.5e6))
    check("subcarrier level inside the -30 to -25 dBc the RTC6705 gives",
          -30 <= FPV.subcarrier_dbc <= -25, f"{FPV.subcarrier_dbc} dBc")
    close("audio pre-emphasis corner, kHz", 1 / (2 * np.pi * FPV.audio_tau) / 1e3,
          12.0, 1e-6)
    close("audio deviation, kHz", FPV.audio_deviation / 1e3, 25.0, 1e-9)
    # The one FPV number that is not the datasheet's, because the datasheet
    # has none: measured off air on 2026-09-16 from a real transmitter on
    # A3, 7.93 MHz peak to peak over 237 frames. The RTC6715's sensitivity
    # condition, +-2.5 MHz, is the only video deviation either document
    # mentions and it is not what a module actually does - see the FPV
    # profile's own note.
    close("video deviation, MHz p-p - measured, not from the datasheet",
          FPV.deviation_pp / 1e6, 7.93, 1e-9)
    items = {name: mhz for name, mhz, _ in fpv_channel_items()}
    check("forty channels", len(items) == 40, str(len(items)))
    for name, mhz in (('A1', 5865), ('A8', 5725), ('B1', 5733), ('E1', 5705),
                      ('E8', 5945), ('F4', 5800), ('R1', 5658), ('R8', 5917)):
        check(f"{name} is {mhz} MHz", items.get(name) == mhz, str(items.get(name)))
    check("the default channel is on the plan", FPV.default_mhz in items.values())

    beta = subcarrier_index(-27.5)
    print(f"       -27.5 dBc is a modulation index of {beta:.4f}: "
          f"{beta * 6.5:.3f} MHz peak deviation from the 6.5 MHz subcarrier")


def check_integrator():
    print("\na sampled FM modulator's running sum, and what undoes it")
    for f in (4.2e6, 6.0e6, 6.5e6, 6.8e6):
        print(f"       at {f / 1e6:g} MHz it swings the carrier "
              f"{20 * np.log10(fm_integrator_gain(f, RF_RATE)):+.2f} dB too far")
    for standard in (NTSC, PAL):
        band = compensation_band(standard.video_band)
        f = np.linspace(0, band, 200)
        w = 2 * np.pi * f / RF_RATE

        def response(taps):
            m = len(taps) // 2
            return np.array([taps[m] + 2 * sum(taps[m + k] * np.cos(k * wi)
                                               for k in range(1, m + 1)) for wi in w])
        gain = np.array([fm_integrator_gain(x, RF_RATE) for x in f])
        tx = response(integrator_compensation_taps(RF_RATE, band))
        rx = response(discriminator_compensation_taps(RF_RATE, band))
        worst_tx = float(np.abs(20 * np.log10(tx * gain)).max())
        worst_rx = float(np.abs(20 * np.log10(rx / gain)).max())
        check(f"{standard.key}: the transmitter's FIR leaves the true swing flat "
              f"to {band / 1e6:g} MHz", worst_tx < 0.02, f"within {worst_tx:.4f} dB")
        check(f"{standard.key}: and a receiver's FIR puts back what differencing "
              "phase loses", worst_rx < 0.02, f"within {worst_rx:.4f} dB")


def check_sidebands():
    print("\nthe subcarriers on the air, as a spectrum analyser would see them")
    for profile in (FPV, RELAY):
        # 1.8 M samples puts every subcarrier - all on 100 kHz steps - in the
        # middle of a bin, and the power is summed across the window's main
        # lobe, so nothing is read short by landing between two bins.
        rf = modulate(profile, VIDEO_CENTRE, 2_100_000)[300_000:]
        n = rf.size
        spec = np.abs(np.fft.fft(rf * np.blackman(n))) ** 2
        f = np.fft.fftfreq(n, 1 / RF_RATE)
        bin_hz = RF_RATE / n

        def peak(at):
            sel = np.abs(f - at) <= 5.5 * bin_hz
            return spec[sel].sum()
        carrier = peak(0.0)
        for sc in profile.subcarriers:
            for side in (+1, -1):
                dbc = 10 * np.log10(peak(side * sc) / carrier)
                close(f"{profile.key}: sideband at {side * sc / 1e6:+g} MHz, dBc",
                      dbc, profile.subcarrier_dbc, 0.5)


def check_deviation():
    print("\nhow far the picture swings the carrier")
    n = 400000
    for profile, standard, want, what in (
            (FPV, NTSC, FPV.deviation_pp, "sync tip to white, no pre-emphasis"),
            (RELAY, NTSC, 2.530e6, "1 V at low frequencies, F.405 525 lines"),
            (RELAY, PAL, 2.2544e6, "1 V at low frequencies, F.405 625 lines")):
        rate = VIDEO_RATES[standard.key]
        t = np.arange(int(n * rate / RF_RATE)) / rate
        square = (np.sin(2 * np.pi * 1000 * t) > 0).astype(np.float64)
        rf = modulate(profile, square, n, standard=standard)
        inst = lowpass(instantaneous_frequency(rf.astype(np.complex128), RF_RATE),
                       RF_RATE, 1.0e6)[n // 8:]
        pp = np.percentile(inst, 75) - np.percentile(inst, 25)
        close(f"{profile.key} {standard.key}: {what}, MHz p-p", pp / 1e6,
              want / 1e6, want / 1e6 * 0.02)

    # Note 1: a 1 V sine at the crossover swings the carrier 8 MHz.
    for curve, standard in ((F405_525, NTSC), (F405_625, PAL)):
        rate = VIDEO_RATES[standard.key]
        t = np.arange(int(n * rate / RF_RATE)) / rate
        fx = curve.crossover_hz
        sine = VIDEO_CENTRE + 0.5 * np.sin(2 * np.pi * fx * t)
        rf = modulate(RELAY, sine, n, standard=standard)
        inst = lowpass(instantaneous_frequency(rf.astype(np.complex128), RF_RATE),
                       RF_RATE, 2.5e6)[n // 8:]
        k = np.arange(inst.size) / RF_RATE
        amp = 2 * np.abs(np.mean(inst * np.exp(-2j * np.pi * fx * k)))
        close(f"f405 {standard.key}: 1 V at the {fx / 1e6:.3f} MHz crossover, "
              "MHz p-p (F.405 note 1)", 2 * amp / 1e6, 8.0, 0.16)


def check_bandwidth(frames):
    print("\nhow wide it is, and whether it fits the radio")
    tone = 0.9 * np.sin(2 * np.pi * 1000 * np.arange(int(AUDIO_RATE * 0.8)) / AUDIO_RATE)
    for standard in (NTSC, PAL):
        enc = CompositeEncoder(VIDEO_RATES[standard.key], standard=standard)
        composite = np.concatenate([enc.encode_frame(frames[standard.key])
                                    for _ in range(5)])
        for profile in (FPV, RELAY):
            # At 40 MS/s, where nothing folds, to see the signal's real width.
            wide = modulate(profile, composite, int(6.2e6), audio48=tone,
                            rf_rate=40e6, standard=standard)[int(0.8e6):]
            bw = occupied_bandwidth(wide, 40e6)
            print(f"       {profile.key} {standard.key}: 99% of the power inside "
                  f"{bw / 1e6:.1f} MHz")
            check(f"{profile.key} {standard.key} fits the {RF_RATE / 1e6:g} MS/s "
                  "the radio runs at", bw < 0.9 * RF_RATE,
                  f"{bw / 1e6:.1f} MHz of {0.9 * RF_RATE / 1e6:g}")


def check_picture(frames, clip=False):
    print("\na picture through the whole chain and back")
    clean = {}
    for standard in (NTSC, PAL):
        frame = frames[standard.key]
        enc = CompositeEncoder(VIDEO_RATES[standard.key], standard=standard)
        composite = np.concatenate([enc.encode_frame(frame) for _ in range(3)])
        reference = filters_only(composite, standard)
        n_out = int(composite.size * RF_RATE / VIDEO_RATES[standard.key]) - 4000
        for profile in (FPV, RELAY):
            label = f"{profile.key} {standard.key}"
            rf = modulate(profile, composite, n_out, standard=standard)
            check(f"{label}: the carrier's envelope is constant, as FM's is",
                  float(np.abs(rf[10000:]).std()) < 1e-3 * BASEBAND_SCALE)
            snr, a, b = picture_snr(reference, recover_composite(
                rf, profile, standard=standard), standard=standard)
            print(f"       {label}: recovered composite {snr:.1f} dB clear of "
                  "the original across the video band")
            check(f"{label}: the chain is transparent to the picture", snr > 40,
                  f"{snr:.1f} dB")
            # Decoded from the same first sample, the decoder's own quirks
            # fall out and what is left is the link.
            out_a, out_b = decode_bars(a, standard), decode_bars(b, standard)
            diff = float(np.abs(out_b - out_a).mean() if clip else
                         max(bar_errors(out_b, frame) - bar_errors(out_a, frame), 0.0))
            close(f"{label}: decoded picture, sent vs received", diff, 0.0, 0.01)
            if standard is NTSC:
                clean[profile.key] = (rf, reference)
    return clean


def check_threshold(clean):
    print("\nFM's threshold: add noise and watch the picture break, not fade")
    rf, composite = clean[FPV.key]
    rng = np.random.default_rng(7)
    power = float(np.mean(np.abs(rf) ** 2))
    legit = click_threshold_hz(FPV) - 3e6
    by = {}
    for cnr in (30, 25, 20, 15, 12, 10, 8, 6, 4):
        sigma = np.sqrt(power / 10 ** (cnr / 10) / 2)
        noisy = rf + sigma * (rng.standard_normal(rf.size)
                              + 1j * rng.standard_normal(rf.size))
        inst = instantaneous_frequency(noisy.astype(np.complex128), RF_RATE)
        # A click: the phase slips a whole turn and the discriminator throws
        # a spike far past anything the picture can swing to.
        clicks = int(np.sum(np.abs(inst) > legit + 3e6))
        per_frame = clicks / (rf.size / RF_RATE / NTSC.frame)
        snr, _, _ = picture_snr(composite, recover_composite(noisy, FPV))
        by[cnr] = (snr, per_frame)
        print(f"       {cnr:3d} dB carrier-to-noise in {RF_RATE / 1e6:g} MHz: "
              f"picture {snr:5.1f} dB, {per_frame:9.1f} clicks a frame")
    slope = (by[30][0] - by[20][0]) / 10
    check("above threshold a dB of carrier is a dB of picture",
          0.85 < slope < 1.15, f"{slope:.2f} dB per dB")
    check("no clicks at all from 15 dB up", by[15][1] == 0)
    # Below threshold the damage arrives as clicks - the white and black
    # sparkles of a weak FM picture - and they multiply about tenfold for
    # every 2 dB of carrier lost. An rms figure undercounts impulses, which
    # is why the picture SNR above strays only a few dB from its line.
    growth = [by[c][1] / max(by[c + 2][1], 1e-9) for c in (8, 6, 4)]
    check("below threshold clicks multiply as the carrier falls",
          by[10][1] > 0 and min(growth) > 3,
          "x" + ", x".join(f"{g:.0f}" for g in growth) + " per 2 dB")
    fall = (by[12][0] - by[4][0]) - (12 - 4)
    check("and the picture falls faster than the carrier does", fall > 1.0,
          f"{fall:.1f} dB more than linear between 12 and 4 dB")


def check_sound(path):
    print("\nthe clip's own sound on every subcarrier")
    if not has_audio(path):
        check("the clip has a soundtrack", False)
        return
    seconds = 1.2
    track = AudioTrack(path)
    want = int(AUDIO_RATE * (seconds + 2.0)) * 4
    raw = b''
    while len(raw) < want:
        piece = os.read(track.fileno(), 1 << 16)
        if not piece:
            break
        raw += piece
    track.close()
    audio = np.frombuffer(raw[:len(raw) // 4 * 4], np.float32).astype(np.float64)
    audio = audio[int(AUDIO_RATE * 2.0):]      # past the clip's opening second or two
    source = audio[:int(AUDIO_RATE * seconds)]
    for profile in (FPV, RELAY):
        rf = modulate(profile, VIDEO_CENTRE, int(RF_RATE * (seconds - 0.05)),
                      audio48=source)
        inst = instantaneous_frequency(rf.astype(np.complex128), RF_RATE)
        del rf
        n = np.arange(inst.size)
        for sc in profile.subcarriers:
            base = sps.resample_poly(inst * np.exp(-2j * np.pi * sc * n / RF_RATE), 1, 100)
            if_rate = RF_RATE / 100
            dev = instantaneous_frequency(base, if_rate)
            peak = np.percentile(np.abs(dev[2000:-2000]), 99.99)
            heard = sps.resample_poly(dev / profile.audio_deviation, 6, 25)
            tb = gr.top_block("deemph", catch_exceptions=True)
            src = blocks.vector_source_f(heard.astype(np.float32).tolist(), False)
            de = analog.fm_deemph(float(AUDIO_RATE), profile.audio_tau)
            snk = blocks.vector_sink_f()
            tb.connect(src, de, snk)
            tb.run()
            heard = np.array(snk.data(), np.float64)
            skip = int(0.15 * AUDIO_RATE)
            sent = np.clip(source, -1, 1)[skip:heard.size]
            got = heard[skip:]
            got = got[:sent.size]
            a, b = sent - sent.mean(), got - got.mean()
            corr = sps.correlate(b, a, mode='full', method='fft')
            lag = int(np.argmax(corr)) - (a.size - 1)
            if lag >= 0:
                x, y = a[:a.size - lag], b[lag:]
            else:
                x, y = a[-lag:], b[:b.size + lag]
            score = float((x * y).sum() / np.sqrt((x * x).sum() * (y * y).sum()))
            print(f"       {profile.key} {sc / 1e6:g} MHz: peak deviation "
                  f"{peak / 1e3:.1f} kHz, lag {lag / AUDIO_RATE * 1e3:+.2f} ms")
            check(f"{profile.key}: the {sc / 1e6:g} MHz subcarrier carries the "
                  "clip's sound", score > 0.98, f"correlation {score:.4f}")
            check(f"{profile.key}: its deviation stays inside "
                  f"{profile.audio_deviation / 1e3:g} kHz",
                  peak <= profile.audio_deviation * 1.03, f"{peak / 1e3:.1f} kHz")


def check_speed(video=None):
    print("\nkeeping up with the air")
    runs = []
    for standard in (NTSC, PAL):
        runs.append((f"{standard.key} colour bars", standard,
                     lambda s=standard: TestPattern(s.width, s.height)))
        if video:
            runs.append((f"{standard.key} clip", standard,
                         lambda s=standard: VideoFile(video, s.width, s.height,
                                                      frame_rate=s.frame_rate)))
    for label, standard, make in runs:
        rate = VIDEO_RATES[standard.key]
        src = ntsc_source(make(), rate, standard=standard)
        tone = analog.sig_source_f(AUDIO_RATE, analog.GR_SIN_WAVE, 1000, 0.5, 0)
        cond = AudioConditioner(FPV.audio_tau, AUDIO_RATE)
        mod = FmVideoModulator(FPV, RF_RATE, rate, standard=standard)
        pace = blocks.throttle(gr.sizeof_gr_complex, RF_RATE)
        sink = blocks.null_sink(gr.sizeof_gr_complex)
        tb = gr.top_block("paced", catch_exceptions=True)
        tb.connect(src, (mod, 0))
        tb.connect(tone, cond, (mod, 1))
        tb.connect(mod, pace, sink)
        tb.start()
        time.sleep(2.0)
        warm = src.repeats
        n0, t0 = sink.nitems_read(0), time.time()
        time.sleep(5.0)
        speed = (sink.nitems_read(0) - n0) / (time.time() - t0)
        steady = src.repeats - warm
        tb.stop()
        tb.wait()
        print(f"       {label}: {speed / RF_RATE:.3f}x the radio's rate with the "
              f"throttle on, on {src.workers} encoder threads, {steady} repeated "
              "frames after warm-up")
        check(f"{label}: the whole chain keeps pace with {RF_RATE / 1e6:g} MS/s",
              speed > 0.97 * RF_RATE, f"{speed / 1e6:.2f} MS/s")
        check(f"{label}: the encoder never has to repeat a frame", steady == 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--video', help='a clip to send instead of bars')
    ap.add_argument('--skip-speed', action='store_true')
    args = ap.parse_args()

    check_f405()
    check_fpv_datasheet()
    check_second_launch()
    check_integrator()
    check_sidebands()
    check_deviation()

    clip = bool(args.video and have_ffmpeg())
    frames = {}
    for standard in (NTSC, PAL):
        frames[standard.key] = colour_bars(standard.width, standard.height)
        if clip:
            src = VideoFile(args.video, standard.width, standard.height,
                            frame_rate=standard.frame_rate)
            for _ in range(90):
                frames[standard.key] = src.next_frame()
            src.close()
    check_bandwidth(frames)
    clean = check_picture(frames, clip)
    if not clip:
        check_threshold(clean)
    if clip:
        check_sound(args.video)
    if not args.skip_speed:
        check_speed(args.video if clip else None)

    print()
    if failures:
        print(f"{len(failures)} FAILED: {', '.join(failures)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
