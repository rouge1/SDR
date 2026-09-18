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
[Running on Windows](devnotes/machines.md#running-on-windows) and [where things
live](#where-things-live-linux-and-windows).

There is also a browser front end onto the same grid and the same settings,
which starts the same apps as separate processes - see
[Web launcher](devnotes/web.md#web-launcher-a-second-front-end):

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

## Where the details are: `devnotes/`

This file is read at the start of every session, so it keeps only what
applies everywhere. What each app, radio and front end has taught - the
measurements, the traps, and why the code is the way it is - is in
`devnotes/`, one file per subject, read when that subject comes up.
**Before changing an app, read its file.** Much of it was found the hard
way, and several of the fixes look like mistakes until you know what they
fixed.

| Notes | Read before touching | What is in them |
|---|---|---|
| [rds.md](devnotes/rds.md) | `rdsReceiver`, `fmRdsTransmitter`, `rds_core`, `rds_encode` | decoding RDS through errors, RadioText and RT+, the clock, stereo and channel separation, Next Track |
| [atsc.md](devnotes/atsc.md) | `atscXmitter`, `atscReceiver`, `atsc_source`, `atsc_rx_core` | 8VSB on the air, AFC, MER, Watch and Record - and why the analog receivers' Watch writes from a thread of its own |
| [ntsc.md](devnotes/ntsc.md) | `ntsc_encode`, `ntsc_decode`, `ntsc_source`, `ntscAnalogVideoRecorded`, `ntscReceiver` | composite video to SMPTE 170M and PAL to BT.1700, video sources, the NTSC transmitter and receiver, and measuring their sound |
| [fm-video.md](devnotes/fm-video.md) | `fmVideoXmitter`, `fmVideoReceiver`, `fm_video_core` | the FPV and F.405 profiles, the receiver as a measuring instrument, and a real FPV transmitter measured |
| [media.md](devnotes/media.md) | `media`, `audio_file`, any file picker | how media is found, MP3, song tags, and plain-ASCII RDS text |
| [radios.md](devnotes/radios.md) | `vsg_sink`, `bb60_source` | the VSG60's and the BB60D's limits, locks, gain and traps |
| [ui.md](devnotes/ui.md) | `RFbenchToolkit.py`, `apps/theme.py`, the window and dialog code in `apps/utils.py`, `settings_dialog` | flip tiles, where windows come back, dialog layout, the one theme for launcher, dialogs and flowgraph windows, the fonts, and the end-to-end GUI test |
| [web.md](devnotes/web.md) | `web/`, `apps/_run.py`, `scripts/probe_radio.py` | the browser front end, and the Stop that does not stop |
| [machines.md](devnotes/machines.md) | `windows/`, anything run on TVAdemo or the Windows laptop | TVAdemo, and running on Windows |

Something learned goes into its subject's file. If it could bite anywhere,
it also gets a line below.

## Rules that bite

The few things, from all of `devnotes/`, that crash, break silently or
damage something. Each links to the why.

- **Opening a VSG60 twice aborts the process**, and its library is not
  thread safe. Go through `vsg_sink`, whose lock and PID file exist for
  exactly this. [radios](devnotes/radios.md#vsg60-notes)
- **A VSG60 and a BB60D will not stream at the same time on one host.**
  Anything that needs one of each puts the transmitter on TVAdemo.
  [radios](devnotes/radios.md#vsg60-notes)
- **0 % power is not off.** A HackRF at its minimum still decoded at 100 %
  several feet away. [rds](devnotes/rds.md#fm--rds-transmitter)
- **Keep a Python reference to every Python block** in a running flowgraph,
  or the process segfaults with no Python frame to say why.
  [rds](devnotes/rds.md#fm--rds-transmitter)
- **Never rebuild a running flowgraph to change what it plays** - Next Track
  swaps files in place, because a rebuild jumps the pilot and RDS phase.
  Anything that must lock one on a VSG60 wraps it in `sink.held_open()`.
  [rds](devnotes/rds.md#fm--rds-transmitter),
  [radios](devnotes/radios.md#vsg60-notes)
- **A HackRF's receive gain goes on after `tb.start()`**: SoapyHackRF
  ignores the AMP stage before it. [rds](devnotes/rds.md#rds-receiver)
- **Hand `file_descriptor_source` an `os.dup()` of a pipe**, never the
  pipe's own descriptor, or the second launch of the app goes out silent.
  [ntsc](devnotes/ntsc.md#ntsc-video-sources)
- **The BB60D is not driven through gr-soapy**: `setupStream` comes before
  any setting, and it is opened by driver name alone.
  [radios](devnotes/radios.md#signal-hound-bb60d-as-a-receiver)
- **A spectrum average cannot see a transmitter that is off half the
  time.** Look at the envelope in time. [atsc](devnotes/atsc.md#atsc-transmitter)
- **Close any running launcher before a radio test**: it holds the HackRF's
  USB handle even while sitting on a config dialog.
  [ui](devnotes/ui.md#testing-the-launcher-end-to-end)
- **Tests never write `config/` or the user's `QSettings`**: patch
  `read_settings`, use a throwaway folder, and never close an app's window -
  its `closeEvent` saves.
  [ui](devnotes/ui.md#how-every-dialog-gets-laid-out),
  [ui](devnotes/ui.md#the-flowgraph-windows-wear-it-too)
- **`apply_flowgraph_theme(self)` comes first in a flowgraph's `__init__`**,
  and no flowgraph stylesheet sets a font on `QWidget` or `QLabel`.
  [ui](devnotes/ui.md#the-flowgraph-windows-wear-it-too)
- **`APP_TILES` stays a plain literal, and `apps/theme.py` imports only the
  standard library**: the web server reads both without importing Qt, and
  the GUI test reads `APP_TILES` with `ast`.
  [web](devnotes/web.md#web-launcher-a-second-front-end),
  [ui](devnotes/ui.md#one-design-two-front-ends)
- **Anything run on TVAdemo gets a `timeout`**, and a transmitter and its
  receiver are started as two separate commands.
  [machines](devnotes/machines.md#the-tvademo-laptop-and-why-there-is-a-second-machine)
- **On a conda machine, `which ffmpeg` finding nothing proves nothing** - it
  is inside the environment.
  [machines](devnotes/machines.md#the-tvademo-laptop-and-why-there-is-a-second-machine)
- **On Windows, activate the `gnu` environment; never call its `python.exe`
  directly** (`DLL load failed`). A GUI started there over SSH runs in
  session 0 and cannot be seen. [machines](devnotes/machines.md#running-on-windows)
- **An app started through `apps/_run.py` ignores SIGTERM**, still
  unsolved, so the browser's Stop does not stop it.
  [web](devnotes/web.md#web-launcher-a-second-front-end)
- **This repository is public.** No IP address, key name or account name of
  a bench machine goes into it; the notes use ssh aliases such as
  `ssh tvademo`.

## Architecture

This is a **PyQt5 launcher** for GNU Radio signal generation/transmission applications. The launcher presents a grid of buttons, each opening a config dialog before launching a GNU Radio flowgraph.

### Launch Flow

1. `RFbenchToolkit.py` — Main window (class `RFbenchToolkit`). Dynamically imports app modules from `apps/` using `importlib`.
2. When a button is clicked → `launch_application(module_name)` instantiates the module's `ConfigDialog` → user configures parameters → on OK, calls `module.main(app=..., config_values=...)`.
3. In **single mode**: launcher hides itself while the app runs, then shows again when the app closes. In **multi mode**: launcher stays visible.

### App Module Contract

Every module in `apps/` must implement:
- `ConfigDialog(QDialog)` — shows configuration UI; must implement `get_values()` returning a dict of config params; saves/loads its own per-app JSON config to `config/<module_name>_config.json`.
- `main(top_block_cls=..., options=None, app=None, config_values=None)` — creates and starts the GNU Radio `top_block`, returns the `top_block` instance (not `app.exec_()`).

The flowgraph class itself (e.g., `amSineGenerator`) extends both `gr.top_block` and `Qt.QWidget`, and its `__init__` calls `apply_flowgraph_theme(self)` before it builds any widget.

### Shared Utilities (`apps/utils.py`)

- `apply_launcher_theme(widget)` — paints the launcher window from the
  shared tokens in `apps/theme.py` — see [one design, two front
  ends](devnotes/ui.md#one-design-two-front-ends).
- `apply_dark_theme(widget)` — the same tokens for a config dialog, and it
  also straightens the layout — see [how every dialog gets laid
  out](devnotes/ui.md#how-every-dialog-gets-laid-out).
- `apply_flowgraph_theme(window)` — the same tokens for a running
  flowgraph window, called first thing in its `__init__` — see [the
  flowgraph windows wear it too](devnotes/ui.md#the-flowgraph-windows-wear-it-too).
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
whichever is chosen** — see [flip tiles](devnotes/ui.md#the-launcher-grid-and-tiles-that-flip).
Pick the VSG60 and every tile turns to its transmitting side; pick the BB60D
and they all turn to receive, with the transmit-only tiles dimmed out. This
replaced a dialog that fired after the click, and before that an app that
opened and then reported "no HackRF found" — which sends people to check a
cable that is not the problem.

- **HackRF One** — USB SDR via SoapySDR (`soapy.sink('driver=hackrf', ...)`). No IP address needed; OK button always enabled. Gain set via `set_gain(0, 'VGA', value)` (0–47 dB) and `set_gain(0, 'AMP', 0)`.
- **Ettus USRP** — Network SDR via UHD (`gnuradio-uhd`). IP addresses configured in the settings gear dialog; OK button disabled when none are set. Gain set via `set_gain(value, 0)`.
- **Signal Hound VSG60** — USB vector signal generator (VID:PID `2817:0008`). Transmit only. No SoapySDR module and no stock GNU Radio block exists, so `apps/vsg_sink.py` wraps the vendor C API (`libvsg_api.so`) with ctypes as a `gr.sync_block`. No IP address needed; OK button always enabled. Level set via `set_level(dBm)` — a *calibrated absolute* output power, not a relative gain index.
- **Signal Hound BB60D** — USB spectrum analyser (VID:PID `2817:0007`). Receive only. It *is* a SoapySDR device, but not one `gr-soapy` can drive, so `apps/bb60_source.py` wraps the raw SoapySDR Python binding as a `gr.sync_block` — see [the BB60D section](devnotes/radios.md#signal-hound-bb60d-as-a-receiver) for why, and for the three things about it that are not like the other radios.

The VSG60's and the BB60D's own details - limits, locking, gain, and
what each does that the other radios do not - are in
[devnotes/radios.md](devnotes/radios.md).

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

### Adding a New Application

1. Create `apps/<module_name>.py` implementing `ConfigDialog` and `main()`,
   with `apply_flowgraph_theme(self)` as the first thing the flowgraph's
   `__init__` does, and add it to `MODULES` in
   `scripts/test_flowgraph_windows.py`.
2. Add an icon to `icons/`.
3. Add a row to `APP_TILES` in `RFbenchToolkit.py`, saying whether the
   app transmits or receives. To give an existing app a second side instead
   of a square of its own - a receiver for a transmitter, say - add a face
   to that tile's list rather than a row. The direction is all the grid
   needs to dim it, flip it and refuse it on the wrong radio. Both front ends and
   `scripts/test_launcher_gui.py` read that one table, so a row added there
   appears in all three.
4. Once the app has taught something worth keeping, write it into
   `devnotes/` - a file of its own for a new subject - and add a row to the
   table under [Where the details are](#where-the-details-are-devnotes).

## Environment

- Conda environment name: `gnu` (defined in `linux/environment.yml`, prefix: `/home/user/miniconda3/envs/gnu`; on Windows `windows/environment.yml`)
- Python 3.12, GNU Radio 3.10.12, PyQt5 5.15, UHD 4.8
- `linux/start_app.sh` activates `gnu` from `~/miniconda3`; edit its `source` line if conda lives elsewhere.
