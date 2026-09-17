#!/usr/bin/env python3
"""FM television: the numbers both ends of an FM video link have to share.

An FM video transmitter frequency-modulates a carrier with composite video
and puts the sound on FM subcarriers above the picture, in the same
baseband. Analog FPV drones on 5.8 GHz do exactly that, and so did analog
satellite television and terrestrial microwave relays. What differs between
them is numbers - how far the picture swings the carrier, whether the
picture is pre-emphasised first, where the sound sits - so here they are
*profiles* of one transmitter rather than separate apps.

Free of GNU Radio and Qt, like ``rds_core`` and ``atsc_rx_core``, so the
curves, the channel plan and the sideband levels can be checked with no
radio at all: ``scripts/test_fm_video_transmit.py``.
"""
import math
from dataclasses import dataclass

import numpy as np

#: The encoder's composite runs from sync tip 0.0 to peak white 1.0, which is
#: exactly the "1 V peak to peak" every FM video deviation is quoted against.
#: The carrier rests at the middle of that swing.
VIDEO_CENTRE = 0.5


# --- the 5.8 GHz channel plan ------------------------------------------------

#: Analog FPV channels, MHz, in the order goggles number them. Bands A, B and
#: E are the RTC6705's own table (docs/RTC6705-DST-001.pdf, "Channel Selection
#: Table"); F (Fatshark / ImmersionRC) and R (Raceband, spaced 37 MHz apart so
#: that eight pilots can fly at once) were added by FPV gear since and every
#: current transmitter and goggle offers them.
FPV_BANDS = (
    ('A', (5865, 5845, 5825, 5805, 5785, 5765, 5745, 5725)),
    ('B', (5733, 5752, 5771, 5790, 5809, 5828, 5847, 5866)),
    ('E', (5705, 5685, 5665, 5645, 5885, 5905, 5925, 5945)),
    ('F', (5740, 5760, 5780, 5800, 5820, 5840, 5860, 5880)),
    ('R', (5658, 5695, 5732, 5769, 5806, 5843, 5880, 5917)),
)


def fpv_channel_items():
    """The plan as ``(name, centre MHz, caption)``, for ``FrequencyChooser``."""
    return tuple((f"{band}{k}", float(mhz), f"{band}{k}  ({mhz} MHz)")
                 for band, freqs in FPV_BANDS
                 for k, mhz in enumerate(freqs, 1))


# --- pre-emphasis --------------------------------------------------------------

