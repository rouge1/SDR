# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Application

```sh
# Using the launch script (activates .venv conda environment):
./start_app.sh

# Or directly (requires the 'gnu' conda environment to be active):
conda activate gnu
python gnuradio_launcher.py
```

The app requires a display (X11/Wayland) and either a HackRF One (USB) or Ettus USRP (network) connected. Radio type is selected in the Settings dialog.

On Windows it is `start_app.ps1` instead, and the environment comes from
`environment-windows.yml` rather than `environment.yml` - see
[Running on Windows](#running-on-windows).

## Architecture

This is a **PyQt5 launcher** for GNU Radio signal generation/transmission applications. The launcher presents a grid of buttons, each opening a config dialog before launching a GNU Radio flowgraph.

### Launch Flow

1. `gnuradio_launcher.py` — Main window (`GNURadioLauncher`). Dynamically imports app modules from `apps/` using `importlib`.
2. When a button is clicked → `launch_application(module_name)` instantiates the module's `ConfigDialog` → user configures parameters → on OK, calls `module.main(app=..., config_values=...)`.
3. In **single mode**: launcher hides itself while the app runs, then shows again when the app closes. In **multi mode**: launcher stays visible.

### App Module Contract

Every module in `apps/` must implement:
- `ConfigDialog(QDialog)` — shows configuration UI; must implement `get_values()` returning a dict of config params; saves/loads its own per-app JSON config to `config/<module_name>_config.json`.
- `main(top_block_cls=..., options=None, app=None, config_values=None)` — creates and starts the GNU Radio `top_block`, returns the `top_block` instance (not `app.exec_()`).

The flowgraph class itself (e.g., `amSineGenerator`) extends both `gr.top_block` and `Qt.QWidget`.

### Shared Utilities (`apps/utils.py`)

- `apply_launcher_theme(widget)` — dark stylesheet for the main launcher window.
- `apply_dark_theme(widget)` — dark stylesheet for config dialogs (also sets minimum dialog size).
- `read_settings()` — reads `config/window_settings.json`, returns dict with `media_directory` and `ip_addresses`.

### Settings / Persistence

All settings are stored in `config/window_settings.json`:
- `window_position` — launcher window geometry (saved/restored on open/close).
- `dialog_position` — last config dialog position.
- `ip_addresses` — list of USRP IP addresses (configured via the settings gear icon).
- `media_directory` — path for recorded audio/video files.
- `radio_mode` — `"single"` or `"multi"` (multi requires ≥2 IP addresses).
- `radio_type` — `"hackrf"`, `"usrp"`, or `"vsg"`.

Per-app configs are saved separately as `config/<module_name>_config.json`.

### USRP / Hardware

Three radio backends are supported, selected via `radio_type` in settings:

- **HackRF One** — USB SDR via SoapySDR (`soapy.sink('driver=hackrf', ...)`). No IP address needed; OK button always enabled. Gain set via `set_gain(0, 'VGA', value)` (0–47 dB) and `set_gain(0, 'AMP', 0)`.
- **Ettus USRP** — Network SDR via UHD (`gnuradio-uhd`). IP addresses configured in the settings gear dialog; OK button disabled when none are set. Gain set via `set_gain(value, 0)`.
- **Signal Hound VSG60** — USB vector signal generator (VID:PID `2817:0008`). No SoapySDR module and no stock GNU Radio block exists, so `apps/vsg_sink.py` wraps the vendor C API (`libvsg_api.so`) with ctypes as a `gr.sync_block`. No IP address needed; OK button always enabled. Level set via `set_level(dBm)` — a *calibrated absolute* output power, not a relative gain index.

#### VSG60 notes

- Limits (enforced by clamping in `vsg_sink.py`): 30 MHz – 6 GHz, 12.5 kS/s – 50 MS/s, −120 to +10 dBm.
- `vsgSubmitIQ` blocks when the device queue is full, so it supplies real backpressure — the flowgraph needs no throttle block.
- `vsgGetDeviceList` needs its count argument **primed with the array capacity** or it reports zero devices.
- **The vendor API is not thread safe.** A setter called from the Qt thread while the work thread is inside `vsgSubmitIQ` corrupts the device: the submit fails and every subsequent call returns an error until reopen. `vsg_sink` serialises all API calls on an `RLock`; `vsgAbort` is deliberately called *outside* the lock during shutdown, since its job is to unblock a parked submit.
- The library ships inside the Sceptre install rather than a system prefix, in a
  directory named after the Sceptre version, so the path differs per machine.
  `vsg_sink.py` therefore searches *directories* — `/opt/sceptre/lib` (the
  symlink the installer points at the current install), then
  `/opt/sceptre-installer/*/lib` newest version first, then `/usr/local/lib`
  and `/usr/lib`, then the bare soname for ldconfig'd installs. `VSG_API_LIB`
  overrides and accepts either the library file or the directory holding it.
  When the load fails the error names every directory searched and every path
  tried; the launcher reports a missing library as a *software* problem rather
  than as "no VSG detected on USB", which is a different fix.
- **Running a VSG without installing Sceptre.** Sceptre is not required — it is
  just where the library happens to ship. `libvsg_api.so.1` is self-contained
  (~8 MB, API 1.2.1): standing alone it links only against system
  `libusb-1.0`, `libstdc++`, `libudev`, `libm`, `libgcc_s`, `libc`, and needs
  no glibc newer than 2.17. Copy that one file to the target machine, point
  `VSG_API_LIB` at it (or at its directory), and install the udev rule
  `SUBSYSTEM=="usb", ATTR{idVendor}=="2817", MODE="0666", GROUP="plugdev"` as
  `/etc/udev/rules.d/sh_usb.rules`. Do **not** copy the whole
  `/opt/sceptre/lib` directory: its `RUNPATH` starts with `$ORIGIN`, so the
  siblings there (a bundled libc, libstdc++, libudev) would be picked up ahead
  of the system ones and mixed into the host runtime.
- **A second open aborts the process.** The vendor library enforces single-client access with C `assert()`, which calls `abort()` — `vsgOpenDevice` on a device another process holds raises SIGABRT and core-dumps before Python sees anything, and can leave the unit needing a USB reset. It is uncatchable, and `vsgGetDeviceList` still lists a held device, so discovery cannot detect the condition either. `vsg_sink` therefore keeps an advisory PID lock at `config/.vsg60.lock`: `_acquire_lock()` runs before the open and raises a normal `RuntimeError` instead, `in_use()` lets the launcher show a dialog, and a lock whose PID is dead is treated as stale and cleared. This only sees users that go through this module — an external Signal Hound application holding the device is invisible to it.
- **Locking a running flowgraph closes the VSG unless it is held open.** GNU
  Radio calls `stop()` and then `start()` on every block when a flowgraph is
  locked and unlocked, which is how the FM + RDS transmitter's Next Track once
  swapped its audio chain. `stop()` closes the device, since it is also the
  only notice of a real shutdown, and the sink once had no `start()`: after
  Next Track the VSG stayed closed, `work()` reported done, and the whole
  broadcast ended with no error - a receiver just saw the station stop.
  `start()` now reopens it, but opening a VSG60 takes 4.7 s (measured), whereas
  `vsgAbort` takes 0.1 s and the open device accepts samples again straight
  after. So a rebuild wraps its `lock()`/`unlock()` in `sink.held_open()`,
  inside which `stop()` leaves the device open; the reopen in `start()` is only
  the fallback. Nothing in the apps locks a running flowgraph any more - Next
  Track now swaps files in place, because a rebuild glitches the pilot and RDS
  whatever the radio (see the FM + RDS notes) - so this is the rule for
  anything that does.

### Output Power

The power slider in every app is a plain **0–100%** control. Each radio has a
different native gain unit and a different usable span, so the percentage is
mapped onto that radio's own range by `scale_power()` in `apps/utils.py` —
0% is always that radio's minimum, 100% always its maximum:

| Radio | Range | Unit |
|-------|-------|------|
| HackRF One | 0 – 47 | dB VGA gain |
| Ettus USRP | queried via `get_gain_range()`; 0 – 31.5 on the N-series/WBX here, which is also the fallback | dB gain |
| Signal Hound VSG60 | −120 – +10 | dBm, calibrated absolute output |

This replaced an earlier scheme where the slider was labelled dBm but fed
`(rfPwr+50)*(rfPwr>-50)` to the radio. That capped HackRF and USRP at 20 dB of
gain, made the bottom 30 dB of the slider a no-op, and — once the VSG was added,
where the value was taken literally as dBm — left the VSG running 40 dB below
its maximum.

The same change retired a second stage: a baseband multiplier of
`10**((rfPwr<=-50)*(rfPwr+50)/20)` that attenuated digitally below −50 on the
old slider. With the analog stage now covering the full range, baseband stays at
full scale and those expressions are plain constants.

Saved per-app configs from before the change hold values like `-50`, which would
clamp to 0% and produce no output. `power_percent()` in `apps/utils.py` catches
anything outside 0–100 on load and substitutes the 50% default.

### Adding a Radio Backend to an App

Each app branches on `radio_type` at four sites: `create_usrp_selector()` in the
dialog, the sink construction in the flowgraph `__init__`, and the `set_rfPwr` /
`set_cf` / `set_samp_rate` callbacks. The flowgraph resolves `self._power_range`
once at construction (re-resolving it for USRP after the sink exists, since the
range comes from the device) and every power call goes through
`scale_power(value, self._power_range)`. `vsg_sink` deliberately implements both the
UHD (`set_center_freq`, `set_samp_rate`, `set_gain(v, chan)`) and Soapy
(`set_frequency`, `set_sample_rate`, `set_gain(chan, name, v)`) setter idioms, so
only the sink construction and the power callback need a VSG branch — the
frequency and sample-rate callbacks work through the existing HackRF path.

### Available Applications

| Module | Description | Tested |
|--------|-------------|--------|
| `askGenerator.py` | ASK signal generator | ✅ |
| `fskGenerator.py` | FSK signal generator | ✅ |
| `amSineGenerator.py` | AM sine wave generator | ✅ |
| `pskGenerator.py` | PSK signal generator | ✅ |
| `fmAudioRecordedGenerator.py` | FM with recorded audio | ✅ |
| `amAudioInternalGeneratorLive.py` | AM with live/recorded audio | ✅ |
| `ppmookAudioXmitter.py` | PPM-OOK live audio transmitter | ✅ |
| `subcarrierRecordedAudio.py` | Subcarrier with recorded audio | ✅ |
| `amVideoRecordedXmitter.py` | AM video transmitter | ⏳ |
| `ntscAnalogVideoRecorded.py` | NTSC analog video transmitter | ⏳ |
| `atscXmitter.py` | ATSC digital TV transmitter | ⏳ |
| `rdsReceiver.py` | RDS/RBDS receiver - decodes FM station data | ✅ |
| `fmRdsTransmitter.py` | FM broadcast transmitter with RDS | ✅ |

### RDS Receiver (the one receiving app)

`rdsReceiver.py` tunes an FM broadcast station and decodes the data on its
57 kHz subcarrier: station ID (PI), program service name, RadioText, program
type and clock time. Two consequences of being the only receiver:

- **It uses the radio chosen in Settings**, like every other app: the HackRF,
  or a USRP picked from the configured addresses. The VSG60 transmits only, so
  with it selected the whole dialog is an error pointing at Settings, and
  closing it launches nothing.
- **Gains are applied after `tb.start()`** (`main()` calls `tb.apply_gain()`).
  SoapyHackRF silently ignores the `AMP` stage when it is set before the stream
  is running - worth ~14 dB, which is the difference between decoding and not.

The decoding itself lives in `apps/rds_core.py`, deliberately free of GNU Radio
and Qt so it can be run against a recorded capture:

```sh
python scripts/test_rds_core.py <capture>   # capture path without .cfile
python scripts/test_rds_radiotext.py        # RadioText changes - no radio, no capture
python scripts/test_rds_clock.py            # clock time, received and sent - no radio
```

`RdsDemod` mixes the MPX down by the 57 kHz subcarrier and integrates each
biphase symbol; `RdsProtocol` syncs to the 26-bit block structure, corrects
error bursts up to 5 bits with the (26,16) code, and assembles the fields.
Three things that are easy to get wrong and cost real time here:

- **The 57 kHz subcarrier and the 1187.5 bit/s clock are both locked to the
  19 kHz stereo pilot** (x3 and /16). One PLL lock on the pilot supplies the
  carrier phase *and* the symbol timing, so no separate recovery loops.
- **The symbol timing offset is not a constant and must be measured.** The bit
  grid is anchored at whatever pilot phase the first sample had, so it differs
  every run and with any filter delay. `_pick_tau` measures it by scoring
  candidate offsets on how many valid offset words appear. A wrong value
  produces plenty of bits at exactly the right rate and decodes *nothing*.
- **RadioText is buffered per A/B flag, not cleared on toggle.** The flag means
  "new message, clear what you have", but it is a single bit in block B, so a
  corrupted one would wipe a good message. `RdsProtocol` keeps a buffer for each
  flag value: a bad bit writes into the page nobody is displaying, and a genuine
  page change clears its target buffer *and writes the same group into it*.
  Clearing without writing loses the first four characters of every page - which
  is exactly what paged paragraphs exposed.
- **A new message is also detected from its content, because many stations
  never toggle the flag.** 98.7 rotates a slogan, the song and an advert through
  RadioText with A/B stuck at 0, so nothing ever cleared the buffer: each message
  overwrote the last segment by segment, the display showed splices like
  "98.7WMZQBest Country", and a car-dealer advert turned up inside the song
  name. A segment that contradicts characters the current message has already
  sent now starts a new message.
- **Only blocks that arrived clean may announce a new message.** The (26,16)
  code maps nearly every syndrome to *some* correction, so a block whose error
  burst is too long comes back wrong rather than rejected - 'Tyler' as 'Eyler',
  a space as '&'. Taking that for a new message blanked the display, and so did
  the clean pass that repaired it. Requiring two differing characters was not
  enough, because a bad block usually changes both of the characters it
  carries. Characters from a block that needed correcting are therefore
  provisional: one fills a position nothing has written yet and stays until a
  clean block replaces it. It never overwrites a clean character - nor another
  provisional one, since a repair that came out right would otherwise be
  replaced by the next that came out wrong - never counts as a contradiction,
  and a corrected A/B flag cannot clear a buffer. Measured with encoded error
  bursts at 96.6% blocks good, the text had been wrong on screen nearly two
  thirds of the time and short or blank a fifth of it; afterwards both were
  zero at 96.6, 98.4 and 99.4%, and `scripts/test_rds_radiotext.py` now
  requires never. Off air, the VSG60 into the Windows laptop's HackRF at 96-97%
  blocks good: 114 wrong or blank displays in five minutes before, none in six
  and a half after.
- **But a repair that comes out the same twice is believed.** Refusing every
  repair was too strict on a weaker link: at 93% blocks good about six repairs
  in seven were right, yet two thirds of RadioText groups carried at least
  one, so the text after Next Track sat with gaps for 54 s, and Now Playing,
  which waits for every tagged character, took 58 s. `_believed()` accepts a
  segment whose repair matches the last repaired reception of that same
  segment, since a wrong repair almost never comes out the same way twice. PS
  goes through it too - taking every repair as it came, PS had flashed a wrong
  value 135 times in four minutes - and so do RT+ tag groups. **Verified off
  air**, the transmitter window on the VSG60 against the receiver window on the
  Windows HackRF, on a link that fell to 80-90% blocks good: PS wrong 0% of the
  time (was 24%, 135 flickers), and the Station Clock turned over within a
  second of every minute (was never shown). What remains is the link itself:
  after Next Track, at 80%, RadioText and Now Playing still took 44-47 s to
  arrive whole.
- **Now Playing is an RT+ item, kept until the song changes.** NRSC-G300-C
  section 6.10 has a receiver keep RT+ title, artist and the rest of content
  types 1-11 across RadioText messages for as long as the item toggle bit
  holds, and purge them when it flips. So the receiver keeps them through
  untagged messages and A/B page switches, and drops them when the toggle
  flips - or when a tag arrives from a different message, so that a title
  tagged in an advert never sits beside the artist of the song before it.
  Clearing them on every new message instead, as it once did, showed Now
  Playing as "-" whenever a station, or the transmitter here, sent any other
  RadioText while the song was still playing.
- **An RT+ tag may only slice characters the current message sent.** Tags that
  arrived while the next message was still filling in cut across both, welding
  "Dan +" from the new text to "ntry" from the tail of "Country". Stations repeat
  the tag group every second or two, so a refused tag lands on the next pass.
- **A clock group is a sync, the way a car radio treats it.** Stations that
  send group 4A do so about once a minute, and many send none: 98.7 sent no 4A
  in 12 minutes of 99.99% clean blocks, yet the receiver once displayed
  "2168-10-28 01:27 (UTC-9)" for it. A block B that the code corrects wrongly
  turns any group into a 4A - those same 12 minutes held one 1B and one 12B,
  types the station never sends - and its C and D then decode as a date. The
  first reading is therefore believed only once another 4A carries the same
  offset and a time that has moved on by as much as the bitstream has
  (`bits_in` at 1187.5 bit/s, so replaying a capture flat out behaves the
  same). From then on the clock runs by itself on that stream time: a lost
  group costs nothing, one group agreeing with the running clock re-syncs it,
  and the window says how long ago that was. Before this, a lost group left
  the display a minute or more behind. Garbage that disagrees is ignored, while
  a genuine change - the offset moving when daylight saving ends - takes two
  agreeing groups. The second witness may be any of the last few readings,
  not only the latest: off air at 93% blocks good, garbage clock groups made
  from repaired B blocks arrived twice in one minute, and remembering a single
  reading kept the clock off the screen for five minutes. Repaired groups are
  still used, because the real ones are repaired too - the 19:53 and 19:54
  groups in that run both had block B repaired and carried the right time.
  A station whose clock is wrong but consistent still shows.
  It is shown as local time: the group carries UTC hours and minutes with the
  offset beside them, so printing those fields next to "(UTC-4)", as the
  receiver once did, reads four
  hours fast and can show tomorrow's date. `clock_text()` does the arithmetic
  for both the receiver and the transmitter's On Air box.
- **Do not average PS or RadioText over time.** US stations scroll messages
  through the 8-character PS field and often alternate two RadioText messages
  without toggling the A/B flag, so averaging blends them into gibberish. The
  live fields take characters as they arrive; the stable station name comes
  from the most common complete PS (`ps_history`).

A station's PI need not match its call sign. 98.7 WMZQ transmits `0x16F2` where
the RBDS formula gives `0x76F2` - altered in the high nibble only, which US
stations do for traffic-data (TMC) services, shared-PI simulcasts and factory
defaults. Mapping `0x16F2` straight back yields the nonsense "KCQK".

`callsign_candidates()` therefore restores each possible high nibble, and
`RdsProtocol.confirmed_callsign()` picks the candidate that appears in the
station's own PS or RadioText - "98.7WMZQ" confirms WMZQ out of the nine
possibilities. The UI shows a confirmed call sign plainly and an
uncorroborated one as "maybe", with the PI itself always the real identifier.

Why the nibble changes, confirmed off-air against NRSC-G300-C section 5.1: the
RDS-TMC standard has a receiver match the PI's *country code* against its map
data, and the US was assigned country code 1, so stations carrying traffic data
set the high nibble to 1. All three local iHeartMedia stations do it - WMZQ
7→1, WIHT 6→1, WBIG 5→1 - and each restores exactly to its real call sign. Only
WMZQ actually transmits TMC (`has_tmc`, ODA AID 0xCD46 in group 8A); the others
appear to follow the group convention.

**RadioText+ (`RTPLUS_AID`, 0x4BD7).** The same NRSC guideline tells receivers
to read the RT+ StationName field rather than back-calculating a call sign, and
all three local stations carry RT+ in group 12A. It tags substrings of the
RadioText by class, so "Love Somebody" and "Morgan Wallen" arrive as separate
`title` and `artist` fields. Stations do ship offsets that do not match the text
they actually sent (99.5 tags two characters late, yielding "jured? Attorne"),
so `_parse_rtplus` drops any tag that would slice a word in half.

### FM + RDS Transmitter

`fmRdsTransmitter.py` plays audio from the media folder as a real FM broadcast
signal and carries a live-editable station name, RadioText and now-playing tags
on the 57 kHz subcarrier. The encoder is `apps/rds_encode.py`, again free of GNU
Radio and Qt so it can be tested without a radio:

```sh
python scripts/test_rds_loopback.py        # encoder -> decoder, no radio at all
python scripts/test_fm_rds_tx.py <wav>     # whole modulation chain -> decoded back
python scripts/test_fm_rds_next_track.py   # Next Track keeps pilot and RDS continuous
```

The multiplex is built at 200 kHz (everything up to 60 kHz fits), interpolated
to the 2 MS/s the radio runs at, and only then frequency modulated - doing it in
that order matters, because the modulated signal is far wider than the
multiplex. Levels are shares of the 75 kHz peak deviation: audio 0.55, pilot
0.09 (the standard 9 %), RDS 0.04. Measured output is ~48 kHz peak deviation
with music playing.

Things worth knowing before changing it:

- **Keep a Python reference to every block.** `rds_source` is a Python block; if
  its wrapper is garbage collected while the C++ scheduler is running, the
  process segfaults with no Python frame in the traceback. The app stores blocks
  on `self`, and `scripts/test_fm_rds_tx.py` keeps a `tb.keepalive` tuple - a
  plain function that builds a flowgraph and returns only the top block will
  crash.
- **0 % power is not off.** On the bench, a HackRF at the minimum VGA setting
  still put the signal 32.5 dB above the noise floor at the receiver several
  feet away, decoding at 100 %. Treat "lowest setting" as "still transmitting",
  pick an empty channel, and do not assume a low slider is harmless.
- The pilot and the RDS subcarrier are generated from one sample counter in
  `RdsSubcarrier`, so 57 kHz stays exactly three times the pilot and the bit
  clock exactly a sixteenth of it. Receivers depend on that lock.
- **Stereo is matrixed, not sent as left and right.** A 2-channel file becomes
  mid (L+R)/2 as ordinary audio plus side (L-R)/2 on a 38 kHz DSB-SC
  subcarrier, which is what keeps the signal listenable on a mono receiver.
  `rds_source` emits that 38 kHz carrier on its second output, from the same
  sample counter as the pilot so it stays exactly twice it - a separate
  oscillator would drift and lose stereo. The chain is always stereo: a mono
  file leaves `audio_source` the same on both sides, so its difference is zero
  and the subcarrier carries nothing - on the air, a mono signal. Verified
  off-air: 38 kHz subcarrier 24.8 dB
  out of the noise, 47 kHz peak deviation, RDS unaffected at 904/904 blocks.
  Test it with `scripts/test_fm_stereo.py <stereo.wav>`.
- **Next Track swaps the file inside a running source; it must never rebuild
  the flowgraph.** It once did - `lock()`, `disconnect_all()`, rebuild,
  `unlock()` - and that throws away every sample in transit, so pilot and RDS
  jumped 139 degrees of pilot phase at each press. A receiver measures its RDS
  bit timing once and then follows the pilot, which reveals only the fraction
  of a cycle that jumped, so its bit grid ended up off by whole sixteenths of a
  bit: decoding fell from 100% to 30-60% in software, and off air to nothing at
  all while the RF was plainly still there. A check that decodes a fresh
  capture never sees this, because it measures the timing anew - which is how
  "RDS unaffected" above was measured. `audio_source` plays WAV files, the tone
  or silence and switches in place; `scripts/test_fm_rds_next_track.py` records
  the multiplex across stereo-to-stereo and stereo-to-mono presses and requires
  the pilot to carry straight on and a frozen-timing decoder to stay at 95% or
  better.
- **The recovered side/mid ratio reads high off the air, and should.** Measured
  -5.8 dB against -8.7 dB in the source file; in a noiseless software run the
  gap is only 1.4 dB. FM noise grows with baseband frequency and the difference
  signal sits at 23-53 kHz where there is more of it. That is the same effect
  that makes stereo reception noisier than mono, not a fault in the chain.
- **Channel separation is the measurement that actually proves stereo, and it
  needs its phase fitted.** `scripts/test_fm_separation.py` drives one channel
  with a tone while the other stays silent and measures how much leaks across,
  reading only at the tone frequency so noise cannot flatter the result
  (validated to 0.1 dB against deliberately injected crosstalk). Measured
  34.3 dB through the chain and 32-33 dB off the air via a BB60D, which is
  normal for FM stereo. But the regenerated 38 kHz subcarrier has to be
  phase-aligned with the multiplex: the pilot reaches the PLL through a
  band-pass whose group delay the multiplex does not share, so assuming zero
  offset reads 18 dB and looks exactly like a broken transmitter. The delay
  arithmetic predicts the offset - a 401-tap band-pass delays 200 samples,
  0.2 of a cycle at 19 kHz, 72 degrees of pilot phase, doubled to ~144 degrees
  at 38 kHz - and the fit lands on 144 in software and 146 off the air.
- **The On Air box reads the encoder, not the edit boxes.** What was typed is
  not always what is being sent: Next Track rewrites RadioText and its RT+
  tags, and a paged paragraph moves on by itself. So Station (call letters and
  PI), PS, Now Playing (the song on air, whichever RadioText page is up), RadioText
  and Station Clock (the last group 4A sent) come from
  `RdsEncoder.snapshot()` on a 500 ms timer - the same fields the RDS Receiver
  shows, so the two windows can be compared side by side.
- **The clock is the computer's own, sent as group 4A** once as the stream
  starts and then at the start of every minute, as NRSC-4-A Annex M asks. The
  hour and minute go out as UTC with the local offset beside them, and
  `system_clock()` is read afresh each minute so daylight saving follows the
  OS. The encoder checks the minute ahead of every group, so the group leaves
  within 88 ms of the edge. A receiver needs two groups before it trusts one,
  so the Station Clock appears one to two minutes after tuning in. An
  `RdsEncoder` built without a `clock` sends none, which is what NRSC-G300-C
  section 5.8 asks of a station with no reliable time source. `docs/` holds
  those rules and the Annex G date formulas, but not the bit layout itself:
  that is Part I section 3.1.5.6, and the NRSC-4-A PDF there is Part II only.
  **Verified off-air**, the VSG60 on the Linux box at 102.1 MHz and -42 dBm
  into the Windows laptop's HackRF: every group left 39-89 ms after its
  minute, and the receiver showed the right local minute within a second of
  it. With the encoder told to stop sending after two groups, the receiver's
  clock went on turning over within half a second of each minute for the
  remaining four.
- **Tests drive the clock from the bitstream, not the wall.** Handing the
  encoder `clock=lambda: start + timedelta(seconds=enc.bits_sent / 1187.5)`
  makes a minute edge arrive on schedule however fast the stream is produced,
  so `scripts/test_rds_clock.py` runs minutes of transmission - daylight saving
  ending, UTC already in the new year - in under a second.
- RT+ offsets are computed from the very RadioText string that gets sent
  (`set_now_playing` does both together), which is precisely what 99.5 locally
  gets wrong.
- **Typed RadioText takes turns with the song, and Now Playing stays on it.**
  Now Playing is not text of its own: it is RT+ tags pointing into RadioText,
  so replacing RadioText used to end it, and Send Text showed Now Playing as
  "-" on both windows. With a song on air, `set_radiotext()` now rotates the
  typed message with the song's own line, three passes each (about 6-10 s,
  depending on length). During the message the RT+ group still goes out, with
  empty tags and the item toggle bit unchanged, which tells receivers to keep
  the song (NRSC-G300-C 6.10); a receiver tuning in later learns the song on
  its turn. The toggle flips only in `set_now_playing()`, i.e. on Next Track,
  and a typed message stays through Next Track. Sending the song's own line,
  or nothing, goes back to the song alone. Pages shorter than 64 characters
  stop at their carriage return instead of sending padding, so each turn gets
  across sooner. An RT+ tag goes out only once every segment it points into
  has gone out, starting from the first segment of the new text: Next Track
  part way through a pass once sent padding first, identical in the old and
  new lines, and a receiver that had seen nothing change sliced "Stereo" out of
  "Stereo B" with the new song's tag - caught by the Next Track test on the
  slower Windows laptop, and now reproduced on purpose in
  `test_rds_radiotext.py`. Waiting for the whole 64-character line instead
  cost 3.4 s per song, and on that laptop, which ran the test flowgraph at
  about 70% of real time, Now Playing never arrived at all.
