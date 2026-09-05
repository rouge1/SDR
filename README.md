# GNU Radio Applications Launcher

A PyQt5-based graphical launcher for GNU Radio applications, providing easy access to a suite of signal generation and transmission tools.

---

## Features

- Clean, dark-themed graphical interface for launching GNU Radio applications
- Supports **HackRF One** (USB via SoapySDR), **Ettus USRP** (network via UHD), and **Signal Hound VSG60** (USB via the vendor VSG API) radio backends
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
- **Signal Hound VSG60** — connected via USB; requires the vendor `libvsg_api.so`, which is **not** included in this repository — see [Signal Hound VSG60 library](#signal-hound-vsg60-library) below. 30 MHz – 6 GHz, up to 50 MS/s, calibrated output from −120 to +10 dBm

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

## Signal Hound VSG60 library

Only needed if you are using a VSG60. The vendor library `libvsg_api.so.1` is
proprietary Signal Hound code with no redistribution grant, so it is **not
committed to this repository** and cannot be installed with pip or conda. You
supply it from your own licensed copy.

It is a single self-contained ~8 MB file. It links only against standard system
libraries (`libusb-1.0`, `libstdc++`, `libudev`) and requires nothing newer than
glibc 2.17, so one file is all you need — no Sceptre install on the target
machine.

```sh
# From a machine that has Sceptre installed locally:
./scripts/setup_vsg.sh

# From an explicit path (a Signal Hound SDK download, a USB stick, ...):
./scripts/setup_vsg.sh /path/to/libvsg_api.so.1

# Copied from another machine that has it:
./scripts/setup_vsg.sh user@host
```

The script puts the library in `vendor/` (gitignored — do not commit it),
installs the udev rule below, and verifies that the library loads and whether a
VSG is detected.

**Where to get the library:** any Sceptre install has it at
`/opt/sceptre/lib/libvsg_api.so.1`, or download the standalone VSG60 SDK from
Signal Hound, which is the same library without the rest of the Sceptre payload.

**Doing it by hand instead.** Drop the file anywhere the loader looks —
`vendor/` in this checkout, `/usr/local/lib` (run `ldconfig` afterwards), or a
path of your choosing exported as `VSG_API_LIB` (the file itself or the
directory holding it). Then add the udev rule, or the API cannot claim the
device even though `lsusb` lists it:

```sh
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="2817", MODE="0666", GROUP="plugdev"' \
  | sudo tee /etc/udev/rules.d/sh_usb.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
```

Replug the VSG60 afterwards.

> **Do not copy the whole `/opt/sceptre/lib` directory.** The library's `RUNPATH`
> starts with `$ORIGIN`, so it would load Sceptre's bundled `libc`, `libstdc++`
> and `libudev` from alongside it instead of the system ones. Copy the single
> file.

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
| Radio Hardware | Select **HackRF One (USB)**, **Ettus USRP (Network)**, or **Signal Hound VSG60 (USB)** |
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
├── scripts/
│   └── setup_vsg.sh              # Installs the VSG60 vendor library + udev rule
├── vendor/                       # Gitignored; holds libvsg_api.so.1 if used
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
Ensure the HackRF is connected before starting. Run `SoapySDRUtil --find` to confirm it is detected. The power slider is a 0–100% control mapped onto the HackRF's VGA range, so 100% is 47 dB of VGA gain.

**App launches but no RF output (USRP)**
Confirm the USRP IP is reachable (`ping <ip>`) and matches what is configured in Settings.

**Signal Hound VSG60: "VSG API library not found" / "Software Not Found"**
The vendor library is missing on this machine — the device itself is fine, and `lsusb | grep 2817` will still list it. The dialog names every directory searched and every path tried. See [Signal Hound VSG60 library](#signal-hound-vsg60-library); usually `./scripts/setup_vsg.sh` is enough. Note the Sceptre install directory is named after its version, so it differs from machine to machine.

**Signal Hound VSG60 detected by `lsusb` but not by the launcher**
The udev rule is missing, so the API cannot claim the device. Install it as shown in [Signal Hound VSG60 library](#signal-hound-vsg60-library) and replug the unit.

**App launches but no RF output (Signal Hound VSG60)**
Confirm the unit is detected with `lsusb | grep 2817`. The power slider maps 0–100% onto −120 to +10 dBm, so 100% is the VSG's maximum calibrated output. Requested frequencies outside 30 MHz – 6 GHz are clamped to the nearest limit and the clamp is logged to the console.

**Signal Hound VSG60 crashes with an assertion**
The vendor library calls `abort()` rather than returning an error if the device is already open in another process, which kills the app and can leave the VSG wedged. Launching twice from this launcher is caught and refused with a dialog, but an external Signal Hound application holding the device cannot be detected. If it does happen: close the other user of the device, then reset it — unplug/replug, or issue a `USBDEVFS_RESET` ioctl on the node shown by `lsusb | grep 2817`.

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
