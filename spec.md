# Canary Islands Sentinel-2 Wallpaper Generator

## Project Goal

Build a Python script that automatically fetches high-resolution Sentinel-2 satellite imagery of random locations within the Canary Islands and sets it as the desktop wallpaper. The script should run on a schedule (cron/launchd/Task Scheduler) and select a new random bounding box within one of the 7 main Canary Islands each time.

---

## Architecture Overview

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  islands.py     │────▶│  sentinel.py     │────▶│  wallpaper.py   │
│                 │     │                  │     │                 │
│ - Island polys  │     │ - CDSE/SentinelHub│    │ - OS detection  │
│ - Random bbox   │     │ - Cloud filtering │    │ - Set wallpaper │
│ - Land coverage │     │ - Image render   │     │                 │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                                 │
                                 ▼
                        ┌──────────────────┐
                        │  main.py         │
                        │                  │
                        │ - CLI entry      │
                        │ - Config loading │
                        │ - Scheduling     │
                        └──────────────────┘
```

---

## Component 1: Island Polygons & Random Bbox Generation (`islands.py`)

### Canary Islands Reference Data

The 7 main islands with approximate bounding boxes (WGS84: `[west, south, east, north]`):

| Island | Bbox | Center (approx) | Area (km²) |
|--------|------|-----------------|------------|
| **Tenerife** | `[-16.92, 28.00, -16.12, 28.60]` | `28.29, -16.52` | 2,034 |
| **Fuerteventura** | `[-14.52, 28.02, -13.82, 28.76]` | `28.39, -14.17` | 1,659 |
| **Gran Canaria** | `[-15.85, 27.73, -15.35, 28.17]` | `27.95, -15.60` | 1,560 |
| **Lanzarote** | `[-13.95, 28.84, -13.40, 29.25]` | `29.04, -13.67` | 846 |
| **La Palma** | `[-18.02, 28.45, -17.72, 28.87]` | `28.66, -17.87` | 708 |
| **La Gomera** | `[-17.36, 28.02, -17.06, 28.22]` | `28.12, -17.21` | 370 |
| **El Hierro** | `[-18.16, 27.64, -17.88, 27.84]` | `27.74, -18.02` | 269 |

### Implementation Requirements

1. **Store island polygons** - Use simplified GeoJSON polygons for each island (not just bboxes - actual coastline shapes to avoid ocean-only selections). These can be sourced from:
   - Natural Earth Data (1:10m cultural vectors)
   - OpenStreetMap exports
   - Or define simplified polygons manually (10-20 vertices per island is sufficient)

2. **Random bbox generation function**:
   ```python
   def generate_random_bbox(
       island: str | None = None,  # None = random island selection
       bbox_size_km: float = 15.0,  # Size of bbox in km (square)
       min_land_coverage: float = 0.3,  # Minimum 30% land in bbox
       max_attempts: int = 50
   ) -> tuple[float, float, float, float]:
       """
       Returns (west, south, east, north) in WGS84.
       
       Algorithm:
       1. Select island (random if not specified, weighted by area)
       2. Generate random point within island polygon
       3. Create bbox of specified size centered on point
       4. Validate land coverage (retry if too much ocean)
       5. Return bbox
       """
   ```

3. **Coordinate math helpers**:
   - At ~28°N latitude: 1° longitude ≈ 97 km, 1° latitude ≈ 111 km
   - For a 15km bbox: ~0.155° longitude, ~0.135° latitude
   - Use `shapely` for polygon operations

4. **Dependencies**: `shapely`, `geojson` (or just store as dicts)

---

## Component 2: Sentinel-2 Data Fetching (`sentinel.py`)

### API Choice: Copernicus Data Space Ecosystem (CDSE)

The old Copernicus Open Access Hub shut down in October 2023. Use the new **CDSE** at `dataspace.copernicus.eu`.

### Authentication

1. Create free account at https://dataspace.copernicus.eu
2. Generate OAuth2 credentials (client_id, client_secret)
3. Token endpoint: `https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token`
4. Tokens expire in 10 minutes, refresh within 60 minutes

### Option A: Sentinel Hub Processing API (Recommended)

Use `sentinelhub-py` library for rendered image output (no band processing needed):

```python
from sentinelhub import (
    SHConfig, SentinelHubRequest, BBox, CRS, 
    MimeType, DataCollection, MosaickingOrder
)

config = SHConfig()
config.sh_client_id = "YOUR_CLIENT_ID"
config.sh_client_secret = "YOUR_CLIENT_SECRET"
config.sh_token_url = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
config.sh_base_url = "https://sh.dataspace.copernicus.eu"

