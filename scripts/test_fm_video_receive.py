#!/usr/bin/env python3
"""The FM video receiver against the FM video transmitter, no radio at all.

    python scripts/test_fm_video_receive.py
    python scripts/test_fm_video_receive.py --quick

``test_fm_video_transmit.py`` checks the transmitter against a numpy model
of a receiver. This checks the *app's own* receiving blocks against the
app's own transmitting ones, which is the pair that actually runs, and it
concentrates on the thing the receiver exists for beyond showing a picture:

- **it measures the deviation it was not told**, off the one step the
  television standard fixes, so a transmitter whose datasheet does not give
  one can be read rather than guessed at;
- **and it measures the pre-emphasis**, off the colour burst, which is the
  other FPV number nobody publishes;
- **a wrong deviation setting does not cost the picture**, because the
  decoder scales itself - which is what makes the two measurements above
  usable against an unknown transmitter in the first place;
- **a wrong pre-emphasis does**, and shows up as exactly the tilt it is;
- **the format is named when it is the other one**, since nothing on the
  air says whether an FPV camera is NTSC or PAL;
- **the sound comes back off every subcarrier**, at the level the profile
  puts it on the air.
"""
import argparse
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from gnuradio import blocks, gr  # noqa: E402

from apps.fm_video_core import FPV, RELAY, preemphasis_for  # noqa: E402
from apps.fmVideoReceiver import (AUDIO_RATE, FmVideoDemod,  # noqa: E402
                                  FmVideoFrameSink, FmVideoSound,
                                  click_level, format_mismatch,
                                  link_quality_chain)
from apps.fmVideoXmitter import RF_RATE, VIDEO_RATES  # noqa: E402
from apps.ntsc_encode import NTSC, PAL, CompositeEncoder  # noqa: E402
from apps.ntsc_source import colour_bars  # noqa: E402
import test_fm_video_transmit as T  # noqa: E402

failures = []


def check(name, ok, detail=''):
    print(f"  {'ok  ' if ok else 'FAIL'} {name}{'  ' + detail if detail else ''}",
          flush=True)
    if not ok:
        failures.append(name)


def close(name, got, want, tol, unit=''):
    ok = got is not None and abs(got - want) <= tol
    shown = 'none' if got is None else f"{got:.6g}{unit}"
    print(f"  {'ok  ' if ok else 'FAIL'} {name}: {shown}", flush=True)
    if not ok:
        print(f"       wanted {want:.6g}{unit} +/- {tol:g}{unit}")
        failures.append(name)


# --- driving the app's own receiving blocks ----------------------------------

def demodulate(rf, profile, standard, deviation_pp=None, preemphasis_key=None):
    """Through ``FmVideoDemod``: composite at the video rate, and the baseband."""
    tb = gr.top_block("fm video rx", catch_exceptions=True)
    demod = FmVideoDemod(profile, standard, RF_RATE, deviation_pp,
                         preemphasis_key)
    src = blocks.vector_source_c(np.asarray(rf, np.complex64).tolist(), False)
    composite = blocks.vector_sink_f()
    baseband = blocks.vector_sink_f()
    tb.connect(src, demod)
    tb.connect((demod, 0), composite)
    tb.connect((demod, 1), baseband)
    tb.run()
    return (np.array(composite.data(), np.float64),
            np.array(baseband.data(), np.float64), demod)


def measured(composite, standard, deviation_pp, dc_gain):
    """What the running window's Measured box would show for this buffer.

    Straight through ``FmVideoFrameSink._decode``, the method the decode
    thread calls, so this is the code that runs and not a copy of it.
    """
    sink = FmVideoFrameSink(VIDEO_RATES[standard.key], standard,
                            deviation_pp, dc_gain)
    sink._decode(np.asarray(composite, np.float64))
    return sink


def rf_source(rf, name='rf.cf32'):
    """A file source for a long capture.

    ``vector_source_c`` wants a Python list, and a third of a second at
    20 MS/s is six and a half million complex numbers - hundreds of
    megabytes of objects to build and hold. Through a file it is 50 MB on
    disk and nothing in the interpreter.
    """
    path = os.path.join(T.TMP, name)
    np.asarray(rf, np.complex64).tofile(path)
    return blocks.file_source(gr.sizeof_gr_complex, path, False)


