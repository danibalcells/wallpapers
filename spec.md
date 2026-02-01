# Canary Islands Sentinel-2 Wallpaper Generator

## Project Goal

Build a Python script that automatically fetches high-resolution Sentinel-2 satellite imagery mosaics for the Canary Islands and sets them as the desktop wallpaper. The script should sample 10 km subtiles, form contiguous 4x3 mosaics, and only fall back to older dates after exhausting all possible mosaics for the most recent date.

---

## Architecture Overview

```
┌───────────────────────┐     ┌──────────────────────┐     ┌─────────────────┐
│ data/subtile_*.json   │────▶│ mosaic_selector.py   │────▶│ sentinel.py     │
│                       │     │                      │     │                 │
│ - Candidate subtiles  │     │ - 4x3 mosaics        │     │ - STAC search   │
│ - Land coverage gate  │     │ - Sampling policy    │     │ - Native reads  │
└───────────────────────┘     └──────────────────────┘     └─────────────────┘
                                │
                                ▼
                       ┌──────────────────┐
                       │  main.py         │
                       │                  │
                       │ - CLI entry      │
                       │ - Config loading │
                       │ - Logging        │
                       └──────────────────┘
                                │
                                ▼
                       ┌──────────────────┐
                       │  wallpaper.py    │
                       │                  │
                       │ - OS detection   │
                       │ - Set wallpaper  │
                       └──────────────────┘
```

---

## Component 1: Candidate Subtiles (`data/subtile_candidates.json`)

Precomputed list of 10 km subtiles that meet a minimum land coverage threshold. This list is only used for sampling locations and should be updated offline when needed.

Schema:

```json
{
  "version": 2,
  "islands": [
    {
      "name": "tenerife",
      "tiles": [
        {
          "tile_id": "28RCS",
          "tile_mgrs": "28RCS",
          "subtiles": [
            {
              "suffix": "10",
              "bbox": [-16.79010, 28.24010, -16.67560, 28.33020],
              "bounds_url": "https://opencagedata.com/tools/bounds-finder#-16.79010,28.24010,-16.67560,28.33020",
              "subtile_mgrs": "28RCS10"
            }
          ]
        }
      ]
    }
  ]
}
```

---

## Component 2: Mosaic Selection (`mosaic_selector.py`)

The selector builds contiguous 4x3 mosaics within each 100 km MGRS tile, then samples without replacement for a given date. A date is only changed after every possible mosaic for that date has been exhausted.

---

## Component 3: Sentinel-2 Data Fetching (`sentinel.py`)

- STAC search is performed by MGRS tile and date (Element 84 Earth Search).
- Bands are read in native UTM coordinates per subtile.
- A subtile is accepted only if valid-pixel coverage exceeds a threshold (default 98%).
- Raw bands are mosaiced first, then true-color is applied once to the final mosaic.

---

## Component 4: Wallpaper Setting (`wallpaper.py`)

### Cross-Platform Implementation

