"""RDS / RBDS encoder - the transmit counterpart of ``rds_core``.

Builds the group sequence a receiver expects, serialises it to the 1187.5 bit/s
stream, and renders the 19 kHz pilot plus the 57 kHz RDS subcarrier as baseband
samples ready to be summed into an FM multiplex.

Kept free of GNU Radio and Qt so the whole chain can be checked offline: encode
groups here, hand the samples to ``rds_core`` and confirm what comes back is
what went in.

Two details matter more than they look:

* **The subcarriers must be phase-locked to the pilot.** Receivers recover the
  57 kHz carrier and the bit clock from the 19 kHz pilot (x3 and /16), so both
  are generated here from one sample counter rather than from separate
  oscillators that would drift apart.
* **Blocks carry an offset word, not a plain CRC.** The checkword is the CRC of
  the information bits XORed with a per-position offset word, which is what lets
  a receiver find block boundaries at all.
"""
import threading
from datetime import date, datetime, timezone

import numpy as np
from scipy import signal

from apps.rds_core import OFFSET, POLY, RTPLUS_AID

BITRATE = 1187.5
SUBCARRIER_HZ = 57000.0
PILOT_HZ = 19000.0
#: Day 0 of the Modified Julian Date that group 4A counts days in.
MJD_EPOCH = date(1858, 11, 17).toordinal()


def system_clock():
    """The computer's local time, carrying its current UTC offset.

    Read afresh for every clock group, so the offset follows daylight saving.
    """
    return datetime.now().astimezone()


def checkword(info):
    """CRC of the 16 information bits, as the 10-bit checkword (no offset)."""
    reg = 0
    msg = (info & 0xFFFF) << 10
    for i in range(25, -1, -1):
        reg = (reg << 1) | ((msg >> i) & 1)
        if reg & 0x400:
            reg ^= (0x400 | POLY)
    return reg & 0x3FF


def make_block(info, offset_name):
    """A 26-bit block: 16 information bits plus checkword XOR offset word."""
    return ((info & 0xFFFF) << 10) | (checkword(info) ^ OFFSET[offset_name])


def _chars(text, size):
    return list(text.ljust(size)[:size])


def paginate(text, width=64):
    """Split a long message into RadioText-sized pages, breaking on words."""
    words, pages, line = text.split(), [], ''
    for word in words:
        candidate = f"{line} {word}".strip()
        if len(candidate) <= width:
            line = candidate
        else:
            if line:
                pages.append(line)
            # A single word longer than a page has to be cut somewhere.
            while len(word) > width:
                pages.append(word[:width])
                word = word[width:]
            line = word
    if line:
        pages.append(line)
    return pages or ['']


