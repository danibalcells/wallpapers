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
import random
import re
import sys
from datetime import date, datetime
from pathlib import Path

import yaml

from PIL import Image

from mosaic_reference import (
    format_top_left_subtile,
    resolve_manual_selection,
)
from sentinel import fetch_tile_mosaic_image
from wallpaper import set_wallpaper

DEFAULT_MAX_CLOUD_COVER = 100
DEFAULT_DAYS_BACK = 30
DEFAULT_VALID_PIXEL_MIN = 0.98
DEFAULT_MOSAIC_WIDTH = 4
DEFAULT_MOSAIC_HEIGHT = 3
DEFAULT_MIN_LAND_PER_SUBTILE = 0.05
DEFAULT_MIN_SUBTILES_WITH_LAND = 1
ALL_NAMED_ISLANDS = [
    "el_hierro", "fuerteventura", "gran_canaria", "la_gomera",
    "la_graciosa", "la_palma", "lanzarote", "tenerife",
]
PROJECT_DIR = Path(__file__).parent.resolve()
OUTPUT_DIR = PROJECT_DIR / "images"
CONFIG_FILE = PROJECT_DIR / "config.yaml"
DEFAULT_CANDIDATE_LIST = PROJECT_DIR / "data" / "subtile_candidates.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logging.getLogger("botocore").setLevel(logging.WARNING)
logging.getLogger("boto3").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("rasterio").setLevel(logging.WARNING)
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


def parse_shape(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d+)x(\d+)", value.strip().lower())
    if not match:
        raise argparse.ArgumentTypeError("Expected shape as WxH, e.g. 4x3")
    width = int(match.group(1))
    height = int(match.group(2))
    if width < 1 or height < 1 or width > 10 or height > 10:
        raise argparse.ArgumentTypeError("Shape width and height must be between 1 and 10")
    return width, height


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
            "min_land_per_subtile": DEFAULT_MIN_LAND_PER_SUBTILE,
            "min_subtiles_with_land": DEFAULT_MIN_SUBTILES_WITH_LAND,
        }
    }
    
    with open(CONFIG_FILE, "w") as f:
        yaml.dump(default_config, f, default_flow_style=False)
    
    logger.info(f"Created default config at {CONFIG_FILE}")


def count_images_generated_today(directory: Path) -> int:
    today_str = date.today().strftime("%Y%m%d")
    count = 0
    for path in directory.glob("canary_mosaic_*_*.png"):
        parts = path.stem.split("_")
        if len(parts) >= 5:
            gen_date = parts[-2]
            if gen_date == today_str:
                count += 1
    return count


