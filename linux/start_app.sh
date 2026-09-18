#!/bin/bash
# Change to the repo root, one up from this script: the launcher opens
# icons/ and config/ by relative path
cd "$(dirname "$0")/.."
# Activate the Conda environment
source ~/miniconda3/bin/activate gnu
# Run app
python RFbenchToolkit.py
