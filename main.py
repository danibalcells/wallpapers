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
from datetime import datetime
from pathlib import Path

import yaml

from sentinel import fetch_tile_mosaic_image
from wallpaper import set_wallpaper

DEFAULT_MAX_CLOUD_COVER = 20
DEFAULT_DAYS_BACK = 30
DEFAULT_VALID_PIXEL_MIN = 0.98
DEFAULT_MOSAIC_WIDTH = 4
DEFAULT_MOSAIC_HEIGHT = 3
PROJECT_DIR = Path(__file__).parent.resolve()
OUTPUT_DIR = PROJECT_DIR / "images"
CONFIG_FILE = PROJECT_DIR / "config.yaml"
DEFAULT_CANDIDATE_LIST = PROJECT_DIR / "data" / "subtile_candidates.json"

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
            "max_cloud_cover": DEFAULT_MAX_CLOUD_COVER,
            "days_back": DEFAULT_DAYS_BACK,
            "candidate_list": str(DEFAULT_CANDIDATE_LIST),
            "valid_pixel_min": DEFAULT_VALID_PIXEL_MIN,
            "mosaic_width": DEFAULT_MOSAIC_WIDTH,
            "mosaic_height": DEFAULT_MOSAIC_HEIGHT,
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
        "--candidate-list",
        type=Path,
        help="Path to candidate subtile list JSON"
    )
    parser.add_argument(
        "--valid-pixel-min",
        type=float,
        help=f"Minimum valid pixel fraction per subtile (default: {DEFAULT_VALID_PIXEL_MIN})"
    )
    parser.add_argument(
        "--mosaic-width",
        type=int,
        help=f"Mosaic width in 10km subtiles (default: {DEFAULT_MOSAIC_WIDTH})"
    )
    parser.add_argument(
        "--mosaic-height",
        type=int,
        help=f"Mosaic height in 10km subtiles (default: {DEFAULT_MOSAIC_HEIGHT})"
    )
    parser.add_argument(
        "--seed",
        type=int,
        help="Random seed for mosaic selection"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't set wallpaper, just save image"
    )
    parser.add_argument(
        "--set-wallpaper",
        action="store_true",
        help="Set wallpaper after downloading image"
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
    candidate_list = args.candidate_list or Path(prefs.get("candidate_list", str(DEFAULT_CANDIDATE_LIST)))
    if not candidate_list.is_absolute():
        candidate_list = PROJECT_DIR / candidate_list
    valid_pixel_min = args.valid_pixel_min if args.valid_pixel_min is not None else prefs.get("valid_pixel_min", DEFAULT_VALID_PIXEL_MIN)
    mosaic_width = args.mosaic_width or prefs.get("mosaic_width", DEFAULT_MOSAIC_WIDTH)
    mosaic_height = args.mosaic_height or prefs.get("mosaic_height", DEFAULT_MOSAIC_HEIGHT)
    max_cloud = args.cloud_cover or prefs.get("max_cloud_cover", DEFAULT_MAX_CLOUD_COVER)
    days_back = args.days or prefs.get("days_back", DEFAULT_DAYS_BACK)
    rng_seed = args.seed
    
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    logger.info("Selecting %dx%d tile mosaic from %s", mosaic_width, mosaic_height, candidate_list)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = args.output or OUTPUT_DIR / f"canary_mosaic_{timestamp}.png"

    logger.info(f"Fetching Sentinel-2 imagery (max {max_cloud}% clouds, last {days_back} days)")
    success = fetch_tile_mosaic_image(
        candidate_list_path=candidate_list,
        output_path=str(output_path),
        max_cloud_cover=max_cloud,
        days_back=days_back,
        valid_pixel_min=valid_pixel_min,
        mosaic_width=mosaic_width,
        mosaic_height=mosaic_height,
        rng_seed=rng_seed,
    )

    if not success:
        logger.error("Failed to fetch imagery - no suitable mosaics found")
        logger.info("Try increasing --days or --cloud-cover, or update the candidate list")
        sys.exit(1)

    logger.info(f"Saved image to {output_path}")
    
    # if not args.dry_run:
    #     logger.info("Setting wallpaper...")
    #     if set_wallpaper(str(output_path)):
    #         logger.info("Wallpaper set successfully!")
    #     else:
    #         logger.error("Failed to set wallpaper (image was saved)")
    #         sys.exit(1)
    # else:
    #     logger.info("Dry run - skipping wallpaper set")
    if args.set_wallpaper and not args.dry_run:
        logger.info("Setting wallpaper...")
        if set_wallpaper(str(output_path)):
            logger.info("Wallpaper set successfully!")
        else:
            logger.error("Failed to set wallpaper (image was saved)")
            sys.exit(1)
    else:
        logger.info("Skipping wallpaper set (use --set-wallpaper)")
    
    cleanup_old_images(OUTPUT_DIR, keep=args.keep)
    
    logger.info("Done!")


if __name__ == "__main__":
    main()