def cleanup_old_images(directory: Path, keep: int = 10):
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
        "--shape",
        type=parse_shape,
        help=f"Mosaic shape WxH (default: {DEFAULT_MOSAIC_WIDTH}x{DEFAULT_MOSAIC_HEIGHT})",
    )
    parser.add_argument(
        "--top-left-subtile",
        type=str,
        help="Use this exact top-left subtile, e.g. 28RCS02"
    )
    parser.add_argument(
        "--from-image",
        type=str,
        help="Derive date and top-left subtile from an existing image filename or path"
    )
    parser.add_argument(
        "--offset-east",
        type=int,
        default=0,
        help="Shift the requested top-left subtile east or west by this many mini-tiles"
    )
    parser.add_argument(
        "--offset-north",
        type=int,
        default=0,
        help="Shift the requested top-left subtile north or south by this many mini-tiles"
    )
    parser.add_argument(
        "--date",
        type=str,
        help="Use this exact capture date (YYYY-MM-DD or YYYYMMDD)"
    )
    parser.add_argument(
        "--seed",
        type=int,
        help="Random seed for mosaic selection"
    )
    parser.add_argument(
        "--min-land-per-subtile",
        type=float,
        help=f"Minimum land fraction per subtile to count as 'has land' (default: {DEFAULT_MIN_LAND_PER_SUBTILE})"
    )
    parser.add_argument(
        "--min-subtiles-with-land",
        type=int,
        help=f"Minimum number of subtiles with land required per mosaic (default: {DEFAULT_MIN_SUBTILES_WITH_LAND})"
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
        "--island",
        type=str,
        metavar="NAME",
        help=(
            "Restrict selection to a single island. "
            "Valid names: tenerife, gran_canaria, fuerteventura, lanzarote, "
            "la_graciosa, la_palma, la_gomera, el_hierro"
        ),
    )
    parser.add_argument(
        "--count",
        type=int,
        default=1,
        metavar="N",
        help=(
            "Number of images to generate in one run (default: 1). "
            "When N > 1, each image is drawn from a distinct randomly-chosen island. "
            "Cannot be combined with --island."
        ),
    )
    parser.add_argument(
        "--island-pool",
        type=str,
        nargs="+",
        metavar="NAME",
        help=(
            "Pool of islands to sample from when --count > 1. "
            f"Defaults to all named islands: {', '.join(ALL_NAMED_ISLANDS)}"
        ),
    )
    parser.add_argument(
        "--max-per-day",
        type=int,
        help="Skip generation if this many images were already generated today"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    args = parser.parse_args()

    if args.count > 1 and args.island:
        parser.error("--count and --island cannot be used together; use --island-pool to restrict the pool")

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    save_default_config()
    config = load_config()
    prefs = config.get("preferences", {})
    candidate_list = args.candidate_list or Path(prefs.get("candidate_list", str(DEFAULT_CANDIDATE_LIST)))
    if not candidate_list.is_absolute():
        candidate_list = PROJECT_DIR / candidate_list
    valid_pixel_min = args.valid_pixel_min if args.valid_pixel_min is not None else prefs.get("valid_pixel_min", DEFAULT_VALID_PIXEL_MIN)
    if args.shape is None:
        mosaic_width = args.mosaic_width or prefs.get("mosaic_width", DEFAULT_MOSAIC_WIDTH)
        mosaic_height = args.mosaic_height or prefs.get("mosaic_height", DEFAULT_MOSAIC_HEIGHT)
    else:
        mosaic_width, mosaic_height = args.shape
    max_cloud = args.cloud_cover or prefs.get("max_cloud_cover", DEFAULT_MAX_CLOUD_COVER)
    days_back = args.days or prefs.get("days_back", DEFAULT_DAYS_BACK)
    rng_seed = args.seed
    min_land_per_subtile = args.min_land_per_subtile if args.min_land_per_subtile is not None else prefs.get("min_land_per_subtile", DEFAULT_MIN_LAND_PER_SUBTILE)
    min_subtiles_with_land = args.min_subtiles_with_land if args.min_subtiles_with_land is not None else prefs.get("min_subtiles_with_land", DEFAULT_MIN_SUBTILES_WITH_LAND)

    try:
        selected_top_left_subtile, selected_date = resolve_manual_selection(
            top_left_subtile=args.top_left_subtile,
            from_image=args.from_image,
            offset_east=args.offset_east,
            offset_north=args.offset_north,
            exact_date=args.date,
        )
    except ValueError as exc:
        parser.error(str(exc))
    
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    max_per_day = args.max_per_day
    if max_per_day is not None:
        existing = count_images_generated_today(OUTPUT_DIR)
        if existing >= max_per_day:
            logger.info("Already generated %d image(s) today (max %d), skipping", existing, max_per_day)
            sys.exit(0)

    if args.count > 1:
        pool = list(args.island_pool or ALL_NAMED_ISLANDS)
        rng = random.Random(rng_seed)
        rng.shuffle(pool)
        island_filters: list[str | None] = [pool[i % len(pool)] for i in range(args.count)]
    else:
        island_filters = [args.island or None]

    logger.info("Selecting %dx%d tile mosaic from %s", mosaic_width, mosaic_height, candidate_list)
    if selected_top_left_subtile is not None:
        logger.info("Requested top-left subtile: %s", selected_top_left_subtile)
    if selected_date is not None:
        logger.info("Requested capture date: %s", selected_date)
    logger.info("Fetching Sentinel-2 imagery (max %d%% clouds, last %d days)", max_cloud, days_back)

    saved_paths: list[Path] = []
    for i, island_filter in enumerate(island_filters):
        if island_filter:
            logger.info("Image %d/%d — island: %s", i + 1, len(island_filters), island_filter)
        per_image_seed = (rng_seed + i) if rng_seed is not None else None

        result = fetch_tile_mosaic_image(
            candidate_list_path=candidate_list,
            max_cloud_cover=max_cloud,
            days_back=days_back,
            valid_pixel_min=valid_pixel_min,
            mosaic_width=mosaic_width,
            mosaic_height=mosaic_height,
            rng_seed=per_image_seed,
            min_land_per_subtile=min_land_per_subtile,
            min_subtiles_with_land=min_subtiles_with_land,
            island_filter=island_filter,
            top_left_subtile=selected_top_left_subtile,
            offset_east=args.offset_east,
            offset_north=args.offset_north,
            exact_date=selected_date,
        )

        if result is None:
            logger.error(
                "Failed to fetch imagery for island %s — no suitable mosaics found",
                island_filter or "(any)",
            )
            continue

        mosaic = result.mosaic
        top_left_tile = format_top_left_subtile(mosaic.top_left_subtile)
        capture_date = result.date.replace("-", "")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = (
            args.output
            if (args.output and len(island_filters) == 1)
            else OUTPUT_DIR / f"canary_mosaic_{capture_date}_{top_left_tile}_{timestamp}.png"
        )
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(result.image).save(output_path, "PNG", optimize=True)
        logger.info("Saved image to %s", output_path)
        saved_paths.append(output_path)

    if not saved_paths:
        logger.error("No images were generated successfully")
        sys.exit(1)

    if args.set_wallpaper and not args.dry_run:
        logger.info("Setting wallpaper...")
        if set_wallpaper(str(saved_paths[-1])):
            logger.info("Wallpaper set successfully!")
        else:
            logger.error("Failed to set wallpaper (images were saved)")
            sys.exit(1)
    else:
        logger.info("Skipping wallpaper set (use --set-wallpaper)")
    
    cleanup_old_images(OUTPUT_DIR, keep=args.keep)
    
    logger.info("Done! Generated %d/%d image(s).", len(saved_paths), len(island_filters))


if __name__ == "__main__":
    main()
