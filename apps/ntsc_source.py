#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Composite NTSC baseband, live, from whatever you point it at.

``ntsc_encode`` turns one frame into one frame's worth of composite video.
This turns a *stream* of frames into a continuous signal a flowgraph can
transmit, and answers the question of what video format this project takes:
**whatever ffmpeg reads**. There is no bespoke format to convert to.

Three things can feed it:

- a **video file** - mp4, mkv, avi, webm, anything ffmpeg decodes - scaled
  to 640x480 and letterboxed if it is not 4:3, looping forever;
- a **still frame**, which is what the instructor's ``.dat`` captures are;
- a **built-in colour-bar pattern**, so the app works with no media at all.

The ``.dat`` files do not come through here. They are already composite
video, sampled at 18 MS/s, so they are played by a plain file source and
resampled - see ``dat_resample_ratio``.

**Frames are encoded on their own thread.** Encoding a frame takes about
20 ms, and a GNU Radio work() call at 10 MS/s covers well under a
millisecond, so encoding inside work() would stall the radio for 20 ms
every 33 ms and underrun it. A small queue between the two is what keeps
the output continuous, and it paces the encoder for free: the queue fills,
the producer blocks, and frames are pulled at exactly the rate the radio
consumes them.
"""

import os
import re
import shutil
import subprocess
import sys
import threading
from fractions import Fraction
from queue import Empty, Full, Queue

import numpy as np
from gnuradio import gr  # type: ignore

from apps.ntsc_encode import FRAME, NtscEncoder, IRE_BLANK, ire_to_unit

#: The instructor's ``*-18M0FS.dat`` captures are composite at this rate.
DAT_SAMPLE_RATE = 18e6

#: What the encoder samples an active line into. 640x480 is 4:3 and matches
#: the 480 active lines the frame is cut into, so one row is one line.
ACTIVE_WIDTH = 640
ACTIVE_HEIGHT = 480

#: 30000/1001, the frame rate everything in NTSC descends from.
FRAME_RATE = 1.0 / FRAME

#: Extensions worth offering, **best first**. ffmpeg reads far more than
#: this; the list is to keep the dialog sensible, not because anything else
#: would fail. The order is the preference - see ``video_files``.
VIDEO_EXTENSIONS = ('.mp4', '.mkv', '.mov', '.m4v', '.webm', '.avi',
                    '.mpg', '.mpeg', '.ts', '.wmv', '.flv', '.ogv')


def have_ffmpeg():
    return shutil.which('ffmpeg') is not None


def video_files(directory):
    """Playable video files in a directory, as (display name, full path).

    **One clip, one entry.** The media folder holds each clip twice - a
    ``.mp4`` for here and a ``.ts`` of the same picture and sound for the
    ATSC transmitter, which needs a transport stream. Offering both made the
    picker forty items long with every title in it twice, spelled
    identically, and nothing on screen said which was which. So files that
    share a name are collapsed to one, keeping the extension earliest in
    ``VIDEO_EXTENSIONS``: the ``.mp4`` is 640x480 with square pixels, which
    is exactly what the encoder wants, where the ``.ts`` is 704x480 at
    10:11 and would have to be stretched back.
    """
    if not directory or not os.path.isdir(directory):
        return []
    best = {}
    for name in sorted(os.listdir(directory)):
        stem, ext = os.path.splitext(name)
        ext = ext.lower()
        if ext not in VIDEO_EXTENSIONS:
            continue
        rank = VIDEO_EXTENSIONS.index(ext)
        if stem not in best or rank < best[stem][0]:
            best[stem] = (rank, name)
    return [(stem.replace('-', ' '), os.path.join(directory, name))
            for stem, (_rank, name) in sorted(best.items())]


#: The instructor's captures are named ``<subject>-946x486-18M0FS.dat``. The
#: geometry and the sample rate are the same for every one of them, so
#: repeating it down the picker says nothing and hides the subject.
_DAT_SUFFIX = re.compile(r'-\d+x\d+-\d+M\d+FS$', re.IGNORECASE)


def dat_files(directory):
    """The ``.dat`` composite captures, as (display name, full path).

    One still frame each, sampled at 18 MS/s - see ``dat_resample_ratio``.
    """
    if not directory or not os.path.isdir(directory):
        return []
    found = []
    for name in sorted(os.listdir(directory)):
        if not name.lower().endswith('.dat'):
            continue
        stem = _DAT_SUFFIX.sub('', os.path.splitext(name)[0])
        found.append((stem.replace('-', ' '), os.path.join(directory, name)))
    return found


def dat_resample_ratio(sample_rate):
    """(interpolation, decimation) to play an 18 MS/s ``.dat`` at this rate.

    The captures are one frame of composite video at 18 MS/s - 1144 samples
    a line, 525 lines, 600600 samples. Played out at any other rate without
    resampling, every timing in them is wrong by that ratio: at 10 MS/s a
    line lasts 114.4 us instead of 63.5556, which is a line rate of 8741 Hz
    where NTSC needs 15734.266. No television can lock to that, which is
    what the app used to transmit.
    """
    ratio = Fraction(int(round(sample_rate)), int(DAT_SAMPLE_RATE))
    return ratio.numerator, ratio.denominator


# --- where frames come from -------------------------------------------------

#: 75% colour bars, the standard order, white through blue.
BAR_COLOURS = [(1, 1, 1), (1, 1, 0), (0, 1, 1), (0, 1, 0),
               (1, 0, 1), (1, 0, 0), (0, 0, 1)]


def colour_bars(width=ACTIVE_WIDTH, height=ACTIVE_HEIGHT, level=0.75):
    """The test pattern the app falls back to when there is no media."""
    img = np.zeros((height, width, 3))
    for k, rgb in enumerate(BAR_COLOURS):
        img[:, k * width // 7:(k + 1) * width // 7] = np.array(rgb) * level
    return img


class FrameSource:
    """Something that produces RGB frames in 0..1, forever."""

    def next_frame(self):
        raise NotImplementedError

    def close(self):
        pass

    @property
    def description(self):
        return self.__class__.__name__


class TestPattern(FrameSource):
    """Colour bars. Needs no file and no ffmpeg."""

    def __init__(self, width=ACTIVE_WIDTH, height=ACTIVE_HEIGHT):
        self._frame = colour_bars(width, height)

    def next_frame(self):
        return self._frame

    @property
    def description(self):
        return "colour bars (built in)"


class StillImage(FrameSource):
    """One frame, held. Anything ffmpeg can open as an image."""

    def __init__(self, rgb, name="still image"):
        self._frame = np.asarray(rgb, dtype=np.float64)
        self._name = name

    def next_frame(self):
        return self._frame

    @property
    def description(self):
        return self._name


class VideoFile(FrameSource):
    """Frames decoded by ffmpeg, looping forever.

    Scaled to 640x480 and *letterboxed* rather than stretched, because most
    of the material worth transmitting here - 1950s advertising, the Blender
    open movies - is either already 4:3 or is widescreen that should not be
    squeezed into it.
    """

    def __init__(self, path, width=ACTIVE_WIDTH, height=ACTIVE_HEIGHT,
                 loop=True):
        if not have_ffmpeg():
            raise RuntimeError(
                "Playing video needs ffmpeg on PATH, and it is not installed.")
        self.path = path
        self.width, self.height = int(width), int(height)
        self._bytes = self.width * self.height * 3
        scale = (f"scale={self.width}:{self.height}"
                 ":force_original_aspect_ratio=decrease,"
                 f"pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2")
        argv = ['ffmpeg', '-hide_banner', '-loglevel', 'error']
        if loop:
            argv += ['-stream_loop', '-1']
        argv += ['-i', path, '-an', '-vf', scale,
                 '-r', f"{FRAME_RATE:.6f}", '-f', 'rawvideo',
                 '-pix_fmt', 'rgb24', 'pipe:1']
        self._proc = subprocess.Popen(argv, stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL)
        self._last = colour_bars(self.width, self.height)

    def next_frame(self):
        raw = self._read_exactly(self._bytes)
        if raw is None:
            return self._last          # ffmpeg ended or died; hold the picture
        frame = (np.frombuffer(raw, dtype=np.uint8)
                 .reshape(self.height, self.width, 3).astype(np.float64) / 255.0)
        self._last = frame
        return frame

    def _read_exactly(self, count):
        """A pipe read returns what it has, not what was asked for."""
        chunks, got = [], 0
        while got < count:
            try:
                piece = self._proc.stdout.read(count - got)
            except (ValueError, OSError):
                return None
            if not piece:
                return None
            chunks.append(piece)
            got += len(piece)
        return b''.join(chunks)

    def close(self):
        proc, self._proc = getattr(self, '_proc', None), None
        if proc is None:
            return
        try:
            proc.stdout.close()
        except Exception:
            pass
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()

    @property
    def description(self):
        return os.path.basename(self.path)


# --- the GNU Radio source ---------------------------------------------------

class ntsc_source(gr.sync_block):
    """Composite NTSC baseband, as a stream of floats at ``sample_rate``.

    Sync tip is 0.0 and white is 1.0, which is what the transmitter expects
    to modulate. See the module docstring for why encoding happens on its
    own thread.
    """

    #: Frames encoded ahead. Three is about 100 ms of slack - enough to ride
    #: out a slow decode, small enough that changing source is not delayed.
    QUEUE_DEPTH = 3

    def __init__(self, frames, sample_rate, color=True):
        gr.sync_block.__init__(self, name='ntsc_source', in_sig=None,
                               out_sig=[np.float32])
        self.sample_rate = float(sample_rate)
        self.frames = frames
        self.encoder = NtscEncoder(self.sample_rate, color=color)
        self._queue = Queue(maxsize=self.QUEUE_DEPTH)
        self._thread = None
        self._running = threading.Event()
        self._buf = None
        self._pos = 0
        self.frames_encoded = 0
        self.starved = 0
        #: What to emit when the encoder has not kept up: blanking level, so
        #: a receiver sees a black frame rather than a burst of noise.
        self._blank = np.float32(ire_to_unit(IRE_BLANK))

    # -- lifecycle -------------------------------------------------------

    def start(self):
        self._running.set()
        self._thread = threading.Thread(target=self._produce, daemon=True,
                                        name='ntsc-encode')
        self._thread.start()
        return True

    def stop(self):
        self._running.clear()
        # Unblock the producer if it is parked on a full queue.
        try:
            self._queue.get_nowait()
        except Empty:
            pass
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=2.0)
        try:
            self.frames.close()
        except Exception as exc:
            print(f"NTSC source: error closing the video source: {exc}",
                  file=sys.stderr)
        return True

    def _produce(self):
        while self._running.is_set():
            try:
                samples = self.encoder.encode_frame(self.frames.next_frame())
            except Exception as exc:
                print(f"NTSC source: encoding stopped: {exc}", file=sys.stderr)
                return
            # Put with a timeout rather than blocking forever, so stop() is
            # never waiting on a queue nobody is draining.
            while self._running.is_set():
                try:
                    self._queue.put(samples.astype(np.float32), timeout=0.2)
                    self.frames_encoded += 1
                    break
                except Full:
                    continue

    # -- streaming -------------------------------------------------------

    def work(self, input_items, output_items):
        out = output_items[0]
        want = len(out)
        done = 0
        while done < want:
            if self._buf is None or self._pos >= self._buf.size:
                try:
                    self._buf = self._queue.get(timeout=0.1)
                    self._pos = 0
                except Empty:
                    if not self._running.is_set():
                        return -1 if done == 0 else done
                    # Rather than stall the radio, fill with blanking and
                    # count it. A starved frame is a dropped one either way,
                    # and a receiver holds sync through black.
                    out[done:want] = self._blank
                    self.starved += want - done
                    return want
            take = min(want - done, self._buf.size - self._pos)
            out[done:done + take] = self._buf[self._pos:self._pos + take]
            self._pos += take
            done += take
        return want