@dataclass(frozen=True)
class Preemphasis:
    """A shelving pre-emphasis in the form ITU-R F.405 gives it.

        relative deviation (dB) = 10 log[(1 + C f^2) / (1 + B f^2)] - A

    with f in MHz. That is one zero at ``1/sqrt(C)`` MHz and one pole at
    ``1/sqrt(B)`` MHz: A dB down at low frequencies, rising through 0 dB at
    the crossover and levelling off above the pole. For 525 lines the zero
    is 187 kHz and the pole 875 kHz, so the shelf is over well below the
    colour subcarrier.

    **Why FM television wants it at all.** FM noise rises with baseband
    frequency, so the fine detail and the colour at the top of the video
    band are what a weak signal spoils first. Cutting the high-energy low
    frequencies - sync, large areas of brightness - lets the deviation be
    spent on the top of the band instead, and the receiver's matching
    de-emphasis takes the noise down with it.
    """

    key: str
    label: str
    A: float
    B: float
    C: float
    #: The top of the video band the tolerance in F.405 section 4 is quoted
    #: up to: 4.2 MHz for 525 lines, 5 MHz for 625.
    video_band: float

    @property
    def zero_hz(self):
        return 1e6 / math.sqrt(self.C)

    @property
    def pole_hz(self):
        return 1e6 / math.sqrt(self.B)

    @property
    def crossover_hz(self):
        """Where the curve passes through 0 dB."""
        g = 10 ** (self.A / 10)
        return 1e6 * math.sqrt((g - 1) / (self.C - g * self.B))

    def relative_db(self, f_hz):
        f = np.asarray(f_hz, dtype=np.float64) / 1e6
        return 10 * np.log10((1 + self.C * f ** 2) / (1 + self.B * f ** 2)) - self.A

    def _bilinear(self, sample_rate, scale):
        """The network through a bilinear transform ``s = scale (z-1)/(z+1)``."""
        gain = 10 ** (-self.A / 20)
        kz = scale / (2 * math.pi * self.zero_hz)
        kp = scale / (2 * math.pi * self.pole_hz)
        a0 = 1 + kp
        return ([gain * (1 + kz) / a0, gain * (1 - kz) / a0],
                [1.0, (1 - kp) / a0])

    def worst_departure(self, b, a, sample_rate):
        """The filter's worst departure from the formula, as a fraction of
        F.405's tolerance, +-(0.1 + 0.05 f/fc) dB, from 10 kHz to the band top."""
        f = np.geomspace(0.01e6, self.video_band, 400)
        z = np.exp(-2j * np.pi * f / sample_rate)
        got = 20 * np.log10(np.abs((b[0] + b[1] * z) / (a[0] + a[1] * z)))
        tolerance = 0.1 + 0.05 * f / self.video_band
        return float(np.max(np.abs(got - self.relative_db(f)) / tolerance))

    def coefficients(self, sample_rate):
        """``(b, a)`` of the network at ``sample_rate``, with ``a[0] == 1``.

        The analog network is ``G (1 + s/wz) / (1 + s/wp)``. Through a
        bilinear transform its gain at DC and at the top are kept exactly -
        ``s`` going to infinity lands on ``z = -1`` - and what moves is the
        frequency axis in between, by an amount the transform's one free
        constant sets.

        **That constant is chosen, not taken from the textbook.** The usual
        ``2 * sample_rate`` put the 525-line curve 0.048 dB out at 4.2 MHz,
        35% of what F.405 allows; but the 625-line curve's pole is at
        1.57 MHz, nearly twice as high, and it came out 0.145 dB out at
        5 MHz - 101% of the tolerance, just outside it. Pre-warping the zero
        and the pole, the other textbook answer, doubled both. So the
        constant is searched for: whichever puts the worst point of the
        curve furthest inside the tolerance across its own video band.
        """
        best = None
        scales = [2 * sample_rate] + [
            2 * math.pi * fm / math.tan(math.pi * fm / sample_rate)
            for fm in np.geomspace(0.05e6, min(self.video_band, 0.45 * sample_rate), 160)]
        for scale in scales:
            b, a = self._bilinear(sample_rate, scale)
            worst = self.worst_departure(b, a, sample_rate)
            if best is None or worst < best[0]:
                best = (worst, b, a)
        return best[1], best[2]

    def inverse_coefficients(self, sample_rate):
        """The matching de-emphasis, which a receiver applies."""
        b, a = self.coefficients(sample_rate)
        return [a[0] / b[0], a[1] / b[0]], [1.0, b[1] / b[0]]


#: ITU-R F.405-1 Table 1 (docs/R-REC-F.405-1-197007-W.pdf): one curve per
#: line standard. The recommendation tabulates 819 lines too, which nothing
#: here makes.
F405_525 = Preemphasis('f405-525', "ITU-R F.405, 525 lines",
                       A=10.0, B=1.306, C=28.58, video_band=4.2e6)
F405_625 = Preemphasis('f405-625', "ITU-R F.405, 625 lines",
                       A=11.0, B=0.4083, C=10.21, video_band=5.0e6)

PREEMPHASES = {F405_525.key: F405_525, F405_625.key: F405_625}
PREEMPHASIS_CHOICES = (('none', "None"), (F405_525.key, F405_525.label),
                       (F405_625.key, F405_625.label))


def preemphasis(key):
    """The curve for a key, or None for no pre-emphasis."""
    return PREEMPHASES.get(key)


def preemphasis_for(key, lines):
    """``key``, turned into F.405's curve for this many lines if it is one.

    F.405 gives each line standard its own network, so the 525-line curve
    on a 625-line picture is simply the wrong one: choosing PAL turns an
    F.405 choice into its 625-line curve, and NTSC turns it back.
    """
    if key in PREEMPHASES:
        return F405_625.key if int(lines) == 625 else F405_525.key
    return key


