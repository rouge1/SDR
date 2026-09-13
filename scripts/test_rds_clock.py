#!/usr/bin/env python3
"""Drive clock time (group 4A) through the receiver and the transmitter.

98.7 sends no clock at all, yet the receiver once showed "2168-10-28 01:27
(UTC-9)": one corrupted group decoded as a group 4A. A clock group is now a
sync, the way a car radio treats it: the first is believed only once another
agrees, and between groups the clock runs on by itself. The first half feeds
hand-built groups straight to the protocol layer, with the bit count set by hand
as the passage of time - no radio, no capture.

The second half runs the transmitter's encoder on a clock that advances with
the bitstream rather than the wall, and decodes its bits straight back, so
minutes of stream take a moment.

    python scripts/test_rds_clock.py
"""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from apps.rds_core import RdsProtocol, clock_text  # noqa: E402
from apps.rds_encode import RdsEncoder, system_clock  # noqa: E402

BITRATE = 1187.5
GROUP_SECONDS = 104 / BITRATE
EDT = timezone(timedelta(hours=-4))
EST = timezone(timedelta(hours=-5))


def group_4a(proto, seconds, year, month, day, hour, minute, offset_hours,
             corrected=()):
    """Deliver one clock group (UTC fields) as if ``seconds`` into the stream.

    ``corrected`` names the blocks that needed error correction on the way in.
    """
    leap = 1 if month <= 2 else 0
    mjd = (14956 + day + int((year - 1900 - leap) * 365.25)
           + int((month + 1 + leap * 12) * 30.6001))
    half_hours = int(round(abs(offset_hours) * 2))
    b = (4 << 12) | (10 << 5) | ((mjd >> 15) & 0x3)
    c = ((mjd & 0x7FFF) << 1) | (hour >> 4)
    d = ((hour & 0xF) << 12) | (minute << 6) | ((offset_hours < 0) << 5) | (half_hours & 0x1F)
    advance(proto, seconds)
    proto._decode_group({'A': 0x16F2, 'B': b, 'C': c, 'D': d},
                        corrected=frozenset(corrected))


def advance(proto, seconds):
    """Move the stream on to ``seconds``, as if that much had been received."""
    proto.bits_in = int(seconds * BITRATE)


def shown(proto):
    """What the receiver window displays: local time, not the UTC fields."""
    return clock_text(proto.snapshot()['clock'])


def synced_ago(proto):
    clock = proto.snapshot()['clock']
    return round(clock['synced_ago_s']) if clock else None


def transmit(clock_at, seconds):
    """Encode ``seconds`` of RDS and decode it straight back, bit for bit.

    ``clock_at(t)`` is the clock reading ``t`` seconds into the stream, or None
    for an encoder with no clock. Returns every group 4A sent as (stream
    second, the group as rds_core reads it), what the receiver ends up
    showing, and the stream second it first showed anything.
    """
    enc = RdsEncoder(pi=0x4413, ps='GNURADIO', pty=5)
    if clock_at is not None:
        enc.clock = lambda: clock_at(enc.bits_sent / BITRATE)
    proto = RdsProtocol(region='RBDS')
    sent, first_shown = [], None
    while enc.bits_sent < seconds * BITRATE:
        at = enc.bits_sent / BITRATE
        bits = enc.next_bits()
        info_b = int(''.join(str(x) for x in bits[26:42]), 2)
        if info_b >> 11 == 0b01000:               # group type 4, version A
            sent.append((at, enc.snapshot()['clock']))
        proto.feed(bits)
        if first_shown is None and shown(proto):
            first_shown = at
    return sent, shown(proto), first_shown


failures = []


