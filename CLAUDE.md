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
- The library ships inside the Sceptre install rather than a system prefix. `vsg_sink.py` searches known paths; `VSG_API_LIB` overrides.
- **A second open aborts the process.** The vendor library enforces single-client access with C `assert()`, which calls `abort()` — `vsgOpenDevice` on a device another process holds raises SIGABRT and core-dumps before Python sees anything, and can leave the unit needing a USB reset. It is uncatchable, and `vsgGetDeviceList` still lists a held device, so discovery cannot detect the condition either. `vsg_sink` therefore keeps an advisory PID lock at `config/.vsg60.lock`: `_acquire_lock()` runs before the open and raises a normal `RuntimeError` instead, `in_use()` lets the launcher show a dialog, and a lock whose PID is dead is treated as stale and cleared. This only sees users that go through this module — an external Signal Hound application holding the device is invisible to it.

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

### Adding a New Application

1. Create `apps/<module_name>.py` implementing `ConfigDialog` and `main()`.
2. Add an icon to `icons/`.
3. Register with `self.create_app_button(...)` in `gnuradio_launcher.py`.

## Environment

- Conda environment name: `gnu` (defined in `environment.yml`, prefix: `/home/user/miniconda3/envs/gnu`)
- Python 3.12, GNU Radio 3.10.12, PyQt5 5.15, UHD 4.8
- The `start_app.sh` script activates `.venv` (a local conda env alias); ensure the conda env is set up before running.