- **Messages longer than RadioText are paged.** `set_paragraph()` splits text on
  word boundaries into 64-character pages, sends each one complete, then toggles
  the A/B flag so receivers clear before the next. Pages advance on segments
  sent rather than a clock, so a page is never replaced halfway out. Budget
  ~4.2 s per page at the standard group mix: a 250-character paragraph is five
  pages and takes about 21 s to deliver in full.
- **Paged text is numbered "2/5 " for a reason.** The cycle repeats forever, so
  a receiver tuning in mid-paragraph gets every page but *rotated*, not in
  reading order - measured off-air, a capture began at page 2 and wrapped to
  page 1 last. The prefix is what allows reassembly without waiting to spot
  where the cycle wraps; it also costs page width, which can add a page and so
  widen the prefix, which `set_paragraph` settles by iterating.

### Testing the launcher end to end

The `scripts/test_*.py` above all bypass the GUI. `scripts/test_launcher_gui.py`
covers what they cannot - that `./start_app.sh` starts, that a button press
reaches `launch_application`, that the dialog accepts, that the flowgraph
window appears, and that closing it brings the launcher back - by driving real
X input through xdotool (`apt install xdotool`):

```sh
python scripts/test_launcher_gui.py "RDS Receiver"
python scripts/test_launcher_gui.py "FM + RDS Transmitter" --hold 30
```

