#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Composite video encoder: NTSC to SMPTE 170M-2004, PAL to ITU-R BT.1700.

Turns ordinary video frames into an interlaced composite baseband signal -
sync, blanking, equalizing pulses, serrations, colour burst and a
quadrature-modulated chroma subcarrier - at whatever sample rate the caller
asks for. NTSC is 525 lines at 29.97 frames a second; PAL is 625 at 25,
with its V axis switched line by line. The module keeps the name it had
when it did only NTSC, because everything that imports its NTSC constants
still does.

Like ``rds_encode``, this is free of GNU Radio and Qt so it can be tested
without a radio: ``scripts/test_ntsc_loopback.py`` and
``scripts/test_pal_loopback.py`` run it into the decoder and compare the
picture that comes back.

Two things drive the whole design:

**The signal is generated from absolute time, not from a sample count per
line.** A line is 63.5556 us in NTSC, which is not a whole number of samples
at any rate anybody wants to transmit at - 635.56 samples at 10 MS/s.
Rounding it per line accumulates error until the picture shears. So every
sample knows its own time ``n / sample_rate``, and the line it belongs to is
worked out from that. Nothing drifts, and any sample rate works.

**Subcarrier phase comes from that same absolute time.** NTSC has exactly
227.5 subcarrier cycles per line (SMPTE 170M clause 11.2), so the burst phase
inverts line to line and the pattern repeats every four fields; PAL's
283.75 cycles plus 25 Hz gives its eight-field sequence the same way. No
per-line bookkeeping, no chance of the colour-frame sequence slipping.