```python
import platform
import subprocess
import os

def set_wallpaper(image_path: str) -> bool:
    """
    Set desktop wallpaper. Returns True on success.
    """
    image_path = os.path.abspath(image_path)
    system = platform.system()
    
    if system == "Darwin":  # macOS
        return _set_wallpaper_macos(image_path)
    elif system == "Linux":
        return _set_wallpaper_linux(image_path)
    elif system == "Windows":
        return _set_wallpaper_windows(image_path)
    else:
        raise NotImplementedError(f"Unsupported OS: {system}")

def _set_wallpaper_macos(image_path: str) -> bool:
    """macOS wallpaper via osascript."""
    script = f'''
    tell application "System Events"
        tell every desktop
            set picture to "{image_path}"
        end tell
    end tell
    '''
    try:
        subprocess.run(["osascript", "-e", script], check=True)
        return True
    except subprocess.CalledProcessError:
        return False

def _set_wallpaper_linux(image_path: str) -> bool:
    """
    Linux wallpaper - try multiple desktop environments.
    """
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    
    # GNOME / Ubuntu
    if "gnome" in desktop or "ubuntu" in desktop:
        try:
            subprocess.run([
                "gsettings", "set", "org.gnome.desktop.background", 
                "picture-uri", f"file://{image_path}"
            ], check=True)
            subprocess.run([
                "gsettings", "set", "org.gnome.desktop.background",
                "picture-uri-dark", f"file://{image_path}"
            ], check=True)
            return True
        except subprocess.CalledProcessError:
            pass
    
    # KDE Plasma
    if "kde" in desktop or "plasma" in desktop:
        script = f'''
        var allDesktops = desktops();
        for (var i = 0; i < allDesktops.length; i++) {{
            var d = allDesktops[i];
            d.wallpaperPlugin = "org.kde.image";
            d.currentConfigGroup = ["Wallpaper", "org.kde.image", "General"];
            d.writeConfig("Image", "file://{image_path}");
        }}
        '''
        try:
            subprocess.run([
                "qdbus", "org.kde.plasmashell", "/PlasmaShell",
                "org.kde.PlasmaShell.evaluateScript", script
            ], check=True)
            return True
        except subprocess.CalledProcessError:
            pass
    
    # XFCE
    if "xfce" in desktop:
        try:
            subprocess.run([
                "xfconf-query", "-c", "xfce4-desktop",
                "-p", "/backdrop/screen0/monitor0/workspace0/last-image",
                "-s", image_path
            ], check=True)
            return True
        except subprocess.CalledProcessError:
            pass
    
    # Fallback: feh (works on many WMs)
    try:
        subprocess.run(["feh", "--bg-fill", image_path], check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    
    return False

def _set_wallpaper_windows(image_path: str) -> bool:
    """Windows wallpaper via ctypes."""
    import ctypes
    
    SPI_SETDESKWALLPAPER = 0x0014
    SPIF_UPDATEINIFILE = 0x01
    SPIF_SENDCHANGE = 0x02
    
    result = ctypes.windll.user32.SystemParametersInfoW(
        SPI_SETDESKWALLPAPER, 0, image_path,
        SPIF_UPDATEINIFILE | SPIF_SENDCHANGE
    )
    return bool(result)
```

---

## Component 5: Main Script (`main.py`)

```python
#!/usr/bin/env python3
"""
Canary Islands Sentinel-2 Wallpaper Generator

Usage:
    python main.py                     # Random tile mosaic, default settings
    python main.py --days 60           # Search further back
    python main.py --candidate-list data/subtile_candidates.json
    python main.py --dry-run           # Preview without setting wallpaper
"""

import argparse
import logging
import sys
from pathlib import Path
from datetime import datetime

from sentinel import fetch_tile_mosaic_image
from wallpaper import set_wallpaper

# Config
DEFAULT_MAX_CLOUD_COVER = 20
DEFAULT_DAYS_BACK = 30
OUTPUT_DIR = Path.home() / ".canary-wallpaper"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Canary Islands satellite wallpaper")
    parser.add_argument("--cloud-cover", type=int, default=DEFAULT_MAX_CLOUD_COVER, help="Max cloud %")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS_BACK, help="Days to search back")
    parser.add_argument("--dry-run", action="store_true", help="Don't set wallpaper")
    parser.add_argument("--output", type=Path, help="Custom output path")
    args = parser.parse_args()
    
    OUTPUT_DIR.mkdir(exist_ok=True)
    
    # Fetch image
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = args.output or OUTPUT_DIR / f"canary_mosaic_{timestamp}.png"
    
    logger.info(f"Fetching Sentinel-2 imagery (max {args.cloud_cover}% clouds, last {args.days} days)")
    success = fetch_tile_mosaic_image(
        candidate_list_path=Path("data/subtile_candidates.json"),
        output_path=str(output_path),
        max_cloud_cover=args.cloud_cover,
        days_back=args.days
    )
    
    if not success:
        logger.error("Failed to fetch imagery - no suitable scenes found")
        sys.exit(1)
    
    logger.info(f"Saved image to {output_path}")
    
    # Set wallpaper
    if not args.dry_run:
        logger.info("Setting wallpaper...")
        if set_wallpaper(str(output_path)):
            logger.info("Wallpaper set successfully!")
        else:
            logger.error("Failed to set wallpaper")
            sys.exit(1)
    else:
        logger.info("Dry run - skipping wallpaper set")
    
    # Cleanup old images (keep last 10)
    cleanup_old_images(OUTPUT_DIR, keep=10)


def cleanup_old_images(directory: Path, keep: int = 10):
    """Remove old wallpaper images, keeping the most recent `keep` files."""
    images = sorted(directory.glob("canary_*.png"), key=lambda p: p.stat().st_mtime)
    for old_image in images[:-keep]:
        old_image.unlink()
        logger.debug(f"Removed old image: {old_image}")


if __name__ == "__main__":
    main()
```

