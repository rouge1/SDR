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
- `radio_type` — `"hackrf"` or `"usrp"`.

Per-app configs are saved separately as `config/<module_name>_config.json`.

### USRP / Hardware

Two radio backends are supported, selected via `radio_type` in settings:

- **HackRF One** — USB SDR via SoapySDR (`soapy.sink('driver=hackrf', ...)`). No IP address needed; OK button always enabled. Gain set via `set_gain(0, 'VGA', value)` (0–47 dB) and `set_gain(0, 'AMP', 0)`.
- **Ettus USRP** — Network SDR via UHD (`gnuradio-uhd`). IP addresses configured in the settings gear dialog; OK button disabled when none are set. Gain set via `set_gain(value, 0)`.

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