# Evalscript for true-color RGB with contrast enhancement
EVALSCRIPT = """
//VERSION=3
function setup() {
    return {
        input: ["B04", "B03", "B02", "CLM"],
        output: { bands: 3, sampleType: "AUTO" }
    };
}

function evaluatePixel(sample) {
    // Skip cloudy pixels (optional: make them slightly visible)
    if (sample.CLM > 0.5) {
        return [0.7, 0.7, 0.7];  // Gray for clouds
    }
    // Brightness boost (2.5-3.5x typical for Sentinel-2)
    let gain = 3.0;
    return [gain * sample.B04, gain * sample.B03, gain * sample.B02];
}
"""

def fetch_sentinel_image(
    bbox: tuple[float, float, float, float],
    output_path: str,
    resolution: tuple[int, int] = (1920, 1080),
    max_cloud_cover: int = 20,
    days_back: int = 30
) -> bool:
    """
    Fetch Sentinel-2 L2A image for bbox.
    
    Args:
        bbox: (west, south, east, north) in WGS84
        output_path: Where to save the PNG
        resolution: Output image dimensions
        max_cloud_cover: Maximum cloud coverage percentage (0-100)
        days_back: How far back to search for imagery
    
    Returns:
        True if successful, False if no suitable imagery found
    """
    from datetime import datetime, timedelta
    
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days_back)
    
    request = SentinelHubRequest(
        evalscript=EVALSCRIPT,
        input_data=[
            SentinelHubRequest.input_data(
                data_collection=DataCollection.SENTINEL2_L2A,
                time_interval=(start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")),
                mosaicking_order=MosaickingOrder.LEAST_CC,
                other_args={"dataFilter": {"maxCloudCoverage": max_cloud_cover}}
            )
        ],
        responses=[SentinelHubRequest.output_response("default", MimeType.PNG)],
        bbox=BBox(bbox, CRS.WGS84),
        size=resolution,
        config=config
    )
    
    data = request.get_data()
    if data and len(data) > 0 and data[0] is not None:
        from PIL import Image
        img = Image.fromarray(data[0])
        img.save(output_path)
        return True
    return False
```

### Option B: STAC API + Element 84 Earth Search (No Auth Required)

For simpler setup without CDSE registration:

```python
from pystac_client import Client
import rasterio
from rasterio.windows import from_bounds
import numpy as np
from PIL import Image

def fetch_via_stac(
    bbox: tuple[float, float, float, float],
    output_path: str,
    max_cloud_cover: int = 20
) -> bool:
    """
    Fetch via Element 84's free STAC API (no auth needed).
    """
    client = Client.open("https://earth-search.aws.element84.com/v1")
    
    search = client.search(
        collections=["sentinel-2-l2a"],
        bbox=bbox,
        datetime="2024-01-01/..",  # Adjust as needed
        query={"eo:cloud_cover": {"lt": max_cloud_cover}},
        sortby=[{"field": "datetime", "direction": "desc"}],
        limit=1
    )
    
    items = list(search.items())
    if not items:
        return False
    
    item = items[0]
    
    # Get COG URLs for RGB bands
    red_url = item.assets["red"].href
    green_url = item.assets["green"].href  
    blue_url = item.assets["blue"].href
    
    # Read and composite (using rasterio with windowed reads)
    bands = []
    for url in [red_url, green_url, blue_url]:
        with rasterio.open(url) as src:
            window = from_bounds(*bbox, src.transform)
            band = src.read(1, window=window)
            # Normalize to 0-255
            p2, p98 = np.percentile(band, (2, 98))
            normalized = np.clip((band - p2) / (p98 - p2) * 255, 0, 255)
            bands.append(normalized.astype(np.uint8))
    
    rgb = np.dstack(bands)
    Image.fromarray(rgb).save(output_path)
    return True
```

### Sentinel-2 Specifications

- **Resolution**: 10m for RGB bands (B02, B03, B04)
- **Tile size**: 10,980 × 10,980 pixels per tile
- **Revisit frequency**: 2-5 days depending on latitude (Canaries: ~3-4 days)
- **Recommended product**: L2A (atmospherically corrected, better colors)
- **Band mapping**: B04=Red, B03=Green, B02=Blue

### Rate Limits (CDSE Free Tier)

- 10,000 Sentinel Hub requests/month
- 12 TB downloads/month
- 300 requests/minute for Sentinel Hub
- More than sufficient for daily wallpaper updates

---

## Component 3: Wallpaper Setting (`wallpaper.py`)

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

## Component 4: Main Script (`main.py`)

```python
#!/usr/bin/env python3
"""
Canary Islands Sentinel-2 Wallpaper Generator

Usage:
    python main.py                    # Random island, default settings
    python main.py --island tenerife  # Specific island
    python main.py --size 20          # 20km bbox
    python main.py --dry-run          # Preview without setting wallpaper
"""

import argparse
import logging
import sys
from pathlib import Path
from datetime import datetime

from islands import generate_random_bbox, ISLANDS
from sentinel import fetch_sentinel_image
from wallpaper import set_wallpaper

# Config
DEFAULT_BBOX_SIZE_KM = 15
DEFAULT_MAX_CLOUD_COVER = 20
DEFAULT_DAYS_BACK = 30
OUTPUT_DIR = Path.home() / ".canary-wallpaper"
RESOLUTION = (2560, 1440)  # Adjust for your display

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Canary Islands satellite wallpaper")
    parser.add_argument("--island", choices=list(ISLANDS.keys()), help="Specific island")
    parser.add_argument("--size", type=float, default=DEFAULT_BBOX_SIZE_KM, help="Bbox size in km")
    parser.add_argument("--cloud-cover", type=int, default=DEFAULT_MAX_CLOUD_COVER, help="Max cloud %")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS_BACK, help="Days to search back")
    parser.add_argument("--dry-run", action="store_true", help="Don't set wallpaper")
    parser.add_argument("--output", type=Path, help="Custom output path")
    args = parser.parse_args()
    
    OUTPUT_DIR.mkdir(exist_ok=True)
    
    # Generate random bbox
    logger.info(f"Generating random bbox (island={args.island or 'random'}, size={args.size}km)")
    bbox, island_name = generate_random_bbox(
        island=args.island,
        bbox_size_km=args.size
    )
    logger.info(f"Selected: {island_name}, bbox={bbox}")
    
    # Fetch image
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = args.output or OUTPUT_DIR / f"canary_{island_name}_{timestamp}.png"
    
    logger.info(f"Fetching Sentinel-2 imagery (max {args.cloud_cover}% clouds, last {args.days} days)")
    success = fetch_sentinel_image(
        bbox=bbox,
        output_path=str(output_path),
        resolution=RESOLUTION,
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

### Config File (`~/.canary-wallpaper/config.yaml`)

```yaml
sentinel_hub:
  client_id: "your-client-id"
  client_secret: "your-client-secret"

preferences:
  bbox_size_km: 15
  max_cloud_cover: 20
  days_back: 30
  resolution: [2560, 1440]
  
  # Optional: weight islands by preference (default: by area)
  island_weights:
    tenerife: 2.0      # 2x more likely
    gran_canaria: 1.5
    # others default to 1.0
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
sentinelhub>=3.10.0
shapely>=2.0.0
Pillow>=10.0.0
pyyaml>=6.0
requests>=2.31.0

# Optional: for STAC approach
pystac-client>=0.7.0
rasterio>=1.3.0
```

### Installation

```bash
pip install -r requirements.txt
```

---

## Error Handling Considerations

1. **No imagery found**: Increase `days_back` or `max_cloud_cover`, or try different island
2. **API auth failure**: Check credentials, token may need refresh
3. **Rate limits**: Free tier is generous (10k requests/month) but add exponential backoff
4. **Network errors**: Retry with backoff, cache last successful image as fallback
5. **Invalid bbox**: Ensure bbox is within island bounds, has sufficient land coverage
6. **Wallpaper setting fails**: Log error, don't crash - image is still saved

---

## Future Enhancements

- [ ] Web UI for previewing locations before setting
- [ ] Historical image browser (store metadata of past images)
- [ ] Multi-monitor support (different island per display)
- [ ] Seasonal preferences (prefer certain islands at certain times)
- [ ] Integration with liewa for additional satellite sources
- [ ] Notification when new cloud-free imagery becomes available

---

## References

- Copernicus Data Space Ecosystem: https://dataspace.copernicus.eu
- Sentinel Hub Python: https://sentinelhub-py.readthedocs.io
- Element 84 Earth Search STAC: https://earth-search.aws.element84.com/v1
- Sentinel-2 Band Info: https://sentiwiki.copernicus.eu/web/s2-mission
- Live-Earth-Wallpapers (inspiration): https://github.com/lennart-rth/Live-Earth-Wallpapers