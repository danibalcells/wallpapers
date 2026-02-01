#!/usr/bin/env python3
import logging
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from PIL import Image
from pystac_client import Client

from sentinel import (
    STAC_API_URL,
    COLLECTION,
    apply_true_color,
    _read_band_native_bbox,
    _asset_proj_bbox,
)
from tiles import Subtile, parse_tile_id, subtile_bbox_utm

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

TILE_ID = "28RBS"
SUBTILES = [
    "08", "09", "15", "16", "17", "18", "19",
    "25", "26", "27", "28", "29",
    "36", "37", "38", "39",
]
OUTPUT_DIR = Path("images/tests")
MAX_CLOUD_COVER = 20
DAYS_BACK = 30


def _select_tile_item() -> object:
    utm_zone, latitude_band, grid_square = parse_tile_id(TILE_ID)
    client = Client.open(STAC_API_URL)
    end_date = datetime.now()
    start_date = end_date - timedelta(days=DAYS_BACK)
    datetime_range = f"{start_date.strftime('%Y-%m-%d')}/{end_date.strftime('%Y-%m-%d')}"

    search = client.search(
        collections=[COLLECTION],
        datetime=datetime_range,
        query={
            "mgrs:utm_zone": {"eq": utm_zone},
            "mgrs:latitude_band": {"eq": latitude_band},
            "mgrs:grid_square": {"eq": grid_square},
            "eo:cloud_cover": {"lt": MAX_CLOUD_COVER},
        },
        limit=5,
    )
    logger.info(
        "Searching for tile %s (zone=%s band=%s square=%s) in %s",
        TILE_ID,
        utm_zone,
        latitude_band,
        grid_square,
        datetime_range,
    )
    items = list(search.items())
    if not items:
        raise RuntimeError(f"No items found for tile {TILE_ID}")
    logger.info("Found %d item(s) for %s, selecting first result", len(items), TILE_ID)
    return items[0]


def _read_rgb_for_bbox(
    item: object,
    bbox_utm: tuple[float, float, float, float],
) -> np.ndarray:
    bands: dict[str, np.ndarray] = {}
    for band_key in ("red", "green", "blue"):
        asset = item.assets.get(band_key)
        if asset is None:
            raise RuntimeError(f"Missing {band_key} asset for {item.id}")
        band_data = _read_band_native_bbox(asset.href, bbox_utm)
        if band_data is None:
            raise RuntimeError(f"Failed to read {band_key} band for {item.id}")
        bands[band_key] = band_data
    return apply_true_color(bands["red"], bands["green"], bands["blue"])


def _write_image(rgb: np.ndarray, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgb).save(output_path, "PNG", optimize=True)


def main() -> None:
    item = _select_tile_item()
    tile_bbox = _asset_proj_bbox(item, "red")
    if tile_bbox is None:
        raise RuntimeError("Missing proj:bbox for red asset")

    logger.info("Using item %s for tile %s", item.id, TILE_ID)
    outputs: list[tuple[str, tuple[float, float, float, float]]] = []
    outputs.append((TILE_ID, tile_bbox))
    for suffix in SUBTILES:
        easting = int(suffix[0])
        northing = int(suffix[1])
        outputs.append((f"{TILE_ID}{suffix}", subtile_bbox_utm(tile_bbox, Subtile(tile_id=TILE_ID, easting=easting, northing=northing))))

    for tile_name, bbox_utm in outputs:
        logger.info("Rendering %s bbox=%s", tile_name, bbox_utm)
        rgb = _read_rgb_for_bbox(item, bbox_utm)
        output_path = OUTPUT_DIR / f"{tile_name}.png"
        _write_image(rgb, output_path)
        logger.info("Saved %s", output_path)


if __name__ == "__main__":
    main()
