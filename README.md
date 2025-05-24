# GNU Radio Applications Launcher

A PyQt5-based graphical launcher for GNU Radio applications, providing easy access to a suite of signal generation and processing tools.

---

## Features

- Clean, intuitive graphical interface for launching GNU Radio applications
- Support for multiple signal generation and processing modules
- Persistent window positioning
- Dark theme support
- Configurable settings for each application
- Flexible operation modes (single/multiple window)

---

## Prerequisites

- [Miniconda](https://docs.conda.io/en/latest/miniconda.html) or [Anaconda](https://www.anaconda.com/)
- GNU Radio (installed via conda)
- Python 3.x (managed by conda)
- Linux (recommended)

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

## Configuration

- Application settings are managed through individual dialogs.
- Window positions are automatically saved and restored.
- Global settings are accessible via the settings icon.

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
