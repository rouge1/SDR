#!/usr/bin/env python3
"""Drive RdsProtocol through a RadioText change of the kind 98.7 WMZQ makes.

The station rotates a slogan, the song and an advert through RadioText and
never toggles the A/B flag that is meant to announce a new message. Groups are
fed straight to the protocol layer here, so this tests the text handling rather
than the demodulator - no radio, no capture.

The last section is the exception: it feeds whole bitstreams with error bursts
in them, to show the display holds steady on a marginal signal.

    python scripts/test_rds_radiotext.py
"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from apps.rds_core import RdsProtocol, RTPLUS_AID  # noqa: E402
from apps.rds_encode import RdsEncoder  # noqa: E402

PTY = 10


def group_2a(proto, ab, addr, chars, corrected=()):
    """One RadioText segment: four characters at ``addr`` * 4.

    ``corrected`` names the blocks that needed error correction on the way in.
    """
    b = (2 << 12) | (0 << 11) | (0 << 10) | (PTY << 5) | (ab << 4) | addr
    c = (ord(chars[0]) << 8) | ord(chars[1])
    d = (ord(chars[2]) << 8) | ord(chars[3])
    proto._decode_group({'A': 0x16F2, 'B': b, 'C': c, 'D': d},
                        corrected=frozenset(corrected))


def send_rt(proto, text, ab=0, upto=None):
    """Send ``text`` as RadioText segments, optionally stopping part way."""
    padded = text.ljust(64)[:64]
    for addr in range(16):
        if upto is not None and addr >= upto:
            return
        group_2a(proto, ab, addr, padded[addr * 4:addr * 4 + 4])


def announce_rtplus(proto):
    """3A group naming 12A as the carrier of RadioText+."""
    b = (3 << 12) | (0 << 11) | (0 << 10) | (PTY << 5) | (12 << 1) | 0
    proto._decode_group({'A': 0x16F2, 'B': b, 'C': 0, 'D': RTPLUS_AID})


def send_rtplus(proto, tag1, tag2=(0, 0, 0)):
    """12A group carrying up to two (content type, start, length-1) tags."""
    bits = ((tag1[0] << 29) | (tag1[1] << 23) | (tag1[2] << 17)
            | (tag2[0] << 11) | (tag2[1] << 5) | tag2[2])
    b = (12 << 12) | (0 << 11) | (0 << 10) | (PTY << 5) | ((bits >> 32) & 0x1F)
    proto._decode_group({'A': 0x16F2, 'B': b,
                         'C': (bits >> 16) & 0xFFFF, 'D': bits & 0xFFFF})


AD = "Make It Malloy Malloy.com1000s of vehicles to choose - 98.7WMZQ"
SONG = "98.7WMZQ - Dan + Shay - Say So"
SLOGAN = "Today's Best Country"

failures = []


def check(name, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {name}: {got!r}")
    if not ok:
        print(f"       wanted {want!r}")
        failures.append(name)


def check_not_containing(name, got, forbidden):
    ok = forbidden not in got
    print(f"  {'ok  ' if ok else 'FAIL'} {name}: {got!r}")
    if not ok:
        print(f"       must not contain {forbidden!r}")
        failures.append(name)


print("a message replacing another under an unchanged A/B flag")
p = RdsProtocol()
send_rt(p, AD)
check("advert arrives whole", p.snapshot()['radiotext'], AD)
# The song now starts overwriting it, four characters at a time. Before the
# fix the buffer read "98.7WMZQ - Dan + Shay - Say Soes to choose - 98.7WMZQ".
send_rt(p, SONG, upto=3)
check_not_containing("part way through the change",
                     p.snapshot()['radiotext'], "choose")
send_rt(p, SONG)
check("song arrives whole", p.snapshot()['radiotext'], SONG)

print("\nRT+ tags belong to the message that carried them")
p = RdsProtocol()
announce_rtplus(p)
send_rt(p, AD)
send_rtplus(p, (1, 0, 51))                       # title = the whole advert
check("advert tagged as title", p.snapshot()['title'],
      "Make It Malloy Malloy.com1000s of vehicles to choose")
send_rt(p, SLOGAN + "\r")
check("tag dropped with its message", p.snapshot()['title'], None)

print("\na tag may not slice text the new message has not sent yet")
p = RdsProtocol()
announce_rtplus(p)
send_rt(p, SLOGAN + "\r")
send_rt(p, SONG, upto=4)                         # "98.7WMZQ - Dan +"
# Offsets for "Dan + Shay" in the finished song text. Before the fix this
# sliced the half-filled buffer and produced "Dan +ntry" - the new message
# welded to the tail of "Country".
send_rtplus(p, (4, 11, 9))
check("tag held back while the text is partial", p.snapshot()['artist'], None)
send_rt(p, SONG)
send_rtplus(p, (4, 11, 9))
check("tag applied once the text is real", p.snapshot()['artist'], "Dan + Shay")

print("\na block the code corrected wrongly cannot touch clean text")
p = RdsProtocol()
announce_rtplus(p)
send_rt(p, SONG)
send_rtplus(p, (4, 11, 9))
# Segment 2 is " - D". A burst too long to repair comes back "corrected" with
# block D wrong, " D" as "&+". Two differing characters used to read as a new
# message and blank the display - and so did the clean pass that repaired it.
group_2a(p, 0, 2, " -&+", corrected=('D',))
check("the clean text stays on display", p.snapshot()['radiotext'], SONG)
check("so does its tag", p.snapshot()['artist'], "Dan + Shay")
group_2a(p, 0, 2, " - D")
check("the next clean pass changes nothing", p.snapshot()['radiotext'], SONG)

print("\na corrected block cannot announce a new message either")
p = RdsProtocol()
send_rt(p, SONG)
group_2a(p, 0, 0, AD[0:4], corrected=('C',))
check("the song stays", p.snapshot()['radiotext'], SONG)
send_rt(p, AD)
check("the advert arriving clean replaces it", p.snapshot()['radiotext'], AD)

print("\na corrupted A/B flag does not blank the display")
p = RdsProtocol()
send_rt(p, SONG)
padded = SONG.ljust(64)
group_2a(p, 1, 5, padded[20:24], corrected=('B',))
group_2a(p, 0, 6, padded[24:28])
check("the text is still whole", p.snapshot()['radiotext'], SONG)
send_rt(p, AD, ab=1)
check("a real A/B change still switches message", p.snapshot()['radiotext'], AD)

print("\nan error the syndrome cannot see, in one character, is not a new message")
p = RdsProtocol()
announce_rtplus(p)
send_rt(p, SONG)
send_rtplus(p, (4, 11, 9))
# A block that arrives clean but wrong. Segment 2 is " - D" and the D of "Dan"
# comes back as an X. Clearing on that one character would blank the display
# for the four seconds a refill takes.
group_2a(p, 0, 2, " - X")
check("text keeps everything but the bad character",
      p.snapshot()['radiotext'], SONG.replace("Dan", "Xan"))
# The tag holds the value sliced when its group arrived, so a bad block
# landing in the text afterwards cannot rewrite it.
check("tag is not thrown away", p.snapshot()['artist'], "Dan + Shay")
group_2a(p, 0, 2, " - D")                        # next pass repairs it
check("next pass repairs it", p.snapshot()['radiotext'], SONG)

print("\na repeated, unchanged message is not treated as a new one")
p = RdsProtocol()
announce_rtplus(p)
send_rt(p, SONG)
send_rtplus(p, (4, 11, 9))
send_rt(p, SONG)
send_rt(p, SONG)
check("text survives repetition", p.snapshot()['radiotext'], SONG)
check("tag survives repetition", p.snapshot()['artist'], "Dan + Shay")


def bursty(seed, bursts_per_block, seconds=120):
    """Encode RadioText, add error bursts to the bits, and watch the display.

    Returns the blocks-good percentage and how many groups, once every
    position had been received and the text read right, left it on display
    wrong or short. Waiting for every position matters: padding that has not
    arrived yet already reads as the right space, and its first reception can
    be a wrongly corrected block like any other.
    """
    rng = random.Random(seed)
    enc = RdsEncoder(pi=0x16F2, ps='98.7WMZQ', pty=PTY)
    enc.set_now_playing('Dan + Shay', 'Say So')
    want = enc.snapshot()['radiotext']
    proto = RdsProtocol()
    filled, bad = False, 0
    for _ in range(int(seconds * 1187.5 / 104)):
        bits = enc.next_bits()
        for blk in range(4):
            if rng.random() < bursts_per_block:
                # Up to 10 bits: always detected, but half of them too long to
                # repair, so the code rejects them or corrects them wrongly.
                n = rng.randint(1, 10)
                start = blk * 26 + rng.randint(0, 26 - n)
                for i in range(n):
                    if i in (0, n - 1) or rng.random() < 0.5:
                        bits[start + i] ^= 1
        proto.feed(bits)
        text = proto.snapshot()['radiotext']
        if filled:
            bad += text != want
        received = proto.rt.written | proto.rt.provisional
        filled = filled or (text == want and len(received) == 64)
    snap = proto.snapshot()
    return 100 * snap['blocks_ok'] / snap['blocks_seen'], bad


print("\na marginal signal: error bursts in the bitstream itself")
# Before corrected blocks were distrusted, one burst in ten blocks (96.6%
# blocks good) kept the text wrong on display nearly two thirds of the time,
# and short or blank a fifth of it.
for seed in range(3):
    good, bad = bursty(seed, 0.10)
    check(f"{good:.1f}% blocks good, groups leaving the text wrong or short",
          bad, 0)

print()
print("RESULT:", "PASS" if not failures else f"FAIL ({', '.join(failures)})")
raise SystemExit(1 if failures else 0)
