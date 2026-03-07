# GNU Radio Applications Launcher

A PyQt5-based graphical launcher for GNU Radio applications, providing easy access to a suite of signal generation and processing tools.

---

## Features

- Clean, intuitive graphical interface for launching GNU Radio applications
- Supports **HackRF One** (USB) and **Ettus USRP** (network) radio backends
- 11 signal generation and transmission modules (audio, video, digital modulations)
- Persistent window positioning and per-app configuration
- Dark theme
- Single and multi-radio operation modes

---

## Prerequisites

- [Miniconda](https://docs.conda.io/en/latest/miniconda.html) or [Anaconda](https://www.anaconda.com/)
- GNU Radio 3.10+ with PyQt5 (installed via conda)
- Python 3.12 (managed by conda)
- Linux (X11 or Wayland display required)
- **HackRF One** (USB, via SoapySDR) or **Ettus USRP** (network, via UHD 4.x)

---

## Installation

1. **Clone the repository:**
    ```sh
    git clone https://github.com/rouge1/gnuradio-launcher.git
    cd gnuradio-launcher/SDR
    ```

2. **Create and activate the Conda environment:**
    ```sh
    conda env create -f environment.yml
    conda activate gnu
    ```

---

## Project Structure

```
SDR/
├── apps/
│   ├── utils.py
│   ├── settings_dialog.py
│   └── [application modules]
├── config/
│   └── window_settings.json
├── icons/
│   └── [application icons]
├── gnuradio_launcher.py
├── start_app.sh
├── environment.yml
```

---

## Usage

1. **Start the launcher using the provided script:**
    ```sh
    ./start_app.sh
    ```
    Or, run directly:
    ```sh
    python gnuradio_launcher.py
    ```

2. **Interact with the GUI:**
    - Click any application button to configure and launch a GNU Radio module.
    - Use the settings icon (top-right) for global configuration.

---

## Available Applications

| App | Description |
|-----|-------------|
| ASK Generator | Amplitude Shift Keying signal generator |
| FSK Generator | Frequency Shift Keying signal generator |
| AM Sine Generator | AM with sinewave carrier |
| PSK Generator | Phase Shift Keying signal generator |
| FM Audio (Recorded) | FM transmitter using recorded WAV audio |
| AM Audio (Live) | AM transmitter with live or recorded audio |
| PPM-OOK Audio | Pulse Position Modulation OOK audio transmitter |
| Subcarrier Audio | Subcarrier transmitter with recorded audio |
| AM Video | AM video transmitter (recorded) |
| NTSC Analog Video | NTSC analog video transmitter |
| ATSC Transmitter | ATSC digital TV transmitter |

---

## Configuration

- Global settings (radio type, IP addresses, media directory) are accessed via the gear icon.
- Each app saves its own settings to `config/<module_name>_config.json`.
- Window positions are automatically saved and restored.

---

## Development

To add a new GNU Radio application:

1. Create a new Python module in the `apps/` directory.
2. Implement a `ConfigDialog` class for your module.
3. Implement a `main()` function that returns your GNU Radio flowgraph.
4. Add an icon to the `icons/` directory.
5. Register the application in `gnuradio_launcher.py`.

---

## Acknowledgments

- GNU Radio community
- PyQt5 developers
- Gary Schafer
- Rick Astley

---
