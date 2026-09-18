#!/usr/bin/env python3
"""Check that an MP3 plays the way a WAV does, and that its tags reach RDS.

    python scripts/test_audio_files.py              # MP3s it makes itself
    python scripts/test_audio_files.py song.mp3     # ... and a real one too

The MP3s are tones at 44.1 kHz, the rate most MP3s are, so a decode that
skipped resampling to the 48 kHz every app assumes would come back 8.8%
sharp - 440 Hz reading as 479 - which the pitch checks catch. Covers both
ways in (``apps/audio_file.py``): the source block the audio and video
transmitters use, and the reader behind the FM + RDS transmitter's Next
Track, including a swap while it runs. Then a song's own title and artist
tags, read and sent as RDS Now Playing through the encoder and decoded back
- accents and curly quotes included, since RDS cannot carry them as they
are. No radio and no display; needs ffmpeg, as playing an MP3 does.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from gnuradio import blocks, gr  # noqa: E402

from apps.audio_file import (AUDIO_RATE, AudioFileSource, PcmReader,  # noqa: E402
                             audio_channels, have_ffmpeg, track_tags)

FAILURES = []


def check(condition, message, detail=''):
    print(('  ok   ' if condition else '  FAIL ') + message
          + (f'  {detail}' if detail else ''))
    if not condition:
        FAILURES.append(message)


def ffmpeg(*args):
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y']
                   + list(args), check=True)


def tone(freq, rate=44100, seconds=1):
    return ['-f', 'lavfi', '-i',
            f'sine=frequency={freq}:sample_rate={rate}:duration={seconds}']


def peaks(x, count):
    """The ``count`` strongest frequencies in ``x``, at AUDIO_RATE, to 1 Hz."""
    x = np.asarray(x[:AUDIO_RATE], np.float64)
    spectrum = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    found = []
    for _ in range(count):
        i = int(np.argmax(spectrum))
        found.append(i * AUDIO_RATE / len(x))
        spectrum[max(0, i - 20):i + 20] = 0
    return sorted(found)


def near(got, want, tol=2.0):
    return len(got) == len(want) and all(abs(g - w) <= tol
                                         for g, w in zip(got, want))


def play(block, seconds):
    """Run a source block for ``seconds`` of audio; its first output."""
    tb = gr.top_block()
    head = blocks.head(gr.sizeof_float, int(seconds * AUDIO_RATE))
    sink = blocks.vector_sink_f()
    tb.connect(block, head, sink)
    tb.run()
    return np.array(sink.data(), np.float32)


def over_the_air(artist, title, seconds=12):
    """Send Now Playing through the RDS encoder and decode it straight back."""
    from apps.rds_core import RdsDemod, RdsProtocol, software_pilot_pll
    from apps.rds_encode import RdsEncoder, RdsSubcarrier
    enc = RdsEncoder(pi=0x4413, ps='GNURADIO', pty=5)
    enc.set_now_playing(artist, title)
    sub = RdsSubcarrier(enc, 200e3)
    mpx = np.concatenate([sub.generate(8192)
                          for _ in range(int(200e3 * seconds) // 8192)])
    mpx = mpx.astype(np.float64)
    ref = software_pilot_pll(mpx, 200e3)
    demod, proto = RdsDemod(200e3), RdsProtocol(region='RBDS')
    for i in range(0, len(mpx), 8192):
        bits = demod.feed(mpx[i:i + 8192], ref[i:i + 8192])
        if len(bits):
            proto.feed(bits)
    snap = proto.snapshot()
    return enc, snap, 100 * (1 - (snap['block_error_rate'] or 0))


def ended(decoder):
    return decoder is None or getattr(decoder, '_proc', None) is None


def main(real=None):
    if not have_ffmpeg():
        print('ffmpeg is not on PATH, and playing an MP3 needs it')
        return 1
    work = tempfile.mkdtemp(prefix='audio-test-')
    try:
        stereo = os.path.join(work, 'Two-Tones.mp3')
        mono = os.path.join(work, 'One-Tone.mp3')
        wav = os.path.join(work, 'Tone.wav')
        ffmpeg(*tone(440), *tone(1000), '-filter_complex',
               '[0][1]join=inputs=2:channel_layout=stereo',
               '-c:a', 'libmp3lame', '-b:a', '192k', stereo)
        ffmpeg(*tone(440), '-c:a', 'libmp3lame', '-b:a', '128k', mono)
        ffmpeg(*tone(700, rate=48000), '-c:a', 'pcm_s16le', wav)

        print('the source block (AM, FM, PPM-OOK, subcarrier, NTSC, FM video)')
        src = AudioFileSource(stereo)
        check(src.rate == AUDIO_RATE, 'an MP3 comes out at 48 kHz', f'{src.rate}')
        proc = src.decoder._proc
        audio = play(src.block, 3)
        check(len(audio) == 3 * AUDIO_RATE,
              'a one-second MP3 plays on for three - it loops, as a WAV does',
              f'{len(audio) / AUDIO_RATE:.2f} s')
        got = peaks(audio[AUDIO_RATE:], 2)
        check(near(got, [440, 1000]),
              'at the right pitch, both channels mixed to mono',
              ', '.join(f'{f:.0f} Hz' for f in got))
        t0 = time.time()
        src.close()
        took = time.time() - t0
        check(proc.poll() is not None and ended(src.decoder) and took < 0.5,
              'close() ends its ffmpeg, at once', f'{took * 1000:.0f} ms')
        src = AudioFileSource(wav)
        check(src.decoder is None and 'wavfile' in src.block.name(),
              'a WAV still plays through wavfile_source, with no ffmpeg',
              src.block.name())
        check(near(peaks(play(src.block, 1), 1), [700]),
              'and at its own pitch')
        src.close()

        print('\nthe reader (FM + RDS Next Track)')
        reader = PcmReader(stereo, channels=2)
        check(reader.wait_ready(), 'a moment of sound is ready before it plays')
        frames = []
        for _ in range(30):                 # 1.5 s at the pace a radio takes it
            frames.append(reader.read(AUDIO_RATE // 20))
            time.sleep(0.05)
        frames = np.vstack(frames)
        check(reader.short == 0, 'paced like a radio, it never runs short',
              f'{reader.short} frames short')
        check(near(peaks(frames[:, 0], 1), [440]) and
              near(peaks(frames[:, 1], 1), [1000]),
              'left is left and right is right')
        proc, t0 = reader._decoder._proc, time.time()
        reader.close()
        took = time.time() - t0
        check(proc.poll() is not None and took < 0.5,
              'close() ends its ffmpeg, at once', f'{took * 1000:.0f} ms')
        check(audio_channels(mono) == 1 and audio_channels(stereo) == 2,
              'ffprobe says how many channels an MP3 has')
        reader = PcmReader(mono, channels=2)
        reader.wait_ready()
        pair = reader.read(AUDIO_RATE)
        check(np.array_equal(pair[:, 0], pair[:, 1]),
              'a mono MP3 is the same on both sides - no stereo difference')
        reader.close()

        print('\nthe FM + RDS audio block')
        from apps.fmRdsTransmitter import audio_source
        block = audio_source(stereo)
        check(block.channels == 2, 'a stereo MP3 is reported as stereo')
        tb = gr.top_block()
        left, right = blocks.vector_sink_f(), blocks.vector_sink_f()
        throttle = blocks.throttle(gr.sizeof_float, AUDIO_RATE)
        tb.connect((block, 0), throttle, left)
        tb.connect((block, 1), right)
        tb.start()
        time.sleep(1.2)
        before = block._pcm
        block.set_source(mono)              # Next Track, while it runs
        after = block._pcm
        # Long enough that the last second is wholly after the swap: the
        # source runs a third of a second ahead of the throttle, so the
        # swap lands later in the samples than on the clock.
        time.sleep(2.5)
        tb.stop()
        tb.wait()
        check(block.channels == 1, 'after Next Track to a mono MP3, it says mono')
        check(ended(before._decoder), "the old song's ffmpeg is ended by the swap")
        check(after.short == 0, 'the new song never ran short, swap included',
              f'{after.short} frames short')
        l, r = np.array(left.data()), np.array(right.data())
        cut = int(1.0 * AUDIO_RATE)
        check(near(peaks(l[:cut], 1), [440]) and near(peaks(r[:cut], 1), [1000]),
              'before the swap: the stereo song, each side right')
        # The same samples on both sides: the right sink runs ahead of the
        # left's throttle, so compare by position, not each one's last second.
        end = min(len(l), len(r))
        tail = l[end - AUDIO_RATE:end]
        check(near(peaks(tail, 1), [440]) and np.allclose(tail, r[end - AUDIO_RATE:end]),
              'after it: the mono song, the same on both sides')
        block.set_source(wav)
        check(block.channels == 1 and block._pcm is None and ended(after._decoder),
              'and on to a WAV, which needs no reader')
        block.close()

        print('\ntags, for RDS Now Playing')
        from apps.fmRdsTransmitter import song
        tagged = os.path.join(work, '01-Tagged.mp3')
        ffmpeg(*tone(440), '-c:a', 'libmp3lame', '-metadata',
               'title=Livin\u2019 On A Prayer', '-metadata',
               'artist=M\u00f6tley Cr\u00fce', tagged)
        tags = track_tags(tagged)
        check(tags == {'title': 'Livin\u2019 On A Prayer',
                       'artist': 'M\u00f6tley Cr\u00fce'},
              "an MP3's ID3 title and artist, accents and curly quote intact",
              repr(tags))
        info = os.path.join(work, 'Info-Tagged.wav')
        ffmpeg(*tone(700, rate=48000), '-c:a', 'pcm_s16le', '-metadata',
               'title=Cone of Silence', '-metadata', 'artist=Get Smart', info)
        check(track_tags(info) == {'title': 'Cone of Silence', 'artist': 'Get Smart'},
              "a WAV's INFO title and artist", repr(track_tags(info)))
        check(track_tags(stereo) == {} and song(stereo) == ('', 'Two Tones'),
              'with no tags, the file name stands in as before', repr(song(stereo)))
        check(song(tagged) == ('M\u00f6tley Cr\u00fce', 'Livin\u2019 On A Prayer'),
              'with them, the song is its tags, not "01 Tagged"')

        enc, snap, good = over_the_air(*song(tagged))
        check(snap['artist'] == 'Motley Crue' and snap['title'] == "Livin' On A Prayer",
              'decoded off the RDS: RT+ artist and title, as RDS can carry them',
              f"{snap['artist']!r} / {snap['title']!r}")
        check(snap['radiotext'].strip() == "Motley Crue - Livin' On A Prayer"
              and good == 100,
              'and the RadioText line with them, every block clean',
              f"{snap['radiotext'].strip()!r}, {good:.1f}% blocks good")
        enc, snap, good = over_the_air(
            'Berlin Philharmonic',
            'Symphony No. 9 in D minor, Op. 125: IV. Presto - Allegro assai')
        sent = enc.snapshot()['now_playing']
        check(snap['artist'] == sent['artist'] == 'Berlin Philharmonic'
              and snap['title'] == sent['title']
              and len(snap['radiotext'].rstrip()) <= 64,
              'a title too long for RadioText is cut at a word, and still decodes',
              f"{snap['title']!r}")

        if real:
            print(f'\na real file: {os.path.basename(real)}')
            print(f'       tags {track_tags(real)!r} -> Now Playing {song(real)!r}')
            src = AudioFileSource(real)
            audio = play(src.block, 5)
            rms = float(np.sqrt(np.mean(audio ** 2))) if len(audio) else 0.0
            check(len(audio) == 5 * AUDIO_RATE and rms > 1e-3,
                  'five seconds of it decode, and it is not silence',
                  f'rms {rms:.3f}, {audio_channels(real)} channel(s)')
            src.close()
            reader = PcmReader(real, channels=2)
            reader.wait_ready()
            for _ in range(20):
                reader.read(AUDIO_RATE // 20)
                time.sleep(0.05)
            check(reader.short == 0, 'read like a radio, it never runs short',
                  f'{reader.short} frames short')
            reader.close()
    finally:
        shutil.rmtree(work, ignore_errors=True)

    print(f"\n{len(FAILURES)} FAILED: {', '.join(FAILURES)}" if FAILURES
          else '\nall checks passed')
    return 1 if FAILURES else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))
