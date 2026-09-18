"""An audio file from the media folder, WAV or MP3, as sound for a flowgraph.

Every app here takes its audio at 48 kHz. A WAV plays exactly as it always
has - GNU Radio's own ``wavfile_source``, or the ``wave`` module in the FM +
RDS transmitter - and needs nothing else installed. An MP3 is decoded by
ffmpeg into a pipe, the way the NTSC and FM video transmitters already take
a clip's soundtrack (``ntsc_source.AudioTrack``), and ffmpeg resamples it on
the way: most MP3s are 44.1 kHz, which the four apps that assume 48 kHz
would otherwise play 8.8% fast, taking the deviation up with it.

Two ways in, because the apps consume sound two ways:

- :class:`AudioFileSource` is a GNU Radio source block, for the apps that
  build their audio chain once. An MP3 comes out of a
  ``file_descriptor_source`` reading ffmpeg's pipe.
- :class:`PcmReader` is for a Python block that swaps files while the
  flowgraph runs - the FM + RDS transmitter's Next Track. See its notes for
  why it decodes on a thread of its own.

A mono source takes an MP3 down to mono as (L+R)/2. A stereo WAV there
still gives only its left channel, as ``wavfile_source`` always has.
"""

import json
import os
import shutil
import subprocess
import threading
import wave

import numpy as np

AUDIO_RATE = 48000


def is_wav(path):
    return path.lower().endswith('.wav')


def have_ffmpeg():
    return shutil.which('ffmpeg') is not None


def wav_rate(path, default=AUDIO_RATE):
    """A WAV's own sample rate, or ``default`` if it cannot be read."""
    try:
        with wave.open(path, 'rb') as w:
            return w.getframerate()
    except Exception:
        return default


def audio_channels(path):
    """How many channels a file carries: 1, 2, ... or 0 if it cannot be read.

    Read from a WAV's header, and asked of ffprobe for anything else - once,
    of the one file chosen, never of the whole folder while a dialog opens.
    """
    if is_wav(path):
        try:
            with wave.open(path, 'rb') as w:
                return w.getnchannels()
        except Exception:
            return 0
    probe = shutil.which('ffprobe')
    if probe is None:
        return 0
    try:
        out = subprocess.run(
            [probe, '-v', 'error', '-select_streams', 'a:0',
             '-show_entries', 'stream=channels', '-of', 'csv=p=0', path],
            capture_output=True, text=True, timeout=10).stdout
        return int(out.strip().splitlines()[0])
    except Exception:
        return 0


def track_tags(path):
    """A file's own ``title`` and ``artist`` tags, as far as it has them.

    ID3 in an MP3, and the INFO chunk a WAV can carry, both read by ffprobe;
    an empty dict for a file with neither, or with no ffprobe to ask.
    ffprobe writes UTF-8, so it is decoded as UTF-8 explicitly: read as
    text in the locale's encoding - cp1252 on Windows - an accented letter
    in a tag would come back as two wrong ones.
    """
    probe = shutil.which('ffprobe')
    if not path or probe is None:
        return {}
    try:
        out = subprocess.run(
            [probe, '-v', 'error', '-show_entries', 'format_tags',
             '-of', 'json', path], capture_output=True, timeout=10).stdout
        tags = json.loads(out.decode('utf-8', 'replace')).get(
            'format', {}).get('tags', {})
    except Exception:
        return {}
    tags = {k.lower(): str(v).strip() for k, v in tags.items()}
    found = {'title': tags.get('title', ''),
             'artist': tags.get('artist') or tags.get('album_artist', '')}
    return {k: v for k, v in found.items() if v}


class Decoder:
    """ffmpeg decoding an audio file to 32-bit float PCM on a pipe, looping.

    ``-stream_loop -1`` loops inside ffmpeg, so the pipe never ends and the
    file runs straight on into its own start, as ``wavfile_source`` with
    repeat on does.
    """

    def __init__(self, path, channels=1, rate=AUDIO_RATE, loop=True):
        if not have_ffmpeg():
            raise RuntimeError(
                f"Playing {os.path.basename(path)} needs ffmpeg on PATH, "
                "and it is not installed. WAV files play without it.")
        self.path = path
        self.channels = int(channels)
        self.rate = int(rate)
        argv = ['ffmpeg', '-hide_banner', '-loglevel', 'error']
        if loop:
            argv += ['-stream_loop', '-1']
        argv += ['-i', path, '-vn', '-ac', str(self.channels),
                 '-ar', str(self.rate), '-f', 'f32le', '-acodec', 'pcm_f32le',
                 'pipe:1']
        self._proc = subprocess.Popen(argv, stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL)

    def fileno(self):
        return self._proc.stdout.fileno()

    def descriptor(self):
        """A duplicate of the pipe, for a block that closes what it is given.

        ``file_descriptor_source`` closes its descriptor when it is
        destroyed and :meth:`close` closes the pipe too; handed the same
        number, the second close lands on whatever was opened in between -
        the next launch's pipe. See ``ntsc_source.AudioTrack.descriptor``,
        where that silenced the second run of an app.
        """
        return os.dup(self.fileno())

    def close(self):
        """End ffmpeg, then the pipe.

        Killed, not asked to stop: an ffmpeg blocked writing to a full pipe
        - the normal state of one decoding ahead of playback - ignores
        SIGTERM, and waiting out a timeout held up closing an app's window
        by two seconds, measured. Nothing is lost killing a decoder. And in
        that order, so a thread blocked reading the pipe sees the end of
        the file rather than a descriptor closed under it.
        """
        proc, self._proc = getattr(self, '_proc', None), None
        if proc is None:
            return
        if proc.poll() is None:
            proc.kill()
        proc.wait()
        try:
            proc.stdout.close()
        except Exception:
            pass