def check(name, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {name}: {got!r}")
    if not ok:
        print(f"       wanted {want!r}")
        failures.append(name)


print("RECEIVER\n")
print("a real clock, and a corrupted group arriving between readings")
p = RdsProtocol()
group_4a(p, 0, 2026, 9, 12, 20, 27, -4)
check("one reading is not trusted", shown(p), None)
group_4a(p, 60, 2026, 9, 12, 20, 28, -4)
check("a second reading a minute on is", shown(p), "2026-09-12 16:28 (UTC-4)")
# What the receiver actually displayed on 98.7, from a group that was never 4A.
group_4a(p, 90, 2168, 10, 28, 1, 27, -9)
check("the corrupted group is never shown", shown(p), "2026-09-12 16:28 (UTC-4)")
check("nor taken as a sync", synced_ago(p), 30)
group_4a(p, 120, 2026, 9, 12, 20, 29, -4)
check("a real reading agreeing with the running clock syncs at once",
      (shown(p), synced_ago(p)), ("2026-09-12 16:29 (UTC-4)", 0))

print("\nbefore the first sync, garbage between two readings does not break the pair")
# Off air at 93% blocks good, two garbage clock groups arrived in one minute.
# Remembering only the last reading, the clock never appeared in five minutes.
p = RdsProtocol()
group_4a(p, 0, 2026, 9, 12, 20, 27, -4)
group_4a(p, 30, 2168, 10, 28, 1, 27, -9)
check("a reading and a garbage group show nothing", shown(p), None)
group_4a(p, 60, 2026, 9, 12, 20, 28, -4)
check("the next real reading pairs with the one before the garbage", shown(p),
      "2026-09-12 16:28 (UTC-4)")

print("\nwhat a 93% link delivered off air: repairs everywhere, garbage between")
# The 19:52 group had block C repaired, a garbage 4A from a repaired block B
# came next, and the 19:53 and 19:54 groups both had block B repaired yet
# carried the right time - so refusing repaired groups would have thrown the
# real ones away along with the garbage.
p = RdsProtocol()
group_4a(p, 0, 2026, 9, 12, 23, 52, -4, corrected=('C',))
group_4a(p, 20, 2206, 10, 30, 4, 37, 7.5, corrected=('A', 'B'))
group_4a(p, 60, 2026, 9, 12, 23, 53, -4, corrected=('B',))
check("synced at 19:53", shown(p), "2026-09-12 19:53 (UTC-4)")
group_4a(p, 120, 2026, 9, 12, 23, 54, -4, corrected=('B', 'C'))
check("and on at 19:54", (shown(p), synced_ago(p)), ("2026-09-12 19:54 (UTC-4)", 0))

print("\nimpossible offsets are rejected outright")
group_4a(p, 140, 2026, 9, 12, 23, 54, -13)
check("a 13-hour offset changes nothing",
      (shown(p), synced_ago(p)), ("2026-09-12 19:54 (UTC-4)", 20))

print("\nthe clock runs on between groups, the way a car radio's does")
p = RdsProtocol()
group_4a(p, 0, 2026, 9, 12, 20, 27, -4)
group_4a(p, 60, 2026, 9, 12, 20, 28, -4)
advance(p, 185)                           # the next two groups were lost
check("two minutes on it still reads the right minute", shown(p),
      "2026-09-12 16:30 (UTC-4)")
check("and knows how long since it was synced", synced_ago(p), 125)
group_4a(p, 240, 2026, 9, 12, 20, 31, -4)
check("one group puts it back in sync", (shown(p), synced_ago(p)),
      ("2026-09-12 16:31 (UTC-4)", 0))
p = RdsProtocol()
group_4a(p, 0, 2026, 9, 13, 3, 58, -4)
group_4a(p, 60, 2026, 9, 13, 3, 59, -4)
advance(p, 150)
check("running past local midnight turns the date", shown(p),
      "2026-09-13 00:00 (UTC-4)")

print("\nreadings must move on with the stream")
p = RdsProtocol()
group_4a(p, 0, 2026, 9, 12, 20, 27, -4)
group_4a(p, 60, 2026, 9, 12, 23, 45, -4)
check("a jump of hours in one minute is not confirmed", shown(p), None)

print("\na station changing its offset (daylight saving ending)")
p = RdsProtocol()
group_4a(p, 0, 2026, 11, 1, 5, 58, -4)
group_4a(p, 60, 2026, 11, 1, 5, 59, -4)            # 01:59 EDT
group_4a(p, 120, 2026, 11, 1, 6, 0, -5)            # 01:00 EST
check("one reading with a new offset is not enough", shown(p),
      "2026-11-01 02:00 (UTC-4)")
group_4a(p, 180, 2026, 11, 1, 6, 1, -5)
check("the second switches the clock over", shown(p), "2026-11-01 01:01 (UTC-5)")

print("\nthe same reading twice confirms nothing, because garbage repeats too")
# Off air at 87% blocks good the receiver showed "2206-10-30 14:21 (UTC+9)" for
# 97 s. A group the station repeats every few seconds - a RadioText segment -
# has the same blocks C and D each time, so if its block B is corrected into a
# 4A the same way twice, the two readings are identical, and a time that has
# not moved on at all was inside the 90 s of slack.
p = RdsProtocol()
group_4a(p, 0, 2206, 10, 30, 5, 21, 9, corrected=('B',))
group_4a(p, 30, 2206, 10, 30, 5, 21, 9, corrected=('B',))
check("an identical garbage reading does not confirm the first", shown(p), None)
group_4a(p, 60, 2026, 9, 13, 2, 12, -4)
group_4a(p, 120, 2026, 9, 13, 2, 13, -4)
check("the real clock confirms a minute on", shown(p), "2026-09-12 22:13 (UTC-4)")
group_4a(p, 150, 2206, 10, 30, 5, 21, 9, corrected=('B',))
group_4a(p, 160, 2206, 10, 30, 5, 21, 9, corrected=('B',))
check("and a repeated garbage pair cannot take over the running clock",
      (shown(p), synced_ago(p)), ("2026-09-12 22:13 (UTC-4)", 40))

print("\na station repeating the same minute's group")
p = RdsProtocol()
group_4a(p, 0.0, 2026, 9, 12, 20, 27, -4)
group_4a(p, 0.5, 2026, 9, 12, 20, 27, -4)
check("waits for the next minute rather than trust a repeat", shown(p), None)
group_4a(p, 60, 2026, 9, 12, 20, 28, -4)
check("which confirms it", shown(p), "2026-09-12 16:28 (UTC-4)")

print("\na station whose clock is wrong but consistent")
p = RdsProtocol()
group_4a(p, 0, 2026, 9, 12, 16, 27, 0)
group_4a(p, 60, 2026, 9, 12, 16, 28, 0)
check("still shows what it sends", shown(p), "2026-09-12 16:28 (UTC+0)")

print("\nshown in local time, which can be the day before UTC")
p = RdsProtocol()
group_4a(p, 0, 2026, 9, 13, 0, 27, -4)
group_4a(p, 60, 2026, 9, 13, 0, 28, -4)
check("00:28 UTC on the 13th is the evening of the 12th", shown(p),
      "2026-09-12 20:28 (UTC-4)")

print("\nthe date survives the round trip through Modified Julian Date")
p = RdsProtocol()
group_4a(p, 0, 2024, 2, 29, 23, 59, 5.5)
group_4a(p, 60, 2024, 3, 1, 0, 0, 5.5)
check("leap day into March, half-hour offset", shown(p), "2024-03-01 05:30 (UTC+5.5)")

print("\nTRANSMITTER, decoded straight back\n")
print("once at the start, then at every minute edge")
start = datetime(2026, 9, 12, 16, 27, 40, tzinfo=EDT)
sent, final, first = transmit(lambda t: start + timedelta(seconds=t), 130)
check("sent at stream seconds", [round(at) for at, _ in sent], [0, 20, 80])
check("each within one group of its moment",
      all(0 <= at - edge < GROUP_SECONDS for (at, _), edge in zip(sent, (0, 20, 80))),
      True)
check("each carries the minute it went out in",
      [clock_text(c) for _, c in sent],
      ["2026-09-12 16:27 (UTC-4)", "2026-09-12 16:28 (UTC-4)",
       "2026-09-12 16:29 (UTC-4)"])
check("the time fields on the air are UTC",
      (sent[1][1]['hour'], sent[1][1]['minute']), (20, 28))
check("the receiver shows it as soon as the second group confirms",
      first is not None and 20 <= first < 21, True)
check("and follows it", final, "2026-09-12 16:29 (UTC-4)")

print("\nUTC already in the new year while it is still evening locally")
start = datetime(2026, 12, 31, 19, 59, 30, tzinfo=EST)
sent, final, _ = transmit(lambda t: start + timedelta(seconds=t), 100)
c = sent[-1][1]
check("the group carries UTC",
      (c['year'], c['month'], c['day'], c['hour'], c['minute']), (2027, 1, 1, 1, 1))
check("the receiver shows local time", final, "2026-12-31 20:01 (UTC-5)")

print("\na half-hour time zone")
start = datetime(2026, 9, 12, 10, 0, 50, tzinfo=timezone(timedelta(hours=5.5)))
sent, final, _ = transmit(lambda t: start + timedelta(seconds=t), 75)
check("UTC+5:30 round trip", final, "2026-09-12 10:02 (UTC+5.5)")

print("\ndaylight saving ending mid-stream (02:00 EDT becomes 01:00 EST)")
change = datetime(2026, 11, 1, 6, 0, tzinfo=timezone.utc)


def new_york(t):
    utc = change + timedelta(seconds=t - 90)
    return utc.astimezone(EDT if utc < change else EST)


sent, final, _ = transmit(new_york, 160)
check("the offset is read afresh every minute",
      [c['utc_offset_hours'] for _, c in sent], [-4.0, -4.0, -5.0, -5.0])
check("the receiver follows the clock back an hour", final,
      "2026-11-01 01:01 (UTC-5)")

print("\nno clock, no clock group")
sent, final, _ = transmit(None, 70)
check("nothing sent in 70 s", len(sent), 0)
check("nothing shown", final, None)
check("the computer's clock carries a UTC offset",
      system_clock().utcoffset() is not None, True)

print()
print("RESULT:", "PASS" if not failures else f"FAIL ({', '.join(failures)})")
raise SystemExit(1 if failures else 0)