def compensation_band(video_band):
    """How far up the modulator's compensation must be right: the video
    band plus the interpolator's transition above it - 5 MHz for NTSC,
    5.8 for PAL, whose chroma reaches past its nominal 5 MHz."""
    return float(video_band) + 0.8e6


# --- a sampled FM modulator --------------------------------------------------------

#: How far up the baseband the picture's compensation has to be right: the
#: video band, with the interpolator's transition above it.
COMPENSATION_BAND_HZ = 5.0e6


def fm_integrator_gain(freq, sample_rate):
    """How much further than asked a sampled FM modulator swings a tone.

    GNU Radio's frequency modulator accumulates phase a sample at a time,
    and a running sum is not an integral: for a tone of ``w`` radians per
    sample it has ``w / (2 sin(w/2))`` times the gain. Near DC that is 1,
    and at the top of the picture it is 8% - but a subcarrier at 6.8 MHz
    of 20 MS/s swings the carrier 22% (1.7 dB) further than intended, which
    is exactly how far its sidebands read high on a spectrum analyser. A
    real receiver's discriminator measures the true swing, so the
    transmitter has to undo it.
    """
    w = 2 * math.pi * freq / sample_rate
    return 1.0 if w == 0 else w / (2 * math.sin(w / 2))


def _cosine_fit(target, sample_rate, band_hz, ntaps):
    """Symmetric FIR whose response fits ``target(w)`` from DC to ``band_hz``."""
    m = ntaps // 2
    w = np.linspace(0, 2 * np.pi * band_hz / sample_rate, 400)
    basis = np.column_stack([np.ones_like(w)] +
                            [2 * np.cos(k * w) for k in range(1, m + 1)])
    half, *_ = np.linalg.lstsq(basis, target(w), rcond=None)
    return np.concatenate([half[:0:-1], half]).tolist()


def integrator_compensation_taps(sample_rate, band_hz=COMPENSATION_BAND_HZ,
                                 ntaps=11):
    """The transmitter's half: an FIR of ``1 / fm_integrator_gain`` across the band."""
    return _cosine_fit(lambda w: np.sinc(w / (2 * np.pi)), sample_rate,
                       band_hz, ntaps)


def discriminator_compensation_taps(sample_rate, band_hz=COMPENSATION_BAND_HZ,
                                    ntaps=11):
    """The receiver's half, for a discriminator that differences phase.

    ``instantaneous_frequency`` below takes the angle between neighbouring
    samples, which is the same running-sum mistake in reverse: it reads a
    tone's true swing short by ``2 sin(w/2) / w``. This puts it back.
    """
    return _cosine_fit(lambda w: 1 / np.sinc(w / (2 * np.pi)), sample_rate,
                       band_hz, ntaps)


# --- sound subcarriers -----------------------------------------------------------

def _bessel_j(n, x, terms=40):
    return sum((-1) ** k / (math.factorial(k) * math.factorial(k + n))
               * (x / 2) ** (2 * k + n) for k in range(terms))


def subcarrier_index(dbc):
    """The modulation index whose first sideband sits ``dbc`` below the carrier.

    A subcarrier frequency-modulates the carrier with a tone, which puts a
    pair of sidebands either side of it at ``J1(beta) / J0(beta)`` of the
    carrier. Datasheets quote that ratio - what a spectrum analyser shows -
    rather than the deviation that produces it, so it is solved for here.
    """
    target = 10 ** (dbc / 20)
    lo, hi = 0.0, 2.0      # J1/J0 climbs from 0 towards infinity at 2.405
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if _bessel_j(1, mid) / _bessel_j(0, mid) < target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def click_threshold_hz(profile, deviation_pp=None, sample_rate=20e6,
                       margin=3e6):
    """Further from the carrier than the signal could legitimately go.

    The picture swings it half the peak-to-peak deviation either way and
    each subcarrier adds its own; past that, plus a margin, an excursion is
    a *click* - the discriminator slipping a whole cycle, which is what FM
    below its threshold does and what puts the sparkles on a weak picture.

    **The margin matters more than it looks.** A discriminator that
    differences phase cannot read further than half the sample rate
    whatever the signal does - 10 MHz at 20 MS/s. Quote the threshold
    against the *peak-to-peak* deviation instead of the peak and it lands
    at 10.1 MHz for FPV, which is beyond that ceiling: the count then reads
    zero on a link that is tearing itself apart, and looks exactly like a
    clean one. Measured, that read 0 clicks a frame at 6 dB
    carrier-to-noise where there should have been thousands.
    """
    deviation = float(deviation_pp or profile.deviation_pp)
    sound = (2 * subcarrier_index(profile.subcarrier_dbc)
             * max(profile.subcarriers, default=0.0))
    legitimate = deviation / 2 + sound
    # The margin is 3 MHz where there is room for it and halfway to the
    # ceiling where there is not. F.405 is the case that needs the second:
    # it swings 4 MHz for the picture and 1.4 for its subcarrier, so a flat
    # 3 MHz on top lands at 9.7 of the 10 a discriminator can read and
    # leaves 3% of range for every click to be found in. FPV, which has
    # room, is unchanged by this.
    return legitimate + min(margin, 0.5 * (sample_rate / 2 - legitimate))


