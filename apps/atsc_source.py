#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A transport stream for the ATSC transmitter, from any video ffmpeg reads.

The transmitter consumes an MPEG-2 transport stream at exactly 19,392,658
bit/s, and it used to take nothing else: it listed the ``.ts`` files in the
media folder and played one. Every clip exists as a ``.ts`` as well as a
``.mp4`` (see ``media/VIDEO-CREDITS.txt``), so on this machine the list
looked complete. TVAdemo, the machine that transmits, was sent the fourteen
``.mp4`` files and not the 3.5 GB of ``.ts`` twins, and its picker offered
the test pattern and nothing else.

So **a clip with no ``.ts`` is encoded into one as it plays**, by ffmpeg,
with the settings the ``.ts`` files were made with, into a pipe the
flowgraph reads. That is cheap: on the Ford clip, the busiest in the folder,
it ran at 21x real time on the 8-core bench and 31x on TVAdemo, and what
came through the pipe was the mux rate to 0.01% in whole 188-byte packets.
The radio paces it - ffmpeg blocks when the pipe is full - so nothing needs
a clock of its own.

**A clip that has its ``.ts`` still plays that file directly.** It costs no
processor, and it is the file that was checked through the loopback.
"""

import os
import subprocess

from apps.ntsc_source import VIDEO_EXTENSIONS, have_ffmpeg, video_files

#: The bit rate A/53 fixes for the transport stream. The flowgraph consumes
#: the stream at this rate whatever it is muxed at, so a stream muxed any
#: other way plays at the wrong speed.
TS_RATE = 19392658

#: The same extensions as the NTSC transmitter, with ``.ts`` moved first:
#: where a clip exists both ways, the transport stream needs no encoding.
ATSC_EXTENSIONS = ('.ts',) + tuple(e for e in VIDEO_EXTENSIONS if e != '.ts')

#: The picture, as ``VIDEO-CREDITS.txt`` records the ``.ts`` files were
#: made: interlaced frames deinterlaced, pixels squared, fitted inside 4:3
#: and letterboxed rather than stretched, 29.97 frames a second, then
#: 704x480 with 10:11 pixels, which is 4:3 again on a television.
#:
#: Top field first is ``setfield=tff`` here, not ``-top 1`` in ``ENCODE``
#: as the credits record. ffmpeg 9 removed ``-top`` and refuses the whole
#: command over it, so a clip without its ``.ts`` would not play at all -
#: which is what a fresh Windows install, getting ffmpeg unpinned, gets.
#: On 7.1.1 the two give byte-identical streams.
VIDEO_FILTER = ('bwdif=deint=interlaced,scale=iw*sar:ih,setsar=1,'
                'scale=640:480:force_original_aspect_ratio=decrease'
                ':flags=lanczos,pad=640:480:(ow-iw)/2:(oh-ih)/2,'
                'fps=30000/1001,scale=704:480:flags=lanczos,setsar=10/11,'
                'setfield=tff')

#: MPEG-2 at a constant 15 Mbit/s and AC-3 at 384 kbit/s, muxed with null
#: packets up to ``TS_RATE`` - also exactly as the ``.ts`` files were made.
ENCODE = ['-c:v', 'mpeg2video', '-b:v', '15M', '-minrate', '15M',
          '-maxrate', '15M', '-bufsize', '1835k', '-g', '15', '-bf', '2',
          '-flags', '+ildct+ilme', '-aspect', '4:3',
          '-c:a', 'ac3', '-b:a', '384k', '-ac', '2', '-ar', '48000',
          '-muxrate', str(TS_RATE), '-f', 'mpegts']


def needs_encoding(path):
    """Whether this file has to go through ffmpeg to become a stream."""
    return not path.lower().endswith('.ts')


def atsc_video_files(directory, encode=None):
    """Video the ATSC transmitter can play, as (display name, full path).

    One entry per clip, its ``.ts`` where there is one. Without ffmpeg only
    the ``.ts`` files can be played, so only they are offered; pass
    ``encode=True`` to list everything regardless.
    """
    if encode is None:
        encode = have_ffmpeg()
    return video_files(directory, ATSC_EXTENSIONS if encode else ('.ts',))


def describe(path):
    """What the window says is on the air."""
    name = os.path.basename(path)
    if needs_encoding(path):
        return f"{name} (encoded to MPEG-2 as it plays)"
    return name


class TransportStream:
    """A video file, encoded into an ATSC transport stream, looping forever.

    The pipe is handed to ``blocks.file_descriptor_source``, for the same
    reason ``ntsc_source.AudioTrack`` hands over its own: there is nothing to
    compute, and a Python block whose wrapper is garbage collected takes the
    process down with it.

    It loops inside ffmpeg (``-stream_loop``) rather than by reopening the
    file, so timestamps run straight on across the seam - where a ``.ts``
    looped by a file source jumps back to its start every pass.
    """

    def __init__(self, path, loop=True):
        if not have_ffmpeg():
            raise RuntimeError(
                "Transmitting a video that is not already a transport stream "
                "needs ffmpeg on PATH, and it is not installed.")
        self.path = path
        argv = ['ffmpeg', '-hide_banner', '-loglevel', 'error']
        if loop:
            argv += ['-stream_loop', '-1']
        argv += ['-i', path, '-vf', VIDEO_FILTER] + ENCODE + ['pipe:1']
        self._proc = subprocess.Popen(argv, stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL)

    def fileno(self):
        return self._proc.stdout.fileno()

    def descriptor(self):
        """A duplicate of the pipe, for a block that will close what it is given.

        **Never hand `fileno()` straight to `blocks.file_descriptor_source`.**
        That block closes the descriptor in its destructor, and `close`
        above closes it too, so the two of them close one number twice. The
        second close lands on whatever has been opened in between - and
        what opens in between is the *next* run of the same app, whose
        pipe is handed the lowest free number, which is the one just
        released. So: launch, close, launch again, and the second run's
        sound dies the moment Python collects the first run's flowgraph,
        with ``file_descriptor_source: error: [read]: Bad file
        descriptor``. Reproduced exactly that way.

        A duplicate gives each owner its own number to close.
        """
        return os.dup(self.fileno())

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
        return describe(self.path)
