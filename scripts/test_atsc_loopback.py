#!/usr/bin/env python3
"""ATSC transmit chain -> dtv.atsc_rx -> transport stream, no radio.

    python scripts/test_atsc_loopback.py <video> <seconds> [snr_db]
    python scripts/test_atsc_loopback.py bars <seconds> [snr_db]

Runs exactly the block chain atscXmitter.py builds, feeds the result to GNU
Radio's own ATSC receiver, and reports how much of the transport stream came
back byte for byte.

The video is anything the transmitter takes: a ``.ts`` plays as it is, and
anything else is encoded by ffmpeg as it plays, through the same pipe the
transmitter reads (``apps/atsc_source.py``). ``bars`` is the transmitter's
built-in colour bars and tone, which need no media at all. Either way the
result is scored against what actually went into the chain, recorded on the
way in, since an encoded stream has no file of its own to compare against.
"""
import math
import os
import sys
import tempfile

from gnuradio import analog, blocks, dtv, filter, gr
from gnuradio.filter import firdes

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from apps.atsc_source import (COLOUR_BARS, TransportStream,  # noqa: E402
                               needs_encoding)

TS_RATE = 19392658.0          # ATSC transport stream bitrate, bits/s


class Loop(gr.top_block):
    def __init__(self, video, ts_sent, ts_out, nbytes, snr_db=None):
        gr.top_block.__init__(self, "atsc loopback", catch_exceptions=True)
        symbol_rate = 4500000.0 / 286 * 684
        pilot_freq = (6000000.0 - (symbol_rate / 2)) / 2
        samp_rate = 12e6

        if needs_encoding(video):
            self.stream = TransportStream(video)
            src = blocks.file_descriptor_source(
                gr.sizeof_char, self.stream.fileno(), False)
        else:
            self.stream = None
            src = blocks.file_source(gr.sizeof_char, video, False, 0, 0)
        head = blocks.head(gr.sizeof_char, nbytes)
        self.connect(head, blocks.file_sink(gr.sizeof_char, ts_sent, False))
        pad = dtv.atsc_pad()
        rand = dtv.atsc_randomizer()
        rs = dtv.atsc_rs_encoder()
        inter = dtv.atsc_interleaver()
        trellis = dtv.atsc_trellis_encoder()
        fsm = dtv.atsc_field_sync_mux()
        v2s = blocks.vector_to_stream(gr.sizeof_char, 1024)
        keep = blocks.keep_m_in_n(gr.sizeof_char, 832, 1024, 4)
        mod = dtv.dvbs2_modulator_bc(dtv.FECFRAME_NORMAL, dtv.C1_4,
                                     dtv.MOD_8VSB, dtv.INTERPOLATION_OFF)
        rot = blocks.rotator_cc(((-3000000.0 + pilot_freq) / symbol_rate) * (math.pi * 2))
        rrc = filter.fft_filter_ccc(
            1, firdes.root_raised_cosine(0.11, symbol_rate, symbol_rate / 2, 0.1152, 200), 1)
        rrc.declare_sample_delay(0)
        up = filter.rational_resampler_ccc(interpolation=143, decimation=54, taps=[], fractional_bw=0)
        down = filter.rational_resampler_ccc(interpolation=8, decimation=19, taps=[], fractional_bw=0)

        chain = [src, head, pad, rand, rs, inter, trellis, fsm, v2s, keep,
                 mod, rot, rrc, up, down]
        for a, b in zip(chain, chain[1:]):
            self.connect(a, b)
        tail = down

        if snr_db is not None:
            # noise_source_c's amplitude is its rms, and this chain puts out
            # 0.3697 rms (measured, peak 1.007, so 8.7 dB of headroom above
            # rms - worth knowing before setting a radio's level). Scaling the
            # noise by that makes the number asked for the real SNR: without
            # it every reading came out 8.6 dB optimistic.
            noise = analog.noise_source_c(
                analog.GR_GAUSSIAN, 0.3697 * 10 ** (-snr_db / 20.0), 0)
            add = blocks.add_cc()
            self.connect(tail, (add, 0))
            self.connect(noise, (add, 1))
            tail = add

        rx = dtv.atsc_rx(samp_rate, 1.5)
        sink = blocks.file_sink(gr.sizeof_char, ts_out, False)
        self.connect(tail, rx, sink)


def compare(ts_in, ts_out):
    """Score the recovered stream against the source.

    Not by position: a transport stream of a static picture repeats itself,
    and null packets are all identical, so searching for a recovered packet
    finds some earlier copy rather than where it really came from. Every
    packet the source ever sent goes into a set instead, and a recovered
    packet counts as right if it is in that set. A corrupted 188-byte packet
    matching some other real one is not a risk worth arithmetic.
    """
    a = open(ts_in, 'rb').read()
    b = open(ts_out, 'rb').read()
    if not b:
        return "receiver produced nothing"
    src = {a[188 * k:188 * (k + 1)] for k in range(len(a) // 188)}
    n = len(b) // 188
    good = [b[188 * k:188 * (k + 1)] in src for k in range(n)]
    if not any(good):
        return f"{n} packets out, not one of them a packet the source sent"
    lock = good.index(True)
    after = good[lock:]
    secs = lock * 188 * 8 / TS_RATE
    return (f"{n} packets out; locked after {lock} ({secs:.2f} s), "
            f"then {sum(after)}/{len(after)} byte-perfect "
            f"({100.0 * sum(after) / len(after):.3f}%)")


if __name__ == '__main__':
    video = COLOUR_BARS if sys.argv[1] == 'bars' else sys.argv[1]
    seconds = float(sys.argv[2])
    snr = float(sys.argv[3]) if len(sys.argv) > 3 else None
    nbytes = int(seconds * TS_RATE / 8) // 188 * 188
    tag = 'clean' if snr is None else f'{snr:.0f}db'
    # Next to the source would put these in the media directory, where the app
    # would then offer the decoder's own output as something to transmit.
    stem = ('colour-bars' if video == COLOUR_BARS
            else os.path.splitext(os.path.basename(video))[0])
    sent = os.path.join(tempfile.gettempdir(), f'{stem}_tx.ts')
    out = os.path.join(tempfile.gettempdir(), f'{stem}_rx_{tag}.ts')
    tb = Loop(video, sent, out, nbytes, snr)
    try:
        tb.run()
    finally:
        if tb.stream is not None:
            tb.stream.close()
    label = "clean" if snr is None else f"{snr:.0f} dB SNR"
    print(f"{label}: {compare(sent, out)}")
