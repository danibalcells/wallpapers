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
import random
import sys
from datetime import datetime
from pathlib import Path

import yaml

from islands import generate_random_bbox, generate_random_view, ISLANDS, IslandName, ViewMode
from sentinel import fetch_sentinel_image
from wallpaper import set_wallpaper

DEFAULT_BBOX_SIZE_MIN_KM = 20
DEFAULT_BBOX_SIZE_MAX_KM = 80
DEFAULT_MAX_CLOUD_COVER = 20
DEFAULT_DAYS_BACK = 30
DEFAULT_RESOLUTION = (2880, 2880)  # Square, let macOS crop to fill
PROJECT_DIR = Path(__file__).parent.resolve()
OUTPUT_DIR = PROJECT_DIR / "images"
CONFIG_FILE = PROJECT_DIR / "config.yaml"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


def load_config() -> dict:
    """Load configuration from config file if it exists."""
    if not CONFIG_FILE.exists():
        return {}
    
    try:
        with open(CONFIG_FILE) as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning(f"Failed to load config: {e}")
        return {}


def save_default_config():
    """Create a default config file if none exists."""
    if CONFIG_FILE.exists():
        return
    
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    default_config = {
        "preferences": {
            "bbox_size_min_km": DEFAULT_BBOX_SIZE_MIN_KM,
            "bbox_size_max_km": DEFAULT_BBOX_SIZE_MAX_KM,
            "max_cloud_cover": DEFAULT_MAX_CLOUD_COVER,
            "days_back": DEFAULT_DAYS_BACK,
            "resolution": list(DEFAULT_RESOLUTION),
        }
    }
    
    with open(CONFIG_FILE, "w") as f:
        yaml.dump(default_config, f, default_flow_style=False)
    
    logger.info(f"Created default config at {CONFIG_FILE}")


def cleanup_old_images(directory: Path, keep: int = 10):
    """Remove old wallpaper images, keeping the most recent `keep` files."""
    images = sorted(directory.glob("canary_*.png"), key=lambda p: p.stat().st_mtime)
    for old_image in images[:-keep]:
        try:
            old_image.unlink()
            logger.debug(f"Removed old image: {old_image}")
        except Exception as e:
            logger.warning(f"Failed to remove {old_image}: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Canary Islands Sentinel-2 satellite wallpaper generator"
    )
    parser.add_argument(
        "--island",
        choices=list(ISLANDS.keys()),
        help="Specific island for single mode (default: random)"
    )
    parser.add_argument(
        "--mode",
        choices=["single", "pair"],
        help="View mode: single island or pair of islands (default: random)"
    )
    parser.add_argument(
        "--size",
        type=float,
        help=f"Bbox size in km (default: random {DEFAULT_BBOX_SIZE_MIN_KM}-{DEFAULT_BBOX_SIZE_MAX_KM})"
    )
    parser.add_argument(
        "--cloud-cover",
        type=int,
        help=f"Max cloud %% (default: {DEFAULT_MAX_CLOUD_COVER})"
    )
    parser.add_argument(
        "--days",
        type=int,
        help=f"Days to search back (default: {DEFAULT_DAYS_BACK})"
    )
    parser.add_argument(
        "--resolution",
        nargs=2,
        type=int,
        metavar=("WIDTH", "HEIGHT"),
        help="Output resolution (default: 2560 1440)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't set wallpaper, just save image"
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Custom output path for the image"
    )
    parser.add_argument(
        "--keep",
        type=int,
        default=10,
        help="Number of old images to keep (default: 10)"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    save_default_config()
    config = load_config()
    prefs = config.get("preferences", {})
    island_weights = prefs.get("island_weights")
    
    if args.size:
        bbox_size = args.size
    else:
        bbox_min = prefs.get("bbox_size_min_km", DEFAULT_BBOX_SIZE_MIN_KM)
        bbox_max = prefs.get("bbox_size_max_km", DEFAULT_BBOX_SIZE_MAX_KM)
        bbox_size = random.uniform(bbox_min, bbox_max)
    max_cloud = args.cloud_cover or prefs.get("max_cloud_cover", DEFAULT_MAX_CLOUD_COVER)
    days_back = args.days or prefs.get("days_back", DEFAULT_DAYS_BACK)
    resolution = tuple(args.resolution) if args.resolution else tuple(prefs.get("resolution", DEFAULT_RESOLUTION))
    
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    island_name = args.island
    view_mode = args.mode
    aspect_ratio = (1, 1)  # Always square bbox, let OS handle cropping
    
    mode_str = view_mode or "random"
    island_str = island_name or "random"
    logger.info(f"Generating random bbox (mode={mode_str}, island={island_str}, size={bbox_size:.1f}km)")
    
    try:
        bbox, selected_islands, actual_mode = generate_random_view(
            mode=view_mode,
            island=island_name,
            bbox_size_km=bbox_size,
            island_weights=island_weights,
            aspect_ratio=aspect_ratio
        )
    except ValueError as e:
        logger.error(f"Failed to generate bbox: {e}")
        sys.exit(1)
    
    if actual_mode == "single":
        island_label = selected_islands
        logger.info(f"Selected: {island_label} (single), bbox={bbox}")
    else:
        island_label = f"{selected_islands[0]}_{selected_islands[1]}"
        logger.info(f"Selected: {selected_islands[0]} + {selected_islands[1]} (pair), bbox={bbox}")
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = args.output or OUTPUT_DIR / f"canary_{island_label}_{timestamp}.png"
    
    logger.info(f"Fetching Sentinel-2 imagery (max {max_cloud}% clouds, last {days_back} days)")
    logger.info(f"Resolution: {resolution[0]}x{resolution[1]}")
    
    success = fetch_sentinel_image(
        bbox=bbox,
        output_path=str(output_path),
        resolution=resolution,
        max_cloud_cover=max_cloud,
        days_back=days_back
    )
    
    if not success:
        logger.error("Failed to fetch imagery - no suitable scenes found")
        logger.info("Try increasing --days or --cloud-cover, or try a different island")
        sys.exit(1)
    
    logger.info(f"Saved image to {output_path}")
    
    if not args.dry_run:
        logger.info("Setting wallpaper...")
        if set_wallpaper(str(output_path)):
            logger.info("Wallpaper set successfully!")
        else:
            logger.error("Failed to set wallpaper (image was saved)")
            sys.exit(1)
    else:
        logger.info("Dry run - skipping wallpaper set")
    
    cleanup_old_images(OUTPUT_DIR, keep=args.keep)
    
    logger.info("Done!")


if __name__ == "__main__":
    main()
