# Canary Islands Satellite Wallpaper

Automatically fetches recent Sentinel-2 satellite imagery of the Canary Islands and sets it as your desktop wallpaper. Every run picks a different cloud-free mosaic so you always have a fresh view from space.

## How it works

1. A precomputed candidate list (`data/subtile_candidates.json`) defines which 10 km MGRS subtiles cover the islands with enough land to be interesting.
2. The mosaic selector builds all possible contiguous grids of subtiles (default 4×3, roughly 40×30 km) and picks one at random.
3. Sentinel-2 L2A imagery is fetched from [Element 84 Earth Search](https://earth-search.aws.element84.com/v1) via the STAC API. Only scenes from the last N days with cloud cover below the threshold are considered.
4. Each subtile must have ≥98% valid pixels (no clouds, no data gaps). Failed subtiles are skipped and the next mosaic candidate is tried.
5. The RGB bands are composited with Copernicus-style true-color tone mapping and saved as a PNG.
6. Optionally the image is set as the desktop wallpaper (macOS, Linux, Windows supported).

A tile status cache (`data/tile_status_cache.json`) remembers which subtiles and dates were invalid so repeated runs don't re-fetch data unnecessarily.

## Requirements

- Python ≥ 3.13
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

## Setup

```bash
git clone <repo>
cd wallpapers
uv venv -p python3.13
source .venv/bin/activate
uv sync
```

## Usage

```bash
# Generate an image with default settings (saves to images/, does not set wallpaper)
python main.py

# Generate and set as wallpaper
python main.py --set-wallpaper

# Search further back and allow more cloud cover
python main.py --days 60 --cloud-cover 50

# Use a different mosaic shape (width x height in subtiles)
python main.py --shape 3x2

# Preview only (skip wallpaper, keep image)
python main.py --dry-run

# Reproducible run with fixed random seed
python main.py --seed 42

# Verbose logging
python main.py -v
```

### All options

| Flag | Default | Description |
|------|---------|-------------|
| `--cloud-cover` | 40 | Maximum cloud cover percentage |
| `--days` | 30 | How many days back to search for imagery |
| `--shape WxH` | `4x3` | Mosaic dimensions in 10 km subtiles |
| `--valid-pixel-min` | 0.98 | Minimum valid-pixel fraction per subtile |
| `--min-land-per-subtile` | 0.05 | Minimum land fraction for a subtile to count as "has land" |
| `--min-subtiles-with-land` | 2 | Minimum subtiles with land required per mosaic |
| `--seed` | random | RNG seed for reproducible mosaic selection |
| `--candidate-list` | `data/subtile_candidates.json` | Path to candidate subtile list |
| `--output` | auto | Custom output path for the image |
| `--keep` | 10 | Number of recent images to retain |
| `--max-per-day` | — | Skip if this many images were already generated today |
| `--set-wallpaper` | false | Set the image as the desktop wallpaper |
| `--dry-run` | false | Save image but skip wallpaper setting |
| `-v` / `--verbose` | false | Enable debug logging |

## Configuration

Settings can be persisted in `config.yaml` so you don't have to pass flags every time. A default file is created on first run.

```yaml
preferences:
  candidate_list: data/subtile_candidates.json
  days_back: 30
  max_cloud_cover: 40
  mosaic_width: 4
  mosaic_height: 3
  valid_pixel_min: 0.98
```

CLI flags always override config file values.

## Scheduling

A helper script at `scripts/cron_wallpaper.sh` wraps the generator and rotates old images. Add it to cron to refresh automatically:

```bash
# Run up to 3 times a day (e.g. morning, afternoon, evening)
0 8,13,18 * * * /Users/you/code/wallpapers/scripts/cron_wallpaper.sh >> /tmp/wallpaper.log 2>&1
```

On macOS you can also use `launchd`. Create `~/Library/LaunchAgents/com.canary-wallpaper.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.canary-wallpaper</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/you/code/wallpapers/scripts/cron_wallpaper.sh</string>
    </array>
    <key>StartCalendarInterval</key>
    <array>
        <dict><key>Hour</key><integer>8</integer><key>Minute</key><integer>0</integer></dict>
        <dict><key>Hour</key><integer>13</integer><key>Minute</key><integer>0</integer></dict>
        <dict><key>Hour</key><integer>18</integer><key>Minute</key><integer>0</integer></dict>
    </array>
    <key>StandardOutPath</key>
    <string>/tmp/canary-wallpaper.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/canary-wallpaper.err</string>
</dict>
</plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.canary-wallpaper.plist
```

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| No imagery found | Increase `--days` or `--cloud-cover` |
| All subtiles invalid | Lower `--valid-pixel-min` or use a wider mosaic shape |
| Wallpaper not updating on macOS Sequoia | See `MACOS_SEQUOIA_WALLPAPER_FIX.md` |
| Slow first run | First run downloads band data from S3 — subsequent runs use the tile status cache |

## Project structure

```
main.py               # CLI entry point
sentinel.py           # STAC search and band fetching
mosaic_selector.py    # Mosaic building and sampling
tiles.py              # MGRS subtile geometry
islands.py            # Island boundary polygons
wallpaper.py          # Cross-platform wallpaper setting
config.yaml           # User preferences
data/
  subtile_candidates.json   # Precomputed candidate subtiles with land fractions
  tile_status_cache.json    # Runtime cache of tile/date validity
images/               # Generated wallpapers
scripts/
  cron_wallpaper.sh   # Scheduler wrapper script
```

## Data sources

- **Imagery**: [Sentinel-2 L2A](https://sentiwiki.copernicus.eu/web/s2-mission) via [Element 84 Earth Search STAC](https://earth-search.aws.element84.com/v1) — free, no account required
- **True-color processing**: based on the [Copernicus Browser](https://browser.dataspace.copernicus.eu) true_color algorithm
