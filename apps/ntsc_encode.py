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

    def __init__(self, sample_rate, color=True):
        self.sample_rate = float(sample_rate)
        self.color = bool(color)
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

    # -- waveform pieces -------------------------------------------------

    def _vertical_interval(self, half_line, tau_half):
        """Level during the nine-line vertical sync block, in IRE.

        Table 3: three lines of pre-equalizing pulses, three of vertical sync
        with serrations, three of post-equalizing - eighteen half-lines. The
        equalizing pulse is a short sync-level notch; the vertical sync
        half-line is the other way round, sync level all the way except for a
        4.7 us serration that keeps a receiver's line oscillator in step.
        """
        out = np.full(tau_half.shape, IRE_BLANK)
        if half_line < 6 or half_line >= 12:          # equalizing pulses
            out[tau_half < EQUALIZING_WIDTH] = IRE_SYNC
        else:                                         # serrated vertical sync
            out[:] = IRE_SYNC
            out[tau_half >= (LINE / 2 - SERRATION_WIDTH)] = IRE_BLANK
        return out

    def _line_luma(self, tau, active):
        """Sync, blanking and porches for one ordinary line, in IRE."""
        out = np.full(tau.shape, IRE_BLANK)
        out[tau < SYNC_WIDTH] = IRE_SYNC
        if active is not None:
            inside = (tau >= ACTIVE_START) & (tau < ACTIVE_START + ACTIVE_LEN)
            u = (tau[inside] - ACTIVE_START) / ACTIVE_LEN
            col = np.clip((u * active.shape[0]).astype(np.int32),
                          0, active.shape[0] - 1)
            out[inside] = active[col]
        return out

    # -- the encoder -----------------------------------------------------

    def encode_frame(self, rgb):
        """One RGB frame (rows, cols, 3) in 0..1 -> composite samples."""
        rgb = np.asarray(rgb, dtype=np.float64)
        if rgb.ndim != 3 or rgb.shape[2] != 3:
            raise ValueError("expected an (rows, cols, 3) RGB frame")

        y, i_comp, q_comp = self._components(rgb)

        n = self._frame_slice()
        t = n / self.sample_rate
        line_idx = np.floor(t / LINE).astype(np.int64)
        tau = t - line_idx * LINE
        line_in_frame = (line_idx % LINES_PER_FRAME).astype(np.int64)

        out = np.empty(n.shape, dtype=np.float64)
        # Subcarrier from absolute time: 227.5 cycles a line means the burst
        # phase flips every line and the four-field sequence looks after
        # itself. sin carries B-Y, cos carries R-Y (annex A, equation 10).
        phase = 2 * np.pi * FSC * t
        sc_sin, sc_cos = np.sin(phase), np.cos(phase)

        for L in np.unique(line_in_frame):
            m = line_in_frame == L
            tau_m = tau[m]
            line_no = int(L) + 1                      # 1-based, as the spec numbers

            vert = self._vertical_half_line(line_no)
            if vert is not None:
                half, tau_half = vert, tau_m.copy()
                second = tau_half >= LINE / 2
                tau_half[second] -= LINE / 2
                levels = np.empty(tau_m.shape)
                levels[~second] = self._vertical_interval(half, tau_half[~second])
                levels[second] = self._vertical_interval(half + 1, tau_half[second])
                out[m] = ire_to_unit(levels)
                continue

            row = self._active_row(line_no)
            if row is None:
                out[m] = ire_to_unit(self._line_luma(tau_m, None))
                # Burst is carried on every line after the vertical block,
                # blanking or not (clause 13.3).
                if self.color and line_no > 9:
                    out[m] += self._burst(tau_m, sc_sin[m])
                continue

            # Annex A equation 10: 0.925*Y + 7.5, which lands black on setup
            # and white on 100 IRE.
            luma = SETUP_GAIN * (y[row] * IRE_WHITE) + IRE_SETUP
            ire = self._line_luma(tau_m, luma)
            out[m] = ire_to_unit(ire)

            if self.color:
                out[m] += self._chroma(tau_m, i_comp[row], q_comp[row],
                                       sc_sin[m], sc_cos[m])
                out[m] += self._burst(tau_m, sc_sin[m])

        return out

    # -- helpers ---------------------------------------------------------

    def _components(self, rgb):
        """Y and the two reduced colour-difference signals, per active row."""
        r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
        y = KR * r + KG * g + KB * b
        b_y = B_Y_SCALE * (b - y)
        r_y = R_Y_SCALE * (r - y)
        return y, b_y, r_y

    def _active_row(self, line_no):
        """Which row of the frame this line carries, or None if it carries none.

        Field one takes the even rows, field two the odd ones - that is what
        makes the two fields interlace into one picture.
        """
        if FIELD1_FIRST_LINE <= line_no < FIELD1_FIRST_LINE + ACTIVE_LINES_PER_FIELD:
            return 2 * (line_no - FIELD1_FIRST_LINE)
        if FIELD2_FIRST_LINE <= line_no < FIELD2_FIRST_LINE + ACTIVE_LINES_PER_FIELD:
            return 2 * (line_no - FIELD2_FIRST_LINE) + 1
        return None

    def _vertical_half_line(self, line_no):
        """Index of this line's first half-line within the nine-line block.

        None if the line is an ordinary one. Returns 0 for the first line of
        the block, so callers must test ``is not None`` rather than truth.
        """
        if 1 <= line_no <= 9:
            return 2 * (line_no - 1)
        if 264 <= line_no <= 272:
            return 2 * (line_no - 264)
        return None

    def _burst(self, tau, sc_sin):
        """Nine cycles on the back porch, at -(B-Y): 180 degrees from +sin."""
        out = np.zeros(tau.shape)
        m = (tau >= BURST_START) & (tau < BURST_START + BURST_LEN)
        out[m] = -BURST_AMPLITUDE * sc_sin[m] / (IRE_WHITE - IRE_SYNC)
        return out

    def _chroma(self, tau, b_y_row, r_y_row, sc_sin, sc_cos):
        out = np.zeros(tau.shape)
        m = (tau >= ACTIVE_START) & (tau < ACTIVE_START + ACTIVE_LEN)
        u = (tau[m] - ACTIVE_START) / ACTIVE_LEN
        col = np.clip((u * b_y_row.shape[0]).astype(np.int32),
                      0, b_y_row.shape[0] - 1)
        amp = SETUP_GAIN * IRE_WHITE / (IRE_WHITE - IRE_SYNC)
        out[m] = amp * (b_y_row[col] * sc_sin[m] + r_y_row[col] * sc_cos[m])
        return out