**What differs between the two is a table, not code.** `VideoStandard`
holds each one's timing, levels, colour axes and - the only structural
difference - which half-lines of the frame carry equalizing pulses, broad
field-sync pulses, or nothing. NTSC's levels are in IRE (sync -40, blanking
0, black 7.5, white 100) and PAL's in millivolts (sync -300, blanking 0,
white 700); either way the output is scaled so sync tip is 0.0 and white is
1.0, which is what the transmitters expect to modulate.
"""

import math
from dataclasses import dataclass

import numpy as np

# --- NTSC, SMPTE 170M-2004 ----------------------------------------------------

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


# --- PAL, ITU-R BT.1700 Part B, 625 lines -------------------------------------

#: Table 1 items 2, 5 and 6. The subcarrier is 283.75 cycles a line plus
#: 25 Hz, which is what gives PAL its eight-field colour sequence.
PAL_FH = 15625.0
PAL_FSC = (1135 / 4 + 1 / 625) * PAL_FH          # 4 433 618.75 Hz
PAL_LINE = 1.0 / PAL_FH                          # 64 us
PAL_FRAME = 625 * PAL_LINE                       # 40 ms

# --- the two standards, as tables ----------------------------------------------

#: What a half-line of the frame carries.
ORDINARY = 0        # a line sync pulse at the start of the line, if a first half
EQUALIZING = 1      # a narrow pulse at the start of the half-line
BROAD = 2           # sync level for the whole half-line but a serration at its end
NO_PULSE = 3        # blanking, no pulse at all


@dataclass(frozen=True)
class VideoStandard:
    """Everything the encoder and decoder need to know about one standard.

    Levels are in the standard's own units - IRE for NTSC, millivolts for
    PAL - so the arithmetic that turns them into 0..1 is the same for both
    and NTSC's output is bit for bit what it was before PAL existed.
    """

    key: str
    label: str
    lines: int
    line_rate: float
    subcarrier: float
    sync_width: float
    equalizing_width: float
    serration_width: float
    #: Blanking starts this far before the horizontal reference.
    blank_start: float
    #: Horizontal reference to the end of blanking.
    active_start: float
    burst_start: float
    burst_cycles: int
    # Levels, native units.
    sync_level: float
    blank_level: float
    black_level: float
    white_level: float
    #: Luma is ``luma_gain * (Y * white_level) + black_level``.
    luma_gain: float
    burst_amplitude: float
    trough_level: float
    peak_level: float
    #: Colour-difference reduction factors on B-Y and R-Y.
    u_scale: float
    v_scale: float
    #: PAL: the V component, and the burst's V half, change sign every line.
    v_switch: bool
    active_lines_per_field: int
    field1_first_line: int
    field2_first_line: int
    #: {line: (first half, second half)} for every line that is not ORDINARY.
    vertical: tuple
    #: The picture an active line is sampled into, square pixels.
    width: int
    height: int
    #: Nominal top of the video band.
    video_band: float

    @property
    def line(self):
        return 1.0 / self.line_rate

    @property
    def frame(self):
        return self.lines * self.line

    @property
    def frame_rate(self):
        return 1.0 / self.frame

    @property
    def active_len(self):
        return self.line - self.active_start - self.blank_start

    @property
    def burst_len(self):
        return self.burst_cycles / self.subcarrier

    @property
    def span(self):
        """Sync tip to white, native units: what 1.0 at the output is."""
        return self.white_level - self.sync_level

    def to_unit(self, level):
        return (level - self.sync_level) / self.span

    @property
    def blank(self):
        return self.to_unit(self.blank_level)

    @property
    def black(self):
        return self.to_unit(self.black_level)

    @property
    def chroma_gain(self):
        """Output units per unit of reduced colour difference."""
        return self.luma_gain * self.white_level / self.span

    @property
    def unit_luma_gain(self):
        """Output units per unit of Y."""
        return self.luma_gain * self.white_level / self.span

    def half_line_types(self):
        """One entry per half-line of the frame: ORDINARY, EQUALIZING, ..."""
        table = np.full(2 * self.lines, ORDINARY, dtype=np.int8)
        for line, (first, second) in self.vertical:
            table[2 * (line - 1)] = first
            table[2 * (line - 1) + 1] = second
        return table

    def burst_lines(self):
        """Whether each line carries a colour burst: only whole ordinary lines.

        NTSC carries none during the nine-line vertical sync block (clause
        13.3), and that is exactly the lines with anything but ordinary
        halves. PAL's standard blanks the burst on a sequence that moves
        field by field (BT.1700 Figs. 8 and 9), so that the first burst after
        field sync always has the same phase; this blanks it on the lines of
        the field-sync blocks only. A receiver locked to the line-by-line
        swing does not need the sequence, and a decoder that reads each
        line's own burst would lose colour on any active line it blanked.
        """
        types = self.half_line_types().reshape(self.lines, 2)
        return np.all(types == ORDINARY, axis=1)

    def first_ordinary_after(self, block_last_line):
        """The first whole ordinary line after a field-sync block."""
        types = self.half_line_types().reshape(self.lines, 2)
        line = block_last_line % self.lines
        while not np.all(types[line] == ORDINARY):
            line = (line + 1) % self.lines
        return line + 1


def _lines(first, last, halves):
    return tuple((line, halves) for line in range(first, last + 1))


NTSC = VideoStandard(
    key='ntsc', label="NTSC - 525 lines, 29.97 frames a second",
    lines=LINES_PER_FRAME, line_rate=FH, subcarrier=FSC,
    sync_width=SYNC_WIDTH, equalizing_width=EQUALIZING_WIDTH,
    serration_width=SERRATION_WIDTH, blank_start=BLANK_START,
    active_start=ACTIVE_START, burst_start=BURST_START,
    burst_cycles=BURST_CYCLES,
    sync_level=IRE_SYNC, blank_level=IRE_BLANK, black_level=IRE_SETUP,
    white_level=IRE_WHITE, luma_gain=SETUP_GAIN,
    burst_amplitude=BURST_AMPLITUDE, trough_level=IRE_TROUGH,
    peak_level=IRE_PEAK, u_scale=B_Y_SCALE, v_scale=R_Y_SCALE,
    v_switch=False, active_lines_per_field=ACTIVE_LINES_PER_FIELD,
    field1_first_line=FIELD1_FIRST_LINE, field2_first_line=FIELD2_FIRST_LINE,
    # Table 3: three lines of six equalizing pulses, three of vertical sync
    # with six serrations, three of equalizing - in each field.
    vertical=(_lines(1, 3, (EQUALIZING, EQUALIZING))
              + _lines(4, 6, (BROAD, BROAD))
              + _lines(7, 9, (EQUALIZING, EQUALIZING))
              + _lines(264, 266, (EQUALIZING, EQUALIZING))
              + _lines(267, 269, (BROAD, BROAD))
              + _lines(270, 272, (EQUALIZING, EQUALIZING))),
    width=640, height=480, video_band=4.2e6,
)

PAL = VideoStandard(
    key='pal', label="PAL - 625 lines, 25 frames a second",
    lines=625, line_rate=PAL_FH, subcarrier=PAL_FSC,
    # Table 2: sync d, datum to the end of blanking b, front porch a - b.
    sync_width=4.7e-6, equalizing_width=2.35e-6, serration_width=4.7e-6,
    blank_start=1.5e-6, active_start=10.5e-6,
    # Table 2 g and h: burst 5.6 us after the datum, ten cycles.
    burst_start=5.6e-6, burst_cycles=10,
    # Table 2 items 1-5: blanking 0, white 700 mV, sync -300 mV, no set-up,
    # burst 300 mV peak to peak.
    sync_level=-300.0, blank_level=0.0, black_level=0.0, white_level=700.0,
    luma_gain=1.0, burst_amplitude=150.0,
    # The legalizer's limits. 75% colour bars are the standard test signal
    # in both systems and must pass untouched, and PAL's red and blue bars
    # swing down to -175 mV - further than NTSC's, which bottom out at
    # -16 IRE inside a -20 floor. A floor copied from NTSC (a fifth of the
    # blanking-to-white step, -140 mV) clipped them, and bars came back
    # 0.032 out. -180 mV passes them and stays above the decoder's sync
    # slice at -195 mV. The top matches NTSC's 120 IRE: a fifth over white.
    trough_level=-180.0, peak_level=840.0,
    # Table 1 item 9.
    u_scale=0.493, v_scale=0.877, v_switch=True,
    # 576 active lines, 288 a field.
    active_lines_per_field=288, field1_first_line=23, field2_first_line=336,
    # Table 3 and Figs. 3-5: two and a half lines each of five equalizing
    # pulses, five broad pulses and five equalizing pulses. The first
    # field's block starts half-way through line 623, so its broad pulses
    # begin exactly on line 1; the second field's starts on line 311, so its
    # broad pulses begin half-way through 313.
    vertical=((623, (ORDINARY, EQUALIZING)),)
             + _lines(624, 625, (EQUALIZING, EQUALIZING))
             + _lines(1, 2, (BROAD, BROAD))
             + ((3, (BROAD, EQUALIZING)),)
             + _lines(4, 5, (EQUALIZING, EQUALIZING))
             + _lines(311, 312, (EQUALIZING, EQUALIZING))
             + ((313, (EQUALIZING, BROAD)),)
             + _lines(314, 315, (BROAD, BROAD))
             + _lines(316, 317, (EQUALIZING, EQUALIZING))
             + ((318, (EQUALIZING, NO_PULSE)),),
    width=768, height=576, video_band=5.0e6,
)

STANDARDS = {NTSC.key: NTSC, PAL.key: PAL}


class NtscEncoder:
    """Encode frames as composite baseband - NTSC unless told otherwise.

    ``encode_frame`` takes one progressive RGB frame and returns the samples
    for a whole frame - both fields, odd rows in the first, even in the
    second. Call it repeatedly; timing carries across calls.
    """

    def __init__(self, sample_rate, color=True, legalize=True, standard=None):
        self.sample_rate = float(sample_rate)
        self.color = bool(color)
        self.standard = standard or NTSC
        #: Hold the active picture inside what a transmitter can carry. On
        #: by default; the only reason to turn it off is to measure how far
        #: a signal would have swung without it.
        self.legalize = bool(legalize)
        self._n = 0                  # absolute sample index, never reset
        self._half_types = self.standard.half_line_types()
        self._burst_lines = self.standard.burst_lines()
        #: Lines with anything but ordinary halves: the field-sync blocks.
        #: Looked up per line rather than per half-line across the frame,
        #: which was a full-frame gather and cost the encoder a fifth.
        self._vertical_lines = ~np.all(
            self._half_types.reshape(self.standard.lines, 2) == ORDINARY, axis=1)

    # -- timing ---------------------------------------------------------

    def frame_bounds(self, n0):
        """[start, end) sample indices of the frame beginning at ``n0``.

        Half-open on time, so consecutive frames neither overlap nor leave a
        gap however the boundary lands between samples. Public because a
        caller encoding frames on several threads has to know where the next
        frame starts *before* this one has finished - see ``ntsc_source``.
        """
        frame = self.standard.frame
        start_time = int(n0) / self.sample_rate
        end_time = (np.floor(start_time / frame) + 1) * frame
        return int(n0), int(np.ceil(end_time * self.sample_rate))

    def _frame_slice(self):
        """Sample indices whose time falls in the next frame."""
        start, n_end = self.frame_bounds(self._n)
        n = np.arange(start, n_end, dtype=np.int64)
        self._n = n_end
        return n

    # -- the encoder -----------------------------------------------------

    def encode_frame(self, rgb):
        """One RGB frame (rows, cols, 3) in 0..1 -> composite samples.

        **Every sample of the frame is computed at once.** This used to walk
        the lines in a Python loop, selecting each line's samples with
        ``line_in_frame == L`` - a comparison across the whole frame, once
        per line, which makes the work O(samples x lines) rather than
        O(samples). At 10 MS/s that ran at 0.14x real time, so the encoder
        could not have fed a radio live however fast the machine was. Doing
        it in whole-frame array operations is about 60x quicker.
        """
        rgb = np.asarray(rgb, dtype=np.float64)
        if rgb.ndim != 3 or rgb.shape[2] != 3:
            raise ValueError("expected an (rows, cols, 3) RGB frame")
        std = self.standard

        y, b_y, r_y = self._components(rgb)
        rows, cols = y.shape

        n = self._frame_slice()
        t = n / self.sample_rate
        line = std.line
        line_idx = np.floor(t / line).astype(np.int64)
        tau = t - line_idx * line
        line_no = (line_idx % std.lines).astype(np.int64) + 1   # 1-based

        level = np.full(n.shape, std.blank_level)

        # -- the field-sync blocks ------------------------------------------
        #
        # An equalizing pulse is a short sync-level notch; a broad pulse is
        # the other way round, sync level all the way except for a serration
        # at its end that keeps a receiver's line oscillator in step. Only a
        # few lines of the frame are in these blocks, so the arithmetic is
        # done on just those samples rather than across the whole frame.
        vertical = self._vertical_lines[line_no - 1]
        block = np.flatnonzero(vertical)
        if block.size:
            tau_v = tau[block]
            late = tau_v >= line / 2
            kind = self._half_types[2 * (line_no[block] - 1) + late]
            tau_half = tau_v - np.where(late, line / 2, 0.0)
            sync = (((kind == EQUALIZING) & (tau_half < std.equalizing_width))
                    | ((kind == BROAD)
                       & (tau_half < line / 2 - std.serration_width))
                    | ((kind == ORDINARY) & ~late & (tau_v < std.sync_width)))
            level[block] = np.where(sync, std.sync_level, std.blank_level)

        # -- every other line: sync pulse, then blanking ------------------
        ordinary = ~vertical
        level[ordinary & (tau < std.sync_width)] = std.sync_level

        # -- the active picture ------------------------------------------
        #
        # Field one takes the even rows, field two the odd ones - that is
        # what makes the two fields interlace into one picture.
        per_field = std.active_lines_per_field
        row = np.full(line_no.shape, -1, dtype=np.int64)
        in_f1 = ((line_no >= std.field1_first_line)
                 & (line_no < std.field1_first_line + per_field))
        in_f2 = ((line_no >= std.field2_first_line)
                 & (line_no < std.field2_first_line + per_field))
        row[in_f1] = 2 * (line_no[in_f1] - std.field1_first_line)
        row[in_f2] = 2 * (line_no[in_f2] - std.field2_first_line) + 1

        active = ((row >= 0) & (row < rows)
                  & (tau >= std.active_start)
                  & (tau < std.active_start + std.active_len))
        if block.size:
            # PAL's last active line of field two shares its second half
            # with the next field's equalizing pulses.
            active[block[kind != ORDINARY]] = False
        here = np.flatnonzero(active)
        u = (tau[here] - std.active_start) / std.active_len
        col = np.clip((u * cols).astype(np.int32), 0, cols - 1)
        pixel_row = row[here]
        # NTSC Annex A equation 10: 0.925*Y + 7.5, which lands black on
        # setup and white on 100 IRE. PAL: 700 mV of white, no setup.
        level[here] = std.luma_gain * (y[pixel_row, col] * std.white_level) \
            + std.black_level

        out = std.to_unit(level)

        if self.color:
            # The subcarrier comes from absolute time, and only where it is
            # actually used, which is the active picture and the burst. A
            # sine over the whole frame was most of what was left of the
            # cost, and in monochrome it was computed and thrown away.
            phase = 2 * np.pi * std.subcarrier * t[here]
            amp = std.luma_gain * std.white_level / std.span
            v = r_y[pixel_row, col]
            if std.v_switch:
                # BT.1700 item 10d: the V component's sign changes every
                # line. The absolute line count's parity does it, and since
                # 625 is odd the pattern repeats every two frames, as it
                # should.
                v = v * (1 - 2 * (line_idx[here] % 2))
            out[here] += amp * (b_y[pixel_row, col] * np.sin(phase)
                                + v * np.cos(phase))
            burst = np.flatnonzero(
                ordinary & self._burst_lines[line_no - 1]
                & (tau >= std.burst_start)
                & (tau < std.burst_start + std.burst_len))
            burst_phase = 2 * np.pi * std.subcarrier * t[burst]
            if std.v_switch:
                # Item 10f: 135 degrees from the U axis, either side, the
                # side following the V switch - so the burst is -U plus or
                # minus V, each at 1/sqrt(2) of its amplitude.
                s = 1 - 2 * (line_idx[burst] % 2)
                out[burst] += (std.burst_amplitude
                               * (-np.sin(burst_phase) + s * np.cos(burst_phase))
                               / math.sqrt(2) / std.span)
            else:
                out[burst] += (-std.burst_amplitude * np.sin(burst_phase)
                               / std.span)

        if self.legalize and here.size:
            # Only the active picture: sync and blanking are already where
            # they belong, and clamping them would flatten the sync pulses.
            out[here] = np.clip(out[here], std.to_unit(std.trough_level),
                                std.to_unit(std.peak_level))

        return out

    # -- helpers ---------------------------------------------------------

    def _components(self, rgb):
        """Y and the two reduced colour-difference signals, per active row."""
        std = self.standard
        r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
        y = KR * r + KG * g + KB * b
        b_y = std.u_scale * (b - y)
        r_y = std.v_scale * (r - y)
        return y, b_y, r_y

    def frame_samples(self):
        """Roughly how many samples a frame takes, for sizing buffers."""
        return int(round(self.standard.frame * self.sample_rate))


#: The same encoder, by a name that does not pretend it only does NTSC.
CompositeEncoder = NtscEncoder