- **Close any running launcher first.** A launcher process keeps a USB handle
  on the HackRF - `/proc/<pid>/fd` shows `/dev/bus/usb/...` - even while it is
  only *sitting on a config dialog*. `SoapySDR.Device.enumerate` then returns
  zero devices and the app under test fails with `Device::make() no match`,
  which surfaces as a modal error box that nothing dismisses, so an automated
  run just hangs. The script refuses to start if it finds one.
- **Button coordinates are found, not computed.** High-DPI scaling moves the
  grid, so `button_grid()` locates the icons as bright blobs in a screenshot
  and `registered_apps()` reads label -> (row, col) out of the launcher's own
  `create_app_button` calls. A button that moves takes the click with it.
- Screenshots are grabbed with Qt rather than scrot/import/maim, none of which
  are guaranteed present, while PyQt5 is already a hard dependency.
- `Return` activates the dialog's default button, which is OK - cheaper than
  hunting for its pixels. Window close buttons sit at `(X + WIDTH - 33,
  Y + 30)` from the frame geometry xdotool reports, *not* at its corner.

### Signal Hound BB60D as a receiver

The BB60D works well for RDS (0.0 % block errors on a strong station) but is
**not** driven through `gr-soapy`. It is a SoapySDR device - the module is a
system one at `/usr/local/lib/SoapySDR/modules0.8/libSignalHoundBB60.so`, so
`SOAPY_SDR_PLUGIN_PATH` must point there - and while `soapy.source(...)`
constructs fine, *every* gr-soapy setter (`set_frequency`, `set_gain`,
`set_sample_rate`) then fails with `setupStream: Invalid format ''`. Its sample
rates are also 40/20/10/5/2.5 MSps with nothing near the 2 MS/s the HackRF path
uses, so 2.5 MSps (decimate by 10) is the one to use.

