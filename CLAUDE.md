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
- `apply_dark_theme(widget)` — dark stylesheet for config dialogs, and it
  also straightens the layout — see [how every dialog gets laid
  out](#how-every-dialog-gets-laid-out).
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

Four radio backends are supported, selected via `radio_type` in settings.
Two of them go one way only, and **the launcher grid arranges itself around
whichever is chosen** — see [flip tiles](#the-launcher-grid-and-tiles-that-flip).
Pick the VSG60 and every tile turns to its transmitting side; pick the BB60D
and they all turn to receive, with the transmit-only tiles dimmed out. This
replaced a dialog that fired after the click, and before that an app that
opened and then reported "no HackRF found" — which sends people to check a
cable that is not the problem.

- **HackRF One** — USB SDR via SoapySDR (`soapy.sink('driver=hackrf', ...)`). No IP address needed; OK button always enabled. Gain set via `set_gain(0, 'VGA', value)` (0–47 dB) and `set_gain(0, 'AMP', 0)`.
- **Ettus USRP** — Network SDR via UHD (`gnuradio-uhd`). IP addresses configured in the settings gear dialog; OK button disabled when none are set. Gain set via `set_gain(value, 0)`.
- **Signal Hound VSG60** — USB vector signal generator (VID:PID `2817:0008`). Transmit only. No SoapySDR module and no stock GNU Radio block exists, so `apps/vsg_sink.py` wraps the vendor C API (`libvsg_api.so`) with ctypes as a `gr.sync_block`. No IP address needed; OK button always enabled. Level set via `set_level(dBm)` — a *calibrated absolute* output power, not a relative gain index.
- **Signal Hound BB60D** — USB spectrum analyser (VID:PID `2817:0007`). Receive only. It *is* a SoapySDR device, but not one `gr-soapy` can drive, so `apps/bb60_source.py` wraps the raw SoapySDR Python binding as a `gr.sync_block` — see [the BB60D section](#signal-hound-bb60d-as-a-receiver) for why, and for the three things about it that are not like the other radios.

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
- **A VSG60 and a BB60D will not stream at the same time on one host.** Start a
  capture while the VSG is transmitting and the BB60 library reports `GetIQ:
  Device packet framing issues` after exactly three buffers, every time, while
  the VSG reports a USB transfer failure. It is not bandwidth (it fails just as
  readily with the VSG at 2 MS/s as at 12.5), not power, not CPU (71% idle),
  not RF (identical at −113 dBm and at −55), and the kernel logs nothing at
  all — no xhci errors, no over-current, no bandwidth complaint. Separate root
  controllers and removing every hub from both paths changed nothing. Both
  radios are perfect alone. So any measurement that needs one of each has to
  put them on different machines, which is what TVAdemo is for.
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
| `ntscAnalogVideoRecorded.py` | NTSC analog video transmitter | ✅ |
| `atscXmitter.py` | ATSC digital TV transmitter | ✅ |
| `atscReceiver.py` | ATSC digital TV receiver - decodes the transport stream | ✅ |
| `rdsReceiver.py` | RDS/RBDS receiver - decodes FM station data | ✅ |
| `fmRdsTransmitter.py` | FM broadcast transmitter with RDS | ✅ |

### RDS Receiver

`rdsReceiver.py` tunes an FM broadcast station and decodes the data on its
57 kHz subcarrier: station ID (PI), program service name, RadioText, program
type and clock time.

- **It uses the radio chosen in Settings**, like every other app: the HackRF,
  a USRP picked from the configured addresses, or the BB60D. The VSG60
  transmits only, so with it selected the whole dialog is an error pointing
  at Settings, and closing it launches nothing.
- **Each radio brings its own sample rate**, because the BB60D's are a
  ladder with nothing at the 2 MS/s the HackRF path uses. `SAMPLE_RATES`
  gives it 2.5 MS/s, and the channel filter decimates by 10 rather than 8 —
  everything after it still runs at the same 250 kHz MPX rate, so nothing
  else in the chain changes. **Verified live on the BB60D**: 98.7 decoded
  as PI `0x16F2` confirmed WMZQ, program type Country, stereo pilot locked.
- **60% is the BB60D's best setting here, and both directions are worse** —
  measured on that station: 40% decodes nothing at all, 60% gives 80% of
  blocks good, 80% gives 68% and 100% gives 75%. That is the same shape as
  the ATSC finding (attenuator open, no RF amplification), and for the same
  reason: RF gain in a band as crowded as FM overloads the front end with
  everything *except* the station you want. 80% blocks good is usable but
  well short of the 96–99% a HackRF gets — the antenna on it is set up for
  UHF television, not the FM band.
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
- **RadioText is buffered per A/B flag, and a page is kept when its flag comes
  back.** The flag means "new message", but it is a single bit in block B, so a
  corrupted one would wipe a good message; `RdsProtocol` keeps a buffer for
  each flag value, and a bad bit writes into the page nobody is displaying. The
  receiver once also cleared a page whenever its flag returned. A station
  rotating two messages under A and B - the FM + RDS transmitter does, with
  typed text and the song - then made it start every page from nothing on
  every turn: simulated at 88% blocks good, a new song's Now Playing never
  arrived in two minutes, and off air at 78% it did not either. Now a page is
  cleared only when a believed segment contradicts its text; straight after a
  change of flag one differing character is enough, so paragraph page "3/5"
  still replaces "1/5" at once. In the same simulation the next song now
  arrives in 24-37 s at 88% and 48-99 s at 84%, never with a wrong title, and
  `scripts/test_rds_radiotext.py` requires it within a minute at 88%. **Verified
  off air** at 87-89% blocks good, the transmitter window on the VSG60 against
  the receiver window on the Windows HackRF, typed text rotating with the song:
  RadioText exactly right on screen 85% of the time (was 4%, wrong 81%), and
  after Next Track the new song's Now Playing arrived in 62 s (was never), with
  no wrong title. A kept page keeps only what was believed, though: when its
  flag comes back, characters no believed segment has confirmed are dropped
  (`drop_provisional`). Without that a wrong repair landing past the end of a
  short page was never overwritten - the transmitter stops each page at its
  carriage return, so nothing sends those positions again - and off air it left
  "#    @8" after the song line for 20 s. Simulated, dropping them cut wrong
  RadioText from 20.4% of the time to 12.9% at 84% blocks good and from 5.7%
  to 4.4% at 88%, at the price of showing gaps instead (3.1% to 15.0% at 84%):
  what is on screen is incomplete rather than wrong, and Now Playing arrives no
  later. Off air again at 89-92% the tail was gone: RadioText wrong 1.5% of the
  time, and that only the song line still up a turn late rather than anything
  garbled, with the next song's Now Playing 37 s after Next Track. A cleared
  page is written with the same group that cleared it - clearing without
  writing loses the first four characters of every page, which is exactly what
  paged paragraphs once exposed. RT+ tags slice the page being sent, which can
  be a group or two ahead of the page on display, and must find every tagged
  character believed on that same page: checked against the page on display
  instead, the simulation stored titles like "Stereo Separatimn Test 1) z"
  from repairs never confirmed.
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
  clean block replaces it or its page comes round again. It never overwrites a
  clean character - nor another provisional one, since a repair that came out
  right would otherwise be replaced by the next that came out wrong - never
  counts as a contradiction,
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
  reading kept the clock off the screen for five minutes. Two identical
  readings cannot confirm each other, though: a group the station repeats every
  few seconds - a RadioText segment - carries the same blocks C and D each
  time, so a block B corrected into a 4A the same way twice gives the same
  time, and a time that has not moved at all sat well inside the 90 s of slack.
  Off air at 87% blocks good that put "2206-10-30 14:21 (UTC+9)" on screen for
  97 s, and the same pair could have displaced a running real clock. The second
  witness must be at least a minute earlier, so a station repeating one
  minute's group is confirmed by its next minute instead. That costs nothing
  off air: the clock still appeared 155 s after tuning in, as it did before the
  rule, and was right at every minute after. Repaired groups are
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

### ATSC Transmitter

`atscXmitter.py` broadcasts an MPEG-2 transport stream as 8VSB on a 6 MHz
television channel, which a real TV can tune. The flowgraph is the stock GNU
Radio `file_atsc_tx` example block for block - same chain, same root-raised
cosine taps, same rotator - so the modulation was never the thing that needed
fixing. Three other things did:

- **It could not be launched at all.** The dialog read a `tsFileList.txt` from
  the working directory, a file that has never existed in this repo, so the
  combo box always fell into its except branch, OK stayed disabled at 30%
  opacity, and no amount of configuring got past the dialog. It scans the
  media directory for `.ts` now, like every other app scans for `.wav`.
- **It could not run on a HackRF.** `samp_rate` was 12.5e6, and SoapyHackRF
  accepts only whole megahertz from 1 to 20 - it raises in the constructor,
  naming every rate it will take. So the app died before transmitting a
  sample on the one radio most likely to be attached. The second resampler is
  8/19 rather than 25/57 now, which lands on exactly 12.000000 MS/s from the
  same 28.5 MS/s intermediate stage and still carries the 6 MHz channel.
- **It clipped.** 8VSB is noise-like: measured 8.7 dB peak-to-average, and the
  chain came out at 1.007 peak against radios that take 1.0 as I/Q full scale,
  so the loudest samples were flattened before the signal left the box - worse
  the longer it ran, as the Gaussian tail reaches further. `BASEBAND_SCALE` is
  0.85 now, leaving 10 dB of headroom; the analog stage sets actual power.

- **It could not be tuned to most frequencies.** The dialog's centre
  frequency was a bare `QSlider` running 50 to 2200 in *whole megahertz*:
  2151 positions rendered a few hundred pixels wide, which is about seven
  megahertz per pixel of mouse travel. Asked for 533 MHz - the channel this
  bench uses - the nearest it would go was 539, and nothing on screen said
  why. Both ATSC apps now share `FrequencyChooser` from `apps/utils.py`:
  type the number, pick the television channel, or drag a slider that moves
  in tenths of a megahertz and whose page step is exactly one 6 MHz channel,
  all three staying in step with each other. The running flowgraph window
  was never affected - its `RangeWidget` is a counter with a 0.1 step, so it
  always took a typed value.

The transport stream must be **constant bit rate at exactly 19.392658 Mbps**,
since the flowgraph consumes it at a rate fixed by the symbol clock - mux it
any slower or faster and the picture plays at the wrong speed. ffmpeg builds
one with `-muxrate 19392658 -f mpegts`, MPEG-2 video and AC-3 audio.

```sh
python scripts/test_atsc_loopback.py <stream.ts> 2      # no radio
python scripts/test_atsc_loopback.py <stream.ts> 2 15   # ... at 15 dB SNR
```

runs the transmit chain into GNU Radio's own ATSC receiver (`dtv.atsc_rx`)
with no radio: locks in 0.42 s, then 99.7% of packets come back byte-perfect,
holding above 98.5% down to about 15 dB SNR and collapsing below 14 - which is
where A/53 puts the cliff, and matching it is the best evidence the chain is
honest.

**Verified off air**, the VSG60 transmitting from the TVAdemo laptop into the
BB60D here on RF channel 24 (533 MHz) at -9.5 dBm: **79,285 video packets
recovered with 209 flagged bad, 99.74% clean**, which is what the same stream
scores decoded purely in software. ffmpeg read it back as 704x480 MPEG-2 at
29.97 fps with AC-3 audio - exactly what went in - and rendered the test
pattern with its frame counter legible.

Four things cost real time getting there, none of them in the app:

- **A weak capture fails identically to a broken decoder.** `dtv.atsc_rx`
  contains an `agc_ff` creeping at 1e-5 per sample toward a reference of 4.0.
  A BB60D capture of a real station arrives around 0.0002 rms, so the loop
  needs a gain of ~20000 and half a minute of samples to reach it; on a
  five-second capture it never converged and decoded pure noise. Scale the
  capture to about unity rms first and it decodes immediately.
- **Measure that scale in the middle of the capture, not at the start.** A
  HackRF opens at whatever gain it had before the requested one is applied, so
  the first half second can sit 24 dB above the rest.
- **A free-running transmitter needs AFC, and twice over.** A HackRF put the
  pilot 7063 Hz from where A/53 places it - 13.3 ppm at 533 MHz, ordinary for
  that radio - which is far outside `atsc_fpll`'s pull-in, so the decode came
  back as noise while the spectrum looked perfect. Correcting the carrier
  alone changed nothing: the same 13.3 ppm scales the **symbol clock**, and
  correcting that took the decode from nothing to 81% of packets. The VSG60,
  being an instrument, needs neither correction, which is exactly why a
  capture of a real station decoded first time and ours did not.
- **The couple of hundred hertz everything reads is the BB60D's, not the
  transmitter's.** The VSG60 measured 158 and later 205 Hz off through this
  receiver, which looked like the VSG's own error until a *live broadcaster*
  on RF 36 read +194 Hz through the same path. Two unrelated transmitters
  cannot agree to within 11 Hz by accident: about 0.4 ppm of it is the
  BB60D's own reference. It makes no difference to decoding - at baseband
  the AFC cannot tell the two apart and corrects the sum, which is all that
  matters - but do not quote 200 Hz as a transmitter's accuracy.
- **A spectrum average hides a transmitter that is off half the time.** Asked
  to modulate 8VSB at 12 MS/s, the Windows laptop's HackRF was silent 45% of
  the time in gaps up to 10.9 ms, while its spectrum looked flat across the
  channel with clean shoulders - better than the real broadcaster's. Only the
  time-domain envelope showed it. Rendering the baseband on a fast machine and
  letting the slow one play the file back cured it completely (0.000% of time
  below threshold).

### ATSC Receiver

`atscReceiver.py` is the other end of `atscXmitter.py`, and shares its tile
in the launcher - the badge in the corner turns one into the other. It tunes
a 6 MHz television channel, demodulates 8VSB, recovers the MPEG-2 transport
stream and says what it found. It does not decode video itself: **Watch**
hands the recovered stream to `ffplay` (or `mpv`, or `vlc`) and **Record**
writes it into the media folder, where `atscXmitter` can pick it up and
transmit it again.

```sh
python scripts/test_atsc_receiver.py <stream.ts>            # no radio
python scripts/test_atsc_receiver.py <stream.ts> --ppm 20   # a worse crystal
```

The arithmetic lives in `apps/atsc_rx_core.py`, free of GNU Radio and Qt
like the RDS and NTSC pairs, so the pilot measurement, the AFC, MER and the
transport-stream parsing can all be checked with no radio at all.

**Verified off air**, the VSG60 transmitting from TVAdemo into the BB60D
here on RF channel 24 (533 MHz) at −9.5 dBm, decoded live and in real time:
**0.00% bad packets sustained over 25 seconds**, 12,900 packets/s (which is
19.392658 Mbps exactly), pilot 205 Hz off — most of which is the receiver's
own reference, not the VSG's — MER 22.0–22.6 dB, no BB60D overflows. The program was read out of its own PAT and PMT as MPEG-2
video on PID 0x0100 with AC-3 audio on 0x0101, the recording came back
through ffprobe as 704×480 at 29.97 fps, and a frame piped to a player
showed the test pattern with its timecode and frame counter legible.

Five things worth knowing before changing it:

- **The chain is built out of `gr-dtv`'s blocks rather than by calling
  `dtv.atsc_rx`.** Same blocks, same order - but the hierarchical block
  makes them locals and throws away the two things a receiver app needs.
  One is the resampler, which is half of the AFC. The other is the
  telemetry: `atsc_rs_decoder` counts packets, unrecoverable packets and
  bytes corrected, which is what separates a weak signal from a mistuned
  one, and the equalizer's soft symbols give MER.
- **AFC is two corrections from one measurement, and half of it is worth
  nothing.** One crystal drives a transmitter's baseband clock and its
  local oscillator, so an error of a few parts per million moves the
  carrier *and* stretches the symbol rate. Measured at baseband the pilot
  shifts by `d*(f_rf + PILOT_OFFSET)` - the carrier carries it up, and the
  stretched baseband carries it back down by `d` times its own 2.69 MHz -
  which is the frequency `afc_correction` takes the ppm figure against.
  `test_atsc_receiver.py` injects 13.3 ppm, the figure a HackRF measured on
  this bench, and pins the result down: uncorrected **99.90% bad and never
  locks**, carrier corrected alone **99.91% bad and never locks**, both
  together **0.00% bad, locked in 0.65 s** - identical to a link that never
  broke. The VSG60, being an instrument, needs neither correction.
- **MER reads optimistically and must never be quoted against the cliff.**
  Slicing each symbol to its nearest 8VSB level is the same thing as
  assuming every symbol was decided correctly, so once noise pushes symbols
  past the halfway point the error to the *wrong* level gets measured
  instead. Against known noise it is right to 0.1 dB down to 22 dB, then
  reads 19.0 for a true 18, 17.7 for a true 15, 16.6 for a true 12 - it
  bottoms out near 16, which is *below* A/53's 15.2 dB threshold of
  visibility. So it cannot see the cliff at all. Read it as how open the
  eye is; read the bad-packet rate for whether the picture is intact. The
  app deliberately says no more than "Breaking up - N% of packets lost".
- **`sps` is the one knob that sets how much work the receiver does.** The
  arbitrary resampler carrying the radio's rate to the symbol clock *is*
  the bottleneck - measured, everything from the equalizer onward is free
  beside it - and it costs `(2*8+1)*sps` taps per output sample. At 12 MS/s
  on the 8-core bench: 1.5 runs at 1.16× real time for 24.0 dB MER, 1.2 at
  1.42× for 23.5 dB, 1.1 at 1.57× for 21.4 dB. It is 1.2. In steady state
  all of them decode a clean signal at 0.000% bad; the differences in the
  *totals* are acquisition time, not quality, which is why the test finds
  where the receiver locked and reports only what came after.
- **It printed four buffer warnings on every run, and they are fixable.**
  GNU Radio rounds every stream buffer up to a 4096-byte page and logs a
  WARN when the size it was asked for was not already there. A transport
  packet is 188 bytes and a Reed-Solomon one is 207, neither a power of
  two, so `atsc_viterbi_decoder`, `atsc_deinterleaver`, `atsc_rs_decoder`
  and `atsc_derandomizer` tripped it every time - four lines about
  something that is not a fault and that nobody can act on. Asking for the
  aligned count up front (`align_output_buffer` in `apps/utils.py`; 4096
  items for 207 bytes, 1024 for 188) silences them while allocating exactly
  what it was going to allocate anyway, and the decode is unchanged. The
  *transmitter* never had this - its items are 256 and 1024 bytes. The four
  that still appear from `scripts/test_atsc_loopback.py` come from
  `dtv.atsc_rx` inside it, whose blocks are locals and cannot be reached;
  that is deliberate, since the point of that test is to check our
  transmitter against GNU Radio's own receiver rather than our own.
- **Watch pipes to the player and drops bytes rather than blocking.** A
  blocking write into a player that has stalled or been closed would park
  the GNU Radio scheduler thread and take the whole receiver down, and
  there is no way to apply backpressure to the air. So the pipe is
  non-blocking, the backlog is capped, and what is discarded is discarded
  in whole 188-byte packets so the player resyncs on the next sync byte
  instead of hunting.

### NTSC composite video

`apps/ntsc_encode.py` builds a 525-line, 2:1 interlaced composite signal to
SMPTE 170M-2004 - sync, blanking, equalizing pulses, serrations, colour burst
and a quadrature-modulated chroma subcarrier - and `apps/ntsc_decode.py`
takes it apart again. Both are free of GNU Radio and Qt, like the RDS pair, so
they can be checked with no radio at all:

```sh
python scripts/test_ntsc_loopback.py       # encoder -> decoder, no radio
python scripts/test_ntsc_transmit.py       # ... and through the modulator
python scripts/test_ntsc_transmit.py --video clip.mp4
```

All seven colour bars return with a worst error under 0.01, and a full-scale
grey ramp within 0.008. `docs/S170m-2004.pdf` holds the timing tables (2 and
3), the levels (table 1) and the encoding equations (annex A).

- **Every sample of a frame is computed at once.** The encoder used to walk
  the 525 lines in a Python loop, picking each line's samples out with
  `line_in_frame == L` - a comparison across the whole frame, 525 times over,
  making the work O(samples x lines). At 10 MS/s that ran at **0.14x real
  time**, so it could never have fed a radio live however fast the machine.
  Whole-frame array operations, computing sin/cos only where the subcarrier
  is actually used, and restricting the vertical-interval arithmetic to the
  eighteen lines it applies to took it to **1.66x** in colour and 2.89x in
  monochrome - twelve times quicker, and bit-for-bit identical output at
  every sample rate tried.
- **Saturated colour has to be legalised or it reaches down to sync level.**
  Chroma adds to luma, so 100% saturated bars swing from 131 IRE down past
  -20, and a receiver then cannot tell picture from sync at all: the decode
  comes back sheared into diagonal noise. Broadcasters run a legalizer for
  exactly this; `NtscEncoder(legalize=True)` is one, clamping active video
  to -20..+120 IRE. It is a no-op on 75% bars, which is why 75% is the
  standard test signal. Real 1950s material peaks around 0.94-1.01 against
  the 1.143 ceiling and never touches it.

### NTSC video sources

`apps/ntsc_source.py` turns a *stream* of frames into a continuous signal,
and settles what video format this project takes: **whatever ffmpeg reads**.
There is no bespoke format. A video file is decoded by an ffmpeg subprocess,
scaled to 640x480 and letterboxed if it is not 4:3, looping forever; there
is also a built-in colour-bar pattern so the app works with an empty media
folder.

- **Frames are encoded on their own thread.** Encoding a frame takes ~20 ms
  and a work() call at 10 MS/s covers well under a millisecond, so encoding
  inside work() would stall the radio for 20 ms in every 33 and underrun it.
  A three-deep queue between the two keeps the output continuous and paces
  the encoder for free - it fills, the producer blocks, and frames are
  pulled at exactly the rate the radio consumes them.
- **The `.dat` captures do not go through it.** They are already composite,
  at 18 MS/s, so they are played by a file source and resampled 5/9 - see
  `dat_resample_ratio`.
- **One clip, one entry in the picker.** The media folder holds each clip
  twice - a `.mp4` for here and a `.ts` of the same picture and sound for
  the ATSC transmitter, which needs a transport stream - so offering every
  readable file made the video list forty items long with every title in it
  twice, spelled identically, and nothing on screen saying which was which.
  `video_files()` collapses files that share a name to one, keeping the
  extension earliest in `VIDEO_EXTENSIONS`: the `.mp4` is 640x480 with
  square pixels, which is exactly what the encoder wants, where the `.ts`
  is 704x480 at 10:11 and would have to be stretched back. The three kinds
  of source - the built-in pattern, the clips, the `.dat` stills - are
  separated in the list, because a clip plays and loops where a `.dat` is
  one frame held on screen. `dat_files()` also drops the
  `-946x486-18M0FS` from those names: it is the same for every one of them,
  so it says nothing and hides the subject.
- **The clips themselves are public domain or CC BY**, and
  `media/VIDEO-CREDITS.txt` is the record of what each one is, where it came
  from, which segment was taken and how it was encoded. The Blender films
  are CC BY, whose terms *require* that credit wherever the clip is shown or
  passed on. Fourteen clips: seven Prelinger advertising reels (four of them
  black and white), three NASA (Apollo 11 launch and moonwalk, ISS Earth
  views), four Blender open movies. All fourteen `.mp4` are exactly 640x480
  square-pixel 29.97 progressive, so nothing is rescaled on the way in.

- **Generate every sample from absolute time, never from a count per line.** A
  line is 63.5556 us, which is 635.56 samples at 10 MS/s and not a whole
  number at any rate worth transmitting at. Rounding per line accumulates
  until the picture shears, so each sample works out which line it belongs to
  from `n / sample_rate`. Nothing drifts and any sample rate works.
- **Take the subcarrier phase from that same absolute time.** There are
  exactly 227.5 subcarrier cycles per line (clause 11.2), so the burst phase
  inverts line to line and the four-field colour sequence repeats by itself.
  Tracking it per line is bookkeeping that can only go wrong.
- **Decode colour against the burst, never against a local oscillator.** The
  burst is nine cycles at a known phase sent on every line for exactly this
  purpose: it says where the subcarrier's zero crossing falls *on this line*.
  Decoding against a locally generated subcarrier gets the hue wrong by
  however much the sampling origin happened to differ.
- **Find sync by pulse width, not by level.** Equalizing pulses (2.3 us),
  horizontal sync (4.7 us) and the vertical serrations all sit at exactly the
  same level, so a threshold crossing says nothing about which is which. How
  long the signal stays down is what separates a field from a line.

The encoder's output has the same geometry as the instructor's captures: at
18 MS/s a frame is 600600 samples of 1144, which is exactly what the
`*-946x486-18M0FS.dat` files in the media folder contain (one still frame
each, sync tip 0.034, white 0.877). Those are the only known-good composite
video in the repo and are worth keeping as a reference.

### The launcher grid, and tiles that flip

Every tile is declared in `APP_TILES` at the top of `gnuradio_launcher.py`
as `(row, column, [face, ...])`, where a face is
`(label, module, icon, direction)` and direction is `'tx'` or `'rx'`.
A tile with more than one face is a **flip tile**: a badge in its corner
turns it over, and the icon and the caption both change with it. That is
how the two ends of one standard share a square - the ATSC transmitter and
receiver, the FM + RDS transmitter and the RDS receiver - instead of
sitting apart as though they were unrelated apps. NTSC and AM video are
single-faced for now and gain a second face when they have receivers.

**The grid follows the radio.** `RADIO_DIRECTIONS` says which way each of
the four can go, and `apply_radio_directions()` runs on startup and again
every time Settings closes:

| Radio | What the grid does |
|-------|--------------------|
| HackRF One, Ettus USRP | both directions - the two pairs stay flippable |
| Signal Hound VSG60 | every tile turns to transmit; badges disappear |
| Signal Hound BB60D | every tile turns to receive; the ten transmit-only tiles dim out |

- **A dimmed tile says why.** Its tooltip names the direction it needs and
  the radio that cannot do it ("AM Sine Generator needs a radio that can
  transmit. The Signal Hound BB60D cannot."). A greyed square that explains
  itself beats an app that opens and then fails on a device it was never
  going to be able to use. `launch_application` still checks, as a
  backstop, but reads the direction off `APP_TILES` rather than keeping a
  second list in step with it.
- **A turn the radio forces is not remembered.** `tile_faces` records what
  the *user* chose with the badge; capability turns pass `remember=False`.
  So flip ATSC to receive on a HackRF, switch to the VSG and watch it turn
  to transmit, switch back - and it returns to receive. Saving the forced
  turn instead would quietly destroy the preference every time the radio
  changed.
- **Dimming is painted, not an effect.** The caption already carries a
  `QGraphicsOpacityEffect` for the fade, and effects do not nest
  predictably, so `_draw` sets the painter's opacity instead.

- **The turn is drawn, not faked with a swap.** `FlipTile` animates a
  `flip_phase` property from 0 to 1 and squeezes the icon horizontally by
  `cos` of it, through zero width and back out, changing face at the moment
  it is edge on - which is exactly when none of it is visible. The caption
  fades on the same curve rather than being squeezed, because squeezed text
  reads as a rendering fault.
- **The property is `flip_phase`, not `flip`.** `flip()` is the method that
  starts a turn; naming the `pyqtProperty` the same thing replaces the
  method with the property object and the badge stops working.
- **The icon box is sized for every face, not the first.** Two icons with
  different aspect ratios otherwise clip the second one - and a box that
  resized mid-turn would shove the caption around while the tile moved.
- **Which side is up lives in `window_settings.json`** under `tile_faces`,
  keyed by the tile's first module name, so a tile left showing the
  receiver is still showing it next time.
- **The single-face path is the same code.** `create_app_button` is kept as
  a one-face call into `create_tile`, so nothing else had to change.

### NTSC Transmitter

`ntscAnalogVideoRecorded.py` puts composite video on a 6 MHz television
channel as System M: vestigial-sideband AM for the picture, an FM aural
carrier 4.5 MHz above the visual one. `cf` is the channel *centre*, as in
the ATSC apps, which puts the visual carrier 1.25 MHz above the lower edge.

**The RF architecture was already right and needed nothing.** Four other
things were wrong, and each of them alone stopped it working:

- **It could only send single still frames.** The dialog offered `.dat`
  files and nothing else, and those are one frame each. It takes any video
  file ffmpeg reads now, via `apps/ntsc_source.py`.
- **It played 18 MS/s captures at 10.** The `*-18M0FS.dat` files are
  composite sampled at 18 MS/s. Played out untouched at the flowgraph's
  10 MS/s, every timing in them is wrong by 1.8: a line lasts 114.4 us
  instead of 63.5556, which is a line rate of **8741 Hz where NTSC needs
  15734.266**. No television could have locked to what this transmitted.
  They are resampled 5/9 now.
- **The polarity defaulted to the wrong one.** US television is negative
  modulation - sync at peak carrier. The flowgraph's two options were
  labelled "Normal" and "Inverted", which says nothing about which a TV
  here can show, and the dialog's unticked default selected *positive*. It
  also drove the carrier to **1.79** against a radio that clips at 1.0.
  The options now say "Negative (US)" and "Positive", and negative is the
  default.
- **The modulation depth was approximate.** It was `1 - 0.9*v` with nothing
  bounding it. `NtscModulator` maps composite onto the carrier properly:
  sync 100%, blanking 75%, peak white 12.5%, per FCC 73.682 - and landing
  blanking on exactly 75% by itself is the check that the composite scale
  and the RF scale agree. A rail stops the most saturated colour switching
  the carrier off. The aural carrier came down from 0.8 to 0.316, which is
  the 10% of peak visual *power* the FCC asks for; it had been 8 dB too
  loud, stealing headroom from the picture.

Two things worth knowing before changing it:

- **The two-stage video mixer is not a redundant one.** Video is mixed to
  -1.725 MHz, filtered, then moved the last -25 kHz. The filter does its
  work in the first frame: a low pass at 2.475 MHz there passes 0.75 MHz
  below the carrier and 4.2 MHz above, which is exactly the vestigial
  sideband and the full video bandwidth. Mixing straight to -1.75 would put
  both edges 25 kHz wrong.
- **Ringing on sync is worse in negative modulation, and that is normal.**
  The sync pulse is the peak of the carrier there - the fastest, largest
  excursion in the signal - so the vestigial filter overshoots about 20% on
  it. What matters is the level reaching the radio, which after scaling the
  sum of vision and sound is 0.77 of full scale.

`scripts/test_ntsc_transmit.py` puts a picture through the modulator and
detects it the way a television does. **Include the Nyquist slope when you
do that**: a receiver's IF is at half response on the visual carrier, rising
to full 0.75 MHz above and falling to nothing 0.75 MHz below. Below that,
both sidebands survive and add; above it only one does. Rectifying without
the slope gives luma at twice chroma's strength - whites too bright, colours
washed toward grey - which reads as a broken modulator and is not one. It
took the measured colour error from 0.43 to 0.13.

**Verified with real material**: 1950s Prelinger advertising and the Blender
open movies through the whole chain and back, 0.078-0.088 mean error, the
black-and-white spots clean and the colour ones looking convincingly like
period colour television.

### How every dialog gets laid out

Each of the fifteen `ConfigDialog`s is assembled by hand out of
`QVBoxLayout` and `QHBoxLayout`, and they were all crooked in the same
ways - which is why `apply_dark_theme` now ends by calling `tidy_dialog`
rather than fifteen dialogs each being fixed on their own. Four faults, all
of them visible in a screenshot, all measured across all fifteen:

- **The label in a row sat four or five pixels below the control beside
  it.** The stylesheet gave every `QLabel` a `margin-top: 10px`, to space a
  caption off whatever was above it. Inside a row that margin pushes the
  *text* down within the label's own rectangle while the spin box or slider
  beside it stays centred, so the box reads as sitting high - which is
  exactly how it was reported ("the 177 box is higher than the text next to
  it"). The margin is gone; vertical space comes from layout spacing, which
  is what layout spacing is for, and a caption gets its extra room above
  through `setContentsMargins` on the caption alone.
- **The controls started at a different x in every row**, because each one
  began wherever its label's text happened to end - four different
  positions in one dialog. Every label that leads a row is given the width
  of the widest of them. It has to be `QSizePolicy.Fixed` as well as a
  minimum width: a label is `Preferred` by default, so in a row with a spin
  box - which is `Expanding` - the two share the slack and that row's
  control still starts 26 px right of every other.
- **A nested row was indented.** Sub-layouts and the plain `QWidget`
  containers that exist only to carry a `QGraphicsOpacityEffect` keep their
  own default 9 px margins, so "Sine Frequency" sat ten pixels right of
  every other label in the same dialog.
- **Short dialogs spread their contents out.** A forced 400 px minimum
  height left the receiver dialogs half empty, and a `QVBoxLayout` hands
  the slack to whatever can grow - which is the labels, so the gaps came
  out uneven. There is no minimum height now, and a stretch before the
  button box collects any slack in one place.

Two things about doing it centrally:

- **A group box is entered for its nested layouts but not for its rows.**
  Its contents are indented from the dialog's column by the frame, so
  pulling its rows into that column would push them back out of the box.
  The RDS box in the FM + RDS transmitter is the one that has both.
- **Anything a stylesheet touches stops drawing its own sub-controls.**
  Styling `QAbstractSpinBox` so it matches the combo boxes - and without
  that it falls through to the plain `QWidget` rule and comes out as a flat
  dark box - leaves the up and down buttons as empty rectangles. Qt's CSS
  subset will not draw a triangle out of borders either; it renders the
  four borders as a rectangle. So the arrows are images, `icons/spin-up.png`
  and `icons/spin-down.png`, referenced through `icon_url()` by absolute
  path: a stylesheet resolves `url()` against the process's working
  directory, and forward slashes are required on Windows because a
  backslash is an escape to the stylesheet parser.

```sh
python scripts/test_dialog_layout.py                  # all 15, all 4 radios
python scripts/test_dialog_layout.py --radio vsg
python scripts/test_dialog_layout.py --save /tmp/shots
```

opens every dialog on Qt's offscreen platform - no radio, no display - and
measures the four things above, plus that no combo box lists the same entry
twice and that nothing is bigger than the 1366x768 laptop. Sixty dialogs in
about twenty seconds. It patches `read_settings` rather than the settings
file, because a test must never write into the user's own configuration.

### Testing the launcher end to end

The `scripts/test_*.py` above all bypass the GUI. `scripts/test_launcher_gui.py`
covers what they cannot - that `./start_app.sh` starts, that a button press
reaches `launch_application`, that the dialog accepts, that the flowgraph
window appears, and that closing it brings the launcher back - by driving real
X input through xdotool (`apt install xdotool`):

```sh
python scripts/test_launcher_gui.py "RDS Receiver"
python scripts/test_launcher_gui.py "FM + RDS Transmitter" --hold 30
python scripts/test_launcher_gui.py "ATSC Video Receiver"
```

- **Close any running launcher first.** A launcher process keeps a USB handle
  on the HackRF - `/proc/<pid>/fd` shows `/dev/bus/usb/...` - even while it is
  only *sitting on a config dialog*. `SoapySDR.Device.enumerate` then returns
  zero devices and the app under test fails with `Device::make() no match`,
  which surfaces as a modal error box that nothing dismisses, so an automated
  run just hangs. The script refuses to start if it finds one.
- **Button coordinates are found, not computed.** High-DPI scaling moves the
  grid, so `button_grid()` locates the icons as bright blobs in a screenshot
  and `registered_apps()` reads the launcher's own `APP_TILES` table. A
  button that moves takes the click with it.
- **That table is parsed with `ast`, not a regex and not an import.** A flip
  tile's faces are a nested list, which is the shape a regex reads wrongly;
  and importing the launcher opens a window, when the whole point is to
  drive the one `start_app.sh` starts. `RADIO_DIRECTIONS` comes out the
  same way, so the test knows which apps the selected radio can run and
  says so up front rather than failing later like a broken button.
- **A blob's position in its row is not its grid column.** Row 2 ends at
  column 3 now that the RDS receiver has moved onto the transmitter's tile,
  and screenshot blobs come back packed left to right knowing nothing about
  gaps. `registered_apps()` works out each tile's position among the tiles
  its row actually has.
- **An app on the back of a flip tile is reached through the saved
  setting**, not by clicking the badge: `tile_showing()` writes the same
  `tile_faces` entry the badge writes, so the launcher comes up already
  showing the app under test, and puts it back afterwards. Clicking the
  badge would test the animation rather than the app, and would mean
  finding a 32-pixel circle in a screenshot. Only that one key is restored,
  because the launcher saves its window position into the same file while
  the test runs.
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
rates are also a ladder - 40/20/10/5/2.5 MSps and on down in halves - with
nothing near the 2 MS/s the HackRF path uses, so 2.5 MSps (decimate by 10) is
the one to use there. At 10 MSps the analog filter is 8 MHz, which is what
makes it usable for a 6 MHz television channel.

`apps/bb60_source.py` drives it live, wrapping the **raw** SoapySDR Python
binding as a `gr.sync_block` in the spirit of `apps/vsg_sink.py`. Measured
streaming 10 MS/s into the ATSC receiver in real time with zero overflows.
Four things about this device that are not like the others:

- **`setupStream` comes before configuration, not after.** Set the rate or
  the frequency on a device whose stream has not been set up and the module
  reports the format as empty and nothing works afterwards.
  `/data/python/bluey-ox-walker/bin/record_iq.py` on the **system** Python
  has always done it in this order.
- **It is opened by driver name alone**, `driver=SignalHoundBB60`. The very
  arguments `enumerate()` hands back are refused: driver plus serial with
  `Device::make() no match`, and the whole dict with `device_id is not a
  number`.
- **The conda binding loads the system module quite happily** once
  `SOAPY_SDR_PLUGIN_PATH` points at it - both are ABI 0.8.
  `ensure_plugin_path()` finds and sets it.
- **`enumerate()` returns `SoapySDRKwargs`, which has no `.get`** - a SWIG
  map proxy, not a dict. Reading it like one raises `AttributeError`, and
  behind a broad `except` that looks *exactly* like no device being plugged
  in. That cost an afternoon; `find_devices()` now converts first and
  prints anything that goes wrong.

Gain is two elements, `ATT` (−30…0 dB) and `RF` (0…20 dB), presented as one
0–100 % slider: the attenuator comes out first, because attenuation costs
noise figure outright, and only then does RF gain go in. So 0 % is −30 dB,
60 % is 0 dB and 100 % is +20 dB.

**The input level falls as the slider rises, and that is correct.** Measured
against a live broadcaster on RF 36 with an empty channel for reference,
because raw level says the opposite of the truth:

| ATT | RF | level | SNR |
|-----|----|-------|-----|
| −30 | 0 | −56.5 dBFS | **−0.1 dB** |
| −20 | 0 | −61.4 dBFS | 0.0 dB |
| −10 | 0 | −69.9 dBFS | 1.2 dB |
| 0 | 0 | −74.0 dBFS | 4.7 dB |
| 0 | 20 | −74.5 dBFS | **6.6 dB** |

Winding the attenuator stage negative adds 18 dB of level and *all* of it is
noise. So `gain_plan` opens the attenuator toward 0 first and only then adds
RF, which makes the slider monotone in signal-to-noise even though the level
meter goes the other way. **An earlier note here claimed the opposite** — 
that 20 dB of RF gain "got the signal clear of the converter" and turned
0 dB SNR into 10 dB. That was reading level instead of SNR, and it was
wrong; the table above is the measurement.

**The last 20 dB of RF is what overdrives the converter.** It is worth under
2 dB of SNR and it is front-end amplification, so on a strong local signal
it overflows the ADC — which is what an 85 % default did the first time the
receiver was run against the bench transmitter. The default is 60 % (the
attenuator open, no RF), within 2 dB of the best this device can do.

**An overdriven converter is invisible in the samples.** They arrive
filtered and decimated, so nothing clips; the only sign is the driver
logging `GetIQ: ADC overflow`. `bb60_source` therefore installs a SoapySDR
log handler that counts those, and the receiver shows "Input overloaded —
turn the RF gain down" instead of it scrolling past in a terminal. The same
handler drops the module's `ConfigureIQCenter` / `ConfigureIO` / `Using
format` chatter, which is logged at ERROR, is harmless, and otherwise
prints several lines per retune.

Recording with raw SoapySDR and decoding offline still works too, and is
still the right thing for anything that does not need to be live -
`record_iq.py --driver SignalHoundBB60` writes complex float32, which
`scripts/test_rds_core.py` reads directly given a JSON sidecar.

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

### The TVAdemo laptop, and why there is a second machine

Anything that needs a transmitter and a receiver at once needs two machines,
because the VSG60 and the BB60D cannot stream together on one (see the VSG60
notes). TVAdemo is the transmitter:

```sh
ssh -i ~/.ssh/id_worklaptop2 user@192.168.50.48        # hostname TVAdemo
```

Ubuntu 24.04, i9-11980HK, 62 GB, 3.4 TB free, GNU Radio 3.10.12.0 with gr-dtv
in a conda env called `gnu`, repo at `/data/python/SDR`. There is **no git**
on it, as on the Windows laptop, so it is kept in step by copying files. It is
on WiFi (the wired port is down), which still moves about 8 MB/s - the fourteen
video clips are 322 MB and took 47 seconds.

- **Its media folder is `/home/user/Documents`, not `/data/python/media`**,
  which does not exist on that machine. `config/window_settings.json` is
  per-machine and is not copied across, so the two differ; copy media there,
  not to the path this box uses. Anything CC BY goes with its credits -
  `VIDEO-CREDITS.txt` belongs in the same folder, because the licence
  requires the credit wherever the clip is passed on.
- **ffmpeg is there, inside the conda env** (7.1.1, from conda-forge) rather
  than in `/usr/bin`, so `which ffmpeg` from a bare SSH shell finds nothing
  and it looks absent. `have_ffmpeg()` runs inside the env and sees it, so
  the video picker works on that machine like any other. Do not conclude
  from a plain `which` that a tool is missing on a conda machine.
- **The VSG library is vendored, not installed.** `vendor/libvsg_api.so.1`
  sits in the repo and `VSG_API_LIB=/data/python/SDR/vendor` points
  `vsg_sink` at it, so nothing needs Sceptre. The udev rule is already in
  place and the device node comes up mode 0666.
- **Prefer it for transmitting anything that must be timed accurately.** Its
  VSG puts the ATSC pilot within 200 Hz of where the standard says, and most
  of even that is the BB60D measuring it (see the ATSC transmitter notes);
  a HackRF managed 7063 Hz, and that one number was the difference between
  nothing decoding and 99.7% of packets decoding.

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
3. Add a row to `APP_TILES` in `gnuradio_launcher.py`, saying whether the
   app transmits or receives. To give an existing app a second side instead
   of a square of its own - a receiver for a transmitter, say - add a face
   to that tile's list rather than a row. The direction is all the grid
   needs to dim it, flip it and refuse it on the wrong radio.

## Environment

- Conda environment name: `gnu` (defined in `environment.yml`, prefix: `/home/user/miniconda3/envs/gnu`)
- Python 3.12, GNU Radio 3.10.12, PyQt5 5.15, UHD 4.8
- The `start_app.sh` script activates `.venv` (a local conda env alias); ensure the conda env is set up before running.