def bars_rf(profile, standard, frames=4, audio48=None, **kw):
    """Colour bars through the transmitter's own modulator."""
    rate = VIDEO_RATES[standard.key]
    enc = CompositeEncoder(rate, standard=standard)
    picture = colour_bars(standard.width, standard.height)
    video = np.concatenate([enc.encode_frame(picture) for _ in range(frames)])
    n_out = int(video.size * RF_RATE / rate)
    return T.modulate(profile, video, n_out, audio48=audio48,
                      standard=standard, **kw)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--quick', action='store_true',
                        help="FPV in NTSC only, and no sound")
    args = parser.parse_args(argv)

    combinations = [(FPV, NTSC)] if args.quick else [
        (FPV, NTSC), (FPV, PAL), (RELAY, NTSC), (RELAY, PAL)]

    for profile, standard in combinations:
        name = f"{profile.key.upper()} in {standard.key.upper()}"
        print(f"\n{name}: the picture, and the numbers read off it")
        key = preemphasis_for(profile.preemphasis, standard.lines)
        rf = bars_rf(profile, standard)
        composite, baseband, demod = demodulate(rf, profile, standard)
        sink = measured(composite, standard, profile.deviation_pp,
                        demod.dc_gain())
        status = sink.status
        check("a frame decodes", sink.frames_decoded == 1 and sink.failures == 0,
              f"{sink.frames_decoded} decoded, {sink.failures} failed")
        close("line rate, Hz", status.get('line_rate'), standard.line_rate,
              1.0)
        # The measurement this receiver exists for.
        close("video deviation, MHz p-p", status.get('deviation_pp', 0) / 1e6,
              profile.deviation_pp / 1e6, 0.02 * profile.deviation_pp / 1e6)
        # Tens of kilohertz, not kilohertz: the offset is read off the
        # sync tip against the measured deviation, so a 1% error in that
        # swing moves it by 25 kHz. See FmVideoFrameSink.measure.
        close("carrier offset, Hz", status.get('carrier_offset'), 0.0, 40e3)
        close("response at the colour subcarrier, dB",
              20 * np.log10(status['burst']) if status.get('burst') else None,
              0.0, 0.5)
        if sink.frame is not None:
            worst = T.bar_errors(sink.frame,
                                 colour_bars(standard.width, standard.height))
            close("worst colour-bar error", worst, 0.0, 0.10)

        print(f"{name}: tuned 200 kHz off")
        # Reading the offset is where the de-emphasis has to be undone: the
        # transmitter sends low frequencies A dB down and the receiver puts
        # them back, so an offset arrives out of the de-emphasis 10 or 11 dB
        # bigger than it was on the air. Get that backwards and an F.405
        # link reads three times its real error.
        away = 200e3
        n = np.arange(rf.size)
        moved = (np.asarray(rf, np.complex128)
                 * np.exp(2j * np.pi * away * n / RF_RATE)).astype(np.complex64)
        composite_o, _, demod_o = demodulate(moved, profile, standard)
        sink_o = measured(composite_o, standard, profile.deviation_pp,
                          demod_o.dc_gain())
        close("the offset reads what was injected, Hz",
              sink_o.status.get('carrier_offset'), away, 40e3)
        check("and the picture is unharmed by it",
              sink_o.frames_decoded == 1 and sink_o.failures == 0,
              f"{sink_o.frames_decoded} decoded, {sink_o.failures} failed")

        print(f"{name}: told the wrong deviation")
        # Half the real deviation: the discriminator's output is twice as
        # big, and the decoder scales it away. What must not happen is a
        # lost picture, and what must happen is that the measurement still
        # reads what the transmitter really does.
        wrong = profile.deviation_pp / 2
        composite_w, _, demod_w = demodulate(rf, profile, standard,
                                             deviation_pp=wrong)
        sink_w = measured(composite_w, standard, wrong, demod_w.dc_gain())
        check("the picture decodes anyway", sink_w.frames_decoded == 1,
              f"{sink_w.frames_decoded} decoded, {sink_w.failures} failed")
        close("and the deviation still reads the transmitter's, MHz p-p",
              sink_w.status.get('deviation_pp', 0) / 1e6,
              profile.deviation_pp / 1e6, 0.02 * profile.deviation_pp / 1e6)
        if sink_w.frame is not None:
            worst = T.bar_errors(sink_w.frame,
                                 colour_bars(standard.width, standard.height))
            close("and the colour is unharmed", worst, 0.0, 0.10)

        print(f"{name}: told the wrong pre-emphasis")
        # The one that is not forgiven. Swapping the curve for the other
        # answer tilts the response, and the burst is where it shows.
        other = 'none' if key != 'none' else preemphasis_for(
            'f405-525', standard.lines)
        composite_p, _, demod_p = demodulate(rf, profile, standard,
                                             preemphasis_key=other)
        try:
            sink_p = measured(composite_p, standard, profile.deviation_pp,
                              demod_p.dc_gain())
            burst = sink_p.status.get('burst')
            tilt = 20 * np.log10(burst) if burst else 0.0
            check("the burst shows the tilt a matched curve did not",
                  abs(tilt) > 3.0, f"{tilt:+.2f} dB against +0.00 matched")
        except ValueError as exc:
            # The stronger outcome, and the honest one for a transmitter
            # that pre-emphasised: without the matching de-emphasis the low
            # frequencies arrive A dB down, which is the sync pulses, so
            # there is nothing to lock to at all.
            check("the picture will not decode at all, which is the whole "
                  "point of getting this one right", True, f"({exc})")

    print("\nthe sound, off every subcarrier the standard has")
    for profile, standard in ([(FPV, NTSC)] if args.quick else
                              [(FPV, NTSC), (RELAY, PAL)]):
        if args.quick:
            break
        tone_hz = 1000.0
        seconds = 0.25
        n = int(AUDIO_RATE * seconds)
        tone = 0.5 * np.sin(2 * np.pi * tone_hz * np.arange(n) / AUDIO_RATE)
        frames = int(np.ceil(seconds / standard.frame)) + 1
        rf = bars_rf(profile, standard, frames=frames, audio48=tone)
        _composite, baseband, _demod = demodulate(rf, profile, standard)
        for freq in profile.subcarriers:
            tb = gr.top_block("sound", catch_exceptions=True)
            src = blocks.vector_source_f(
                np.asarray(baseband, np.float32).tolist(), False)
            sound = FmVideoSound(profile, freq, RF_RATE, AUDIO_RATE,
                                 volume=1.0)
            snk = blocks.vector_sink_f()
            tb.connect(src, sound, snk)
            tb.run()
            heard = np.array(snk.data(), np.float64)
            # Skip the filters' warm-up, then read the tone's own amplitude
            # at its own frequency, so noise cannot flatter it.
            heard = heard[int(0.05 * AUDIO_RATE):]
            if heard.size < 2000:
                check(f"{freq / 1e6:g} MHz subcarrier produced audio", False,
                      f"{heard.size} samples")
                continue
            k = np.arange(heard.size)
            phasor = np.exp(-2j * np.pi * tone_hz * k / AUDIO_RATE)
            amplitude = 2 * abs(np.mean(heard * phasor))
            rest = np.sqrt(max(np.mean(heard ** 2) - amplitude ** 2 / 2, 0))
            print(f"  {profile.key} {freq / 1e6:g} MHz: {amplitude:.4f} at "
                  f"{tone_hz:g} Hz, everything else {rest:.4f}")
            close(f"{profile.key} {freq / 1e6:g} MHz subcarrier: the tone, "
                  "the size it was sent", amplitude, 0.5, 0.05)
            close(f"{profile.key} {freq / 1e6:g} MHz subcarrier: its sideband "
                  "level, dBc", sound.sidebands_dbc(profile.deviation_pp),
                  profile.subcarrier_dbc, 0.5)

    print("\nnaming the format when it is the other one")
    for standard, other in ((NTSC, PAL), (PAL, NTSC)):
        check(f"{standard.key.upper()} set, {standard.key.upper()} arriving: "
              "nothing said",
              format_mismatch(standard.line_rate, standard) is None)
        check(f"{standard.key.upper()} set, {other.key.upper()} arriving: "
              f"says {other.key.upper()}",
              format_mismatch(other.line_rate, standard) == other.key)
        # A real transmitter is a few parts per million off, not 0.7%.
        check(f"{standard.key.upper()} a few ppm off is still "
              f"{standard.key.upper()}",
              format_mismatch(standard.line_rate * 1.00002, standard) is None)
    check("no signal names nothing", format_mismatch(0.0, NTSC) is None)

    print("\nwhat counts as a click")
    for profile in (FPV, RELAY):
        level = click_level(profile, profile.deviation_pp)
        # A discriminator that differences phase cannot read past half the
        # sample rate, so a threshold above that can never be crossed and
        # the count reads zero however badly the link is breaking up.
        ceiling = (RF_RATE / 2) / profile.deviation_pp
        print(f"  {profile.key}: {level:.3f} of the video deviation, against "
              f"{ceiling:.3f} a discriminator can read "
              f"({level / ceiling * 100:.0f}% of it)")
        check(f"{profile.key}: the picture's own swing is not a click",
              level > 0.5)
        check(f"{profile.key}: and the threshold is one a discriminator can "
              "actually reach", level < 0.9 * ceiling,
              f"{level:.3f} against {ceiling:.3f}")

    print("\nhanding the pictures to a player")
    # A picture is 921,600 bytes in NTSC and 1,327,104 in PAL, where a pipe
    # holds 65,536. Writing one straight down a non-blocking pipe delivers
    # a fifteenth of it: measured against a real transmitter, 7.1% of the
    # bytes reached the player - 1.25 pictures a second - while the unsent
    # remainder grew to 183 MB. Nothing here caught that, so this does.
    for profile, standard in ([(FPV, NTSC)] if args.quick else
                              [(FPV, NTSC), (FPV, PAL)]):
        rf = bars_rf(profile, standard, frames=4)
        out = os.path.join(T.TMP, f'player-{standard.key}.raw')
        open(out, 'w').close()
        tb = gr.top_block("to a player", catch_exceptions=True)
        # Paced, and repeating: run flat out and the decoder is starved of
        # the processor by every other thread, so one buffer in three gets
        # decoded and the byte count proves nothing.
        src = blocks.vector_source_c(np.asarray(rf, np.complex64).tolist(),
                                     True)
        head = blocks.head(gr.sizeof_gr_complex, int(RF_RATE * 0.8))
        pace = blocks.throttle(gr.sizeof_gr_complex, RF_RATE)
        demod = FmVideoDemod(profile, standard, RF_RATE)
        sink = FmVideoFrameSink(VIDEO_RATES[standard.key], standard,
                                profile.deviation_pp, demod.dc_gain())
        tb.connect(src, head, pace, demod)
        tb.connect((demod, 0), sink)
        # Stands in for ffplay: reads as fast as it can, keeps what arrives.
        sink.start_player(['bash', '-c', f'cat > {out}'])
        tb.run()
        deadline = time.time() + 5.0
        size = standard.width * 2 * standard.active_lines_per_field * 3
        while (time.time() < deadline
               and os.path.getsize(out) < sink.frames_decoded * size):
            time.sleep(0.1)
        sink.stop_player()
        got = os.path.getsize(out)
        want = sink.frames_decoded * size
        print(f"  {standard.key.upper()}: {sink.frames_decoded} decoded, "
              f"{got / 1e6:.1f} MB to the player = {got / size:.1f} pictures, "
              f"{sink.frames_unsent} skipped")
        check(f"{standard.key.upper()}: every decoded picture reaches the player",
              got == want and sink.frames_decoded >= 5,
              f"{got} bytes of {want}, {sink.frames_decoded} decoded")
        check(f"{standard.key.upper()}: and arrives as whole frames",
              got % size == 0, f"{got % size} bytes over")

    print("\ncarrier-to-noise, and the clicks below FM threshold")
    # FM's whole character is its threshold, so the two numbers that say
    # where the link sits against it have to be right. Noise is added to a
    # known signal at a known ratio and the receiver is asked what it sees.
    profile, standard = FPV, NTSC
    # A third of a second: the estimator averages over a quarter of one, so
    # anything shorter never completes a window and reads nothing at all.
    clean = bars_rf(profile, standard, frames=11)
    rng = np.random.RandomState(4)
    signal_power = float(np.mean(np.abs(clean.astype(np.complex128)) ** 2))
    for wanted in (30.0, 20.0, 12.0, 6.0):
        noise_power = signal_power / 10 ** (wanted / 10)
        noisy = (clean.astype(np.complex128)
                 + np.sqrt(noise_power / 2) * (rng.randn(clean.size)
                                               + 1j * rng.randn(clean.size))
                 ).astype(np.complex64)
        tb = gr.top_block("cnr", catch_exceptions=True)
        src_b = rf_source(noisy, 'noisy.cf32')
        demod = FmVideoDemod(profile, standard, RF_RATE)
        composite = blocks.null_sink(gr.sizeof_float)
        tb.connect(src_b, demod)
        tb.connect((demod, 0), composite)
        quality, _ = link_quality_chain(
            tb, src_b, (demod, 1),
            click_level(profile, profile.deviation_pp), RF_RATE)
        tb.run()
        frames = quality.samples / RF_RATE / standard.frame
        per_frame = quality.clicks / frames if frames else 0.0
        print(f"  wanted {wanted:4.1f} dB: read {quality.cnr_db:5.1f} dB, "
              f"{quality.clicks:,} clicks in {frames:.1f} frames "
              f"({per_frame:.0f} a frame)")
        close(f"carrier to noise at {wanted:g} dB", quality.cnr_db, wanted,
              1.5, ' dB')
        if wanted >= 20:
            check(f"nothing counts as a click at {wanted:g} dB",
                  per_frame < 1.0, f"{per_frame:.2f} a frame")
        if wanted <= 6:
            check(f"and plenty do at {wanted:g} dB", per_frame > 10,
                  f"{per_frame:.0f} a frame")

    print("\nkeeping up with the air, at the radio's own rate")
    # Everything the receiver does to the samples - discriminate, undo the
    # pre-emphasis, filter and decimate the picture, decode frames on their
    # own thread, both sound subcarriers, and the link's own statistics -
    # fed at 20 MS/s with nothing to draw. The displays cost more on top,
    # which is why this is quoted as a multiple rather than as a pass mark.
    for profile, standard in ([(FPV, NTSC)] if args.quick else
                              [(FPV, NTSC), (FPV, PAL)]):
        rf = bars_rf(profile, standard, frames=4)
        seconds = 2.0
        tb = gr.top_block("keeping up", catch_exceptions=True)
        src = blocks.vector_source_c(np.asarray(rf, np.complex64).tolist(),
                                     True)
        head = blocks.head(gr.sizeof_gr_complex, int(RF_RATE * seconds))
        demod = FmVideoDemod(profile, standard, RF_RATE)
        sink = FmVideoFrameSink(VIDEO_RATES[standard.key], standard,
                                profile.deviation_pp, demod.dc_gain())
        tb.connect(src, head, demod)
        tb.connect((demod, 0), sink)
        quality, _ = link_quality_chain(
            tb, head, (demod, 1), click_level(profile, profile.deviation_pp),
            RF_RATE)
        sounds = [FmVideoSound(profile, freq, RF_RATE, AUDIO_RATE)
                  for freq in profile.subcarriers]
        for sound in sounds:
            snk = blocks.null_sink(gr.sizeof_float)
            tb.connect((demod, 1), sound, snk)
            sound.keepalive = snk
        started = time.perf_counter()
        tb.run()
        elapsed = time.perf_counter() - started
        check(f"{profile.key} {standard.key.upper()}: faster than the air",
              seconds / elapsed > 1.0, f"{seconds / elapsed:.2f}x")
        headroom = seconds / elapsed

        # **And again at the rate a radio actually delivers.** Run flat out,
        # every other thread takes the processor the decoder wants and
        # buffers get dropped - which says nothing about the bench, where
        # the radio paces the whole graph at exactly real time. So the
        # frames are counted with a throttle in, as the transmitter's own
        # test does, and the multiple above is quoted separately.
        paced = gr.top_block("paced", catch_exceptions=True)
        src = blocks.vector_source_c(np.asarray(rf, np.complex64).tolist(),
                                     True)
        head = blocks.head(gr.sizeof_gr_complex, int(RF_RATE * seconds))
        pace = blocks.throttle(gr.sizeof_gr_complex, RF_RATE)
        demod = FmVideoDemod(profile, standard, RF_RATE)
        sink = FmVideoFrameSink(VIDEO_RATES[standard.key], standard,
                                profile.deviation_pp, demod.dc_gain())
        paced.connect(src, head, pace, demod)
        paced.connect((demod, 0), sink)
        quality, _ = link_quality_chain(
            paced, pace, (demod, 1),
            click_level(profile, profile.deviation_pp), RF_RATE)
        sounds = [FmVideoSound(profile, freq, RF_RATE, AUDIO_RATE)
                  for freq in profile.subcarriers]
        for sound in sounds:
            snk = blocks.null_sink(gr.sizeof_float)
            paced.connect((demod, 1), sound, snk)
            sound.keepalive = snk
        cpu = time.process_time()
        paced.run()
        cores = (time.process_time() - cpu) / seconds
        ceiling = 1.0 / (standard.frame * sink.BUFFER_FRAMES)
        print(f"  {profile.key} {standard.key.upper()}: {headroom:.2f}x real "
              f"time flat out; at the radio's rate {sink.frames_decoded} "
              f"pictures ({sink.frames_decoded / seconds:.1f}/s of "
              f"{ceiling:.1f}), {sink.frames_dropped} dropped, "
              f"{cores:.2f} cores")
        check(f"{profile.key} {standard.key.upper()}: decodes every frame "
              "the buffer allows, at the radio's rate",
              sink.frames_decoded / seconds > 0.9 * ceiling
              and sink.frames_dropped == 0,
              f"{sink.frames_decoded / seconds:.1f}/s of {ceiling:.1f}, "
              f"{sink.frames_dropped} dropped")

    print()
    if failures:
        print(f"{len(failures)} FAILED: {', '.join(failures)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == '__main__':
    sys.exit(main())