class RdsEncoder:
    """An endless, live-editable RDS group sequence.

    Setters are safe to call from a UI thread while the flowgraph pulls groups.

    ``clock`` is a callable returning the current time as a timezone-aware
    datetime (``system_clock`` for the computer's own). With one, a group 4A
    goes out as soon as the stream starts and then at the start of every
    minute; without one, no clock time is sent at all, which is what the NRSC
    asks of a station that has no reliable time source.
    """

    def __init__(self, pi=0x4CA1, ps='GNURADIO', radiotext='', pty=0,
                 tp=0, ta=0, ms=1, station_name=None, clock=None):
        self._lock = threading.Lock()
        self.clock = clock
        self.bits_sent = 0                # stream position, at 1187.5 bit/s
        self._ct_minute = None            # the minute last sent as group 4A
        self._ct_sent = None              # that group, as rds_core reads it
        self.pi = pi
        self.pty = pty
        self.tp = tp
        self.ta = ta
        self.ms = ms                      # 1 = music, 0 = speech
        self._ps = _chars(ps, 8)
        self._rt = _chars(radiotext, 64)
        self._rt_ab = 0
        self._rtplus = None               # (ctype, start, len) pairs
        self.station_name = station_name
        self._seq_index = 0
        self._ps_seg = 0
        self._rt_seg = 0
        self._pages = []            # paragraph mode: RadioText pages in order
        self._page_i = 0
        self._page_repeats = 1
        self._page_cycles = 0

    # -- live edits --------------------------------------------------------
    def set_ps(self, text):
        with self._lock:
            self._ps = _chars(text, 8)

    def set_radiotext(self, text):
        with self._lock:
            self._set_rt_locked(text)

    def set_paragraph(self, text, repeats=1, number_pages=True):
        """Send a message longer than RadioText as a sequence of pages.

        RadioText holds 64 characters, so anything longer is paged: each page is
        transmitted complete, then the A/B flag toggles to tell receivers to
        clear before the next arrives. Pages advance on *segments sent* rather
        than a clock, so a page is never replaced halfway out.

        Pages are numbered "2/5 " by default. The cycle repeats forever, so
        anyone tuning in mid-paragraph receives the pages rotated - every page
        arrives, but not in reading order. The numbering is what lets them be
        reassembled without waiting to spot where the cycle wraps.
        """
        with self._lock:
            pages = paginate(text, 64)
            if number_pages and len(pages) > 1:
                # The prefix eats into the page width, which can add a page,
                # which can widen the prefix. Settle it rather than assume.
                total = len(pages)
                for _ in range(4):
                    pages = paginate(text, 64 - len(f"{total}/{total} "))
                    if len(pages) == total:
                        break
                    total = len(pages)
                pages = [f"{i+1}/{total} {p}" for i, p in enumerate(pages)]
            self._pages = pages
            self._page_i = 0
            self._page_repeats = max(1, int(repeats))
            self._page_cycles = 0
            self._rt_seg = 0
            self._rtplus = None
            self._load_page_locked()

    def _load_page_locked(self):
        page = self._pages[self._page_i]
        # A carriage return ends a short page, so receivers do not leave the
        # tail of a longer previous page on screen.
        self._rt = _chars(page + '\r' if len(page) < 64 else page, 64)

    def _set_rt_locked(self, text):
        text = text[:64]
        self._pages = []            # a single message cancels paragraph mode
        self._rt = _chars(text, 64)
        # Drop any RT+ tags: they are offsets into the *previous* message, and
        # left in place they would slice the new text at the wrong points and
        # advertise a half-word as the title - exactly the fault a local
        # station ships. set_now_playing() reinstates them straight after,
        # having computed them from the string it just set.
        self._rtplus = None
        # Toggling the A/B flag is how a receiver is told to clear the old
        # message rather than overwrite it character by character.
        self._rt_ab ^= 1
        self._rt_len = len(text)

    def set_now_playing(self, artist, title):
        """Set RadioText and the matching RT+ tags in one consistent step.

        RT+ tags are offsets into the RadioText, so they have to be computed
        from the very string that gets sent or a receiver slices the wrong
        characters - exactly the bug seen off-air on a local station.
        """
        artist, title = (artist or '').strip(), (title or '').strip()
        with self._lock:
            if artist and title:
                text = f"{artist} - {title}"
                self._set_rt_locked(text)
                self._rtplus = ((4, 0, len(artist) - 1),
                                (1, len(artist) + 3, len(title) - 1))
            elif title:
                self._set_rt_locked(title)
                self._rtplus = ((1, 0, len(title) - 1), (0, 0, 0))
            else:
                self._rtplus = None

    def snapshot(self):
        with self._lock:
            return {
                'pi': self.pi, 'pi_hex': f"0x{self.pi:04X}",
                'ps': ''.join(self._ps), 'radiotext': ''.join(self._rt).rstrip(),
                'pty': self.pty, 'tp': self.tp, 'ta': self.ta,
                'rtplus': self._rtplus,
                'clock': self._ct_sent,
            }

    # -- group construction ------------------------------------------------
    def _common_b(self, gtype, version_b=0):
        return ((gtype & 0xF) << 12 | (version_b & 1) << 11
                | (self.tp & 1) << 10 | (self.pty & 0x1F) << 5)

    def _group_0a(self):
        seg = self._ps_seg & 0x3
        self._ps_seg = (self._ps_seg + 1) & 0x3
        b = self._common_b(0) | (self.ta & 1) << 4 | (self.ms & 1) << 3 | seg
        # 0xE0E0 is the "no alternative frequencies" filler.
        c = 0xE0E0
        d = (ord(self._ps[seg * 2]) << 8) | ord(self._ps[seg * 2 + 1])
        return [make_block(self.pi, 'A'), make_block(b, 'B'),
                make_block(c, 'C'), make_block(d, 'D')]

    def _group_2a(self):
        seg = self._rt_seg & 0xF
        self._rt_seg = (self._rt_seg + 1) & 0xF
        b = self._common_b(2) | (self._rt_ab & 1) << 4 | seg
        c = (ord(self._rt[seg * 4]) << 8) | ord(self._rt[seg * 4 + 1])
        d = (ord(self._rt[seg * 4 + 2]) << 8) | ord(self._rt[seg * 4 + 3])
        group = [make_block(self.pi, 'A'), make_block(b, 'B'),
                 make_block(c, 'C'), make_block(d, 'D')]
        if self._rt_seg == 0 and self._pages:
            # A whole page has just gone out; move on once it has been sent
            # the requested number of times, toggling A/B so receivers clear.
            self._page_cycles += 1
            if self._page_cycles >= self._page_repeats:
                self._page_cycles = 0
                self._page_i = (self._page_i + 1) % len(self._pages)
                self._load_page_locked()
                self._rt_ab ^= 1
        return group

    def _group_3a(self):
        """Announce that group 12A carries RadioText+."""
        b = self._common_b(3) | ((12 << 1) | 0)
        return [make_block(self.pi, 'A'), make_block(b, 'B'),
                make_block(0x0000, 'C'), make_block(RTPLUS_AID, 'D')]

    def _group_12a(self):
        (t1, s1, l1), (t2, s2, l2) = self._rtplus
        running = 1
        toggle = self._rt_ab & 1
        bits = ((toggle & 1) << 36 | (running & 1) << 35
                | (t1 & 0x3F) << 29 | (s1 & 0x3F) << 23 | (l1 & 0x3F) << 17
                | (t2 & 0x3F) << 11 | (s2 & 0x3F) << 5 | (l2 & 0x1F))
        b = self._common_b(12) | ((bits >> 32) & 0x1F)
        c = (bits >> 16) & 0xFFFF
        d = bits & 0xFFFF
        return [make_block(self.pi, 'A'), make_block(b, 'B'),
                make_block(c, 'C'), make_block(d, 'D')]

    def _group_4a(self, now):
        """Clock time and date.

        The hour and minute are UTC, not local time, with the local offset
        alongside in half hours: the receiver adds the two. The date is a
        Modified Julian Date, 17 bits split across blocks B and C.
        """
        utc = now.astimezone(timezone.utc)
        offset = now.utcoffset().total_seconds() / 3600
        half_hours = int(round(abs(offset) * 2))
        mjd = utc.toordinal() - MJD_EPOCH
        b = self._common_b(4) | ((mjd >> 15) & 0x3)
        c = ((mjd & 0x7FFF) << 1) | (utc.hour >> 4)
        d = ((utc.hour & 0xF) << 12 | utc.minute << 6
             | (offset < 0) << 5 | (half_hours & 0x1F))
        self._ct_sent = {
            'year': utc.year, 'month': utc.month, 'day': utc.day,
            'hour': utc.hour, 'minute': utc.minute,
            'utc_offset_hours': (-1 if offset < 0 else 1) * half_hours / 2.0,
        }
        return [make_block(self.pi, 'A'), make_block(b, 'B'),
                make_block(c, 'C'), make_block(d, 'D')]

    #: Roughly the mix a real station sends: PS often, RadioText steadily, and
    #: the RT+ announcement and tags sprinkled in.
    SEQUENCE = ('0A', '0A', '2A', '0A', '2A', '0A', '2A', '3A', '0A', '2A',
                '0A', '12A')

    def next_group(self):
        with self._lock:
            group = self._clock_group_due()
            if group is None:
                group = self._scheduled_group()
            self.bits_sent += 104
            return group

    def _clock_group_due(self):
        """Group 4A if the minute has turned since the last one, else None.

        Checked ahead of every group, so the clock leaves the encoder within
        one group (88 ms) of the minute edge, which is when the standard wants
        it - the flowgraph and the radio's buffers then add their own delay.
        """
        if self.clock is None:
            return None
        now = self.clock()
        if now.tzinfo is None:
            now = now.astimezone()        # naive: the computer's local time
        minute = now.replace(second=0, microsecond=0)
        if minute == self._ct_minute:
            return None
        self._ct_minute = minute
        return self._group_4a(now)

    def _scheduled_group(self):
        for _ in range(len(self.SEQUENCE)):
            kind = self.SEQUENCE[self._seq_index % len(self.SEQUENCE)]
            self._seq_index += 1
            if kind in ('3A', '12A') and not self._rtplus:
                continue                          # nothing to announce yet
            return {'0A': self._group_0a, '2A': self._group_2a,
                    '3A': self._group_3a, '12A': self._group_12a}[kind]()
        return self._group_0a()

    def next_bits(self):
        """104 bits: one group of four 26-bit blocks, most significant first."""
        out = np.empty(104, dtype=np.uint8)
        for i, blk in enumerate(self.next_group()):
            for j in range(26):
                out[i * 26 + j] = (blk >> (25 - j)) & 1
        return out


