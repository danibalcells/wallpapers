#!/usr/bin/env bash
set -e
PROJECT_DIR="/Users/dani/code/wallpapers"
cd "${PROJECT_DIR}"
source .venv/bin/activate
exec python main.py --shape 3x2 --max-per-day 3
