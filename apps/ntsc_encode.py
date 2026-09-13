#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NTSC composite video encoder, to SMPTE 170M-2004.

Turns ordinary video frames into a 525-line, 2:1 interlaced composite
baseband signal - sync, blanking, equalizing pulses, serrations, colour
burst and a quadrature-modulated chroma subcarrier - at whatever sample
rate the caller asks for.

Like ``rds_encode``, this is free of GNU Radio and Qt so it can be tested
without a radio: ``scripts/test_ntsc_loopback.py`` runs it into the decoder
and compares the picture that comes back.

Two things drive the whole design:

**The signal is generated from absolute time, not from a sample count per
line.** A line is 63.5556 us, which is not a whole number of samples at any
rate anybody wants to transmit at - 635.56 samples at 10 MS/s. Rounding it
per line accumulates error until the picture shears. So every sample knows
its own time ``n / sample_rate``, and the line it belongs to is worked out
from that. Nothing drifts, and any sample rate works.

**Subcarrier phase comes from that same absolute time.** There are exactly
227.5 subcarrier cycles per line (clause 11.2), so the burst phase inverts
line to line and the whole pattern repeats every four fields, all by itself
- no per-line bookkeeping, no chance of the colour-frame sequence slipping.

Levels are IRE units (table 1): sync -40, blanking 0, black 7.5, white 100.
The output is scaled so sync tip is 0.0 and white is 1.0, which is what
``ntscAnalogVideoRecorded`` expects to modulate.
"""

import numpy as np

# Clause 11: everything descends from the colour subcarrier.
FSC = 315e6 / 88                     # 3.579545... MHz
FH = 2 * FSC / 455                   # 15734.265... Hz line rate
LINE = 1.0 / FH                      # 63.5556... us
LINES_PER_FRAME = 525
FRAME = LINES_PER_FRAME * LINE       # 33.3667 ms

# Table 2, horizontal timing. Times are from the horizontal reference point,
# which is the 50% point of the falling edge of sync.
SYNC_WIDTH = 4.70e-6
BLANK_END = 9.20e-6                  # h. ref to end of blanking
BLANK_START = 1.5e-6                 # blanking starts this far before h. ref
BURST_START = 19 / FSC               # 19 cycles, 5.308 us
BURST_CYCLES = 9
BURST_LEN = BURST_CYCLES / FSC
ACTIVE_START = BLANK_END
ACTIVE_LEN = LINE - BLANK_END - BLANK_START      # 52.856 us

# Table 3, vertical timing.
EQUALIZING_WIDTH = 2.30e-6
SERRATION_WIDTH = 4.70e-6            # the blanking-level gap in vertical sync
VERT_BLANK_LINES = 20

# Table 1, levels in IRE.
IRE_SYNC = -40.0
IRE_BLANK = 0.0
IRE_SETUP = 7.5
IRE_WHITE = 100.0
BURST_AMPLITUDE = 20.0               # 40 IRE peak to peak

# How far the composite signal is allowed to swing once chroma is added to
# luma. Saturated colour legitimately overshoots 100 IRE - 100% yellow and
# cyan reach about 131 - and undershoots below blanking by as much, and a
# transmitter cannot carry that: past 120 IRE it drives the carrier through
# zero, and below -20 IRE the picture reaches down to *sync level*, where a
# receiver stops being able to tell sync from vision at all. Broadcasters
# run a "legalizer" for exactly this. These are its limits; -20 IRE is also
# precisely the bottom of the colour burst, so it never touches that.
IRE_PEAK = 120.0
IRE_TROUGH = -20.0

# Annex A: luminance matrix, and the reduction factors that keep chroma
# excursions inside what 1950s transmitters could carry.
KR, KG, KB = 0.299, 0.587, 0.114
B_Y_SCALE = 0.492111
R_Y_SCALE = 0.877283
SETUP_GAIN = 0.925                   # 0.925*Y + 7.5 puts black at setup

# Active picture. 240 lines per field, the usual 480-line frame inside the
# 243 the standard leaves room for.
ACTIVE_LINES_PER_FIELD = 240
FIELD1_FIRST_LINE = 21               # 1-based, after the 20 blanked lines
FIELD2_FIRST_LINE = 283


def ire_to_unit(ire):
    """IRE to the 0..1 the transmitter modulates: sync tip 0, white 1."""
    return (ire - IRE_SYNC) / (IRE_WHITE - IRE_SYNC)


class NtscEncoder:
    """Encode frames as NTSC composite baseband.

    ``encode_frame`` takes one progressive RGB frame and returns the samples
    for a whole 525-line frame - both fields, odd rows in the first, even in
    the second. Call it repeatedly; timing carries across calls.
    """

    def __init__(self, sample_rate, color=True, legalize=True):
        self.sample_rate = float(sample_rate)
        self.color = bool(color)
        #: Hold the active picture inside what a transmitter can carry. On
        #: by default; the only reason to turn it off is to measure how far
        #: a signal would have swung without it.
        self.legalize = bool(legalize)
        self._n = 0                  # absolute sample index, never reset

    # -- timing ---------------------------------------------------------

    def _frame_slice(self):
        """Sample indices whose time falls in the next frame.

        Half-open on time, so consecutive frames neither overlap nor leave a
        gap however the boundary lands between samples.
        """
        start_time = self._n / self.sample_rate
        end_time = (np.floor(start_time / FRAME) + 1) * FRAME
        n_end = int(np.ceil(end_time * self.sample_rate))
        n = np.arange(self._n, n_end, dtype=np.int64)
        self._n = n_end
        return n

    # -- the encoder -----------------------------------------------------

    def encode_frame(self, rgb):
        """One RGB frame (rows, cols, 3) in 0..1 -> composite samples.

        **Every sample of the frame is computed at once.** This used to walk
        the 525 lines in a Python loop, selecting each line's samples with
        ``line_in_frame == L`` - a comparison across the whole frame, 525
        times over, which makes the work O(samples x lines) rather than
        O(samples). At 10 MS/s that ran at 0.14x real time, so the encoder
        could not have fed a radio live however fast the machine was. Doing
        it in whole-frame array operations is about 60x quicker and produces
        bit-for-bit the same samples.
        """
        rgb = np.asarray(rgb, dtype=np.float64)
        if rgb.ndim != 3 or rgb.shape[2] != 3:
            raise ValueError("expected an (rows, cols, 3) RGB frame")

        y, b_y, r_y = self._components(rgb)
        rows, cols = y.shape

        n = self._frame_slice()
        t = n / self.sample_rate
        line_idx = np.floor(t / LINE).astype(np.int64)
        tau = t - line_idx * LINE
        line_no = (line_idx % LINES_PER_FRAME).astype(np.int64) + 1   # 1-based

        ire = np.full(n.shape, IRE_BLANK)

        # -- the two nine-line vertical blocks ---------------------------
        #
        # Table 3: three lines of pre-equalizing pulses, three of vertical
        # sync with serrations, three of post-equalizing - eighteen
        # half-lines. An equalizing pulse is a short sync-level notch; a
        # vertical sync half-line is the other way round, sync level all the
        # way except for a 4.7 us serration that keeps a receiver's line
        # oscillator in step.
        first = (line_no >= 1) & (line_no <= 9)
        vertical = first | ((line_no >= 264) & (line_no <= 272))
        # Only eighteen lines of 525 are in these blocks, so the arithmetic
        # is done on just those samples rather than across the whole frame.
        block = np.flatnonzero(vertical)
        if block.size:
            tau_v = tau[block]
            late = tau_v >= LINE / 2                   # the second half-line
            half = (np.where(first[block], 2 * (line_no[block] - 1),
                             2 * (line_no[block] - 264))
                    + late.astype(np.int64))
            tau_half = tau_v - np.where(late, LINE / 2, 0.0)
            equalizing = (half < 6) | (half >= 12)
            ire[block] = np.where(
                equalizing,
                np.where(tau_half < EQUALIZING_WIDTH, IRE_SYNC, IRE_BLANK),
                np.where(tau_half >= (LINE / 2 - SERRATION_WIDTH),
                         IRE_BLANK, IRE_SYNC))

        # -- every other line: sync pulse, then blanking ------------------
        ordinary = ~vertical
        ire[ordinary & (tau < SYNC_WIDTH)] = IRE_SYNC

        # -- the active picture ------------------------------------------
        #
        # Field one takes the even rows, field two the odd ones - that is
        # what makes the two fields interlace into one picture.
        row = np.full(line_no.shape, -1, dtype=np.int64)
        in_f1 = ((line_no >= FIELD1_FIRST_LINE)
                 & (line_no < FIELD1_FIRST_LINE + ACTIVE_LINES_PER_FIELD))
        in_f2 = ((line_no >= FIELD2_FIRST_LINE)
                 & (line_no < FIELD2_FIRST_LINE + ACTIVE_LINES_PER_FIELD))
        row[in_f1] = 2 * (line_no[in_f1] - FIELD1_FIRST_LINE)
        row[in_f2] = 2 * (line_no[in_f2] - FIELD2_FIRST_LINE) + 1

        active = ((row >= 0) & (row < rows)
                  & (tau >= ACTIVE_START) & (tau < ACTIVE_START + ACTIVE_LEN))
        here = np.flatnonzero(active)
        u = (tau[here] - ACTIVE_START) / ACTIVE_LEN
        col = np.clip((u * cols).astype(np.int32), 0, cols - 1)
        pixel_row = row[here]
        # Annex A equation 10: 0.925*Y + 7.5, which lands black on setup and
        # white on 100 IRE.
        ire[here] = SETUP_GAIN * (y[pixel_row, col] * IRE_WHITE) + IRE_SETUP

        out = ire_to_unit(ire)

        if self.color:
            # The subcarrier comes from absolute time - 227.5 cycles a line,
            # so the burst phase flips line to line and the four-field
            # sequence looks after itself - but only where it is actually
            # used, which is the active picture and the burst. A sine over
            # the whole frame was most of what was left of the cost, and in
            # monochrome it was computed and then thrown away entirely.
            phase = 2 * np.pi * FSC * t[here]
            amp = SETUP_GAIN * IRE_WHITE / (IRE_WHITE - IRE_SYNC)
            out[here] += amp * (b_y[pixel_row, col] * np.sin(phase)
                                + r_y[pixel_row, col] * np.cos(phase))
            # Burst is carried on every line after the vertical block,
            # blanking or not (clause 13.3).
            burst = np.flatnonzero(
                ordinary & (line_no > 9)
                & (tau >= BURST_START) & (tau < BURST_START + BURST_LEN))
            out[burst] += (-BURST_AMPLITUDE
                           * np.sin(2 * np.pi * FSC * t[burst])
                           / (IRE_WHITE - IRE_SYNC))

        if self.legalize and here.size:
            # Only the active picture: sync and blanking are already where
            # they belong, and clamping them would flatten the sync pulses.
            out[here] = np.clip(out[here], ire_to_unit(IRE_TROUGH),
                                ire_to_unit(IRE_PEAK))

        return out

    # -- helpers ---------------------------------------------------------

    def _components(self, rgb):
        """Y and the two reduced colour-difference signals, per active row."""
        r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
        y = KR * r + KG * g + KB * b
        b_y = B_Y_SCALE * (b - y)
        r_y = R_Y_SCALE * (r - y)
        return y, b_y, r_y

    def frame_samples(self):
        """Roughly how many samples a frame takes, for sizing buffers."""
        return int(round(FRAME * self.sample_rate))