class RdsSubcarrier:
    """Renders pilot + RDS subcarrier samples at an arbitrary sample rate.

    Both come from one sample counter, so the 57 kHz carrier stays exactly three
    times the pilot and the bit clock exactly a sixteenth of it - which is what
    a receiver relies on to demodulate coherently.
    """

    def __init__(self, encoder, rate, rds_injection=0.05, pilot_level=0.09,
                 shaping_hz=2400.0, ntaps=127):
        self.enc = encoder
        self.fs = float(rate)
        self.rds_injection = rds_injection
        self.pilot_level = pilot_level
        self._n = 0                       # absolute sample index
        self._bits = np.zeros(0, dtype=np.uint8)
        self._bit0 = 0                    # absolute index of self._bits[0]
        self._last_tx = 0                 # differential encoder state
        self._shape = signal.firwin(ntaps, shaping_hz, fs=self.fs)
        self._zi = np.zeros(ntaps - 1)

    def _fill_to(self, abs_index):
        """Ensure the buffer holds every bit up to and including ``abs_index``."""
        while self._bit0 + len(self._bits) <= abs_index:
            data = self.enc.next_bits()
            # Differential encoding: send the running XOR, so a receiver that
            # is 180 degrees out still recovers the right data.
            tx = np.empty_like(data)
            state = self._last_tx
            for i, bit in enumerate(data):
                state ^= int(bit)
                tx[i] = state
            self._last_tx = state
            self._bits = np.concatenate([self._bits, tx])

    def generate(self, count):
        """Just the pilot + RDS sum, for callers that need nothing else."""
        return self.generate_all(count)[0]

    def generate_all(self, count):
        """Return (pilot + RDS, 38 kHz stereo carrier) for the next samples.

        The stereo carrier comes from the same sample counter as the pilot, so
        it stays at exactly twice the pilot frequency just as RDS stays at
        exactly three times it. Separate oscillators would drift apart, and a
        receiver recovering both from the pilot would slowly lose stereo.
        """
        n = np.arange(self._n, self._n + count, dtype=np.float64)
        t = n / self.fs

        # Manchester: each bit is a positive half followed by a negative half
        # (or the reverse), which puts no energy at the subcarrier frequency.
        bit_pos = t * BITRATE
        # Track the buffer's absolute bit index rather than inferring it from
        # the sample arithmetic: a chunk boundary landing exactly on a bit
        # boundary otherwise slips the whole stream by one bit, which corrupts
        # blocks even with no noise anywhere.
        first_bit = int(np.floor(bit_pos[0]))
        last_bit = int(np.floor(bit_pos[-1]))
        drop = first_bit - self._bit0
        if drop > 0:
            self._bits = self._bits[drop:]
            self._bit0 += drop
        self._fill_to(last_bit + 1)
        idx = np.floor(bit_pos).astype(np.int64) - self._bit0
        idx = np.clip(idx, 0, len(self._bits) - 1)
        half = (bit_pos - np.floor(bit_pos)) < 0.5
        symbol = np.where(self._bits[idx] > 0, 1.0, -1.0)
        manchester = np.where(half, symbol, -symbol)

        shaped, self._zi = signal.lfilter(self._shape, 1.0, manchester,
                                          zi=self._zi)
        rds = shaped * np.cos(2 * np.pi * SUBCARRIER_HZ * t)
        pilot = np.cos(2 * np.pi * PILOT_HZ * t)

        carrier38 = np.cos(2 * (2 * np.pi * PILOT_HZ) * t)
        self._n += count
        subcarriers = (self.pilot_level * pilot
                       + self.rds_injection * rds).astype(np.float32)
        return subcarriers, carrier38.astype(np.float32)
