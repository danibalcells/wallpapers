#!/usr/bin/env bash
set -e
PROJECT_DIR="/Users/dani/code/wallpapers"
cd "${PROJECT_DIR}"
source .venv/bin/activate
python main.py --shape 3x2 --max-per-day 3

mkdir -p "${PROJECT_DIR}/images/old"
ls -t "${PROJECT_DIR}/images/"*.png 2>/dev/null | tail -n +4 | while read -r f; do
    mv "$f" "${PROJECT_DIR}/images/old/"
done
