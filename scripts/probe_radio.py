#!/usr/bin/env python3
"""Ask whether a radio is present, in a process that then goes away.

Enumerating a HackRF leaves a USB handle open in whoever did the asking.
CLAUDE.md records what that costs: a launcher sitting on a config dialog
still holds ``/dev/bus/usb/...``, so ``SoapySDR.Device.enumerate`` returns
nothing in the app launched next and it fails with ``Device::make() no
match``. The desktop launcher gets away with it because it is the same
process that goes on to build the flowgraph. A web launcher lives for days
and would hold that handle for days, breaking every launch after the
first.

So the check lives here instead, and the handle dies with this process::

    python scripts/probe_radio.py hackrf
    {"ok": true, "title": "", "detail": ""}

Failures come back as ``ok: false`` with the same wording the desktop
launcher puts in its dialogs, so both front ends say the same thing.
Exit status is 0 whenever the question was answered, present or not.

Run it with the ``gnu`` environment's Python - SoapySDR lives there.
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def answer(ok, title="", detail=""):
    print(json.dumps({"ok": bool(ok), "title": title, "detail": detail}))
    return 0


def probe_hackrf():
    try:
        import SoapySDR  # type: ignore
        if not SoapySDR.Device.enumerate({'driver': 'hackrf'}):
            raise RuntimeError("no hackrf device found")
    except Exception:
        return answer(
            False, "HackRF Not Found",
            "No HackRF One was detected on USB.\n\n"
            "Connect your HackRF One and try again, or change the radio "
            "type to USRP in Settings.")
    return answer(True)


def probe_usrp():
    # The USRP is on the network, so there is nothing on USB to look for -
    # the desktop dialog simply disables OK until an address is set.
    settings_path = os.path.join(ROOT, 'config', 'window_settings.json')
    addresses = []
    try:
        with open(settings_path) as fh:
            addresses = json.load(fh).get('ip_addresses') or []
    except Exception:
        pass
    if not addresses:
        return answer(
            False, "No USRP Address Set",
            "The Ettus USRP is reached over the network, and no address is "
            "configured.\n\nAdd one in Settings.")
    return answer(True)


def probe_bb60():
    try:
        sys.path.insert(0, ROOT)
        from apps.bb60_source import (find_devices as find_bb60,
                                      is_available as bb60_software)
    except Exception as exc:
        return answer(False, "Signal Hound BB60D Software Not Found", str(exc))
    if not bb60_software():
        return answer(
            False, "Signal Hound BB60D Software Not Found",
            "The SoapySDR module for the BB60D could not be found, so it "
            "cannot be used on this machine.\n\nIt is a system module - "
            "normally /usr/local/lib/SoapySDR/modules0.8/"
            "libSignalHoundBB60.so - and is not part of this conda "
            "environment.")
    if not find_bb60():
        return answer(
            False, "Signal Hound BB60D Not Found",
            "No Signal Hound BB60D was detected on USB.\n\nCheck it is "
            "connected, and that no other application already has it open.")
    return answer(True)


def probe_vsg():
    try:
        sys.path.insert(0, ROOT)
        from apps.vsg_sink import (find_devices, in_use, is_available,
                                   library_error)
    except Exception as exc:
        return answer(False, "Signal Hound VSG Software Not Found", str(exc))
    # A missing vendor library is a software install problem, not an absent
    # device - reporting it as "not detected on USB" sends people to check
    # a cable that was never the fault.
    if not is_available():
        return answer(
            False, "Signal Hound VSG Software Not Found",
            "The Signal Hound VSG API library could not be loaded, so the "
            f"VSG60 cannot be used on this machine.\n\n{library_error()}")
    if not find_devices():
        return answer(
            False, "Signal Hound VSG Not Found",
            "No Signal Hound VSG60 was detected on USB.\n\nConnect your "
            "VSG60 and try again, or change the radio type in Settings.")
    # The vendor library aborts the process on a second open, so refuse
    # before we get anywhere near it.
    if in_use():
        return answer(
            False, "Signal Hound VSG In Use",
            "The Signal Hound VSG60 is already being used by another "
            "running flowgraph.\n\nClose that application first - opening "
            "the VSG twice crashes both and can leave the device needing a "
            "USB reset.")
    return answer(True)


PROBES = {'hackrf': probe_hackrf, 'usrp': probe_usrp,
          'bb60': probe_bb60, 'vsg': probe_vsg}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 1 or argv[0] not in PROBES:
        print(f"usage: probe_radio.py {{{'|'.join(PROBES)}}}", file=sys.stderr)
        return 2
    return PROBES[argv[0]]()


if __name__ == '__main__':
    sys.exit(main())