What does work today is recording with raw SoapySDR and decoding offline -
`/data/python/bluey-ox-walker/bin/record_iq.py` on the **system** Python already
does this (`--driver SignalHoundBB60`), and its output is complex float32, which
`scripts/test_rds_core.py` reads directly given a JSON sidecar. Note that module
wants `setupStream` called *before* any configuration.

Driving it live from the launcher would mean a small source block wrapping raw
SoapySDR, in the spirit of `apps/vsg_sink.py`.

**Verified off-air, HackRF transmitting into the BB60D** at 102.1 MHz and 78 %
power: the signal read 63.6 dB above the noise floor and decoded 912/912 blocks
with 0.0 % errors - PI, PS, RadioText, RT+ and PTY all as sent. Channel
separation measured 33.7 dB and 32.9 dB with the 38 kHz phase fitted to 144
degrees, matching the software chain. A RadioText edit typed into the running
app arrived intact on the next capture. Its RT+ tags were cleared then, which
is no longer the design: a typed message now takes turns with the song, and
Now Playing stays on the song (see the FM + RDS Transmitter notes).

Three things cost time on the way there, all in the *measuring*, not the radio:

- **Flat SNR across gain means the antenna, not the gain.** With the BB60D's
  antenna off, a local FM station sat ~16 dB above the noise floor at every one
  of 0/20/30/40 dB of gain - more gain lifts signal and noise together.
  Connecting it raised the capture rms by 23 dB and the station to 27.6 dB.
  (`record_iq.py --gain 0` also genuinely zeroes the RF stage; its default is
  30.) A bare CW carrier is the quickest way to split "the RF path is dead"
  from "the app is not radiating" - one read 76.8 dB out of the noise.
