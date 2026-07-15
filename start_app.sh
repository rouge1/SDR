#!/bin/bash
# Change to the directory containing this script
cd "$(dirname "$0")"
# Activate the Conda environment
source ~/miniconda3/bin/activate gnu
# Run app
python gnuradio_launcher.py
