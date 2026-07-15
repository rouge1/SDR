# GNU Radio Applications Launcher

A PyQt5-based graphical launcher for GNU Radio applications, providing easy access to a suite of signal generation and transmission tools.

---

## Features

- Clean, dark-themed graphical interface for launching GNU Radio applications
- Supports **HackRF One** (USB via SoapySDR) and **Ettus USRP** (network via UHD) radio backends
- 11 signal generation and transmission modules (audio, video, digital modulations)
- Persistent window positioning and per-app configuration
- Single and multi-radio operation modes

---

## Prerequisites

### System Requirements

- Linux (X11 or Wayland display required)
- [Miniconda](https://docs.conda.io/en/latest/miniconda.html) or [Anaconda](https://www.anaconda.com/)
- Audio: **PipeWire** (ALSA audio source is not supported)

### Hardware (one of the following)

- **HackRF One** — connected via USB; SoapySDR HackRF driver must be available in the conda environment
- **Ettus USRP** — reachable over the network via UHD 4.x; IP address configured in the Settings dialog

---

## Installation

### 0. Install Miniconda (skip if already installed)

```sh
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash Miniconda3-latest-Linux-x86_64.sh
```

Follow the prompts and accept the default install path (`~/miniconda3`). When asked to initialize conda, choose **yes**. Then reload your shell:

```sh
source ~/.bashrc
```

### 1. Clone the repository

```sh
git clone https://github.com/rouge1/SDR.git
cd SDR
```

### 2. Create the conda environment

The `environment.yml` contains a hardcoded `prefix` for the original machine. Override it with `--name` so it installs correctly on any system:

```sh
conda env create -f environment.yml --name gnu
```

> If conda reports that the environment already exists:
> ```sh
> conda env update -f environment.yml --name gnu --prune
> ```

### 3. Verify the environment

```sh
conda activate gnu
python -c "from gnuradio import gr; print(gr.version())"
```

Expected output: `3.10.12.0`

---

## Running the Application

```sh
./start_app.sh
```

Or activate the environment manually first:

```sh
conda activate gnu
python gnuradio_launcher.py
```

> `start_app.sh` assumes Miniconda is installed at `~/miniconda3`. If your installation is elsewhere (e.g., `/opt/miniconda3`), edit the `source` line in that script accordingly.

---

## First-Run Configuration

On first launch, open the **Settings** dialog (gear icon, top-right) and configure:

| Setting | Description |
|---------|-------------|
| Media Directory | Path to WAV/video files used by audio and video transmitter apps |
| Radio Hardware | Select **HackRF One (USB)** or **Ettus USRP (Network)** |
| Launcher Mode | **Single** — launcher hides while an app runs; **Multi** — launcher stays open (requires ≥ 2 USRP IPs) |
| SDR IP Addresses | USRP only — enter each USRP IP address and click Add |

Settings are saved to `config/window_settings.json` (created automatically on first run).

---

## Project Structure

```
SDR/
├── apps/
│   ├── utils.py                  # Shared theme + settings helpers
│   ├── settings_dialog.py        # Global settings UI
│   └── *.py                      # GNU Radio application modules
├── config/                       # Auto-created; gitignored
│   └── window_settings.json      # Global settings (radio type, IPs, media dir)
├── icons/                        # Button icons
├── gnuradio_launcher.py          # Main launcher window
├── start_app.sh                  # Launch helper script
└── environment.yml               # Conda environment definition
```

---

## Available Applications

| App | Description | Status |
|-----|-------------|--------|
| AM Sine Generator | AM with sinewave carrier (DSB/SSB, full/suppressed carrier) | Tested |
| ASK Generator | Amplitude Shift Keying signal generator | Tested |
| FSK Signal Generator | Frequency Shift Keying signal generator | Tested |
| PSK Signal Generator | Phase Shift Keying signal generator | Tested |
| PPM-OOK Generator | Pulse Position Modulation OOK audio transmitter | Tested |
| AM Audio Generator | AM transmitter with live or recorded WAV audio | Tested |
| FM Audio Generator | FM transmitter using recorded WAV audio | Tested |
| FM Subcarrier | Subcarrier transmitter with recorded WAV audio | Tested |
| ATSC Video Transmitter | ATSC digital TV transmitter | Untested |
| NTSC Analog Video | NTSC analog video transmitter | Untested |
| AM Video Transmitter | AM video transmitter (recorded) | Untested |

Audio/video apps that use recorded files require WAV files placed in the **Media Directory** configured in Settings.

---

## Configuration Details

- **Global settings** — `config/window_settings.json` (radio type, IP addresses, media directory, launcher mode, window geometry)
- **Per-app settings** — `config/<module_name>_config.json` (last-used parameter values, dialog position)
- Both files are created automatically and are excluded from version control

---

## Adding a New Application

1. Create `apps/<module_name>.py` implementing:
   - `ConfigDialog(QDialog)` — configuration UI; must implement `get_values()` returning a dict
   - `main(top_block_cls=..., options=None, app=None, config_values=None)` — creates and starts the GNU Radio flowgraph, returns the `top_block` instance
2. Add an icon to `icons/`
3. Register the app in `gnuradio_launcher.py` with `self.create_app_button(...)`

Refer to `apps/amSineGenerator.py` as a reference implementation.

---

## Troubleshooting

**`conda env create` fails with prefix conflict**
Add `--name gnu` to override the hardcoded prefix in `environment.yml`.

**App launches but no RF output (HackRF)**
Ensure the HackRF is connected before starting. Run `SoapySDRUtil --find` to confirm it is detected. The VGA gain formula maps power slider values of −50 dBm → 0 dB VGA and −30 dBm → 20 dB VGA.

**App launches but no RF output (USRP)**
Confirm the USRP IP is reachable (`ping <ip>`) and matches what is configured in Settings.

**Audio apps produce no sound / error on launch**
ALSA audio source is not supported. The system must use PipeWire. Verify with `pactl info | grep "Server Name"`.

**Launcher window appears off-screen after moving between display configurations**
Delete `config/window_settings.json` to reset all saved window positions.

---

## Environment Details

| Component | Version |
|-----------|---------|
| Python | 3.12 |
| GNU Radio | 3.10.12 |
| PyQt5 | 5.15 |
| UHD | 4.8 |
| SoapySDR | 0.8.1 |
| Conda environment name | `gnu` |

---

## Acknowledgments

- GNU Radio community
- PyQt5 developers
- Gary Schafer
- Rick Astley