def subcarrier_dbc(index):
    """What a modulation index shows as - the inverse of `subcarrier_index`.

    A receiver measures the swing a subcarrier puts on the carrier and wants
    the number the datasheet quotes, which is the first sideband against the
    carrier. That is what tells you whether a real transmitter's sound sits
    where its datasheet says.
    """
    j0 = _bessel_j(0, index)
    j1 = _bessel_j(1, index)
    if j0 == 0 or j1 <= 0:
        return float('nan')
    return 20 * math.log10(j1 / j0)


# --- profiles ----------------------------------------------------------------------

@dataclass(frozen=True)
class Profile:
    """One kind of FM video signal: everything a transmitter must match."""

    key: str
    label: str
    #: Peak-to-peak deviation for a 1 V peak-to-peak video signal - sync tip
    #: to peak white. With pre-emphasis it is measured at the crossover
    #: frequency, without it at every frequency; ITU-R F.405 note 1 defines
    #: it that way.
    deviation_pp: float
    preemphasis: str
    #: Sound subcarrier frequencies, Hz, each carrying the programme sound.
    subcarriers: tuple
    #: Each subcarrier's first sideband against the carrier, dB.
    subcarrier_dbc: float
    #: Peak deviation of a subcarrier by full-scale audio, Hz.
    audio_deviation: float
    #: Audio pre-emphasis time constant, seconds.
    audio_tau: float
    channels: tuple = ()
    #: Where the dialog tunes when this profile is picked, or 0 to leave it.
    default_mhz: float = 0.0

    def sound_summary(self):
        mhz = ' and '.join(f"{f / 1e6:g}" for f in self.subcarriers)
        noun = 'subcarrier' if len(self.subcarriers) == 1 else 'subcarriers'
        return f"Sound goes out on FM {noun} at {mhz} MHz"


def subcarrier_amplitude(profile, freq, deviation_pp):
    """How big to add a subcarrier into the video, for its level on air.

    The modulator swings the carrier ``deviation_pp`` for a video swing of
    1.0, so a subcarrier of amplitude ``a`` deviates it ``a * deviation_pp``
    peak - which has to be ``beta * freq``. Keeping this separate from the
    video deviation means turning the picture's deviation up or down leaves
    the sound's level on the air where the profile put it.
    """
    return subcarrier_index(profile.subcarrier_dbc) * freq / deviation_pp


