#!/bin/bash
# Install the Signal Hound VSG60 vendor library and udev rule on this machine.
#
# The library is proprietary and is NOT shipped in this repository, so it has to
# come from a machine or install that already has it:
#
#   ./linux/setup_vsg.sh                       # find it in a local Sceptre install
#   ./linux/setup_vsg.sh /path/libvsg_api.so.1
#   ./linux/setup_vsg.sh user@host             # copy from another machine via scp
#
# It lands in vendor/ next to the code, which is gitignored and is the first
# place apps/vsg_sink.py looks.

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
VENDOR="$REPO/vendor"
LIB=libvsg_api.so.1
SRC="${1:-}"

mkdir -p "$VENDOR"

if [ -z "$SRC" ]; then
    # Newest Sceptre install wins, same order the loader uses.
    SRC=$(ls -1 /opt/sceptre/lib/$LIB \
             /opt/sceptre-installer/*/lib/$LIB 2>/dev/null | head -1 || true)
    if [ -z "$SRC" ]; then
        echo "No Sceptre install found on this machine." >&2
        echo "Pass the library path, or a host to copy it from:" >&2
        echo "  $0 /path/to/$LIB" >&2
        echo "  $0 user@host" >&2
        exit 1
    fi
    echo "Found local install: $SRC"
elif [[ "$SRC" == *@* && "$SRC" != /* ]]; then
    echo "Copying from $SRC ..."
    scp "$SRC:/opt/sceptre/lib/$LIB" "$VENDOR/$LIB"
    SRC=""
fi

if [ -n "$SRC" ]; then
    [ -f "$SRC" ] || { echo "Not a file: $SRC" >&2; exit 1; }
    # -L: resolve the symlink, we want the real object not a dangling link.
    cp -L "$SRC" "$VENDOR/$LIB"
fi

echo "Installed $VENDOR/$LIB"

# Without this the API cannot claim the device even though lsusb shows it.
RULE=/etc/udev/rules.d/sh_usb.rules
if [ -f "$RULE" ]; then
    echo "udev rule already present: $RULE"
else
    # A refused sudo must not abort the run: the library is already in place and
    # is still worth verifying, and the rule can be added by hand afterwards.
    echo "Installing udev rule (needs sudo) ..."
    if echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="2817", MODE="0666", GROUP="plugdev"' \
            | sudo tee "$RULE" > /dev/null \
            && sudo udevadm control --reload-rules && sudo udevadm trigger; then
        echo "Rule installed - replug the VSG60 for it to take effect."
    else
        echo "WARNING: could not install the udev rule." >&2
        echo "  The library still loads, but opening the device will fail with a" >&2
        echo "  permission error until $RULE contains:" >&2
        echo '  SUBSYSTEM=="usb", ATTR{idVendor}=="2817", MODE="0666", GROUP="plugdev"' >&2
    fi
fi

echo
echo "Verifying ..."
cd "$REPO"
# The app runs under the 'gnu' conda environment; outside it there may be no
# `python` at all, and a stray python3 will not have GNU Radio.
PYTHON=$(command -v python || command -v python3 || true)
if [ -z "$PYTHON" ]; then
    echo "No python on PATH - activate the 'gnu' conda environment and re-run" >&2
    echo "to verify. The library itself is installed." >&2
    exit 0
fi
"$PYTHON" - <<'PY'
try:
    from apps.vsg_sink import is_available, library_error, find_devices
except ImportError as e:
    # Not a failure of the install, so exit clean - same as finding no python
    # at all above. Only a library that will not load is an error.
    print("NOT VERIFIED: cannot import the app (%s)." % e)
    print("The library is installed. Activate the 'gnu' conda environment and")
    print("re-run this script to confirm it loads.")
    raise SystemExit(0)
if not is_available():
    print("FAILED to load the library:\n" + library_error())
    raise SystemExit(1)
print("Library loads OK.")
devices = find_devices()
print("VSG units detected: %s" % (devices or "none (check USB / replug after the udev rule)"))
PY
