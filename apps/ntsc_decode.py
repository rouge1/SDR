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
# Annex A equation 10 again, as the decoder needs it: the encoder wrote
# 0.925*Y + 7.5 for luma and 0.925*100*(b-y, r-y) for chroma, in IRE.
CHROMA_GAIN = SETUP_GAIN * IRE_WHITE            # 92.5
LUMA_GAIN = SETUP_GAIN * IRE_WHITE              # 92.5, Y in 0..1


class NtscDecoder:
    """Decode composite baseband into frames."""

    def __init__(self, sample_rate, width=640, active_lines=240):
        self.sample_rate = float(sample_rate)
        self.width = int(width)
        self.active_lines = int(active_lines)

    # -- levels ----------------------------------------------------------

    def levels(self, x):
        """Sync tip and blanking level, read off the signal itself.

        A capture arrives at whatever scale the radio gave it, so nothing can
        be assumed about absolute level. The sync tip is a low percentile,
        robust against spikes; blanking is the commonest level in the lower
        part of the range, because the porches occupy more time than any
        single picture value.
        """
        sync = float(np.percentile(x, 0.5))
        top = float(np.percentile(x, 99.5))
        hist, edges = np.histogram(x, bins=256, range=(sync, top))
        lo, hi = int(0.10 * len(hist)), int(0.60 * len(hist))
        blank = float(edges[lo + int(np.argmax(hist[lo:hi]))])
        return sync, blank

    # -- sync ------------------------------------------------------------

    def find_pulses(self, x, sync, blank):
        """Start index and width in seconds of every excursion to sync level."""
        thresh = sync + SYNC_SLICE * (blank - sync)
        low = x < thresh
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
        """Decode the first whole frame in ``x`` into an RGB array in 0..1."""
        x = np.asarray(x, dtype=np.float64)
        sync, blank = self.levels(x)
        if blank <= sync:
            raise ValueError("no sync found: blanking is not above sync level")
        # (x - blank) * ire_scale puts blanking at 0 IRE and sync at -40.
        ire_scale = -IRE_SYNC / (blank - sync)

        starts, widths = self.find_pulses(x, sync, blank)
        fields = self.find_fields(starts, widths)
        if len(fields) < 2:
            raise ValueError("could not find two fields - no vertical sync?")

        rows = np.zeros((2 * self.active_lines, self.width, 3))
        for parity, f in enumerate(fields[:2]):
            # f is line 10 of the field; the active picture starts at line 21.
            first_active = f + 11
            for k in range(self.active_lines):
                idx = first_active + k
                if idx >= starts.size:
                    break
                y, b_y, r_y = self._sample_line(x, int(starts[idx]), blank,
                                                ire_scale, color)
                rows[2 * k + parity] = self._to_rgb(y, b_y, r_y)
        return np.clip(rows, 0, 1)

    def _sample_line(self, x, h_ref, blank, ire_scale, color):
        """Y and the two colour-difference signals across one active line."""
        n0 = h_ref + int(round(ACTIVE_START * self.sample_rate))
        n1 = n0 + int(round(ACTIVE_LEN * self.sample_rate))
        if n1 > x.size:
            zero = np.zeros(self.width)
            return zero, zero, zero
        seg = (x[n0:n1] - blank) * ire_scale

        pos = np.linspace(0, seg.size - 1, self.width)
        if not color:
            y = np.interp(pos, np.arange(seg.size), seg)
            zero = np.zeros(self.width)
            return (y - IRE_SETUP) / LUMA_GAIN, zero, zero

        # Complex envelope: s(t) = Re{Z e^{jwt}}, so Z = 2*LPF{s e^{-jwt}}.
        t = np.arange(n0, n1) / self.sample_rate
        carrier = np.exp(-2j * np.pi * FSC * t)
        span = max(1, int(round(self.sample_rate / FSC)))
        kernel = np.ones(span) / span
        z = 2.0 * np.convolve(seg * carrier, kernel, mode='same')

        # The burst says what phase this line's subcarrier actually has. The
        # encoder sent -20*sin(wt), whose complex envelope is +20j, so the
        # measured envelope divided by its own unit vector and multiplied by
        # j puts every line back on the same axis.
        b0 = h_ref + int(round(BURST_START * self.sample_rate))
        b1 = b0 + int(round(BURST_LEN * self.sample_rate))
        tb = np.arange(b0, b1) / self.sample_rate
        burst = (x[b0:b1] - blank) * ire_scale
        zb = 2.0 * np.mean(burst * np.exp(-2j * np.pi * FSC * tb))
        if abs(zb) > 1e-9:
            z = z * (1j * abs(zb) / zb)

        # Z = 92.5*(r_y - j*b_y), from the encoder's sin/cos assignment.
        r_y = np.real(z) / CHROMA_GAIN
        b_y = -np.imag(z) / CHROMA_GAIN
        chroma = np.real(z * np.conj(carrier))          # back to a real signal
        luma = seg - chroma

        y = np.interp(pos, np.arange(seg.size), luma)
        b = np.interp(pos, np.arange(seg.size), b_y)
        r = np.interp(pos, np.arange(seg.size), r_y)
        return (y - IRE_SETUP) / LUMA_GAIN, b, r

    def _to_rgb(self, y, b_y, r_y):
        """Undo the reduction factors and the luminance matrix."""
        bmy = b_y / B_Y_SCALE
        rmy = r_y / R_Y_SCALE
        b = bmy + y
        r = rmy + y
        g = (y - KR * r - KB * b) / KG
        return np.stack([r, g, b], axis=-1)
