# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Application

```sh
# Using the launch script (activates the 'gnu' conda environment):
./linux/start_app.sh

# Or directly (requires the 'gnu' conda environment to be active):
conda activate gnu
python RFbenchToolkit.py
```

The app requires a display (X11/Wayland) and either a HackRF One (USB) or Ettus USRP (network) connected. Radio type is selected in the Settings dialog.

On Windows it is `windows/start_app.ps1` instead, and the environment comes
from `windows/environment.yml` rather than `linux/environment.yml` - see
[Running on Windows](#running-on-windows) and [where things
live](#where-things-live-linux-and-windows).

There is also a browser front end onto the same grid and the same settings,
which starts the same apps as separate processes - see
[Web launcher](#web-launcher-a-second-front-end):

```sh
conda activate gnu
python web/server.py                 # http://127.0.0.1:8730
```

## Where things live: linux/ and windows/

Every line of Python runs on both operating systems, so the code is not
split by OS at all: `RFbenchToolkit.py`, `apps/`, `web/`, `icons/`,
`fonts/` and `scripts/` are shared, and a difference between the two is a
branch at run time in the one place it matters (`vsg_sink.py`'s library
search, say), never a second copy of a file. Only the edges differ - how
the launcher is started, what conda installs, and one-time setup - and
those, and nothing else, go in a folder named for the OS:

| | `linux/` | `windows/` |
|---|---|---|
| Start the launcher | `start_app.sh` | `start_app.ps1` |
| Conda environment | `environment.yml`, a full pinned solve | `environment.yml`, only what the code imports |
| One-time setup | `setup_vsg.sh`, the VSG60 library and udev rule | `bootstrap.ps1`, conda and the environment |

The same name in both folders is the same job, which is the point of the
arrangement: a change to one should make you look at the other. Both
start scripts step up to the repo root before running anything, because
the launcher opens `icons/` and `config/` by relative path, and both
setup scripts find the root the same way. So a script moved into or out
of these folders has to fix that one line. Nothing that runs on both
belongs in them - a module that only one OS happened to need first is
still shared code and goes in `apps/`.

## Architecture

This is a **PyQt5 launcher** for GNU Radio signal generation/transmission applications. The launcher presents a grid of buttons, each opening a config dialog before launching a GNU Radio flowgraph.

### Launch Flow

1. `RFbenchToolkit.py` — Main window (`GNURadioLauncher`). Dynamically imports app modules from `apps/` using `importlib`.
2. When a button is clicked → `launch_application(module_name)` instantiates the module's `ConfigDialog` → user configures parameters → on OK, calls `module.main(app=..., config_values=...)`.
3. In **single mode**: launcher hides itself while the app runs, then shows again when the app closes. In **multi mode**: launcher stays visible.

### App Module Contract

Every module in `apps/` must implement:
- `ConfigDialog(QDialog)` — shows configuration UI; must implement `get_values()` returning a dict of config params; saves/loads its own per-app JSON config to `config/<module_name>_config.json`.
- `main(top_block_cls=..., options=None, app=None, config_values=None)` — creates and starts the GNU Radio `top_block`, returns the `top_block` instance (not `app.exec_()`).

The flowgraph class itself (e.g., `amSineGenerator`) extends both `gr.top_block` and `Qt.QWidget`.

### Shared Utilities (`apps/utils.py`)

- `apply_launcher_theme(widget)` — paints the launcher window from the
  shared tokens in `apps/theme.py` — see [one design, two front
  ends](#one-design-two-front-ends).
- `apply_dark_theme(widget)` — the same tokens for a config dialog, and it
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
| `fmVideoXmitter.py` | FM video transmitter - analog FPV on 5.8 GHz, or ITU-R F.405 relay/satellite; NTSC or PAL | ✅ |
| `fmVideoReceiver.py` | FM video receiver - pictures, sound, and what the transmitter's own numbers actually are | ✅ |
| `ntscAnalogVideoRecorded.py` | NTSC analog video transmitter | ✅ |
| `ntscReceiver.py` | NTSC analog video receiver - pictures and sound | ✅ |
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
  media directory now, like every other app - and for every video, not
  only `.ts` (below).
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
- **It played only transport streams, which on the machine that transmits
  meant one.** The picker listed `.ts` files. Every clip exists as a `.ts`
  here, so the list looked complete - but TVAdemo was sent the fourteen
  clips as `.mp4` only, and its picker offered the test pattern and nothing
  else. It lists every video ffmpeg reads now, one entry per clip, and a
  clip with no `.ts` of its own is encoded as it plays by
  `apps/atsc_source.py`: ffmpeg, with the settings `VIDEO-CREDITS.txt`
  records the `.ts` files were made with, into a pipe the flowgraph reads
  through `file_descriptor_source`. That is cheap - 21x real time on the
  8-core bench and 31x on TVAdemo, measured on the busiest clip, and
  transmitting on TVAdemo it used 0.26 of a core beside the modulator's
  2.06. The radio paces it, since ffmpeg blocks when the pipe is full, and
  what comes through is the mux rate to 0.01% in whole 188-byte packets.
  - A clip that has its `.ts` still plays that file: it costs nothing, and
    it is the one checked through the loopback.
  - Without ffmpeg only the `.ts` files are offered, and the list says how
    many more need it rather than looking like an emptier folder.
  - A choice is remembered by clip name, not file name, so one saved here
    as a `.ts` reopens on TVAdemo as the `.mp4`.
  - `close_stream()` ends ffmpeg once the flowgraph has stopped. Left
    alone it would sit blocked on a full pipe for as long as the launcher
    stays open.
- **Closing its window took the launcher down with it.** Its `main()` was
  the one app's not written for the launcher: it called `app.exec_()`
  regardless, and replaced the window's `closeEvent` with one that called
  `app.quit()`. Inside the launcher the event loop is already running, so
  `exec_()` printed "The event loop is already running" and returned -1 at
  once. Handed -1 instead of a window, the launcher never hooked the close
  to show itself again - and closing the window then quit the launcher's
  own loop, so the tile grid never came back because the launcher had
  exited. It returns the window now, as every other app does, and closing
  goes through the class's `closeEvent`, which also stops ffmpeg; started
  on its own it still runs a loop of its own. Verified on TVAdemo with the
  real flowgraph on the VSG60: the launcher came back, its loop survived,
  ffmpeg exited and the VSG lock was released. `scripts/test_app_close.py`
  checks every app for this.

The transport stream must be **constant bit rate at exactly 19.392658 Mbps**,
since the flowgraph consumes it at a rate fixed by the symbol clock - mux it
any slower or faster and the picture plays at the wrong speed. ffmpeg builds
one with `-muxrate 19392658 -f mpegts`, MPEG-2 video and AC-3 audio.

```sh
python scripts/test_atsc_loopback.py <video> 2      # no radio
python scripts/test_atsc_loopback.py <video> 2 15   # ... at 15 dB SNR
```

runs the transmit chain into GNU Radio's own ATSC receiver (`dtv.atsc_rx`)
with no radio: locks in 0.42 s, then 99.7% of packets come back byte-perfect,
holding above 98.5% down to about 15 dB SNR and collapsing below 14 - which is
where A/53 puts the cliff, and matching it is the best evidence the chain is
honest. The video can be anything the transmitter takes, and a non-`.ts` goes
through the same ffmpeg pipe; either way the score is against what actually
entered the chain, recorded on the way in. The Ford `.mp4` encoded as it
played came back 99.93% byte-perfect after locking in 0.42 s, beside 99.96%
for the test pattern's `.ts`.

**Verified off air**, the VSG60 transmitting from the TVAdemo laptop into the
BB60D here on RF channel 24 (533 MHz) at -9.5 dBm: **79,285 video packets
recovered with 209 flagged bad, 99.74% clean**, which is what the same stream
scores decoded purely in software. ffmpeg read it back as 704x480 MPEG-2 at
29.97 fps with AC-3 audio - exactly what went in - and rendered the test
pattern with its frame counter legible.

**And a clip encoded as it plays**, over the same link: TVAdemo transmitted
`Prelinger-Ford-1960-Wonderful-New-World.mp4`, a clip it has only as an
`.mp4`, through the app's own flowgraph. **0 bad packets of 759,936** over a
minute (0.000%), MER 22.0-23.1 dB, pilot +199 Hz, no BB60D overflows;
TVAdemo's modulator ran on 2.07 cores and its ffmpeg on 0.26, and ffmpeg was
gone the moment `close_stream()` ran. The recording read back as 704x480
MPEG-2 at 29.97 fps, 4:3, with AC-3 stereo, a frame of it rendered cleanly,
and its sound correlated 1.000 with the clip's own soundtrack at 48 kHz. Two
readings of that recording look like faults and are not:

- **Correlated at 8 kHz it scores 0.965** - and so does the clip's `.ts`
  twin, with no radio anywhere near it. That figure belongs to measuring at
  8 kHz, not to the link.
- **ffmpeg reports fourteen frames with no dimensions** whenever it opens
  the recording, even told to start a second in, because it reads the start
  of the file to find the streams. A recording begins partway through a
  15-frame group of pictures; the pristine `.ts` decodes with none, from its
  start or from 30 s in.

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

**The analog receivers' Watch is a different problem, and got this wrong.**
A transport stream is a river of small packets, so writing what fits and
dropping the rest works. A picture is one object of 921,600 bytes in NTSC
and 1,327,104 in PAL, where a pipe holds 65,536 - and `_to_player` wrote
once per decoded frame. A non-blocking write to a pipe delivers at most one
pipe buffer, so **each picture lost fourteen fifteenths of itself**, and the
remainder queued against a cap that only applied inside the branch that
never ran. Measured against a real FPV transmitter: of 214 pictures decoded
in 12 seconds, 7.1% of the bytes reached the player - **1.25 pictures a
second** - while the unsent backlog grew to **183 MB**. On screen that is a
picture that updates about once a second and falls further behind, which is
exactly what it was reported as.

`CompositeFrameSink` writes from a thread of its own now, blocking, and
holds a single frame rather than a queue: a player that has fallen behind
gets the newest picture and never a backlog, which is what the comment
above always claimed. Afterwards, 100% of decoded pictures arrive, whole,
at 17.57 a second with memory flat. Two details that matter:

- **The stop drains.** Asking the writer to finish before taking the pipe
  away from it is what stops the last picture of every session being
  thrown out; checked after the write rather than before it, the count is
  exactly the number decoded.
- **Tell the player the rate pictures actually arrive at**, which is one
  per buffer - 17.6 a second in NTSC, 14.7 in PAL - not the standard's
  29.97 or 25. A player told 29.97 and fed 17.6 starves between frames.

`scripts/test_fm_video_receive.py` checks the whole path now, because
nothing did: it runs the decoder at the radio's pace into a stand-in player
and requires every decoded picture to arrive whole. Against the old write
it reads 1.0 pictures of 14.

### NTSC composite video

`apps/ntsc_encode.py` builds a 2:1 interlaced composite signal - sync,
blanking, equalizing pulses, serrations, colour burst and a
quadrature-modulated chroma subcarrier - and `apps/ntsc_decode.py` takes it
apart again: NTSC to SMPTE 170M-2004, and PAL to ITU-R BT.1700 Part B (see
[PAL](#pal-625-lines) below; the modules kept their names). Both are free of
GNU Radio and Qt, like the RDS pair, so they can be checked with no radio at
all:

```sh
python scripts/test_ntsc_loopback.py       # encoder -> decoder, no radio
python scripts/test_pal_loopback.py        # ... the same for PAL
python scripts/test_ntsc_transmit.py       # ... and through the modulator
python scripts/test_ntsc_transmit.py --video clip.mp4   # picture and sound
```

With `--video` the transmit test also checks the clip's soundtrack all the
way onto the aural carrier and back, and that the source keeps up when it is
paced at the rate a radio consumes.

All seven colour bars return with a worst error around 1e-11 and a full-scale
grey ramp within 0.002 - it was 0.0089 and 0.0092 until blanking started
coming off the back porch (below). `docs/S170m-2004.pdf` holds the timing
tables (2 and 3), the levels (table 1) and the encoding equations (annex A).

- **Sync and blanking come off the pulses, not off how the samples are
  distributed.** `levels()` makes a first guess and `decode_frame` refines
  it: blanking on the breezeway after each line sync, which is where a
  television clamps, and the sync tip in the middle of the pulses. The first
  guess has failed twice, both times silently.
  - It was the histogram's commonest level inside the 10-60% band of
    sync-to-white. On a dark scene the top of that range collapses toward
    blanking, which then sat outside the window: `find_pulses` found **no
    pulses at all**, and off air 17 frames in a row failed every time a clip
    reached a dark shot.
  - Widened to 5-98% it held until there was noise. Then the porches spread
    across many bins and any large flat area spread the same way over more
    samples: with noise of 0.05 of the swing the commonest level on a white
    picture was 2.5 times the sync-to-blanking step too high, and on colour
    bars off the FM link it was the white bar. The slicer cut at blanking
    level, every "pulse" was a whole blanking interval, and the picture came
    out wrong **with no error raised**.
  - Now it is two percentiles. Sync tips are about 8% of all samples and
    blanking-level samples about the next 16%, whatever the picture does,
    so the 4th percentile sits in the tips and the 20th in blanking. That
    decoded every picture tried - white, black, grey, dark, 90% white,
    saturated red and blue, clean and noisy, at 10 MS/s and 4x subcarrier -
    and read real off-air signals within 0.96-1.09 of their back porch.
  - The refinement matters as much. A low percentile of noisy samples sits
    below the real tip by however far the noise reaches - the FM off-air
    captures read 0.02-0.05 low - where the middle of the pulses reads
    within 0.001, and the tip is half of what sets the picture's scale.
  - **The breezeway is counted from where each pulse began plus the sync
    width, not from where the slicer says it ended.** That end moves with
    noise: on saturated red and blue a window hung off it slid onto the
    edge and read blanking 0.011 low, against 0.0026. The front porch is
    the obvious alternative and is worse where it matters - through the
    vestigial-sideband transmitter the picture rings into it, and colour
    came back 0.102 out against the breezeway's 0.081.

  Getting blanking exactly right is also what made the loopback exact.
  Re-slicing with the refined levels is not worth the fifth of a decode it
  costs - measured, 883 pulses either way - so it only happens if the first
  guesses were out by more than half the span.
- **Chroma is taken out of luma before its envelope is turned to the
  burst.** Decoded colour used to depend on which sample a buffer happened
  to start on: colour bars straight from the encoder, never near a radio,
  came back anywhere from 0.017 to 0.20 out as the first sample moved, and
  0.59 out at a single pixel. To subtract chroma from luma the decoder
  rebuilds the chroma waveform from its complex envelope, and it did that
  *after* rotating the envelope to line up with the burst - so the rebuilt
  chroma was out of phase with the real one by exactly that rotation, which
  is set by where the buffer starts. Most of the chroma stayed in luma as a
  dot pattern that a 40-row average mostly hid. `test_ntsc_loopback.py`
  decoded from sample 0 at 4x subcarrier, the one start where the rotation
  is zero, so it never showed; off air, where a buffer starts anywhere, it
  was every frame. Fixed, twelve different starts all read the same, and
  the NTSC transmit test's colour error - which had been put down to the
  vestigial sideband - fell from 0.13 to 0.081. Both loopbacks now decode
  from twelve starts.

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

#### PAL, 625 lines

The same encoder and decoder make and read 625-line PAL to ITU-R BT.1700
Part B (`docs/1700-e.pdf`), which the FM video transmitter offers because
FPV cameras send either. What differs between the standards is a table,
`VideoStandard`: timing, levels, colour axes, and which half-lines of the
frame carry equalizing pulses, broad pulses or nothing - the only
structural difference. **NTSC's output is bit for bit what it was before
PAL existed**, at every rate, colour and legalizer setting tried, and it
encodes exactly as fast (32.3 ms a frame against 32.5).

- **The numbers**, Tables 1-3: lines at 15,625 Hz, subcarrier
  (1135/4 + 1/625) x fH = 4,433,618.75 Hz, a 64 us line with 12 us blanked,
  sync 4.7 us, a ten-cycle burst from 5.6 us; sync -300 mV, blanking 0,
  white 700 mV and no set-up; 576 active lines, sampled into 768x576 square
  pixels at 25 frames a second. Each field-sync block is five equalizing,
  five broad and five equalizing pulses, two and a half lines each. The
  first field's block begins half-way through line 623, so its broad pulses
  start exactly on line 1; the second's begins on 311. `test_pal_loopback.py`
  finds 610 line syncs, 20 equalizing and 10 broad pulses in a frame.
- **The V switch.** V, and the V half of the burst, change sign every line.
  The encoder takes the sign from the absolute line count's parity, which
  with an odd 625 lines repeats every two frames, as the standard's
  eight-field sequence needs. The decoder cannot know it in advance: the
  burst sits 45 degrees either side of -U, so four neighbouring lines'
  bursts average to the reference axis, and each line's own burst, measured
  against that, gives its sign. Four lines is 256 us, too short for two
  radios' clocks to turn the subcarrier measurably. Reading the switch
  backwards turns green magenta, which the test checks.
- **The burst is left off the field-sync lines only.** BT.1700 blanks it on
  a sequence that moves from field to field (Figs. 8 and 9) so that the
  first burst after field sync always has the same phase. Here it is off on
  the 16 lines with equalizing or broad pulses and on the other 609. A
  receiver locked to the line-by-line swing does not need the sequence, and
  a decoder that reads each line's own burst would lose colour on any active
  line the sequence blanked.
- **The legalizer's floor is -180 mV, not NTSC's scaled.** PAL's own 75%
  bars swing down to -175 mV in red and blue, where NTSC's bottom out at
  -16 IRE inside a -20 floor. A floor scaled from NTSC's (-140 mV) clipped
  them, and bars came back 0.032 out; -180 passes them and stays above the
  decoder's sync slice at -195.
- **It costs more to encode**: a 768x576 frame at 12.5 MS/s takes 50.9 ms
  of its 40 on one thread, 0.79x real time against NTSC's 1.03x, in
  proportion to its 1.5 times as many samples.
- **Every row lands on its row** whichever field a buffer opens on: a
  six-row band decodes onto exactly rows 300-305 from buffers starting a
  quarter, a half and four fifths of the way into a frame.
- **A PAL frame is a whole number of samples, so frame boundaries are worked
  in samples.** The encoder found where each frame ends in seconds - floor
  the start time over the frame period, step one, ceil back to samples -
  which is harmless while a frame is never a whole number of samples, and
  NTSC's never is. PAL's is: 500,000 at 12.5 MS/s, 800,000 at 20. Frames
  came out a sample long, then a sample short, and at frame 30, 1.2 s in, a
  quotient that should have been a whole number came out a hair under it:
  that frame ended where it began, and so did every frame after it. The
  source block took an empty frame as the one to replay when the encoder
  fell behind, and looped on it without producing a sample - so the
  transmitter went quiet after 1.2 s and **could not be stopped**:
  `tb.wait()` never returned, and the FM video test sat on TVAdemo for ten
  hours with three threads spinning. Boundaries now snap to a whole sample
  when they are within rounding of one, a frame is never empty, and the
  source refuses one if it ever is. PAL then runs at exactly the radio's
  rate, repeats nothing after warm-up, and stops at once; NTSC's stream is
  bit for bit unchanged. The loopbacks never saw it because they encode two
  or three frames and the fault needed thirty, so `test_pal_loopback.py`
  now walks 100,000 frame boundaries.

### How the pickers find media

Every list of files in every dialog - the WAV lists in AM Audio, FM Audio,
FM Subcarrier, PPM-OOK, FM + RDS and the two video transmitters' sound, the
clips, the ATSC streams and the `.dat` stills - comes from
`media_files()` in **`apps/media.py`**. They used to list the folder each
in their own way, and disagreed:

- **None of them looked in subfolders**, so a clip filed under
  `media/Prelinger/` was invisible to every app. The walk goes to any
  depth now, and an entry is labelled with its folder -
  `Prelinger/Chevrolet 1955 Heres Looking`. A file at the top keeps exactly
  the label it always had, and its full path is unchanged, which is what
  keeps a choice saved before this pointing at the same file.
- **Five matched `.wav` case-sensitively and the rest did not.** AM Audio,
  FM Audio, FM Subcarrier, PPM-OOK and FM + RDS used `glob('*.wav')`, which
  on Linux misses `SONG.WAV`, while the NTSC and FM video transmitters
  lower-cased the name first. So one file could be offered by one
  transmitter and not the next - on Linux only, since Windows filenames
  are not case-sensitive at all. Every extension now matches whatever its
  case.
- **Two did not sort**, and came out in whatever order the filesystem
  returned. Everything is top-level files first, then each subfolder's
  grouped, alphabetical ignoring case.

Things it skips on purpose: hidden folders and files - macOS leaves a
`._song.wav` beside every file it copies to a foreign disk, which has the
right extension and is not audio, and fails only once someone presses OK -
and symbolic links to folders, so a link back up the tree cannot make the
walk run forever. Labels use `/` on Windows too.

`video_files()` still offers one entry per clip, but a clip is now a name
*within a folder*: `Prelinger/clip.mp4` and `Prelinger/clip.ts` are one
entry, and a `clip.mp4` in each of two folders is two. The ATSC transmitter
used to find its saved clip by bare name, which with subfolders could land
on a same-named clip in another folder; it tries the exact file first now
and falls back to the name, so a choice saved where it was a `.ts` still
finds the `.mp4` elsewhere.

**The list is built when a dialog opens**, not while one is open: the
launcher makes a fresh dialog on every click, so a new file or a new media
folder shows up the next time an app is opened. A running FM + RDS
transmitter's Next Track steps through the list its dialog was opened
with.

```sh
python scripts/test_media.py    # no radio, no display; Linux and Windows
```

builds a throwaway folder with every case above and checks what comes
back, including a link that points back up the tree.

### NTSC video sources

`apps/ntsc_source.py` turns a *stream* of frames into a continuous signal,
and settles what video format this project takes: **whatever ffmpeg reads**.
There is no bespoke format. A video file is decoded by an ffmpeg subprocess,
scaled to 640x480 and letterboxed if it is not 4:3, looping forever; there
is also a built-in colour-bar pattern so the app works with an empty media
folder.

- **Frames are encoded on their own threads - more than one of them.**
  Encoding inside work() would stall the radio, so it happens behind a
  queue. One encoder thread is not enough, though: a frame at 10 MS/s takes
  26-32 ms against a 33.4 ms budget, measured on both machines, so a single
  thread runs at 1.03-1.21x real time *before* it shares the processor with
  the modulator, the resamplers and the radio sink. Off air it lost. numpy
  releases the interpreter lock inside the large array operations this
  encoder is made of, so plain threads scale - measured 1.03x, 1.62x, 2.16x
  and 2.49x on one, two, three and four - and `encode_workers()` uses three
  on anything with eight cores. Frames are independent given where each one
  starts, and `NtscEncoder.frame_bounds()` says that without encoding
  anything, so the next frame can be dispatched while this one is still
  being computed; the results go into the queue in order.
- **A late frame must never take the transmitter off the air.** work() used
  to wait a tenth of a second for a frame before giving up, which turned a
  slow encoder into a *silent carrier*: nothing came out of the block, so
  nothing reached the radio. Measured on the VSG60 with a real clip: **74
  gaps in three seconds, the longest 18.6 ms, 25% of the air time missing**
  - and the picture still decoded at 17.4 frames a second with zero
  failures, so nothing but the envelope showed it. This is the same trap as
  the HackRF ATSC case below, and the same lesson: a spectrum average
  cannot see a transmitter that is off half the time. The wait is two
  milliseconds now, and what fills a gap is the *previous frame* rather
  than blanking - a frozen picture keeps sync pulses and colour burst
  coming, where blanking is a level a receiver loses lock on. The first
  frame is encoded before the block reports itself started, so the
  transmitter never opens with blanking either. `repeats` and `starved`
  count both, and `scripts/test_ntsc_transmit.py` requires zero of each in
  steady state at the radio's own rate.
- **The `.dat` captures do not go through it.** They are already composite,
  at 18 MS/s, so they are played by a file source and resampled 5/9 - see
  `dat_resample_ratio`.
- **A pipe handed to `file_descriptor_source` must be a duplicate, or the
  *second* launch of the app goes out silent.** That block closes the
  descriptor it was given in its destructor, and `AudioTrack.close` - which
  `close_sources` calls on closeEvent - closes it too. Two owners, one
  number, closed twice. The second close lands on whatever was opened in
  between, and what opens in between is the next run of the same app: its
  pipe is handed the lowest free descriptor, which is the one just
  released. So launch, close, launch again, and the moment Python collects
  the first run's flowgraph the second run's sound dies with
  `file_descriptor_source: error: [read]: Bad file descriptor`. Reported
  from TVAdemo against a clip, reproduced exactly, and both descriptors
  read 3 in the reproduction. `AudioTrack.descriptor()` and
  `TransportStream.descriptor()` hand out `os.dup` of it now, so each owner
  closes its own; the NTSC transmitter, the FM video transmitter and the
  ATSC transmitter all went through `fileno()` and all had it.
  `scripts/test_fm_video_transmit.py` runs the launch-close-launch sequence
  in the order that used to break.
- **One clip, one entry in the picker.** The media folder holds each clip
  twice - a `.mp4` for here and a `.ts` of the same picture and sound, which
  the ATSC transmitter plays without having to encode it - so offering every
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
- **Pixels are squared before the picture is fitted.** ffmpeg's
  `force_original_aspect_ratio` works on the stored width and height, not
  the shape on screen, so a `.ts` at 704x480 with 10:11 pixels - the ATSC
  test pattern, or anything the ATSC receiver records - played 9% too
  short, with 22 black rows top and bottom. `VideoFile` scales to `iw*sar`
  first, as `apps/atsc_source.py` does. Square-pixel clips come out
  bit-identical to before. Measured: 10:11 and DVD 8:9 material now fills
  the frame, DVD 16:9 letterboxes to rows 60-419 as it should, and a file
  with no aspect ratio recorded still plays.
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

Every tile is declared in `APP_TILES` at the top of `RFbenchToolkit.py`
as `(row, column, [face, ...])`, where a face is
`(label, module, icon, direction)` and direction is `'tx'` or `'rx'`.
A tile with more than one face is a **flip tile**: a badge in its corner
turns it over, and the icon and the caption both change with it. That is
how the two ends of one standard share a square - the ATSC, NTSC and
FM + RDS transmitters and their receivers - instead of sitting apart as
though they were unrelated apps. All three video standards
now have both ends on one tile, FM video included.

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
- **Every face is cropped to the same 4:3 box**, so two icons with
  different aspect ratios cannot clip one another or shove the caption
  around mid-turn. The caption is given the height of the longest name on
  the grid, for the same reason: otherwise one long name makes its own
  tile taller than the rest of its row.
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
- **The sound came from a different file than the picture.** The aural
  carrier was fed by a `.wav` picked separately in the dialog, which was
  all that was possible when the only video the app could send was a single
  still frame. Once it could send clips, a 1950s car advertisement went out
  with an unrelated cartoon soundtrack over it. The clip's own track is the
  default now - a second ffmpeg on the same file, decoded to 48 kHz mono
  and handed to `blocks.file_descriptor_source` - and the two stay in step
  for free, since GNU Radio consumes exactly one audio sample per composite
  sample and both are paced by the radio's clock. The dialog still offers a
  `.wav`, and offers silence, because the built-in pattern and the `.dat`
  stills have no sound of their own; "From the video clip" greys out when
  the source is not one, and comes back when it is.
- **Clip audio has to be conditioned or the carrier is 10 dB
  under-deviated.** The clips are loudness-normalised to -24 LKFS (ATSC
  A/85), which is deliberately quiet: measured across all fourteen, peaks
  ran 0.30 to 1.11 and rms 0.038 to 0.088, where full deviation is |1.0|.
  A fixed gain cannot fix it, because the loudness is uniform and the crest
  factor is not - 8 dB puts speech where it belongs and clips the two
  music-heavy Blender films on 0.17% of their samples. `AUDIO_FILTER`
  compresses and then lifts, which gives rms 0.091-0.210 and peaks
  0.64-1.54 across the whole set, with the worst needing the rail on
  0.0017% of samples. ffmpeg's own `loudnorm` is the obvious tool and the
  wrong one: its dynamic mode looks three seconds ahead, and since the
  picture comes from a *separate* ffmpeg on the same file, that delay lands
  as three seconds of lip-sync error.

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
took the measured colour error from 0.43 to 0.13 - and much of what was
left was the decoder, not the vestigial sideband: with its chroma
separation fixed (see [NTSC composite video](#ntsc-composite-video)) the
same test reads 0.081, and its tolerance came down from 0.15 to 0.10.

**Verified with real material**: 1950s Prelinger advertising and the Blender
open movies through the whole chain and back, **0.00002-0.0099 mean error**
(it was 0.078-0.088 until blanking came off the back porch and fixed the
IRE scale), the black-and-white spots clean and the colour ones looking
convincingly like period colour television.

**Verified off air, picture and sound**, the VSG60 transmitting
`Prelinger-Chevrolet-1955-Heres-Looking.mp4` from TVAdemo into the BB60D
here on RF channel 24 (533 MHz) at -9.5 dBm:

- **1,049 frames decoded, none dropped**, 17.4-17.9 a second against the
  17.6 the receiver's buffer allows, line rate 15,734.2-15,734.4 Hz against
  the 15,734.266 the standard specifies - a few parts per million, which is
  the NTSC equivalent of the ATSC pilot offset.
- **The carrier was present 100.00% of the time**, no gap at all, against
  25% of the air time missing before the encoder was given more threads.
- **The sound is the clip's own**: the aural carrier demodulated and
  cross-correlated against the same clip decoded locally scores **0.999**
  over the matching window, with the next-best alignment at 10% of that.
  Peak deviation 17.1 kHz of the 25 kHz System M allows, envelope
  std/mean 0.005 - a clean FM carrier.
The first run of this also found a fault in the *receiver*, which is worth
recording because of how it looked. About seventeen frames in a row failed,
once a run, always with the same exception - "could not find two fields - no
vertical sync?" - and the input level never moved, there were no BB60D
overflows and no dropped buffers. It looked like the receiver settling; it
was nothing of the kind. The failures were **exactly one buffer period
apart, seventeen of them, spanning one second**, and they landed at a
different time in every run. Transmitting the built-in colour bars for 150
seconds instead gave 2,616 frames and not one failure, which placed it in
the *picture*: the clip fades through a dark shot about once per 106-second
loop, and on a dark picture the blanking estimate collapsed onto the sync
tip. See the back-porch note under [NTSC composite
video](#ntsc-composite-video); `scripts/test_ntsc_loopback.py` now
reproduces it with no radio at all. Afterwards the same link ran **3,498
frames with none failed, none dropped and no overflows** over 200 seconds,
which is nearly two full passes of the clip and of its dark shot, and 4,183
frames with none failed over four minutes before that.

Two things about measuring this that wasted time, neither of them a fault
in the radio:

- **Demodulate well above the audio rate, then filter down.** Subsampling
  the instantaneous frequency straight from 20 MS/s to 48 kHz folds
  everything up to 60 kHz back into the audio band. That read 0.087
  correlation on a link that was in fact perfect.
- **Normalise a correlation over the window that matched**, not over the
  whole reference. Three seconds of recovered audio against a 106-second
  clip cannot score above sqrt(3/106) = 0.168 however exact it is, which
  reads as a failure and is arithmetic.
- **Search negative lags too.** GNU Radio does not prepend a filter's group
  delay to its output, so the first sample out of a chain corresponds to an
  input sample some way in and the recovered signal can *lead* the
  reference. A forward-only search finds a spurious peak: it scored a
  chain that was in fact carrying the sound at 0.947 as **0.03**, and cost
  an hour of looking for a fault that was not there. The alignment search
  in `test_ntsc_transmit.py` is checked against a signal delayed by a known
  amount before it is trusted.

### NTSC Receiver

`ntscReceiver.py` is the other end of `ntscAnalogVideoRecorded.py` and
shares its tile. The picture side is described above; the **sound** is a
second, separate chain off the same radio, because System M puts it on its
own FM carrier 4.5 MHz above the visual one and the picture's Nyquist
filter exists partly to throw it away (a video detector fed both produces
no recognisable sync at all).

- **It is an FM receiver.** `NtscSound` mixes the aural carrier to zero,
  filters to Carson's 80 kHz - 2 x (25 kHz deviation + 15 kHz audio) - and
  decimates 100:1, all in one `freq_xlating_fir_filter`, which costs a dot
  product per *output* sample so 20 MS/s in costs what 200 kS/s costs.
  Then quadrature demodulation, 15 kHz low pass, 6/25 to 48 kHz,
  de-emphasis, volume, `audio.sink`.
- **Demodulate well above the audio rate.** Taking the instantaneous
  frequency straight to 48 kHz folds everything up to 60 kHz into the audio
  band - see the measuring notes above.
- **A missing audio device must not take the picture down**, so the sink is
  built inside a try/except and a failure turns sound off and says so, the
  same shape as the RDS receiver.
- **Two meters, not one.** Sound Carrier says the sound is being
  transmitted at all; Deviation says something is modulating it. A strong
  carrier with no deviation is a station sending silence, which is a
  different fault from no carrier - and below about 100 Hz rms the readout
  says "silent" rather than quoting the demodulator's own noise floor as
  though it were programme.
- **Mute keeps the chain running**, so both meters go on reading. That is
  the point of having them.
- **The spectrum shows the channel, not the radio.** Fed straight off the
  radio the sink is centred on the *local oscillator*, which is
  `LO_OFFSET` - 6 MHz - above the channel centre: 20 MHz wide with the
  television channel squashed into the left third and two thirds of the
  plot empty air. Side by side with the transmitter's own 10 MHz
  channel-centred plot of the same signal, the two looked like different
  signals, and the obvious reading of the receiver's was that it had
  invented a second carrier. It had not - **both windows show two
  carriers, and both are right**: measured off air, visual at 531.2504
  MHz, aural at 535.7499 (visual + 4.4995 against the standard's 4.5) and
  the colour subcarrier at 534.8295 (visual + 3.5791 against 3.579545).
  The receiver now mixes the channel back to the centre and decimates to
  the transmitter's own 10 MS/s in one `freq_xlating_fir_filter`, and the
  transmitter's plot - which is called *RF* Spectrum and was labelled 0 Hz
  at the channel centre - is labelled in RF. The two windows now have the
  same span, the same centre and the same axis.
  - The filter is flat across the whole 6 MHz channel and stops at
    exactly 5 MHz, the decimated Nyquist, so nothing folds into the plot.
    A display that invents a signal is worse than no display - and the
    price of that is that the noise floor *outside* the channel is the
    filter's skirt rather than the air, so do not read adjacent-channel
    interference off this plot.
  - It costs about 0.7 of a core of the eight. Measured off air with it
    in and with it out, back to back on the same transmission: 1,764
    frames either way, 17.6 a second, **0 failed, 0 dropped, 0 BB60D
    overflows**, 3.83 cores against 3.13.
- **The BB60D's analog filter is flat to +-8.5 MHz and gone by +-9.0**
  (measured off its own noise floor at 20 MS/s: -0.7 dB at 8.5,
  -10.9 at 9.0, -70.7 at 9.5, where the decimation filter takes over).
  Tuned 6 MHz above the channel centre the channel occupies -9 to -3 MHz
  of that, so the bottom of the vestigial sideband - 0.75 MHz below the
  visual carrier, at -8.5 MHz - sits in the last half megahertz of flat
  response. It fits, and decoding is unaffected, but there is no margin
  below it: a larger receive offset would start cutting the vestige.

**The transmitter had no pre-emphasis, and adding the receiver is what
found it.** System M sound is 75 us pre-emphasised like FM broadcast, and a
receiver de-emphasises; the FM + RDS transmitter here has always done it,
and the NTSC one never did. Sent that way, every set rolls the treble off -
the sound is not wrong, just dull, which is the kind of fault nobody
reports and everybody hears. `fm_preemph` goes in ahead of the rail,
because pre-emphasis lifts transients by up to 18 dB on this material and
the limiter has to be the thing that catches them; that is the order a real
station processes in. Measured through both chains afterwards: the response
is flat to **0.03 dB from 200 Hz to 10 kHz**, and the rail holds 0.000% to
0.011% of samples at full deviation.

**Verified off air**, the VSG60 transmitting a clip from TVAdemo into the
BB60D here on RF 24: the sound carrier reads a steady -53.0 dBFS, deviation
tracks the programme between 1.7 and 6.5 kHz rms, the picture goes on
decoding at 17.6 frames a second beside it, and the recovered audio
correlates **0.999** with the same clip decoded locally, the next-best
alignment scoring 8% of that.

**And verified again on 2026-09-17, after the decoder changed underneath
it.** The blanking percentiles, the chroma separation and - most of all -
`CompositeFrameSink`, which this receiver now shares with the FM video
receiver and which grew a writer thread of its own for Watch, had all been
checked in software and none of them against real RF on this path. Same
link, same clip, the app's own flowgraph run headless for 220 seconds,
which is two full passes of the clip and of the dark shot that once broke
the blanking estimate:

- **3,868 pictures, 17.63 a second of the 17.63 the buffer allows, 0
  dropped, 0 failed, 0 BB60D overflows.** Line rate 15,734.2-15,734.5 Hz
  (-6 to +16 ppm), input -45 to -37 dBFS, colour throughout.
- **Watch delivered every picture, whole.** Over a 60-second window 1,059
  pictures were decoded and **1,059 arrived at the player - 975,974,400
  bytes, not one byte of a partial frame** - at 17.63 a second, with
  nothing superseded in the holder and the process's memory moving from
  497 to 522 MB across the minute. The same path with the old
  non-blocking write delivered 7.1% of the bytes and 183 MB of backlog.
- **The sound is the clip's own**: 0.9987-0.9997 at four points across the
  run, against the next-best alignment's 0.04-0.12. The clip offset it
  finds advances exactly with the clock at every one of them - 62.99 s at
  40 s in, 6.79 at 90, 56.79 at 140, 96.79 at 180 - which is the 106.206 s
  loop tracked for nearly four minutes without a slip. Sound carrier
  -48.0 to -47.2 dBFS, deviation 0.7-11.0 kHz rms.

One measuring trap, again nothing to do with the receiver: **an FFT
cross-correlation peaks at minus the offset.** `irfft(A * conj(B))` peaks
where `a[j] = b[j-m]`, so a slice taken at clip offset t puts the peak at
-t. Reading that index as the offset picks the wrong segment of the
reference to normalise against, and scored a recovery that was in fact
perfect at **0.007** - which looks exactly like sound that never arrived.
Delaying the slice by a known amount is what catches it: the reported
offset moved by 1234 samples the wrong way.

### FM Video Transmitter

`fmVideoXmitter.py` frequency-modulates a carrier with composite video and
puts the sound on FM subcarriers above the picture, in the same baseband.
That is what an analog FPV drone sends on 5.8 GHz, and what analog
microwave relay and satellite links sent. It replaced the AM video
transmitter, which matched nothing a real transmitter sends.

**One app, with a Standard pull-down.** FPV and a microwave relay are the
same transmitter with different numbers, so the dialog's first choice fills
in the rest - channel plan, deviation, pre-emphasis - and leaves them
editable, so an FPV transmitter that turns out to deviate differently from
the datasheet's hint can be matched without touching code. The numbers live
in `apps/fm_video_core.py`, free of GNU Radio and Qt:

| | FPV drone (RTC6705) | Microwave relay / satellite (ITU-R F.405) |
|---|---|---|
| Deviation | 7.93 MHz p-p for 1 V, at every frequency - **measured off air**, not a datasheet figure | 8 MHz p-p for 1 V at the curve's crossover - 0.7616 MHz for 525 lines, 1.512 for 625 - which is 2.53 or 2.255 MHz at low frequencies |
| Picture pre-emphasis | none | F.405's shelf for the picture's line count: 525 lines, zero at 187 kHz, pole at 875 kHz, 10 dB down at DC; 625 lines, zero at 313 kHz, pole at 1.565 MHz, 11 dB down |
| Sound | FM subcarriers at 6.0 MHz (left) and 6.5 MHz (right), -27.5 dBc, +-25 kHz, 12 kHz corner | one at 6.8 MHz, -20 dBc, +-50 kHz, 75 us |
| Channels | 40, bands A, B, E, F and R | a typed frequency |
| 99% bandwidth, colour bars | 10.8 MHz in NTSC, 12.1 in PAL | 14.7 MHz in NTSC, 14.6 in PAL |

**And a Format pull-down: NTSC or PAL.** FPV cameras and goggles do either,
and a transmitter sends whatever its camera gives it. The format picks the
encoder's standard, the picture's size and rate (640x480 at 29.97, 768x576
at 25), the rate the picture is encoded at, and which of F.405's curves
applies; changing the format moves an F.405 choice onto the curve for the
new line count. The standard itself is described under [PAL](#pal-625-lines).

The sources are in `docs/`: `RTC6705-DST-001.pdf` and `RTC6715-DST-001.pdf`
(the transmitter and receiver chips nearly all analog FPV gear is built on)
and `R-REC-F.405-1-197007-W.pdf`. Two of the numbers are this project's
choices rather than a document's, and are worth measuring against real
equipment before they are trusted:

- **Neither RichWave datasheet gives the video deviation or any video
  pre-emphasis**, so both were this project's guesses until 2026-09-16,
  when a real FPV transmitter was measured on A3 (5825 MHz) into the BB60D
  with the FM video receiver's own readout - see its section for the whole
  set. The deviation was **7.93 MHz p-p** over 237 frames (spread
  7.89-7.96), not the 5.0 the datasheets imply: +-2.5 MHz is the RTC6715's
  *sensitivity test condition*, the only video deviation either mentions,
  and it under-deviates a real link by 4 dB. The profile carries the
  measured figure now, and the dialog's Deviation box is editable because
  one unit is one unit. The pre-emphasis guess was right: the colour burst
  came back +0.14 dB against DC (spread 0.08-0.18), so whatever R/C network
  that module has does nothing measurable at the colour subcarrier.
- **F.405 says nothing about sound.** One subcarrier at 6.8 MHz with 75 us
  is what analog C-band satellite channels commonly carried; its level and
  deviation are chosen.

```sh
python scripts/test_fm_video_transmit.py                  # both standards, no radio
python scripts/test_fm_video_transmit.py --video clip.mp4 # ... picture and sound
```

Things worth knowing before changing it:

- **A sampled FM modulator over-deviates the top of the baseband.**
  `frequency_modulator_fc` sums phase a sample at a time, and a running sum
  is not an integral: for a tone of w radians per sample it has
  w/(2 sin(w/2)) times the gain - +0.64 dB at 4.2 MHz of 20 MS/s, +1.72 dB
  at 6.8 MHz. A spectrum analyser, or a real goggle's discriminator, sees
  the true swing, so the subcarriers' sidebands read 0.5-1.3 dB high until
  the transmitter took it out: an FIR on the picture
  (`integrator_compensation_taps`), an exact correction in each
  subcarrier's level. Afterwards they measure -27.50 and -20.00 dBc, as
  specified. A receiver that differences phase reads the same amount
  *low*, which `discriminator_compensation_taps` puts back.
- **The subcarriers are added after the pre-emphasis.** F.405's curve is for
  the picture.
- **The picture is encoded slower than the radio runs and interpolated up.**
  The encoder cannot keep up at 20 MS/s. NTSC is encoded at 10 MS/s and
  interpolated by 2. PAL cannot be: its chroma sidebands reach 5.7 MHz,
  which at 10 MS/s would fold back onto the chroma itself, so it is encoded
  at 12.5 and interpolated by 8/5 (`VIDEO_RATES`). The interpolator's
  passband is 0.45 of the video rate (`INTERPOLATOR_BW`); GNU Radio's
  default 0.4 is flat only to 4 MHz at NTSC's rate.
- **20 MS/s for every radio**, the HackRF's ceiling, and both standards fit
  inside it in both formats. The USRP here has a WBX, which stops at
  2.2 GHz, so it cannot reach 5.8 GHz at all.
- **F.405's networks are bilinear transforms whose one free constant is
  searched for.** The transform keeps a network's gain at DC and at the top
  exactly and moves the frequency axis in between. With the textbook
  constant the 525-line curve came out 0.048 dB off at 4.2 MHz, 35% of the
  recommendation's tolerance - but the 625-line curve's pole is nearly twice
  as high, and it came out 0.145 dB off at 5 MHz, 101%, just outside.
  Pre-warping the zero and pole, the other textbook answer, doubled both.
  So `coefficients` tries the constants that match the curve exactly at
  each of 160 frequencies and keeps whichever lands the worst point furthest
  inside the tolerance: 32% for 525 lines, 90% for 625.
  `iir_filter_ffd(b, a, False)` reads the taps the way scipy writes them,
  checked to 4e-7.
- **FM has a threshold, and the test shows it.** With noise added to the FPV
  signal, every dB of carrier is a dB of picture down to about 12 dB
  carrier-to-noise in 20 MHz - 46.8 dB of picture at 30, 36.8 at 20, 28.7
  at 12 - with no clicks at all from 15 dB up. Below that the damage
  arrives as clicks, the sparkles of a weak FM picture: 88 a frame at
  10 dB, 708 at 8, 3,937 at 6, 13,608 at 4. An AM picture fades into snow
  instead. (Those picture figures are 4 dB better than they were before the
  deviation was measured, which is the whole of FM's trade in one line: the
  datasheet's 5 MHz p-p was throwing 4 dB away.)

Four things about measuring it cost time, and none of them was in the
transmitter:

- **Judge the link by waveform, not by decoded colour.** Decoded colour
  measures the decoder as well as the link, and at the time the decoder's
  colour depended on which sample a buffer started on - a bug, since fixed
  (see [NTSC composite video](#ntsc-composite-video)). It read as the FM
  chain being 0.168 wrong for both standards, to six figures - identical for
  two different modulations, which is what gave it away.
- **Compare against the composite through the same video filters, not the
  untouched original.** The encoder's bars switch in a single sample and
  carry energy up to the video rate's Nyquist that no real video path
  passes; against the original that alone reads 21 dB. Against the
  filters-only reference the FM chain is 118-136 dB transparent in NTSC and
  83-88 dB in PAL, whose 8/5 resampling is the difference.
- **Find the alignment on the luma, and not too far away.** Colour bars
  repeat every line and their chroma every other frame or so, so a match a
  whole line away scores nearly as well as the right one - and lands the
  chroma upside down. And at PAL's 12.5 MS/s the 4.43 MHz chroma is 2.8
  samples a cycle, so a full-band correlation swings from 0.30 to 0.94
  between neighbouring lags while the true delay, through 8/5 resampling, is
  a fraction of a sample no whole lag lands on: the best whole lag was two
  lines away, and PAL bars read 24 dB where they are 83. The lag is found on
  a copy low-passed to 1.5 MHz, whose peak is broad; searched only 200
  samples either way in software; tried three lines either side off the
  air, keeping the smallest residual; and the fraction is fitted from the
  phase below 3 MHz.
- **The median of the swing is not the carrier's offset.** Colour bars spend
  their time a little above the rest frequency and read as 80 kHz, 13.7 ppm,
  off. Sync tip and blanking are the levels the standard fixes, so the
  off-air analysis slices at its own sync-to-blanking step and reads both
  off the pulses - which the decoder itself now does too.

**Verified off air**, the VSG60 on TVAdemo transmitting on FPV channel F4
(5800 MHz) at -9.5 dBm into the BB60D here at 60% gain and 20 MS/s, the
app's own flowgraph run headless. A sweep of 5645-5945 MHz beforehand found
WiFi at 5742-5763 MHz and nothing else.

| | FPV, colour bars | FPV, Chevrolet clip with sound | F.405, colour bars |
|---|---|---|---|
| Carrier-to-noise in 20 MHz | 18.6 dB | 18.7 dB | 17.6 dB |
| Clicks | none in 90 frames | none | none |
| Frames decoded | 51 of 51 | 51 of 51 | 51 of 51 |
| Line rate | 15734.2-15734.3 Hz | the same | the same |
| Sync-to-blanking step, against sent | -2.9% | -0.4% | -0.6% |
| Picture, p-p over rms in 4.2 MHz | 29.0 dB | - | 35.4 dB |
| Sound | - | both subcarriers the clip's own (0.992, 0.991); sidebands -27.5 and -27.7 dBc | - |

The carrier sat 0.1-0.3 ppm from where it was tuned, both radios together,
which is the BB60D's own reference as before. At the same power F.405's
larger deviation and its pre-emphasis bought about 7 dB more picture than
FPV for 1.6 times the bandwidth, which is FM's whole trade in one line.
TVAdemo ran the transmitter on 4.3 cores with bars and 5.0 with the clip,
repeating a frame only while starting, and the no-radio test there held
the radio's 20 MS/s exactly with no repeats.

**And PAL**, the next morning over the same link at the same power, both
runs through the app's own flowgraph on its PAL format:

| | FPV, Chevrolet clip with sound | F.405 (625-line curve), colour bars |
|---|---|---|
| Carrier-to-noise in 20 MHz | 25.6 dB | 19.6 dB |
| Clicks | none in 75 frames | none |
| Frames decoded | 43 of 43 | 43 of 43 |
| Line rate | 15625.0 Hz | 15625.0 Hz |
| Sync-to-blanking step, against sent | +0.5% | +1.1% |
| Picture, p-p over rms across 5 MHz | - | 38.2 dB, colour bars within 0.036 |
| Sound | both subcarriers the clip's own (0.998); sidebands -27.5 and -27.6 dBc | - |

TVAdemo ran the PAL transmitter on 5.5 cores with the clip and 4.2 with
bars, repeating frames only while starting, and stopped it cleanly each
time; the no-radio test there held both formats at exactly the radio's rate.
The first analysis of the colour-bar capture failed in the alignment rather
than the link: off the air a 5 ms segment sits anywhere in a reference
several frames long, so its lag is far bigger than the segment, and a guard
written for software - skip any lag bigger than half the shorter signal -
skipped them all. It checks how much the two overlap now.

### FM Video Receiver

`fmVideoReceiver.py` is the other end of `fmVideoXmitter.py` and the other
side of its tile. It discriminates the carrier, takes the pre-emphasis back
out, decodes the composite into pictures and demodulates the sound off the
subcarriers riding above them. **Watch** hands the decoded pictures to
`ffplay` (or `mpv`), as the ATSC and NTSC receivers do; there is no
transport stream to pass on, so what goes across the pipe is raw frames.

**It is also a measuring instrument, which is why it was worth building
before the real FPV hardware arrived.** The FPV profile's 5 MHz deviation
and its "no pre-emphasis" are this project's guesses - neither RichWave
datasheet gives either - so a receiver pointed at a real FPV transmitter has
to be able to say what that transmitter actually does rather than assume the
guesses and show a picture that is quietly wrong. Everything under
**Measured** is read against levels the television standard fixes, so none
of it needs a test signal or any knowledge of what is being televised:

- **Video Deviation**, from the step between sync tip and blanking. That
  step is 40 IRE of 140, or 300 mV of 1000, whatever the picture is doing,
  so how big it comes back says how far the transmitter really swings the
  carrier for a volt. It does not depend on the pre-emphasis: both are flat
  parts of the signal, so the curve and its inverse cancel on them exactly.
- **Carrier Offset**, from where the sync tip landed, which is half the
  swing below the carrier.
- **Response at Subcarrier**, from the colour burst. Both standards make the
  burst exactly as big peak-to-peak as the sync-to-blanking step, so one is
  the path's gain at 3.58 or 4.43 MHz and the other its gain at DC: their
  ratio is the frequency response of everything in between, with no
  reference signal at all. 1.0 is flat and anything else is a lift that has
  not been undone - which is how an FPV module's own undocumented R/C
  pre-emphasis can be read off the air.

```sh
python scripts/test_fm_video_receive.py          # both standards, both formats
python scripts/test_fm_video_receive.py --quick  # FPV in NTSC, no sound
```

drives the app's own receiving blocks against the app's own transmitting
ones with no radio, and concentrates on those measurements rather than on
the picture alone.

**Getting the deviation wrong does not cost the picture. Getting the
pre-emphasis wrong does.** `CompositeDecoder` reads sync and blanking off
the signal and scales by the step between them, so a deviation setting that
is out by a factor simply rescales what it is handed - told half the real
deviation it decodes colour bars to the same 0.017 worst error. That is what
makes the instrument usable against a transmitter whose numbers nobody
knows. Pre-emphasis is the one that does not forgive: with F.405's curve on
the air and none taken out, the low frequencies arrive 10 dB down, which is
the sync pulses, and the picture will not decode at all.

**Verified off air**, the VSG60 on TVAdemo transmitting FPV colour bars in
NTSC on channel F4 (5800 MHz) at -9.5 dBm into the BB60D here at 60% and
20 MS/s, the app's own flowgraph run headless:

| | told the truth (5 MHz) | told 5 MHz, sending 8 |
|---|---|---|
| Status | Locked - picture decoding | Locked - picture decoding |
| Frames | 17.7-17.8 a second of 17.6, **0 dropped, 0 failed** | 17.8 a second, 0 dropped |
| BB60D overflows | 0 in 30 s | 0 |
| Carrier to noise | 23.2 dB in 20 MHz | 22.4 dB |
| Line rate | 15,734.3 Hz (0 to +2 ppm) | 15,734.2 Hz (-2 ppm) |
| **Video deviation** | **4.94-4.97 MHz p-p** of 5.00 sent | **8.01 MHz p-p** of 8.00 sent |
| **Carrier offset** | - | **+9 kHz (+1.5 ppm)** |
| **Response at 3.58 MHz** | -0.00 to +0.07 dB | -0.09 dB |
| Sound subcarriers | -27.7 to -28.2 dBc of -27.5 sent | - |

The second column is the one that matters: the receiver was told the FPV
profile's 5 MHz and the transmitter was swinging 8, and it read **8.01** -
which is the job it will have to do against a real FPV transmitter. Set to
PAL with NTSC on the air it said "This is NTSC - reopen with Format set to
NTSC", which is the other thing nothing on the air announces.

**And then against the real thing.** On 2026-09-16 an actual analog FPV
transmitter and camera were put on the bench, on channel A3 (5825 MHz),
into the BB60D at 60%. A sweep of 5645-5945 MHz found it first - centre of
mass 5824.83 MHz, 99% bandwidth 8.03 MHz, 24.2 dB carrier-to-noise in
20 MHz, no BB60D overflows - and then the receiver locked and decoded a
colour picture sharp enough to read a serial number off an instrument's
front panel. Over 60 seconds and 237 measured frames, with 1,059 pictures
decoded at 17.7 a second, **0 dropped, 0 failed and 0 overflows**:

| | the profile's guess | what it actually does |
|---|---|---|
| Video deviation | 5.0 MHz p-p | **7.93 MHz p-p**, spread 7.89-7.96 |
| Video pre-emphasis | none | **none** - burst +0.14 dB against DC, spread 0.08-0.18 |
| Sound subcarriers | 6.0 and 6.5 MHz at -27.5 dBc | **none sent at all** |
| Format | unknown until measured | **NTSC**, 15,734.52 Hz, +16.4 ppm |

Three things that came out of it:

- **The deviation was the guess that was wrong, and by 59%.** `FPV` in
  `fm_video_core` carries 7.93 MHz now. It is worth 4 dB of picture: the
  threshold table above moved from 42.8 dB at 30 dB carrier-to-noise to
  46.8, because the datasheet's figure was throwing that away.
- **The pre-emphasis guess was right**, and the burst reading is what says
  so - +0.14 dB with a spread of a tenth of a decibel, on a transmitter
  nobody has documented.
- **The receiver reported noise as sound, and that is now fixed.** The
  6.0 and 6.5 MHz chains read **-51.9 dBc and 30 kHz rms** - which reads as
  a subcarrier carrying loud programme - when the baseband above 4.25 MHz
  was in fact flat noise at -39.5 dB with no structure at either frequency.
  Both numbers were the empty band. A subcarrier weaker than
  `NO_SUBCARRIER_DBC` (-45 dBc) is reported as "nothing here" now and its
  deviation is not shown at all; and the "silent" threshold on one that
  *is* there went from 100 Hz to 2 kHz, because a real subcarrier 27 dB
  down measures 1.0-1.2 kHz rms of the demodulator's own noise on a 23 dB
  link with silence going out, so 100 Hz would never once have fired.

Its carrier sat **-399 kHz** from where it was tuned and wandered between
-222 and -521 kHz over the minute, which is a cheap VTX warming up and is
well outside anything the measurement's own precision could invent.

Six things worth knowing before changing it, five of them mistakes this made
first:

- **There is no local-oscillator offset, unlike the NTSC receiver.** That
  one tunes 6 MHz above its channel so the radio's own leakage falls outside
  a 6 MHz channel in a 20 MHz window. FM video has no such room: the signal
  is 9 to 15 MHz wide and the radio's 20 MS/s is all of it, so the carrier
  sits in the middle and the radio's DC lands on it. The BB60D centres its
  own IQ; a radio that does not would show it as a periodic distortion of
  the picture rather than as a spike in the spectrum.
- **The picture filter must not depend on the profile, because it is part of
  the instrument.** It has to be flat over the picture and *gone* by the
  lowest sound subcarrier - decimating to NTSC's 10 MS/s folds 6.0 MHz onto
  4.0, straight into the chroma, and PAL's own band reaches 5.0 MHz so there
  are 400 kHz to stop in. Letting the transition widen when the sound sat
  higher (F.405's is at 6.8) is cheaper and looks harmless: 21 taps instead
  of 35, still 34 dB down where the sound is. But a windowed sinc with a
  wide transition droops long before it, and that one read **0.68 dB low at
  the colour subcarrier** - so the receiver would have reported most of a
  decibel of its own filter as the transmitter's pre-emphasis. Fixed at
  6.0 MHz for every profile it is 0.008 dB. An FFT filter makes the sharp
  version affordable: 12x real time at 20 MS/s against a plain FIR's 8x.
- **The burst has to be windowed before it is averaged.** Mixing it down and
  taking the mean leaves a term at twice the subcarrier which only cancels
  over a whole number of cycles, and seven cycles of NTSC's subcarrier is
  19.56 samples at 10 MS/s. Rounded to 20, the leftover read a *perfect*
  loopback as 0.974 - a 0.23 dB lift that is not there. A Hann window puts
  it back to 1.0000 at 10, 12.5 and 20 MS/s in both standards.
- **The carrier offset has to be measured against the deviation just found,
  not the one the receiver was told.** The sync tip sits half the swing
  below the carrier, so its position carries both; taking the set deviation
  for the real one books the difference as tuning error. Off air against the
  transmitter swinging 8 MHz while the receiver expected 5, that read the
  carrier as **1.5 MHz off** when it was within a couple of kilohertz. Its
  precision follows the deviation's, though - 1% of a 5 MHz swing is
  25 kHz - so read it in tens of kilohertz, not in parts per million.
- **A click threshold has to be one a discriminator can actually reach.**
  Differencing phase cannot read further than half the sample rate, 10 MHz
  at 20 MS/s. Quoting the threshold against the *peak-to-peak* deviation
  rather than the peak puts it at 10.1 MHz for FPV, beyond that ceiling: the
  count then reads zero however badly the link is breaking up, and an empty
  channel and a perfect one look alike. Measured, that read **0 clicks a
  frame at 6 dB carrier-to-noise** where there should have been thousands.
  `click_threshold_hz` in `fm_video_core` is now the one definition, shared
  with the transmitter's own test, and the margin is 3 MHz where there is
  room and halfway to the ceiling where there is not - F.405 swings 5.4 of
  the 10 available and needs the second. With it right, 3,622 clicks a frame
  at 6 dB, against the 3,588 the transmit test measures independently.
- **The link statistics must not be a Python block at the radio's rate.**
  Carrier-to-noise and clicks were one `gr.sync_block` reading the RF and
  the discriminator at 20 MS/s. It worked, and it held the interpreter lock
  that the frame decoder - also Python, on its own thread - needs to get a
  picture out. Measured at the radio's own pace: without it, every frame the
  buffer allows and none dropped; with it, **7 buffers of 70 dropped in NTSC
  and 13 of 58 in PAL**. Squaring the envelope, keeping one sample in eight,
  rectifying and comparing are C++ blocks now, and what reaches Python is
  three streams at 100 S/s. Flat out that took the chain from 1.21x real
  time to 3.01x.

Carrier-to-noise is the number FM lives by, because FM has a threshold, and
it comes from the second and fourth moments of the envelope - for a carrier
of power `c` in complex noise, `m4 = 2 m2^2 - c^2`. Against known noise it
reads within 0.01 dB at 30, 20, 12 and 6 dB. **No carrier at all is not a
low carrier-to-noise**: pure noise satisfies `m4 = 2 m2^2` exactly, so the
carrier term comes out zero rather than small and there is no ratio to
quote. Every sample of noise is also a phase jump, so the click count on an
empty channel is the sample rate - 190,012 a frame, measured - which is
arithmetic rather than information. The readout says "no carrier" and leaves
the clicks blank instead.

The window shows the **RF spectrum** on the transmitter's own span and
centre, so the two can be read side by side; the **recovered baseband**,
which the transmitter has no equivalent of and which is where an unknown
transmitter's sound subcarriers appear at whatever frequency they really
are; and the **composite** itself. At the radio's rate with no displays the
chain costs 2.6 cores of the eight in NTSC and 3.4 in PAL, and decodes every
frame the buffer allows.

**The frame decoder is shared with the NTSC receiver**, as
`CompositeFrameSink` - the same threaded decode, drop-rather-than-fall-
behind buffer and non-blocking player pipe, with the video standard as a
parameter so it does PAL too. Its `measure()` hook is where the numbers
above are taken, with the sync pulses already found.

### Where the windows come back

Three windows remember where they were left, and all three keep it the same
way: plain `x`, `y`, `width`, `height` in JSON, applied size-first, and only
when the saved position would land somewhere still reachable
(`geometry_is_reachable` in `apps/utils.py`, which looks across every
screen rather than just the primary one).

**The launcher also remembers being maximized**, as `"maximized": true`
beside the other four - which then hold its *normal* geometry, from Qt's
`normalGeometry()`, so un-maximizing after a restart gives back the size it
had. Saved as `pos()` and `size()` while maximized, as it used to be, they
held the whole screen instead. Two things about it:

- **On GNOME a window cannot be maximized before it is on screen.** Set on
  the hidden window, the state never reaches the window manager: Qt reports
  the window maximized, GNOME maps it at its normal size, and a moment later
  Qt agrees with GNOME. Qt's own `showMaximized()` fails the same way,
  measured. So `load_window_position` places the window at its normal
  geometry and `showEvent` asks for maximized once it is up - which costs a
  glimpse of the normal-sized window first. The same path serves single
  mode, where the launcher is hidden while an app runs and shown again.
- **The Windows side has not been seen working.** Everything started over
  SSH on the laptop runs in session 0, where Windows reports no window as
  visible, and Qt only asks Windows to maximize a window it believes is
  visible - so nothing there can be maximized from inside, whatever the
  code does. On a real desktop the request is the same `ShowWindow` a click
  on the maximize button makes. Verified on GNOME, through the window
  manager rather than through Qt: maximized, closed, reopened maximized,
  restored to exactly the geometry it had, and through single mode's hide
  and show, with no drift.

| Window | Where it is kept |
|--------|------------------|
| The launcher | `window_position` in `config/window_settings.json` |
| An app's config dialog | `dialog_position` in `config/<module>_config.json` |
| An app's flowgraph window | `flowgraph_position`, in that same per-app file |

**The flowgraph's was the one that did not work, and it looked like it was
never being saved.** Every app already calls Qt's own
`saveGeometry`/`restoreGeometry` against `QSettings("GNU Radio", <app>)`,
and the *saving* half works - the stored blobs hold real geometries, 1782
x1161 at (215, 258) and so on. Two things stopped them coming back:

- **Qt 5 refuses to restore at all when the screen has changed size.**
  `restoreGeometry` compares the screen width the blob was saved on against
  the current one and returns false, restoring nothing, if they differ by
  more than a quarter. The blobs here were written on screens 2880 and 3840
  wide - a laptop with an external monitor does that every time it is
  plugged in - so 3840/2880 = 1.33 tripped it.
- **It runs before the window exists.** Each app calls it at the top of its
  `__init__`, which is the GRC-generated idiom, and then builds every
  control, box and plot afterwards. The layout can overrule the restored
  size once the widgets are in.

So the geometry is applied *after* `main()` has shown the window, by
whichever launcher started it - `RFbenchToolkit.py` for the desktop
grid, `apps/_run.py` for the browser - and saved from the close-event
wrapper the launcher already installs, read before the app's own
`closeEvent` stops the flowgraph. **No app needed changing**, and each
keeps its `QSettings` calls, which is what an app run directly still uses.

The saved size is clamped to the current screen but the position is not:
a window deliberately parked against an edge, or on a second monitor,
should come back there.

**Where each of them goes the first time, before anything is saved:**

- The launcher **works out its own size** (`natural_size`): wide enough
  for the widest bank's five tiles in one row at `PREFERRED_TILE`, 185 px,
  and exactly tall enough for every bank - which on this machine is
  **997x826**, centred on the primary screen at (941, 397) on a 2880x1620
  display. The width is arithmetic; the height is *measured*, by laying
  the grid out at that width and asking the column how tall it came out,
  because it depends on how tall the machine sets a line of text. A size
  written down by hand, 1000x820, fitted here by 2 px and would have
  scrolled on any machine whose fonts run a pixel taller; measured, it is
  right wherever it runs - make the type a pixel taller and it picks 835,
  four pixels and the captions wrap and it picks 928, with nothing to
  scroll and 2 px less scrolling every time. It is then clamped to the
  screen's *available* geometry, so a 1366x768 laptop, which cannot show
  all three banks, gets as much as fits and a scroll bar rather than a
  window partly under the panel. Before any of this there was no default
  at all: with no `window_position` it fell back to its 800x600
  *minimum*, which wrapped the first bank onto two rows on a screen with
  room to spare.
- A config dialog opens **in the middle of the launcher**, which is where
  the eye already is, having just clicked a tile. It used to be the
  launcher's top-left corner plus fifty pixels, which on a wide window put
  it well off to one side of what was clicked. `centre_on` in
  `apps/utils.py` does it, and has to `adjustSize()` first: the dialog has
  not been shown yet, so its size must be asked for rather than read.
  It clamps into the screen the launcher is on, because a launcher parked
  against an edge would otherwise centre part of the dialog off it -
  measured, a launcher at (2600, 1300) on a 2880x1620 screen wants a
  centre of (3099, 1739) and the dialog is pulled back to (2497, 1111).
- The settings dialog needs none of this: it is built with `parent=self`,
  so Qt centres it on the launcher already. The config dialogs cannot be,
  because each app's `ConfigDialog()` takes no parent - which is why Qt
  would otherwise drop them in the middle of the *screen*, nowhere near
  the launcher on a wide desktop.

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
  four borders as a rectangle. So they are images - `icons/spin-up.png`,
  `icons/spin-down.png`, which the combo boxes use for their own arrow
  too, and `icons/check.png` for a ticked box - referenced through
  `icon_url()` by absolute path: a stylesheet resolves `url()` against the
  process's working directory, and forward slashes are required on Windows
  because a backslash is an escape to the stylesheet parser.

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
covers what they cannot - that `linux/start_app.sh` starts, that a button press
reaches `launch_application`, that the dialog accepts, that the flowgraph
window appears, and that closing it brings the launcher back - by driving real
X input through xdotool (`apt install xdotool`):

```sh
python scripts/test_launcher_gui.py "FM + RDS Receiver"
python scripts/test_launcher_gui.py "FM + RDS Transmitter" --hold 30
python scripts/test_launcher_gui.py "ATSC Video Receiver"
```

`scripts/test_app_close.py` checks the last of those for every app at once,
with no radio, no display and no launcher to close first. It calls each
app's real `main()` the way `launch_application` does, with a stand-in
window for the flowgraph, closes the window, and requires the launcher to be
visible again with its event loop still running. The ATSC transmitter failed
it (see its notes); nothing else did.

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
  drive the one `linux/start_app.sh` starts. `RADIO_DIRECTIONS` comes out the
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

### Web launcher (a second front end)

`web/server.py` serves the grid, the settings and the icons to a browser and
starts each app as its own process. The flowgraph and its configuration
dialog are the ones that already exist, unchanged: this is a second front end
onto the same `APP_TILES` table and the same `window_settings.json`, not a
replacement, and `RFbenchToolkit.py` is untouched. Run either, or both.

```sh
conda activate gnu
python web/server.py                 # http://127.0.0.1:8730
python web/server.py --host 0.0.0.0  # prints a URL with a token in it
```

| File | Does |
|------|------|
| `web/server.py` | Serves the page, its icons and its fonts, reads and writes the settings file, starts and stops apps. Imports no GNU Radio, no Qt, no SoapySDR. |
| `web/index.html` | The page: grid, settings, and what is running. |
| `apps/theme.py` | The palette, the type scale and the faces, for both front ends. Stdlib only, which is why the server may import it. |
| `apps/_run.py` | Runs one app module with its own Qt event loop. |
| `scripts/probe_radio.py` | Asks whether a radio is there, in a process that then exits. |
| `web/prototype/index.html` | A mockup of a browser *panel* for a running app, drawn from simulated AM. Nothing behind it - it is the design reference for that step, not part of the launcher. |

The window opens on the display the **server** can reach, not in the browser,
so start the server from the desktop session that owns the screen and it
inherits `DISPLAY` and `XAUTHORITY`. That makes the useful shape phone as the
control surface, bench monitor as the display - it is not remote operation.
The page says so plainly when `DISPLAY` is missing rather than launching apps
into nothing. On Windows this is the session-0 problem already described
under [Running on Windows](#running-on-windows).

Things worth knowing before changing it:

- **The server must never open a radio.** `launch_application` enumerates the
  HackRF before launching, and the process that asks keeps a USB handle
  afterwards - which is why a launcher sitting on a config dialog already
  makes the app that follows fail with `Device::make() no match`. The desktop
  launcher gets away with it because it is the same process that goes on to
  build the flowgraph. A server that lives for days would hold that handle
  for days and break every launch after the first. So every presence check -
  HackRF, BB60D, VSG - runs in `scripts/probe_radio.py`, a process that exits
  and takes its handles with it. Its refusals repeat the desktop launcher's
  wording so both front ends say the same thing.
- **`apps/_run.py` exists because a module cannot run itself.** Each app's
  `main()` ends `if app.instance(): return tb else: return app.exec_()`,
  which is the launcher contract above - the launcher already owns a
  QApplication and its loop. But `app.instance()` is truthy the moment a
  QApplication exists, so a module run directly takes that same branch: it
  builds the flowgraph, shows the window, returns, and the window never gets
  an event loop. `_run.py` is the piece the desktop launcher usually
  supplies. It also does the `XInitThreads()` each app's own `__main__` block
  does, since importing a module skips that block.
- **Single mode means something different here.** The desktop launcher hides
  its window while an app runs and shows it again on close, which a browser
  cannot do. The server holds the processes instead, so the page lists what
  is running with a Stop button - something the desktop launcher cannot do -
  and single mode is an enforced one-at-a-time rather than an implicit one.
  Stop is `terminate`, and **that is not yet enough to stop an app started
  through `apps/_run.py`.** Every app installs a `SIGTERM` handler in its
  `main()`, and run under `_run.py` on TVAdemo the FM video transmitter
  ignored both `SIGTERM` and `SIGINT`: five minutes after the first one it
  was still on the air on 419% of a core across 53 threads, its main thread
  parked in Qt's poll, and only `SIGKILL` ended it - on two separate runs.
  **It is not that app.** The NTSC transmitter, launched the same way for
  the receiver's off-air re-test, did exactly the same thing: still on the
  air six seconds after `SIGTERM`, 479% of a core across 61 threads, gone
  on `SIGKILL`. So whatever swallows the signal is in the shared path -
  `_run.py`, the app contract's `main()`, or Qt - and not in one
  flowgraph.
  It is *not* the obvious cause: each `main()` starts a 500 ms timer so the
  interpreter gets control to run the handler, and then returns, dropping
  the only reference to it - but a stripped-down reproduction with the timer
  collected still took `SIGTERM` immediately, so something else is
  swallowing it. Until this is found, the browser's Stop button should be
  assumed not to stop an app, and anything launched through `_run.py` by
  hand needs its PID. A killed transmitter leaves `config/.vsg60.lock`
  behind, and that is only harmless because the lock is keyed by a PID and a
  dead one is treated as stale.
- **Loopback is open, wider is not.** Sitting at the machine is already the
  permission, so `127.0.0.1` needs no token. `--host` anything else mints one
  and puts it in the printed URL. Every tile keys a transmitter and 0 % power
  is not off, so treat that URL as the key it is.
- **The grid is `APP_TILES`, read with `ast`.** The server never imports the
  launcher - that would open a window and pull in PyQt5. It reads the table
  out of the source the same way `scripts/test_launcher_gui.py` does and for
  the same reason, so keep `APP_TILES` a plain literal and all three keep
  working.
- **Settings are merged, not replaced.** `window_position`, `dialog_position`
  and the tile-face state the desktop app keeps in the same file all survive
  being edited from a browser. Which side a tile is showing is per-viewer
  here, in `localStorage`, rather than fought over in the shared file.

Exercised so far: the tile table parsing, the settings round trip and its
merge, every launch refusal (wrong direction, single mode, unknown module,
radio absent), spawn, the running list, reaping, Stop, and the token. All of
it against a stubbed interpreter, because it was written on a machine without
the `gnu` environment. **Not yet exercised: the assumption the whole design
rests on**, that the probe subprocess releases the USB handle in time for
the app that follows - neither machine here has a HackRF, which is the radio
that trap belongs to.

`apps/_run.py` itself has now run a real app against a real radio: it
started the FM video transmitter on TVAdemo's VSG60 from a `--config` file,
headless, and transmitted correctly - see the Stop note above for the one
thing that did not work. `scripts/test_app_close.py` used to fail on
`_run.py`, which lives in `apps/` and has a `main()` of its own; it skips
names beginning with an underscore now, since a leading underscore there
means a helper rather than an app.

The per-app configuration dialogs are still Qt, and appear on the server's
display like the flowgraph does. Moving them into the browser needs no app
edits: `apps/_run.py` already takes `--config values.json` and skips the
dialog when given one. What it needs is a parameter manifest per app, which
would also retire the duplication where a range is stated once in
`ConfigDialog` and again in the flowgraph's `RangeWidget`.

### One design, two front ends

The desktop launcher and the browser page are meant to look like one
program, and for a while they did not: the page was drawn to a design and
the launcher kept the grey stylesheet it had always had. So the palette,
the type scale and the faces live in **`apps/theme.py`** and both sides
read them - `apply_launcher_theme` and `apply_dark_theme` take Qt style
sheets from it, and `web/server.py` generates `/theme.css` from the same
`TOKENS` and the page links that instead of declaring its own `:root`.
Edit a colour there and both front ends move.

`apps/theme.py` **imports nothing but the standard library at module
level**, which is what lets the server import it: everything else in
`apps/` pulls GNU Radio or Qt, and a web server must have neither. It is
the one import the server makes from `apps/`; the tile tables it still
reads out of the launcher's *source* with `ast`, as before.

```sh
python scripts/test_theme.py    # no radio, no display, no GNU Radio
```

checks that every `var()` the page uses is a name `/theme.css` defines,
that the page asks nothing of the network, that neither Qt stylesheet has
an unsubstituted token, that the six faces and their licence are in
`fonts/`, and that every row of tiles has a heading. That is the check
that stops the two drifting, which is the whole point of the arrangement.

**A Qt stylesheet is not CSS, and four of the things the page does have no
QSS equivalent at all.** They are done to the pixels instead, in
`RFbenchToolkit.py`:

| The page says | Qt has no such thing, so |
|---|---|
| `--ground` and the rest of `:root` | Python formats the tokens into the sheet, the way `icon_url()` already got absolute paths into a `url()` |
| `object-fit: cover` with `filter: saturate(.82)` | `cover_pixmap()` crops each icon to 4:3 about its middle and pulls the colour back, once, with PIL and numpy |
| `letter-spacing` on the TRANSMIT/RECEIVE line | `token_font()`, because only a QFont has it |
| `.bank-name::after`, the hairline running off the heading | a `QFrame` in the row - Qt's `::` are sub-controls of a known widget, not pseudo-elements anyone can invent |

A fifth, `opacity` on a tile the radio cannot run, was already solved: the
picture is dimmed by the painter in `_draw` and the caption by the
stylesheet's own `:disabled` colours, because the two caption labels carry
an opacity effect each for the flip and effects do not nest predictably.

**The grid wraps now**, which is the page's
`repeat(auto-fill, minmax(150px, 1fr))` done by hand in `_relayout` -
a stylesheet does no layout at all. Tiles are at least 150 px wide, as
many to a row as fit, inside a column capped at 1080 and centred in the
window, as the page's `max-width: 1080px; margin: 0 auto` does for both
the rail's contents and the body (`centred_column`). Without the centring
a maximised launcher kept its tiles in the leftmost 1080 px while the
rail and the bank hairlines ran on across the whole screen.

**It never makes more columns than the widest bank has tiles**, which is
five. A sixth column could only ever be empty, and it arrived right at
the default width: 980 px of window gave five tiles of 181, 1000 gave six
of 153 - three pixels off the minimum, the sixth slot holding nothing in
any bank. Capped, a wider window widens the five instead, until the
column reaches 1080 and they stop at 208. Measured: four columns below
about 840 px of window, five from there to a full 1920, and at the
launcher's own size five of 185 with nothing to scroll. The cap is read off
`APP_TILES` rather than written down as 5, so a bank that gains a sixth
tile gets a sixth column. Two more things worth knowing:

- **Watch the scroll area's viewport, not the window.** The viewport
  changes width without the window being resized - the scroll bar
  appearing is enough - so a `resizeEvent` on the window alone left the
  grid laid out for whatever width it had before it was first shown: six
  columns of room, three columns of tiles, measured. It is an event filter
  on `viewport()` instead.
- **`scripts/test_launcher_gui.py` finds tiles as bright blobs**, and a
  wrapped bank puts one row of tiles on two rows of blobs, after which
  every click lands on the wrong tile. It compares the blob rows against
  `APP_TILES` now and says the window is too narrow, rather than failing
  several steps later like a broken button. The size window it accepts
  also had to come down: a picture is 4:3 rather than a 200 px square, and
  as short as 111 px at the width where a fifth column has only just
  fitted.

Two smaller traps, both found by looking at a screenshot:

- **A child widget paints its own background over its parent's border.**
  The rail's `border-bottom` came out interrupted under the wordmark, and
  would have vanished under the centred column its contents now sit in,
  so everything inside `#rail` is transparent.
- **A QFont sizes in points and a stylesheet in pixels.** A font built the
  obvious way from a token meant for QSS comes out about a third too big
  on a 96 dpi screen; `token_font()` calls `setPixelSize`.
- **A layout does not know a stylesheet drew a border.** The tile's layout
  began at the button's edge, so its picture sat on the 1 px border at the
  top and left and left a strip of panel before the one on the right. The
  layout is inset by 1 px all round.

Three more, all found making the launcher measure its own height before
it is shown - each one made it come out at its 600 px minimum:

- **A QPushButton ignores the layout it holds.** It sizes itself from its
  own text and icon, and a tile has neither, so its size hint was a small
  empty button. On screen that never showed, because showing a window
  activates each layout and pushes the real size on as a minimum - too
  late to measure from. `FlipTile.sizeHint` returns its layout's.
- **Qt invalidates a layout by posting an event.** Before the event loop
  has run, the outer widget answers from its cache: 143x196 for a page
  really 997x766. `natural_size` asks the column's own layout.
- **A stylesheet's type sizes arrive when a widget is polished**, which is
  otherwise on first show; `ensurePolished()` first, or every label is
  measured in the default font.

The launcher also gained a **header rail** - wordmark, the radio Settings
has chosen, and the gear - and a **scroll area**, which it badly needed:
the old grid had none, so on a 768-high laptop the video row sat below the
bottom edge with no way to reach it. The gear is the page's own SVG of
three faders, rendered through QtSvg, which retired twenty lines of PIL
that brightened a photograph of a cog and keyed its background out.

The one part of the browser page deliberately **not** carried across is the
ON AIR panel. That is not paint, it is a running-apps list the desktop
launcher has never kept - and in single mode it hides itself while an app
runs, so there would be nothing to show it to.

### The typefaces

`fonts/` holds Barlow and Barlow Semi Condensed as six static TTFs, beside
the SIL OFL they are licensed under. They are *vendored* rather than
installed, for the same reason `vendor/libvsg_api.so.1` is: Google Fonts is
only where Barlow happens to ship.

- **There is no apt package.** `fonts-barlow` is not in the Ubuntu archive
  at all, and an apt install would only ever fix one of the three machines
  anyway - the Windows laptop has no apt, and TVAdemo has no git and is kept
  in step by copying files. A system font install is a per-machine step that
  nothing checks, and a missing face does not raise: the app renders in
  something else, which is the kind of wrongness only ever found by looking
  at the screen.
- **The browser front end serves them itself**, from a `/fonts/` route in
  `web/server.py` with the same containment check as the icons, so the page
  needs no network. It used to link `fonts.googleapis.com`, which on a bench
  with no connection falls back to Helvetica without a word - and the two
  front ends then stop matching for a reason nobody would guess.
  `web/prototype/index.html` refers to them relatively, since that mockup is
  opened as a file rather than served. Nothing else in the tree reaches the
  network at run time: the two URLs left in `windows/bootstrap.ps1`
  are for installing Windows from scratch.
- **Qt loads them with `QFontDatabase.addApplicationFont`**, so the desktop
  side needs no system install either and both platforms render the same.
- **Qt clamps to the heaviest face shipped rather than synthesising one.**
  Asking for weight 700 in Barlow measures exactly what 600 does, because
  SemiBold is the heaviest of the three cut here; a synthesiser would have
  smeared it wider. So asking for a weight the set does not carry is not an
  error and does not look like one - it is silently the nearest that is
  there.
- **The whole directory travels together.** The OFL requires the licence
  alongside the fonts wherever they are passed on, which is the same rule
  `media/VIDEO-CREDITS.txt` follows for the CC BY clips: copying `fonts/` to
  TVAdemo means copying `OFL.txt` with it.

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
saying `GetIQ: ADC overflow`. `bb60_source` counts those, and the receiver
shows "Input overloaded — turn the RF gain down" instead of it scrolling
past in a terminal. It also drops the module's `ConfigureIQCenter` /
`ConfigureIO` / `Using format` chatter, which is harmless and otherwise
prints several lines per retune.

**A SoapySDR log handler does not catch any of it, and this said it did.**
`SoapySDR.registerLogHandler` works - a message logged from Python arrives
- and `install_log_handler` now registers through the C API on *every*
copy of the library in the process, because there are two: the BB60 module
is a system module linking `/lib/x86_64-linux-gnu/libSoapySDR.so.0.8`
(318 kB) while the conda binding carries its own (629 kB). A message logged
through either copy's own C API reaches the handler, both checked. And yet
during a real open and two retunes the handler was called **zero times**
while the module printed fifteen lines, whose `[INFO] %s` formatting comes
out of libSoapySDR's *default* handler - so the module does log through the
library, and the level is consulted somewhere the handler is not
(`SoapySDR_setLogLevel(FATAL)` silences it completely, and so does
`SOAPY_SDR_LOG_LEVEL=fatal`).

That cost more than a tidy terminal. `adc_overflows` counted only what the
handler saw, so it stayed at zero however hard the front end was driven and
the ATSC receiver's "Input overloaded" could never fire. Raising the log
level would have hidden the overflow line too, since it is at the same
level as the chatter. So `_DriverOutput` takes file descriptor 2 for as
long as a BB60 is streaming, drops the chatter, counts the overflows and
passes everything else — GNU Radio's warnings, Python's tracebacks —
straight through to the real stderr. Verified: fifteen chatter lines to
none, `GetIQ: ADC overflow` counted with its text kept, an unrecognised
error passed through, and stderr restored when the last source stops.
**The separate `overflows` counter, for samples actually lost, comes from
`readStream`'s return code and was never affected** — the off-air figures
quoted in this file are that one.

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

- **Check where its media folder actually is before copying anything
  there.** `config/window_settings.json` is per-machine and is *not* one of
  the files kept in step, so `media_directory` can differ; it has been
  `/home/user/Documents` and is now `/data/python/media`, the same as here.
  Read the file, do not assume. Anything CC BY goes with its credits -
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
- **Put a timeout on anything run there that could hang.** A test run over
  SSH with its output filtered through `grep` shows nothing until it exits,
  so a hang looks exactly like a slow run: the FM video test hung there on a
  PAL frame-boundary fault (see [PAL](#pal-625-lines)) and ran for ten hours
  with three threads spinning, holding up the off-air job waiting behind
  it. `timeout` on the remote command turns that into a failure within
  minutes.
- **Launch the transmitter and start the receiver as two commands.** A job
  put in the background inside an SSH command can hold that command open
  until the job ends: with `setsid nohup bash -ic ... > log 2>&1 < /dev/null
  &`, a 20-second job kept `ssh` from returning for 20.7 s. A script that
  launches the transmitter that way and then starts the receiver begins
  listening *after* the transmission is over. Four runs like that read the
  BB60D's bare noise floor, the known-good test pattern included - which
  looks exactly like a disconnected antenna, and was reported as one. The
  two logs gave it away: the transmitter off air at 17:48:26, the first
  reading here at 17:48:31, with the clocks agreeing to 0.3 s. Start the
  transmitter as its own backgrounded command and have the receiver wait on
  its log.
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
powershell -ExecutionPolicy Bypass -File .\windows\bootstrap.ps1
powershell -ExecutionPolicy Bypass -File .\windows\start_app.ps1
```

`windows/bootstrap.ps1` installs Miniforge if there is no conda, builds the
`gnu` environment, then verifies that gnuradio, qtgui, soapy, PyQt5 and
SoapySDR import, reports how many radios Soapy sees, and says whether
ffmpeg is there. It is idempotent -
re-run it after a pull and it updates in place.

- **`linux/environment.yml` cannot solve on Windows at all.** It is a full Linux
  solve: every package pinned to a `linux-64` build string, with `alsa-lib`,
  `pulseaudio-client` and `libgcc` in the list. `windows/environment.yml` names
  only what the code imports and lets conda choose builds, which is also why it
  needs no edit when conda-forge rolls a build number.
- **Activate; do not call the environment's `python.exe` directly.** GNU
  Radio's DLLs live in `envs\gnu\Library\bin`, which only activation puts on
  PATH. Without it the import dies with a bare `DLL load failed` that names
  nothing useful. `windows/start_app.ps1` goes through the conda *shell hook*, so it
  works without `conda init` having been run.
- `windows/start_app.ps1` also has to `Set-Location` to the repo root, one
  above its own folder, for the same reason `linux/start_app.sh` does its
  `cd ..`: the launcher opens `icons/settings.png` and `config/` by relative
  path.
- **ffmpeg comes from `windows/environment.yml` unpinned, and a new major
  version broke the ATSC transmitter.** The laptop had none at all until
  2026-09-18, so its video transmitters offered colour bars and nothing
  else. conda-forge then gave it 9.0.1, where Linux pins 7.1.1 - and 9
  removed `-top`, the option `apps/atsc_source.py` set top field first
  with. ffmpeg refuses the whole command over one unknown option, so every
  clip without its own `.ts` ended before a byte came out:
  `test_atsc_loopback.py` reported "receiver produced nothing" in one
  second. `setfield=tff` at the end of the filter chain does the same job
  on both - byte-identical to `-top 1` on 7.1.1, and 99.57% byte-perfect
  through the loopback on 9.0.1. The NTSC and FM video transmitters
  decode clips through ffmpeg too, and passed on 9.0.1 as they were. So a
  new ffmpeg arriving on one machine is worth a loopback run before it is
  trusted.
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
3. Add a row to `APP_TILES` in `RFbenchToolkit.py`, saying whether the
   app transmits or receives. To give an existing app a second side instead
   of a square of its own - a receiver for a transmitter, say - add a face
   to that tile's list rather than a row. The direction is all the grid
   needs to dim it, flip it and refuse it on the wrong radio. Both front ends and
   `scripts/test_launcher_gui.py` read that one table, so a row added there
   appears in all three.

## Environment

- Conda environment name: `gnu` (defined in `linux/environment.yml`, prefix: `/home/user/miniconda3/envs/gnu`; on Windows `windows/environment.yml`)
- Python 3.12, GNU Radio 3.10.12, PyQt5 5.15, UHD 4.8
- `linux/start_app.sh` activates `gnu` from `~/miniconda3`; edit its `source` line if conda lives elsewhere.
