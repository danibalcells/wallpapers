#!/usr/bin/env python3
"""Fetch a Sentinel-2 image for a fixed bbox and save pre/post color outputs."""

import argparse
import logging
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from PIL import Image
from pystac_client import Client

from main import DEFAULT_RESOLUTION
from sentinel import (
    COLLECTION,
    STAC_API_URL,
    TRUE_COLOR_DEFAULTS,
    apply_true_color,
    _read_band_as_reflectance,
)

DEFAULT_BBOX = (-16.06818, 27.05682, -13.18182, 29.94318)
DEFAULT_MAX_CLOUD_COVER = 20
DEFAULT_DAYS_BACK = 30

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def _select_best_item(
    bbox: tuple[float, float, float, float],
    max_cloud_cover: int,
    days_back: int,
) -> object | None:
    client = Client.open(STAC_API_URL)
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days_back)
    datetime_range = f"{start_date.strftime('%Y-%m-%d')}/{end_date.strftime('%Y-%m-%d')}"
    search = client.search(
        collections=[COLLECTION],
        bbox=bbox,
        datetime=datetime_range,
        query={"eo:cloud_cover": {"lt": max_cloud_cover}},
        sortby=[{"field": "properties.eo:cloud_cover", "direction": "asc"}],
        limit=10,
    )
    items = list(search.items())
    if not items:
        return None
    return items[0]


def _save_image(rgb: np.ndarray, output_path: Path) -> None:
    image = Image.fromarray(rgb)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, "PNG", optimize=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch and save bbox imagery pre/post color correction")
    parser.add_argument(
        "--bbox",
        type=str,
        default=",".join(str(value) for value in DEFAULT_BBOX),
        help="BBox as west,south,east,north (WGS84)",
    )
    parser.add_argument("--resolution", nargs=2, type=int, default=DEFAULT_RESOLUTION)
    parser.add_argument("--cloud-cover", type=int, default=DEFAULT_MAX_CLOUD_COVER)
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS_BACK)
    parser.add_argument("--output-dir", type=Path, default=Path("images"))
    args = parser.parse_args()

    bbox = tuple(float(value) for value in args.bbox.split(","))
    if len(bbox) != 4:
        raise ValueError("Expected bbox format west,south,east,north")

    item = _select_best_item(bbox, args.cloud_cover, args.days)
    if item is None:
        raise RuntimeError("No imagery found for bbox")

    red_url = item.assets["red"].href
    green_url = item.assets["green"].href
    blue_url = item.assets["blue"].href

    resolution = tuple(args.resolution)
    red = _read_band_as_reflectance(red_url, bbox, resolution)
    green = _read_band_as_reflectance(green_url, bbox, resolution)
    blue = _read_band_as_reflectance(blue_url, bbox, resolution)

    if red is None or green is None or blue is None:
        raise RuntimeError("Failed to read one or more bands")

    raw_rgb = np.clip(np.dstack([red, green, blue]), 0, 1)
    raw_rgb = (raw_rgb * 255).astype(np.uint8)

    corrected_rgb = apply_true_color(
        red,
        green,
        blue,
        **TRUE_COLOR_DEFAULTS,
    )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    pre_path = args.output_dir / f"bbox_pre_color_{timestamp}.png"
    post_path = args.output_dir / f"bbox_post_color_{timestamp}.png"

    _save_image(raw_rgb, pre_path)
    _save_image(corrected_rgb, post_path)

    logger.info(f"Saved pre-color image: {pre_path}")
    logger.info(f"Saved post-color image: {post_path}")


if __name__ == "__main__":
    main()