class AudioFileSource:
    """A media-folder audio file as a looping mono float source.

    ``block`` goes into the flowgraph where ``blocks.wavfile_source`` went,
    and ``rate`` is what comes out of it: the file's own rate for a WAV, and
    48 kHz for an MP3. Call :meth:`close` once the flowgraph has stopped, or
    an MP3's ffmpeg sits blocked on a full pipe until the launcher exits.
    """

    def __init__(self, path):
        from gnuradio import blocks, gr
        self.path = path
        self.decoder = None
        if is_wav(path):
            self.block = blocks.wavfile_source(path, True)
            self.rate = wav_rate(path)
        else:
            self.decoder = Decoder(path, channels=1)
            self.block = blocks.file_descriptor_source(
                gr.sizeof_float, self.decoder.descriptor(), False)
            self.rate = self.decoder.rate

    def close(self):
        if self.decoder is not None:
            self.decoder.close()


class PcmReader:
    """An MP3 decoded ahead on a thread, read without ever waiting.

    For the FM + RDS transmitter's audio block, which swaps files inside a
    running flowgraph. Reading ffmpeg's pipe from its ``work()`` would
    stall the whole flowgraph whenever the pipe ran dry - at the start of
    every track, while ffmpeg opens the file - and the radio would run out
    of samples mid-broadcast. On Windows a pipe holds 4 KB by default, 10 ms
    of stereo float. So a thread keeps up to ``ahead`` seconds decoded, and
    :meth:`read` takes what is there, filling any shortfall with silence
    and counting it in ``short``. ffmpeg decodes an MP3 many times faster
    than it plays, so in steady state there is none; :meth:`wait_ready` is
    for the start of a track, so a new song does not open on a gap.
    """

    def __init__(self, path, channels=2, rate=AUDIO_RATE, ahead=1.0):
        self.channels = int(channels)
        self.short = 0
        self._decoder = Decoder(path, channels=self.channels, rate=rate)
        self._frame = 4 * self.channels
        self._limit = int(ahead * rate) * self._frame
        self._buf = bytearray()
        self._closed = False
        self._cond = threading.Condition()
        self._thread = threading.Thread(target=self._fill, daemon=True,
                                        name='mp3 decode')
        self._thread.start()

    def _fill(self):
        fd = self._decoder.fileno()
        while True:
            with self._cond:
                while len(self._buf) >= self._limit and not self._closed:
                    self._cond.wait()
                if self._closed:
                    return
            try:
                chunk = os.read(fd, 65536)
            except OSError:
                chunk = b''
            with self._cond:
                if not chunk:
                    self._closed = True
                    self._cond.notify_all()
                    return
                self._buf += chunk
                self._cond.notify_all()

    def wait_ready(self, seconds=0.2, timeout=3.0):
        """Wait until ``seconds`` of sound are decoded, or ffmpeg has ended."""
        want = min(int(seconds * AUDIO_RATE) * self._frame, self._limit)
        with self._cond:
            self._cond.wait_for(
                lambda: len(self._buf) >= want or self._closed, timeout)
            return len(self._buf) >= want

    def read(self, n):
        """The next ``n`` frames, shape (n, channels), silence where short."""
        with self._cond:
            take = min(n * self._frame,
                       len(self._buf) // self._frame * self._frame)
            data = bytes(self._buf[:take])
            del self._buf[:take]
            self._cond.notify_all()
        frames = np.frombuffer(data, np.float32).reshape(-1, self.channels)
        if len(frames) < n:
            self.short += n - len(frames)
            frames = np.vstack([frames, np.zeros((n - len(frames),
                                                  self.channels), np.float32)])
        return frames

    def close(self):
        with self._cond:
            self._closed = True
            self._cond.notify_all()
        self._decoder.close()
        self._thread.join(timeout=2)
