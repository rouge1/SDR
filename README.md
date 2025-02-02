# GNU Radio Applications Launcher
A PyQt5-based graphical launcher for GNU Radio applications, providing easy access to various 
signal generation and processing tools.

Features:

	Clean, intuitive graphical interface for launching GNU Radio applications
	Support for multiple signal generation applications.
	Persistent window positioning
	Dark theme support
	Configurable settings for each application
	Flexible radio mode operation (single/multiple window mode)

# Prerequisites

	Python 3.x
	PyQt5
	GNU Radio
	Pillow (PIL)

# Installation

Clone the repository:

	git clone https://github.com/rouge1/gnuradio-launcher.git

cd SDR/

Install required dependencies:

	pip install PyQt5 Pillow

Ensure GNU Radio is installed on your system

	Project Structure
	SDR/
	├── apps/
	│   ├── utils.py
	│   ├── settings_dialog.py
	│   └── [application modules]
	├── config/
	│   └── window_settings.json
	├── icons/
	│   └── [application icons]
	└── gnuradio_launcher.py

# Usage

Run the launcher:

	python3 gnuradio_launcher.py

Click on any application button to launch it

Configure the application parameters in the dialog that appears

Click "OK" to start the GNU Radio application

# Configuration

Application settings are managed through individual configuration dialogs

Window positions are automatically saved and restored

Global settings can be accessed through the settings icon in the top-right corner

# Development
To add a new GNU Radio application:

	Create a new Python module in the apps directory
	Implement the required ConfigDialog class
	Implement the main() function that returns your GNU Radio flowgraph
	Add an icon to the icons directory
	Register the application in gnuradio_launcher.py

# Acknowledgments

	GNU Radio community
	PyQt5 developers
	Gary Schafer
 	Rick Astley
