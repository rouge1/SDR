#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The parts of ATSC reception that are arithmetic rather than flowgraph.

``atscReceiver`` wires GNU Radio's ``gr-dtv`` blocks together; everything
that can be decided with numpy lives here, free of GNU Radio and Qt so it
can be tested without a radio - the same split as ``rds_core`` against
``rdsReceiver``.

Four jobs:

**Find the pilot, and say how far it is from where A/53 puts it.** 8VSB
carries a small residual carrier 309.441 kHz above the lower edge of the
channel, which is 2.6906 MHz below the centre a receiver tunes to. It is a
bare spike in a flat haystack, so a windowed FFT finds it to a few hertz.

**Turn that one number into two corrections.** Two free-running crystals do
not agree, and a clock that is fast by some parts per million moves the
carrier *and* stretches the symbol clock by the same fraction. Correcting
only the carrier leaves the symbol clock wrong, and the decoder then
produces noise from a signal whose spectrum looks perfect - this cost real
time to find, and is why ``afc_correction`` returns both.

**Measure how open the eye is.** ``gr-dtv``'s equalizer emits soft symbols
on the ideal 8VSB grid, so the distance from each to its nearest level is
the error, and the ratio of signal power to that is MER.

**Say what is in the recovered stream.** A transport stream announces its
own programs in the PAT and PMT, so a few hundred bytes of parsing turns
"packets are arriving" into "two programs, MPEG-2 video on PID 0x0100".
"""

import numpy as np

# A/53 part 2. Everything descends from the symbol rate.
SYMBOL_RATE = 4.5e6 / 286 * 684       # 10.762237 MS/s
CHANNEL_BW = 6.0e6
# The pilot sits 309.441 kHz above the lower channel edge, which is this far
# below the centre frequency. Same expression as the transmitter's rotator.
PILOT_OFFSET = -3e6 + (CHANNEL_BW - SYMBOL_RATE / 2) / 2      # -2.6906 MHz
# A/53 puts the threshold of visibility at 15.2 dB SNR.
THRESHOLD_OF_VISIBILITY_DB = 15.2
# The eight 8VSB levels, after the equalizer has normalised them.
VSB_LEVELS = np.array([-7.0, -5.0, -3.0, -1.0, 1.0, 3.0, 5.0, 7.0])


# --- the television channel plan -------------------------------------------
#
# Only the channel *centre* matters here: both this receiver and
# ``atscXmitter`` are tuned to it, not to the visual carrier.

def channel_center_mhz(channel):
    """Centre frequency of a US television channel, in MHz.

    Raises ValueError for the numbers that are not television channels -
    there is no channel 1, and 37 is reserved for radio astronomy.
    """
    n = int(channel)
    if 2 <= n <= 4:
        return 57.0 + 6.0 * (n - 2)          # 54-72 MHz
    if 5 <= n <= 6:
        return 79.0 + 6.0 * (n - 5)          # 76-88 MHz
    if 7 <= n <= 13:
        return 177.0 + 6.0 * (n - 7)         # 174-216 MHz
    if 14 <= n <= 36:
        return 473.0 + 6.0 * (n - 14)        # 470-608 MHz
    raise ValueError(f"{channel} is not a US television channel")


def channels():
    """Every valid channel as (number, centre MHz), low to high."""
    out = []
    for n in list(range(2, 14)) + list(range(14, 37)):
        out.append((n, channel_center_mhz(n)))
    return out


def channel_for_center(mhz, tolerance=0.05):
    """The channel whose centre this is, or None for a frequency off-plan."""
    for n, centre in channels():
        if abs(centre - mhz) <= tolerance:
            return n
    return None


def tv_channel_items():
    """The channel plan as ``(number, centre MHz, caption)``, for a combo box.

    Here rather than in either app so the transmitter and the receiver offer
    the same list, and free of Qt like the rest of this module.
    """
    return [(n, centre, f"{'VHF' if n <= 13 else 'UHF'} {n}  ({centre:g} MHz)")
            for n, centre in channels()]


# --- automatic frequency control -------------------------------------------

def pilot_offset_hz(samples, sample_rate, search=75e3):
    """How far the pilot is from where the standard puts it, in Hz.

    Returns ``(error_hz, prominence_db)``. The prominence is how far the
    peak stands above the median of the search window, which is what tells
    a pilot from the noise where there is no station: 8VSB data is flat, so
    a real pilot stands 10 dB or more proud of it.

    ``samples`` are complex baseband centred on the channel, as the radio
    delivers them. ``search`` bounds how large a clock error can be found:
    75 kHz is 140 ppm at 533 MHz, far past any crystal that is working at
    all, and narrow enough that data either side cannot be mistaken for the
    pilot.
    """
    x = np.asarray(samples, dtype=np.complex64)
    if x.size < 4096:
        return 0.0, 0.0
    n = 1 << int(np.floor(np.log2(x.size)))
    x = x[:n]
    # A window matters more than length here: the pilot is a bare spike a
    # few tens of dB above a flat haystack, and an unwindowed FFT's
    # sidelobes smear the haystack right across it.
    spec = np.abs(np.fft.fftshift(np.fft.fft(x * np.hanning(n)))) ** 2
    freqs = np.fft.fftshift(np.fft.fftfreq(n, 1.0 / sample_rate))

    band = np.abs(freqs - PILOT_OFFSET) < search
    if band.sum() < 8:
        return 0.0, 0.0
    f, s = freqs[band], spec[band]
    j = int(np.argmax(s))
    peak = f[j]
    if 0 < j < len(s) - 1:
        # Parabolic interpolation on the log magnitudes, so the answer is
        # not quantised to the bin spacing - at 12 MS/s and 2^21 samples a
        # bin is 5.7 Hz, and the fit gets well inside that.
        a, b, c = (np.log(s[j - 1] + 1e-30), np.log(s[j] + 1e-30),
                   np.log(s[j + 1] + 1e-30))
        denom = a - 2 * b + c
        if denom != 0:
            peak = f[j] + 0.5 * (a - c) / denom * (f[1] - f[0])
    median = float(np.median(s))
    prominence = 10 * np.log10(s[j] / median) if median > 0 else 0.0
    return float(peak - PILOT_OFFSET), float(prominence)


def afc_correction(error_hz, center_hz):
    """Turn a measured pilot error into the two corrections it implies.

    Returns ``(rotator_hz, clock_ratio)``: shift the baseband by
    ``rotator_hz`` and multiply the resampler's rate by ``clock_ratio``.

    The two are not independent, which is the whole point. A transmitter
    whose crystal is fast by a fraction d puts its carrier d*f_rf high
    *and* clocks its symbols d faster. Measured at baseband the pilot moves
    by d*(f_rf + PILOT_OFFSET) - the carrier carries it up, and stretching
    the baseband carries it back down by d times its own 2.69 MHz - so that
    is the frequency the ppm figure has to be taken against. Correcting the
    carrier alone leaves the symbol clock d fast, and the equalizer never
    converges: the spectrum looks perfect and the output is noise.
    """
    pilot_hz = float(center_hz) + PILOT_OFFSET
    if pilot_hz <= 0:
        return 0.0, 1.0
    ppm_fraction = float(error_hz) / pilot_hz
    return float(error_hz), 1.0 + ppm_fraction


class Afc:
    """Holds the correction and only moves it when a measurement earns it.

    The pilot measurement is good to a few hertz, so the loop does not need
    to creep: one measurement is enough to jump to. What it does need is to
    refuse to act on nonsense, because a receiver pointed at an empty
    channel measures the largest noise bin in the search window and would
    otherwise chase it around.
    """

    #: Below this the "pilot" is just the biggest bin in a flat window.
    #:
    #: Measured on a BB60D across eight UHF channels: empty ones read 11-15
    #: dB with the peak landing anywhere in the +-75 kHz window, a live
    #: broadcaster on RF 36 read 44.2 dB and the VSG60 on RF 24 read 46 dB.
    #: The gap is that wide because the FFT bin is 22 Hz: a carrier lands
    #: entirely in one bin while data and noise spread across all of them,
    #: which is worth about 54 dB and barely depends on how strong the
    #: signal is. So a decodable station reads 40-plus however weak it is,
    #: and 30 sits clear of both sides. At 8, which this was first, an empty
    #: channel reported a pilot and the app said "Pilot found, not
    #: decoding" where it should have said there was no signal at all.
    MIN_PROMINENCE_DB = 30.0
    #: Do not disturb a working lock for less than this.
    DEADBAND_HZ = 40.0

    def __init__(self, center_hz):
        self.center_hz = float(center_hz)
        self.error_hz = 0.0
        self.clock_ratio = 1.0
        self.prominence_db = 0.0
        self.locked = False

    def retune(self, center_hz):
        """Start again on a new channel; the old correction means nothing."""
        self.center_hz = float(center_hz)
        self.error_hz = 0.0
        self.clock_ratio = 1.0
        self.prominence_db = 0.0
        self.locked = False

    def update(self, samples, sample_rate):
        """Measure and take the correction. True if it changed."""
        raw, prominence = pilot_offset_hz(samples, sample_rate)
        self.prominence_db = prominence
        if prominence < self.MIN_PROMINENCE_DB:
            self.locked = False
            return False
        # The measurement is of the *uncorrected* stream, so it is the total
        # error every time rather than a residual to accumulate.
        self.locked = True
        if abs(raw - self.error_hz) < self.DEADBAND_HZ:
            return False
        self.error_hz, self.clock_ratio = afc_correction(raw, self.center_hz)
        return True

    @property
    def ppm(self):
        return (self.clock_ratio - 1.0) * 1e6


# --- how open the eye is ---------------------------------------------------

#: Below about this, a decision-directed MER stops telling the truth - see
#: ``mer_db``. Measured on synthetic symbols, not guessed.
MER_FLOOR_DB = 16.0


def mer_db(symbols):
    """Modulation error ratio of equalized 8VSB soft symbols, in dB.

    ``gr-dtv``'s equalizer emits symbols already on the ideal grid (mean
    absolute value 4.0, which is what equiprobable +-1, +-3, +-5, +-7
    gives), so each symbol's error is its distance to the nearest level and
    MER is 21 - the mean square of those levels - over the mean square
    error.

    **It reads optimistically once the eye starts closing, and cannot be
    compared against the 15.2 dB cliff.** Slicing to the nearest level is
    what every receiver's MER does, and it is the same thing as assuming
    every symbol was decided correctly; once noise starts pushing symbols
    past the halfway point the error to the *wrong* level is measured
    instead, which is smaller. Measured against known noise, this reads
    within 0.1 dB down to 22 dB, 19.0 for a true 18, 17.7 for a true 15 and
    16.6 for a true 12 - so it bottoms out around 16 whatever is really
    happening. Read it as "how open is the eye", and read the bad-packet
    rate for whether the picture is intact.
    """
    x = np.asarray(symbols, dtype=np.float64)
    if x.size == 0:
        return 0.0
    err = x - VSB_LEVELS[np.argmin(np.abs(x[:, None] - VSB_LEVELS[None, :]),
                                   axis=1)]
    mse = float(np.mean(err ** 2))
    if mse <= 0:
        return 99.0
    return float(10 * np.log10(float(np.mean(VSB_LEVELS ** 2)) / mse))


def mer_quality(mer):
    """A word for an MER reading, honest about where it stops meaning much."""
    if mer <= 0:
        return ''
    # Pitched against what this receiver actually reads, not against the
    # theoretical cliff: a software loopback with no noise at all tops out
    # near 24 dB, and off air a link running at 0.00% bad packets reads
    # 19.5-22.5. Calling that "closing" alarms people about a perfect
    # picture, which an earlier version of this did.
    if mer >= 21:
        return 'eye wide open'
    if mer >= 18:
        return 'eye open'
    return (f'near the floor - the slicer cannot see past about '
            f'{MER_FLOOR_DB:.0f} dB')


# --- what is in the stream -------------------------------------------------

STREAM_TYPES = {
    0x01: 'MPEG-1 video', 0x02: 'MPEG-2 video', 0x03: 'MPEG-1 audio',
    0x04: 'MPEG-2 audio', 0x06: 'private data', 0x0f: 'AAC audio',
    0x1b: 'H.264 video', 0x24: 'HEVC video', 0x81: 'AC-3 audio',
    0x86: 'SCTE-35', 0x87: 'E-AC-3 audio',
}

PID_PAT = 0x0000
PID_NULL = 0x1fff


class TsAnalyzer:
    """Counts packets and reads the programs out of a transport stream.

    Fed whatever bytes the decoder produces, in whatever sized pieces. It
    keeps no more than one packet of leftover, so it can run on a live
    stream forever.

    Everything it reports is cumulative; ``since()`` turns two snapshots
    into the rates that actually matter live, because a receiver's totals
    are dominated by however long it spent acquiring lock.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self._buf = b''
        self.packets = 0
        self.errors = 0          # transport_error_indicator set
        self.discontinuities = 0
        self.pids = {}           # pid -> packet count
        self.programs = {}       # program number -> {'pmt_pid', 'streams'}
        self._pmt_pids = {}      # pmt pid -> program number
        self._continuity = {}    # pid -> last continuity counter
        self._synced = False

    # -- feeding ---------------------------------------------------------

    def feed(self, data):
        """Take a chunk of transport stream bytes."""
        buf = self._buf + bytes(data)
        i = 0
        n = len(buf)
        while i + 188 <= n:
            if buf[i] != 0x47:
                # Resynchronise: look for the next sync byte that also has
                # one 188 bytes further on, so a 0x47 inside payload does
                # not drag the parser out of step.
                j = self._find_sync(buf, i, n)
                if j < 0:
                    i = max(i, n - 187)
                    break
                i = j
                continue
            self._packet(buf[i:i + 188])
            i += 188
        self._buf = buf[i:]

    @staticmethod
    def _find_sync(buf, start, end):
        i = start
        while True:
            i = buf.find(0x47, i + 1, end)
            if i < 0:
                return -1
            if i + 376 > end or buf[i + 188] == 0x47:
                return i

    def _packet(self, pkt):
        self.packets += 1
        pid = ((pkt[1] & 0x1f) << 8) | pkt[2]
        self.pids[pid] = self.pids.get(pid, 0) + 1
        if pkt[1] & 0x80:                      # transport_error_indicator
            self.errors += 1
            return                             # its contents are not to be trusted
        self._check_continuity(pid, pkt)
        if pid == PID_PAT:
            self._section(pkt, self._parse_pat)
        elif pid in self._pmt_pids:
            self._section(pkt, self._parse_pmt)

    def _check_continuity(self, pid, pkt):
        # Null packets are exempt - A/53 stuffing does not carry a counter,
        # and packets with no payload do not advance it either.
        if pid == PID_NULL or not (pkt[3] & 0x10):
            return
        cc = pkt[3] & 0x0f
        last = self._continuity.get(pid)
        if last is not None and cc != (last + 1) % 16:
            self.discontinuities += 1
        self._continuity[pid] = cc

    def _section(self, pkt, parse):
        """Hand a table section to a parser, if this packet starts one.

        Sections that span packets are skipped rather than reassembled: a
        PAT and the PMTs of a broadcast stream fit in one packet each, and
        they repeat every hundred milliseconds, so waiting for a whole one
        costs nothing and saves carrying reassembly state through errors.
        """
        if not (pkt[1] & 0x40):                # payload_unit_start_indicator
            return
        i = 4
        if pkt[3] & 0x20:                      # adaptation field present
            i += 1 + pkt[4]
        if i >= 188:
            return
        i += 1 + pkt[i]                        # pointer_field
        if i + 3 > 188:
            return
        length = ((pkt[i + 1] & 0x0f) << 8) | pkt[i + 2]
        end = i + 3 + length
        if end > 188:
            return
        parse(pkt[i:end])

    # -- tables ----------------------------------------------------------

    def _parse_pat(self, sec):
        if not sec or sec[0] != 0x00 or len(sec) < 8:
            return
        body = sec[8:-4]                       # past the header, before the CRC
        for k in range(0, len(body) - 3, 4):
            program = (body[k] << 8) | body[k + 1]
            pid = ((body[k + 2] & 0x1f) << 8) | body[k + 3]
            if program == 0:                   # network PID, not a program
                continue
            self._pmt_pids[pid] = program
            self.programs.setdefault(program, {'pmt_pid': pid, 'streams': {}})

    def _parse_pmt(self, sec):
        if not sec or sec[0] != 0x02 or len(sec) < 12:
            return
        program = (sec[3] << 8) | sec[4]
        info_len = ((sec[10] & 0x0f) << 8) | sec[11]
        k = 12 + info_len
        body = sec[:-4]                        # drop the CRC
        streams = {}
        while k + 5 <= len(body):
            stream_type = body[k]
            pid = ((body[k + 1] & 0x1f) << 8) | body[k + 2]
            es_len = ((body[k + 3] & 0x0f) << 8) | body[k + 4]
            streams[pid] = stream_type
            k += 5 + es_len
        entry = self.programs.setdefault(program, {'pmt_pid': None,
                                                   'streams': {}})
        entry['streams'] = streams

    # -- reporting -------------------------------------------------------

    def snapshot(self):
        return {
            'packets': self.packets,
            'errors': self.errors,
            'discontinuities': self.discontinuities,
            'pids': dict(self.pids),
            'programs': {p: dict(v) for p, v in self.programs.items()},
        }

    def describe_programs(self):
        """One human-readable line per program, or an empty list."""
        out = []
        for program in sorted(self.programs):
            streams = self.programs[program]['streams']
            if not streams:
                out.append(f"program {program}: (no PMT yet)")
                continue
            parts = [f"{STREAM_TYPES.get(t, f'type 0x{t:02x}')} "
                     f"on 0x{pid:04x}" for pid, t in sorted(streams.items())]
            out.append(f"program {program}: " + ", ".join(parts))
        return out


def since(before, after):
    """Rates over the interval between two snapshots.

    A receiver's totals are swamped by however long it took to lock - the
    loopback spends its first 5000 packets acquiring - so everything the
    user reads while it runs should be a difference, not a total.
    """
    packets = after['packets'] - before['packets']
    errors = after['errors'] - before['errors']
    return {
        'packets': packets,
        'errors': errors,
        'discontinuities': after['discontinuities'] - before['discontinuities'],
        'error_rate': (errors / packets) if packets else None,
    }