---

## Configuration & Credentials

### Config File (`config.yaml`)

```yaml
sentinel_hub:
  client_id: "your-client-id"
  client_secret: "your-client-secret"

preferences:
  candidate_list: data/subtile_candidates.json
  max_cloud_cover: 20
  days_back: 30
  mosaic_width: 4
  mosaic_height: 3
  valid_pixel_min: 0.98
```

### Environment Variables (Alternative)

```bash
export SENTINEL_HUB_CLIENT_ID="your-client-id"
export SENTINEL_HUB_CLIENT_SECRET="your-client-secret"
```

---

## Scheduling

### macOS (launchd)

Create `~/Library/LaunchAgents/com.canary-wallpaper.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.canary-wallpaper</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>/path/to/main.py</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>9</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/tmp/canary-wallpaper.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/canary-wallpaper.err</string>
</dict>
</plist>
```

Load with: `launchctl load ~/Library/LaunchAgents/com.canary-wallpaper.plist`

### Linux (cron)

```bash
# Run daily at 9am
0 9 * * * /usr/bin/python3 /path/to/main.py >> /tmp/canary-wallpaper.log 2>&1
```

### Linux (systemd timer)

`~/.config/systemd/user/canary-wallpaper.service`:
```ini
[Unit]
Description=Canary Islands Satellite Wallpaper

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /path/to/main.py
```

`~/.config/systemd/user/canary-wallpaper.timer`:
```ini
[Unit]
Description=Run Canary Wallpaper daily

[Timer]
OnCalendar=*-*-* 09:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

Enable with: `systemctl --user enable --now canary-wallpaper.timer`

---

## Dependencies

### requirements.txt

```
Pillow>=10.0.0
pyyaml>=6.0
pystac-client>=0.7.0
rasterio>=1.3.0
numpy>=1.24.0
pyobjc-framework-Cocoa>=10.0; sys_platform == "darwin"
```

### Installation

```bash
pip install -r requirements.txt
```

---

## Error Handling Considerations

1. **No imagery dates found**: Increase `days_back` or `max_cloud_cover`
2. **No mosaics available**: Candidate list may be empty or too sparse
3. **Low valid pixels**: Lower `valid_pixel_min` or update candidate list
4. **Network errors**: Retry with backoff, cache last successful image as fallback
5. **Wallpaper setting fails**: Log error, image is still saved

---

## Future Enhancements

- [ ] Web UI for previewing locations before setting
- [ ] Historical image browser (store metadata of past images)
- [ ] Multi-monitor support (different regions per display)
- [ ] Seasonal preferences (prefer certain regions at certain times)
- [ ] Integration with liewa for additional satellite sources
- [ ] Notification when new cloud-free imagery becomes available

---

## References

- Copernicus Data Space Ecosystem: https://dataspace.copernicus.eu
- Element 84 Earth Search STAC: https://earth-search.aws.element84.com/v1
- Sentinel-2 Band Info: https://sentiwiki.copernicus.eu/web/s2-mission
- Live-Earth-Wallpapers (inspiration): https://github.com/lennart-rth/Live-Earth-Wallpapers