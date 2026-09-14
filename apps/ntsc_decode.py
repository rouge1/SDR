#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NTSC composite video decoder - the other half of ``ntsc_encode``.

Takes composite baseband samples and gives back pictures: finds sync, locks
the line and field structure, samples the active line into pixels, and
demodulates chroma against the colour burst.

It exists to *check* the encoder, the way ``rds_core`` checks ``rds_encode``.
``scripts/test_ntsc_loopback.py`` runs a frame through both and compares the
picture that comes back with the one that went in, so a timing or phase
mistake shows up as a number rather than as "the TV looked wrong".

Free of GNU Radio and Qt, so it also runs against a recorded capture.

Two things worth knowing before changing it:

**Sync is found by pulse width, not by level.** Equalizing pulses (2.3 us),
horizontal sync (4.7 us) and the vertical serrations all sit at exactly the
same level, so a threshold crossing says nothing about which is which.
How long the signal stays down is what separates the start of a field from
the start of a line.

**Colour is measured against the burst, never against the sample clock.**
The burst is nine cycles of the subcarrier at a known phase, sent on every
line for exactly this purpose: it says where the subcarrier's zero crossing
is *on this line*, which is the only way to know what the chroma phase on
that line means. Decoding against a locally generated subcarrier instead
gets the hue wrong by however much the sampling origin happened to differ.
"""

import numpy as np

from apps.ntsc_encode import (
    ACTIVE_LEN, ACTIVE_START, B_Y_SCALE, BURST_AMPLITUDE, BURST_LEN,
    BURST_START, EQUALIZING_WIDTH, FSC, IRE_SETUP, IRE_SYNC, IRE_WHITE, KB,
    KG, KR, LINE, R_Y_SCALE, SETUP_GAIN, SYNC_WIDTH,
)

# A pulse longer than this is a horizontal sync rather than an equalizer.
SYNC_DISCRIMINANT = (EQUALIZING_WIDTH + SYNC_WIDTH) / 2
# Stay at sync level longer than this and it is a vertical serration.
VERTICAL_RUN = 10e-6

# Where to slice sync from vision, as a fraction of the way from sync tip to
# blanking. **Not the half-way point**, which is -20 IRE - and -20 IRE is
# exactly how far down a *legal* picture is allowed to swing, so saturated
# colour sat on that floor put false sync pulses in the middle of the
# active line. Since lines are numbered by counting pulses, one spurious
# pulse shifts every line after it and the picture comes out sheared. 0.35
# of the way up is -26 IRE, which leaves six IRE of daylight.
SYNC_SLICE = 0.35
# No sync pulse of any kind is shorter than an equalizing pulse's 2.3 us, so
# anything much shorter is ringing or noise crossing the slice level.
SYNC_MIN_WIDTH = 1.5e-6
#: How much averaging the sync separator does before slicing. Long enough to
#: bury the colour subcarrier and the noise, short enough to leave a 4.7 us
#: pulse its shape.
SYNC_SEPARATOR = 0.5e-6

# How many ordinary lines pass between the first one after a vertical block
# and the first line of active picture. They differ by one between the two
# fields - see decode_frame - which is what makes the interlace work.
FIELD1_LINE_OFFSET = 11         # block ends at line 9, picture starts at 21
FIELD2_LINE_OFFSET = 10         # block ends at line 272, picture starts at 283
# Annex A equation 10 again, as the decoder needs it: the encoder wrote
# 0.925*Y + 7.5 for luma and 0.925*100*(b-y, r-y) for chroma, in IRE.
CHROMA_GAIN = SETUP_GAIN * IRE_WHITE            # 92.5
LUMA_GAIN = SETUP_GAIN * IRE_WHITE              # 92.5, Y in 0..1


def _box_filter(a, span):
    """Row-wise moving average, matching ``np.convolve(row, box, 'same')``.

    A prefix sum rather than a convolution: the kernel is uniform, so every
    output is one subtraction, and it runs on the whole field of lines at
    once instead of once per line.
    """
    if span <= 1:
        return a.copy()
    n = a.shape[1]
    totals = np.concatenate(
        [np.zeros((a.shape[0], 1), dtype=a.dtype), np.cumsum(a, axis=1)],
        axis=1)
    # np.convolve's 'same' takes the middle of the full convolution, which
    # starts (span-1)//2 in.
    centre = np.arange(n) + (span - 1) // 2
    hi = np.minimum(n, centre + 1)
    lo = np.maximum(0, centre - span + 1)
    return (totals[:, hi] - totals[:, lo]) / span


def chroma_span(sample_rate, max_cycles=8):
    """Averaging length whose null lands on the colour subcarrier.

    Chroma is pulled out with a box filter, and a box of length L has its
    first null at ``sample_rate / L`` - so the length has to be chosen so
    that a null falls on 3.579545 MHz, not merely near it.

    The obvious ``round(fs / FSC)`` only works when the sample rate happens
    to be a whole multiple of the subcarrier. At 4x subcarrier - 14.318 MS/s,
    which the loopback test uses - it is exact, and the colour comes back
    within 0.01. At 10 MS/s it gives 3 samples, whose null is at 3.333 MHz,
    246 kHz adrift, and the error is fifteen times worse. Averaging over
    several subcarrier cycles instead lets the null land almost exactly: five
    cycles is 14 samples at 10 MS/s, which is 8 kHz out.

    The cost is horizontal chroma resolution, and NTSC has little to spare -
    but the standard already limits chroma to about 1.3 MHz, so a filter
    this wide is close to what the signal carries anyway.
    """
    best = None
    for cycles in range(1, max_cycles + 1):
        span = max(1, int(round(cycles * sample_rate / FSC)))
        error = abs(cycles * sample_rate / span - FSC)
        if best is None or error < best[0]:
            best = (error, span)
    return best[1]


class NtscDecoder:
    """Decode composite baseband into frames."""

    def __init__(self, sample_rate, width=640, active_lines=240):
        self.sample_rate = float(sample_rate)
        self.width = int(width)
        self.active_lines = int(active_lines)
        self.chroma_span = chroma_span(self.sample_rate)

    # -- levels ----------------------------------------------------------

    def levels(self, x):
        """Sync tip and blanking level, read off the signal itself.

        A capture arrives at whatever scale the radio gave it, so nothing can
        be assumed about absolute level. The sync tip is a low percentile,
        robust against spikes; blanking is the commonest single level,
        because the porches occupy about 18% of every line at exactly one
        value while picture content is spread over many.

        **Where blanking sits in the range depends on the picture, and
        bounding the search by a fraction of that range is what broke it.**
        The window used to be the 10-60% band of sync-to-white, which is
        right for an ordinary picture: blanking came out at 45% of the
        range. But the top of the range is the *brightest thing in this
        buffer*, so on a dark scene it collapses toward blanking and
        blanking moves to 89% of what is left - outside the window
        entirely. The estimate then landed on dark picture content a
        thousandth above the sync tip, the slicer had nothing to slice, and
        `find_pulses` returned no pulses at all. Off air that cost about a
        second of picture every time the clip reached a dark shot: 17
        consecutive frames, always the same exception, and nothing wrong
        with the signal - the input level never moved.
        `scripts/test_ntsc_loopback.py` reproduces it with no radio.

        The window is 5-98% now, and `decode_frame` refines the answer on
        the back porch afterwards, which is what a television clamps on and
        is independent of the picture altogether.
        """
        # Every fourth sample is plenty: a frame is a third of a million of
        # them and this only needs two percentiles and a histogram, while
        # np.percentile on the lot was a sixth of the whole decode.
        sample = x[::4] if x.size > 40000 else x
        sync = float(np.percentile(sample, 0.5))
        top = float(np.percentile(sample, 99.5))
        hist, edges = np.histogram(sample, bins=256, range=(sync, top))
        lo, hi = int(0.05 * len(hist)), int(0.98 * len(hist))
        blank = float(edges[lo + int(np.argmax(hist[lo:hi]))])
        return sync, blank

    #: Where to read blanking once the sync pulses are known: the breezeway,
    #: between the trailing edge of sync and the start of the colour burst.
    #: The burst begins 0.6 us after sync ends, so this stops well short.
    BREEZEWAY = (0.1e-6, 0.5e-6)

    def back_porch_level(self, x, starts, widths, fallback):
        """Blanking, measured where a television measures it.

        Every real receiver clamps on the back porch, because it is the one
        part of the line whose level is fixed by the standard rather than
        by the picture. Once `find_pulses` has found the sync pulses, the
        breezeway just after each one gives blanking directly - no
        histogram, no assumption about how bright the scene is.

        Only full-width horizontal sync counts: an equalizing pulse is too
        narrow and a vertical serration too wide, and neither is followed
        by a porch - what comes after them is more sync.
        """
        horizontal = (widths > SYNC_DISCRIMINANT) & (widths < VERTICAL_RUN)
        if horizontal.sum() < 8:
            return fallback
        ends = starts[horizontal] + (widths[horizontal] * self.sample_rate)
        lo = (ends + self.BREEZEWAY[0] * self.sample_rate).astype(np.int64)
        hi = (ends + self.BREEZEWAY[1] * self.sample_rate).astype(np.int64)
        span = int(np.median(hi - lo))
        if span < 2:
            return fallback
        lo = lo[hi < x.size]
        if lo.size < 8:
            return fallback
        windows = x[lo[:, None] + np.arange(span)[None, :]]
        return float(np.median(windows))

    # -- sync ------------------------------------------------------------

    def find_pulses(self, x, sync, blank):
        """Start index and width in seconds of every excursion to sync level.

        **Slicing the signal as it arrives does not work off the air.** Sync
        is a low-frequency feature but the composite it sits in carries the
        3.58 MHz colour subcarrier and whatever noise the radio added, and
        those cross the slice level over and over inside a single pulse. A
        real capture came back with its longest run at 9.8 us where the
        vertical block's are 27.1, chopped into fragments, and no field was
        ever found. Every television has a sync separator in front of its
        slicer for exactly this reason; half a microsecond of averaging is
        enough, and it recovers the 27.10 us runs exactly.
        """
        span = max(1, int(round(SYNC_SEPARATOR * self.sample_rate)))
        detect = (np.convolve(x, np.ones(span) / span, 'same') if span > 1
                  else x)
        thresh = sync + SYNC_SLICE * (blank - sync)
        low = detect < thresh
        edges = np.diff(low.astype(np.int8))
        starts = np.flatnonzero(edges == 1) + 1
        ends = np.flatnonzero(edges == -1) + 1
        if ends.size and starts.size and ends[0] < starts[0]:
            ends = ends[1:]
        n = min(starts.size, ends.size)
        starts, ends = starts[:n], ends[:n]
        widths = (ends - starts) / self.sample_rate
        # Drop anything too brief to be a sync pulse. Lines are numbered by
        # counting these, so a single spurious one shears everything after.
        keep = widths >= SYNC_MIN_WIDTH
        return starts[keep], widths[keep]

    def find_fields(self, starts, widths):
        """Index of the first horizontal sync after each vertical block.

        The nine-line vertical block is the only place the signal sits at
        sync level for most of a half-line at a time. Those long runs mark a
        field; the first full-width sync after the post-equalizing pulses is
        line 10, from which the active picture is counted.
        """
        longs = np.flatnonzero(widths > VERTICAL_RUN)
        if longs.size == 0:
            return []
        groups = np.split(longs, np.flatnonzero(np.diff(longs) > 3) + 1)
        fields = []
        for g in groups:
            after = int(g[-1]) + 1
            while after < widths.size and widths[after] < SYNC_DISCRIMINANT:
                after += 1                    # skip the post-equalizing pulses
            if after < widths.size:
                fields.append(after)
        return fields

    # -- picture ---------------------------------------------------------

    def decode_frame(self, x, color=True):
        """Decode the first whole frame in ``x`` into an RGB array in 0..1.

        **Every active line of a field is sampled at once.** This used to
        take one line at a time in a Python loop - 480 of them per frame,
        each with its own convolution and three interpolations - and ran at
        0.54x real time, 16 frames a second against the 29.97 a receiver
        needs. The lines are all the same length and all want the same
        operations, so they go into one 2-D array instead.
        """
        x = np.asarray(x, dtype=np.float64)
        sync, blank = self.levels(x)
        if blank <= sync:
            raise ValueError("no sync found: blanking is not above sync level")

        starts, widths = self.find_pulses(x, sync, blank)
        # Now that the pulses are known, take blanking off the back porch
        # rather than off a histogram. The histogram is a guess about where
        # blanking sits among the picture levels; the porch is the
        # standard's own reference and does not move with the picture. It
        # is what sets the IRE scale, and getting it exactly right took the
        # loopback colour error from 0.0089 to about 1e-11.
        refined = self.back_porch_level(x, starts, widths, blank)
        if refined > sync:
            # Slicing again is almost never worth it, and costs a fifth of
            # the whole decode. The slice sits at 35% of the way from sync
            # to blanking, so it stays well inside the pulses even when the
            # first estimate was off by the 19% that black setup routinely
            # puts it out by - measured off air, 883 pulses either way.
            # This is only a guard for an estimate that was wildly wrong.
            moved = abs(refined - blank) > 0.5 * (blank - sync)
            blank = refined
            if moved:
                starts, widths = self.find_pulses(x, sync, blank)
        # (x - blank) * ire_scale puts blanking at 0 IRE and sync at -40.
        ire_scale = -IRE_SYNC / (blank - sync)

        fields = self.find_fields(starts, widths)
        if len(fields) < 2:
            raise ValueError("could not find two fields - no vertical sync?")

        # **Which field came first has to be worked out, not assumed.** A
        # capture starts wherever it starts, so the first vertical block in
        # it is field one about half the time and field two the rest. Put
        # field two's lines on the even rows and the picture is offset by a
        # line - every edge grows a comb, and the error roughly trebles.
        #
        # The two blocks are not evenly spaced: a field is 262.5 lines, so
        # consecutive vertical blocks are 263 lines apart and then 262. A
        # gap of 263 to the next one means this block is field one.
        lines_between = ((starts[fields[1]] - starts[fields[0]])
                         / (LINE * self.sample_rate))
        swap = 0 if lines_between > 262.5 else 1

        rows = np.zeros((2 * self.active_lines, self.width, 3))
        for parity, f in enumerate(fields[:2]):
            parity = (parity + swap) % 2
            # **The two fields do not start the same number of lines after
            # their vertical block.** Field one's block is lines 1-9 and its
            # picture starts at line 21, eleven lines later; field two's
            # block is lines 264-272 and its picture starts at 283, which is
            # ten. Using eleven for both - which this did - puts half the
            # picture one line low, so every horizontal edge grows a comb.
            # Measured against horizontal stripes, 11/10 beats 11/11 by
            # nearly two to one.
            k = np.arange(self.active_lines)
            pulse = f + (FIELD1_LINE_OFFSET if parity == 0
                         else FIELD2_LINE_OFFSET) + k
            keep = pulse < starts.size
            k, pulse = k[keep], pulse[keep]
            if k.size == 0:
                continue
            y, b_y, r_y = self._sample_lines(x, starts[pulse], blank,
                                             ire_scale, color)
            rows[2 * k + parity] = self._to_rgb(y, b_y, r_y)
        return np.clip(rows, 0, 1)

    def _sample_lines(self, x, h_refs, blank, ire_scale, color):
        """Y and the colour-difference signals for a whole field of lines.

        Returns three ``(lines, width)`` arrays.
        """
        seg_len = int(round(ACTIVE_LEN * self.sample_rate))
        start = h_refs + int(round(ACTIVE_START * self.sample_rate))
        # A line whose segment would run off the end of the capture reads as
        # black rather than wrapping round to the beginning.
        usable = (start >= 0) & (start + seg_len <= x.size)
        at = np.clip(start[:, None] + np.arange(seg_len)[None, :],
                     0, x.size - 1)
        seg = (x[at] - blank) * ire_scale
        seg[~usable] = 0.0

        # The same resampling positions for every line, so the interpolation
        # is two gathers and a blend rather than 480 calls to np.interp.
        pos = np.linspace(0, seg_len - 1, self.width)
        lo = np.floor(pos).astype(np.int64)
        hi = np.minimum(lo + 1, seg_len - 1)
        frac = pos - lo

        def resample(a):
            return a[:, lo] * (1.0 - frac) + a[:, hi] * frac

        if not color:
            zero = np.zeros((h_refs.size, self.width))
            return (resample(seg) - IRE_SETUP) / LUMA_GAIN, zero, zero

        # Complex envelope: s(t) = Re{Z e^{jwt}}, so Z = 2*LPF{s e^{-jwt}}.
        carrier = np.exp(-2j * np.pi * FSC * at / self.sample_rate)
        z = 2.0 * _box_filter(seg * carrier, self.chroma_span)

        # The burst says what phase this line's subcarrier actually has. The
        # encoder sent -20*sin(wt), whose complex envelope is +20j, so the
        # measured envelope divided by its own unit vector and multiplied by
        # j puts every line back on the same axis.
        b_len = int(round(BURST_LEN * self.sample_rate))
        b_at = np.clip(h_refs[:, None] + int(round(BURST_START * self.sample_rate))
                       + np.arange(b_len)[None, :], 0, x.size - 1)
        burst = (x[b_at] - blank) * ire_scale
        zb = 2.0 * np.mean(
            burst * np.exp(-2j * np.pi * FSC * b_at / self.sample_rate), axis=1)
        rotate = np.ones(h_refs.size, dtype=np.complex128)
        found = np.abs(zb) > 1e-9
        rotate[found] = 1j * np.abs(zb[found]) / zb[found]
        z = z * rotate[:, None]

        # Z = 92.5*(r_y - j*b_y), from the encoder's sin/cos assignment.
        r_y = np.real(z) / CHROMA_GAIN
        b_y = -np.imag(z) / CHROMA_GAIN
        chroma = np.real(z * np.conj(carrier))          # back to a real signal
        luma = seg - chroma

        return ((resample(luma) - IRE_SETUP) / LUMA_GAIN,
                resample(b_y), resample(r_y))

    def _to_rgb(self, y, b_y, r_y):
        """Undo the reduction factors and the luminance matrix."""
        bmy = b_y / B_Y_SCALE
        rmy = r_y / R_Y_SCALE
        b = bmy + y
        r = rmy + y
        g = (y - KR * r - KB * b) / KG
        return np.stack([r, g, b], axis=-1)