#: Analog FPV, as the RichWave RTC6705 transmitter and RTC6715 receiver - the
#: chips nearly every analog FPV transmitter and goggle is built on - define
#: it (docs/RTC6705-DST-001.pdf, docs/RTC6715-DST-001.pdf):
#:
#: - video in at 1 V peak to peak;
#: - sound on 6.0 MHz (left) and 6.5 MHz (right), each 25-30 dB under the
#:   carrier, taken here as the middle of that;
#: - audio deviation +-25 kHz, the condition the THD figure is quoted at;
#: - audio pre-emphasis with its 3 dB corner at 12 kHz.
#:
#: **Neither datasheet gives the video deviation or any video
#: pre-emphasis**, so both were guesses until a real transmitter was
#: measured. On 2026-09-16 one was, on A3 (5825 MHz) into the BB60D, using
#: the FM video receiver's own readout over 237 frames:
#:
#: - **deviation 7.93 MHz peak to peak** (spread 7.89-7.96), read off the
#:   sync-to-blanking step, which the television standard fixes. That is
#:   what is here now. The datasheet's own figure would have been 5.0 - the
#:   RTC6715's sensitivity is measured at +-2.5 MHz, the only video
#:   deviation either document mentions - and a transmitter set to that
#:   under-deviates a real link by 4 dB.
#: - **no pre-emphasis, confirmed**: the colour burst came back +0.14 dB
#:   against DC (spread 0.08-0.18), so whatever R/C network the module has
#:   does nothing measurable at 3.58 MHz. The guess was right.
#: - **no sound subcarriers at all.** That unit sends none - the 6.0 and
#:   6.5 MHz bands were the FM noise floor, 53 dB under the carrier - but
#:   they stay in the profile, because the datasheet defines them and gear
#:   with a microphone does use them.
#:
#: One unit is one unit, and the dialog's Deviation box is editable for
#: exactly that reason.
FPV = Profile(
    key='fpv',
    label="FPV drone - 5.8 GHz analog (RTC6705)",
    deviation_pp=7.93e6,
    preemphasis='none',
    subcarriers=(6.0e6, 6.5e6),
    subcarrier_dbc=-27.5,
    audio_deviation=25e3,
    audio_tau=1.0 / (2 * math.pi * 12e3),
    channels=fpv_channel_items(),
    default_mhz=5800.0,
)

#: Terrestrial microwave relay, and the analog satellite television that
#: took its pre-emphasis. The video half is ITU-R F.405-1 exactly: the
#: curve for the picture's line count (see `preemphasis_for`), and 8 MHz
#: peak to peak for 1 V at the crossover frequency (note 1, from ITU-R
#: F.276) - 2.53 MHz at low frequencies for 525 lines, 2.255 for 625.
#: **F.405 says nothing about sound.** One subcarrier at 6.8 MHz with 75 us
#: pre-emphasis is what analog C-band satellite channels commonly carried;
#: its level and deviation are this project's choice, not a standard's.
RELAY = Profile(
    key='f405',
    label="Microwave relay / satellite - ITU-R F.405",
    deviation_pp=8.0e6,
    preemphasis=F405_525.key,
    subcarriers=(6.8e6,),
    subcarrier_dbc=-20.0,
    audio_deviation=50e3,
    audio_tau=75e-6,
)

PROFILES = {p.key: p for p in (FPV, RELAY)}
DEFAULT_PROFILE = FPV.key


# --- the receiving end -------------------------------------------------------------

#: Where a receiver's picture filter stops, per format: past the top of the
#: video band, short of the lowest sound subcarrier at 6.0 MHz. It has to be
#: a real filter rather than a gentle roll-off, because what lies just above
#: it is a subcarrier at a tenth of the picture's own swing - and decimating
#: to the format's video rate would fold 6.0 MHz onto 4.0 in NTSC, right
#: beside the colour subcarrier. PAL's own band reaches 5.0 MHz, which
#: leaves only 400 kHz to do it in.
RECEIVE_CUTOFF = {'ntsc': 4.6e6, 'pal': 5.6e6}


def lowest_subcarrier():
    """The lowest frequency any profile puts sound on.

    A receiver's picture filter has to stop by here, and by here for every
    profile rather than only for the one selected - see the note on
    ``FmVideoReceiver``'s picture taps for what a filter that relaxed when
    the sound sat higher did to a measurement.
    """
    return min((f for p in PROFILES.values() for f in p.subcarriers),
               default=6.0e6)


def instantaneous_frequency(iq, sample_rate):
    """Hertz, one sample shorter than the input: the angle between neighbours.

    This is the whole of an FM discriminator. It needs no carrier recovery
    and no gain control, which is most of why FM video was the easy one to
    receive: a constant-envelope signal's information is all in the phase.
    """
    iq = np.asarray(iq)
    return np.angle(iq[1:] * np.conj(iq[:-1])) * sample_rate / (2 * np.pi)