- **Redirect a capture harness's stdout and Python block-buffers it.** A script
  that waits on a log line to know the transmitter is up will start recording
  long after it should, or not while it is running at all, and the capture
  comes back as pure noise with nothing wrong anywhere. Run it with `python
  -u`.
- **Slice well clear of a live change.** Measuring a field that was edited
  mid-capture, a window that straddles the transition catches an RT+ tag
  belonging to the *outgoing* message and reads exactly like a stale-tag bug.
  Decode a slice safely after the change before believing one.

### Running on Windows

The launcher runs natively on Windows - no WSL, no USB/IP passthrough.
conda-forge ships the *same* GNU Radio for win-64 that this repo uses on Linux
(3.10.12.0, py312), so the flowgraphs run against the version they were written
for.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap_windows.ps1
powershell -ExecutionPolicy Bypass -File .\start_app.ps1
```

`bootstrap_windows.ps1` installs Miniforge if there is no conda, builds the
`gnu` environment, then verifies that gnuradio, qtgui, soapy, PyQt5 and
SoapySDR import and reports how many radios Soapy sees. It is idempotent -
re-run it after a pull and it updates in place.

- **`environment.yml` cannot solve on Windows at all.** It is a full Linux
  solve: every package pinned to a `linux-64` build string, with `alsa-lib`,
  `pulseaudio-client` and `libgcc` in the list. `environment-windows.yml` names
  only what the code imports and lets conda choose builds, which is also why it
  needs no edit when conda-forge rolls a build number.
- **Activate; do not call the environment's `python.exe` directly.** GNU
  Radio's DLLs live in `envs\gnu\Library\bin`, which only activation puts on
  PATH. Without it the import dies with a bare `DLL load failed` that names
  nothing useful. `start_app.ps1` goes through the conda *shell hook*, so it
  works without `conda init` having been run.
- `start_app.ps1` also has to `Set-Location` to the repo root, for the same
  reason `start_app.sh` does its `cd`: the launcher opens `icons/settings.png`
  and `config/` by relative path.
- **Check whether WinUSB is already bound before sending anyone to Zadig.** The
  HackRF here needed no driver work at all - Windows had already attached its
  own WinUSB. `(Get-PnpDeviceProperty -InstanceId <id>)` showing
  `DEVPKEY_Device_Service = WINUSB` means the driver step is done; Soapy
  enumerating 0 devices is what says it is not.
- **Pillow is newer on Windows than on Linux** (12.3.0 against 11.1.0 here), so
  PIL calls can be silent in one place and warn in the other -
  `getdata()`/`putdata()` are deprecated in 12 and removed in 14. The launcher
  keys the settings icon's light background out with numpy instead, which is
  version-independent and produces a pixel-identical image.
- `vmcircbuf_prefs ... failed to open` on startup is cosmetic. The path it
  prints is malformed - `AppData\Roaming.config\gnuradio`, `%APPDATA%` and
  `.config` run together with no separator - so the preference never gets
  written and the line reprints every run. It does not affect the flowgraph.
- **A GUI started over SSH never reaches the desktop.** Windows OpenSSH runs
  children in session 0; the user's desktop is session 1. Flowgraphs still run
  headless there with `QT_QPA_PLATFORM=offscreen` (font warnings are expected
  and harmless), which is enough to transmit and be measured, but the window is
  invisible. `Get-Process python | Select Id,SessionId` is what tells you whose
  process is whose.
- `gr-audio` is present in the Windows build, so `rdsReceiver.py` can run there
  too, not just the transmitters.

**Verified cross-machine**, Windows HackRF transmitting and a BB60D on the
Linux box receiving: 102.1 MHz at 78 % read 66.3 dB above the noise floor and
decoded 1368/1368 blocks at 0.0 % errors, with PS, RadioText and PTY exactly as
configured. The transmitter was launched from the Windows GUI, not headless.

The one thing that cost time was, again, not the code: with no antenna on the
HackRF the whole chain came up clean - device opened, gains applied, no errors -
and put *nothing* on the air. The bare CW carrier at maximum gain read 2.6 dB
above the floor where the same test on the Linux bench reads 76.8 dB; with the
antenna connected the signal jumped to 66.3 dB and the capture rms rose 44 dB.
Validate the receiver against a known-strong station first - a wideband sweep
that finds 57 FM carriers proves the fault is on the transmit side before you
go looking for it there.

### Adding a New Application

1. Create `apps/<module_name>.py` implementing `ConfigDialog` and `main()`.
2. Add an icon to `icons/`.
3. Register with `self.create_app_button(...)` in `gnuradio_launcher.py`.

## Environment

- Conda environment name: `gnu` (defined in `environment.yml`, prefix: `/home/user/miniconda3/envs/gnu`)
- Python 3.12, GNU Radio 3.10.12, PyQt5 5.15, UHD 4.8
- The `start_app.sh` script activates `.venv` (a local conda env alias); ensure the conda env is set up before running.
