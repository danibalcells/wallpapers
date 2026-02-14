"""
Sentinel-2 satellite imagery fetching via STAC API.
"""

import json
import logging
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
import rasterio.windows
from PIL import Image
from pystac_client import Client

from mosaic_selector import (
    MosaicDefinition,
    build_mosaics,
    filter_mosaics,
    filter_mosaics_by_land,
    mosaics_containing_seed,
    pick_mosaic,
    pick_seed,
)
from tiles import CandidateListError, Subtile, load_candidate_subtiles_with_land, parse_tile_id, subtile_bbox_utm

logger = logging.getLogger(__name__)

STAC_API_URL = "https://earth-search.aws.element84.com/v1"
COLLECTION = "sentinel-2-l2a"
CACHE_PATH = Path(__file__).parent / "data" / "tile_status_cache.json"

TRUE_COLOR_DEFAULTS = {
    "max_r": 3.0,
    "mid_r": 0.13,
    "saturation": 1.2,
    "gamma": 1.8,
    "gamma_offset": 0.01,
    "highlight_knee": 0.72,
    "highlight_strength": 5.0,
}


def apply_true_color(
    red: np.ndarray,
    green: np.ndarray,
    blue: np.ndarray,
    max_r: float = 3.0,
    mid_r: float = 0.13,
    saturation: float = 1.2,
    gamma: float = 1.8,
    gamma_offset: float = 0.01,
    highlight_knee: float = 0.82,
    highlight_strength: float = 2.0,
) -> np.ndarray:
    """
    Apply Copernicus-style true color processing to RGB bands.
    
    Based on Copernicus Browser true_color algorithm.
    
    Args:
        red: Red band (B04) as float array, reflectance values (0-1 scale after /10000)
        green: Green band (B03) as float array
        blue: Blue band (B02) as float array
        max_r: Gain/stretch factor for reflectance
        mid_r: Reference midpoint for tone curve
        saturation: Saturation multiplier (1.0 = no change)
        gamma: Gamma correction value
        gamma_offset: Offset added before gamma correction
        highlight_knee: Start of highlight compression in [0, 1]
        highlight_strength: Compression strength for highlights
    
    Returns:
        RGB image as uint8 numpy array with shape (height, width, 3)
    """
    rgb = np.dstack([red, green, blue]).astype(np.float64)
    
    logger.info(f"Raw reflectance stats - min: {rgb.min():.4f}, max: {rgb.max():.4f}, mean: {rgb.mean():.4f}")
    
    gain = 2.5
    rgb = rgb * gain
    rgb = np.maximum(rgb, 0.0)
    
    logger.info(f"After gain ({gain}x) - min: {rgb.min():.4f}, max: {rgb.max():.4f}, mean: {rgb.mean():.4f}")
    
    if highlight_strength > 0 and highlight_knee < 1.0:
        rgb = _compress_highlights(rgb, highlight_knee, highlight_strength)
    
    if saturation != 1.0:
        rgb = _apply_saturation(rgb, saturation)
    
    rgb = np.clip(rgb * 255, 0, 255).astype(np.uint8)
    
    return rgb


def _apply_saturation(rgb: np.ndarray, saturation: float) -> np.ndarray:
    """
    Apply saturation adjustment using luminance-based method (vectorized).
    
    Args:
        rgb: RGB array with values in [0, 1]
        saturation: Multiplier for saturation (1.0 = no change)
    
    Returns:
        RGB array with adjusted saturation
    """
    luminance = 0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]
    luminance = luminance[:, :, np.newaxis]
    
    result = luminance + saturation * (rgb - luminance)
    
    return np.clip(result, 0, 1)


def _compress_highlights(rgb: np.ndarray, knee: float, strength: float) -> np.ndarray:
    if knee <= 0.0:
        knee = 0.0
    if knee >= 1.0 or strength <= 0.0:
        return np.clip(rgb, 0, 1)
    x = np.maximum(rgb, 0.0)
    t = float(knee)
    s = float(strength)
    max_val = max(float(x.max()), 1.0)
    range_above = max(max_val - t, 1e-6)
    denom = 1.0 - np.exp(-s)
    if denom <= 0.0:
        return np.clip(x, 0, 1)
    u = (x - t) / range_above
    u = np.clip(u, 0.0, 1.0)
    comp = 1.0 - np.exp(-s * u)
    y = t + (1.0 - t) * (comp / denom)
    return np.where(x <= t, x, y)


class TileReadError(RuntimeError):
    pass


@dataclass(frozen=True)
class MosaicResult:
    image: np.ndarray
    date: str
    mosaic: MosaicDefinition


@dataclass(frozen=True)
class SubtileBands:
    subtile: Subtile
    red: np.ndarray
    green: np.ndarray
    blue: np.ndarray
    valid_fraction: float


def _empty_cache() -> dict[str, Any]:
    return {"version": 2, "tile_dates": {}, "subtiles": {}, "mosaics": {}}


def _load_cache(path: Path) -> dict[str, Any]:
    try:
        if not path.exists():
            return _empty_cache()
        return json.loads(path.read_text())
    except Exception:
        return _empty_cache()


def _save_cache(path: Path, cache: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2, sort_keys=True))


def _cache_get_tile_item_status(cache: dict[str, Any], date: str, tile_id: str) -> str | None:
    return (
        cache.get("tile_dates", {})
        .get(date, {})
        .get(tile_id, {})
        .get("item")
    )


def _cache_set_tile_item_status(cache: dict[str, Any], date: str, tile_id: str, status: str) -> None:
    cache.setdefault("tile_dates", {}).setdefault(date, {}).setdefault(tile_id, {})["item"] = status


def _cache_get_subtile_status(cache: dict[str, Any], date: str, subtile: Subtile) -> str | None:
    return (
        cache.get("subtiles", {})
        .get(date, {})
        .get(subtile.tile_id, {})
        .get(subtile.suffix())
    )


def _cache_set_subtile_status(cache: dict[str, Any], date: str, subtile: Subtile, status: str) -> None:
    cache.setdefault("subtiles", {}).setdefault(date, {}).setdefault(subtile.tile_id, {})[subtile.suffix()] = status


def _mosaic_key(mosaic: MosaicDefinition) -> str:
    return f"{mosaic.tile_id}:{mosaic.origin_easting},{mosaic.origin_northing}:{mosaic.width}x{mosaic.height}"


def _cache_get_used_mosaics(cache: dict[str, Any], date: str) -> set[str]:
    used = cache.get("mosaics", {}).get(date, [])
    if isinstance(used, list):
        return set(used)
    if isinstance(used, set):
        return used
    return set()


def _cache_add_used_mosaic(cache: dict[str, Any], date: str, mosaic_key: str) -> None:
    mosaics = cache.setdefault("mosaics", {}).setdefault(date, [])
    if isinstance(mosaics, list):
        if mosaic_key not in mosaics:
            mosaics.append(mosaic_key)
        return
    if isinstance(mosaics, set):
        mosaics.add(mosaic_key)


def _available_mosaics(
    mosaics: list[MosaicDefinition],
    invalid_subtiles: set[Subtile],
    used_mosaics: set[str],
) -> list[MosaicDefinition]:
    available = filter_mosaics(mosaics, invalid_subtiles)
    if not used_mosaics:
        return available
    return [mosaic for mosaic in available if _mosaic_key(mosaic) not in used_mosaics]


def fetch_tile_mosaic_image(
    candidate_list_path: Path,
    max_cloud_cover: int = 20,
    days_back: int = 30,
    valid_pixel_min: float = 0.98,
    mosaic_width: int = 4,
    mosaic_height: int = 3,
    rng_seed: int | None = None,
    max_items_per_tile: int = 20,
    min_land_per_subtile: float = 0.05,
    min_subtiles_with_land: int = 2,
) -> MosaicResult | None:
    try:
        candidates, land_fractions = load_candidate_subtiles_with_land(candidate_list_path)
    except CandidateListError as exc:
        logger.error("%s", exc)
        return None
    logger.info("Loaded %d candidate subtiles from %s", len(candidates), candidate_list_path)

    try:
        mosaics = build_mosaics(candidates, width=mosaic_width, height=mosaic_height)
    except ValueError as exc:
        logger.error("%s", exc)
        return None
    if not mosaics:
        logger.error("No %dx%d mosaics available from candidate list", mosaic_width, mosaic_height)
        return None
    logger.info("Built %d mosaics for sampling", len(mosaics))
    if land_fractions:
        mosaics = filter_mosaics_by_land(mosaics, land_fractions, min_land_per_subtile, min_subtiles_with_land)
        if not mosaics:
            logger.error("No mosaics with at least %d subtiles having >= %.1f%% land", min_subtiles_with_land, min_land_per_subtile * 100)
            return None
        logger.info("After land filter: %d mosaics", len(mosaics))

    tile_ids = sorted({subtile.tile_id for subtile in candidates})
    dates = _list_tile_dates(
        tile_ids=tile_ids,
        days_back=days_back,
        max_cloud_cover=max_cloud_cover,
        max_items_per_tile=max_items_per_tile,
    )
    if not dates:
        logger.warning("No imagery dates found for candidate tiles")
        return None

    cache = _load_cache(CACHE_PATH)
    rng = random.Random(rng_seed)
    for date in dates:
        invalid_subtiles: set[Subtile] = set()
        for subtile in candidates:
            if _cache_get_subtile_status(cache, date, subtile) == "invalid":
                invalid_subtiles.add(subtile)
        used_mosaics = _cache_get_used_mosaics(cache, date)
        available = _available_mosaics(mosaics, invalid_subtiles, used_mosaics)
        logger.info("Attempting date %s with %d mosaics", date, len(available))
        while available:
            seed = pick_seed(candidates, invalid_subtiles, rng)
            if seed is None:
                break
            if _cache_get_tile_item_status(cache, date, seed.tile_id) == "none":
                invalid_subtiles.add(seed)
                available = _available_mosaics(mosaics, invalid_subtiles, used_mosaics)
                continue
            seed_mosaics = mosaics_containing_seed(available, seed)
            if not seed_mosaics:
                invalid_subtiles.add(seed)
                available = _available_mosaics(mosaics, invalid_subtiles, used_mosaics)
                continue
            chosen = pick_mosaic(seed_mosaics, rng)
            if chosen is None:
                invalid_subtiles.add(seed)
                available = _available_mosaics(mosaics, invalid_subtiles, used_mosaics)
                continue
            logger.info(
                "Processing tile %s for date %s (mosaic origin %d,%d size %dx%d)",
                chosen.tile_id,
                date,
                chosen.origin_easting,
                chosen.origin_northing,
                chosen.width,
                chosen.height,
            )
            try:
                rgb, failed_subtiles = _attempt_mosaic(
                    mosaic=chosen,
                    date=date,
                    max_cloud_cover=max_cloud_cover,
                    valid_pixel_min=valid_pixel_min,
                    cache=cache,
                )
            except TileReadError as exc:
                logger.warning("%s", exc)
                failed = set(chosen.subtiles)
                failed.add(seed)
                invalid_subtiles.update(failed)
                available = _available_mosaics(mosaics, invalid_subtiles, used_mosaics)
                continue
            if rgb is None:
                failed = set(failed_subtiles)
                failed.add(seed)
                invalid_subtiles.update(failed)
                available = _available_mosaics(mosaics, invalid_subtiles, used_mosaics)
                continue

            _cache_add_used_mosaic(cache, date, _mosaic_key(chosen))
            _save_cache(CACHE_PATH, cache)
            return MosaicResult(image=rgb, date=date, mosaic=chosen)

        logger.info("Exhausted all mosaics for date %s", date)
        _save_cache(CACHE_PATH, cache)

    logger.error("Failed to fetch imagery for any available date")
    _save_cache(CACHE_PATH, cache)
    return None


def _read_band_native_bbox(
    url: str,
    bbox_utm: tuple[float, float, float, float],
) -> np.ndarray | None:
    try:
        with rasterio.open(url) as src:
            window = rasterio.windows.from_bounds(
                *bbox_utm,
                transform=src.transform,
            )
            data = src.read(1, window=window, boundless=True, fill_value=0)
        return data.astype(np.float32) / 10000.0
    except Exception as e:
        logger.error("Error reading native band window from %s: %s", url, e)
        return None


def _item_date(item: object) -> str | None:
    item_datetime = getattr(item, "datetime", None)
    if item_datetime:
        return item_datetime.date().isoformat()
    properties = getattr(item, "properties", {})
    datetime_text = properties.get("datetime")
    if not datetime_text:
        return None
    try:
        parsed = datetime.fromisoformat(datetime_text.replace("Z", "+00:00"))
        return parsed.date().isoformat()
    except ValueError:
        return None


def _asset_proj_bbox(
    item: object,
    asset_key: str,
) -> tuple[float, float, float, float] | None:
    asset = item.assets.get(asset_key)
    if asset is None:
        return None
    proj_bbox = asset.extra_fields.get("proj:bbox")
    if not proj_bbox or len(proj_bbox) != 4:
        try:
            with rasterio.open(asset.href) as src:
                bounds = src.bounds
            return float(bounds.left), float(bounds.bottom), float(bounds.right), float(bounds.top)
        except Exception:
            return None
    return float(proj_bbox[0]), float(proj_bbox[1]), float(proj_bbox[2]), float(proj_bbox[3])

def _list_tile_dates(
    tile_ids: list[str],
    days_back: int,
    max_cloud_cover: int,
    max_items_per_tile: int,
) -> list[str]:
    dates: set[str] = set()
    for tile_id in tile_ids:
        items = _search_tile_items(
            tile_id=tile_id,
            days_back=days_back,
            max_cloud_cover=max_cloud_cover,
            limit=max_items_per_tile,
        )
        for item in items:
            date = _item_date(item)
            if date is not None:
                dates.add(date)
    return sorted(dates, reverse=True)


def _search_tile_items(
    tile_id: str,
    days_back: int,
    max_cloud_cover: int,
    limit: int,
) -> list:
    utm_zone, latitude_band, grid_square = parse_tile_id(tile_id)
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days_back)
    datetime_range = f"{start_date.strftime('%Y-%m-%d')}/{end_date.strftime('%Y-%m-%d')}"
    client = Client.open(STAC_API_URL)
    search = client.search(
        collections=[COLLECTION],
        datetime=datetime_range,
        query={
            "mgrs:utm_zone": {"eq": utm_zone},
            "mgrs:latitude_band": {"eq": latitude_band},
            "mgrs:grid_square": {"eq": grid_square},
            "eo:cloud_cover": {"lt": max_cloud_cover},
        },
        limit=limit,
    )
    items = list(search.items())
    items.sort(
        key=lambda item: getattr(item, "datetime", None) or getattr(item, "properties", {}).get("datetime"),
        reverse=True,
    )
    return items


def _select_item_for_tile_date(
    tile_id: str,
    date: str,
    max_cloud_cover: int,
) -> object | None:
    utm_zone, latitude_band, grid_square = parse_tile_id(tile_id)
    datetime_range = f"{date}T00:00:00Z/{date}T23:59:59Z"
    client = Client.open(STAC_API_URL)
    search = client.search(
        collections=[COLLECTION],
        datetime=datetime_range,
        query={
            "mgrs:utm_zone": {"eq": utm_zone},
            "mgrs:latitude_band": {"eq": latitude_band},
            "mgrs:grid_square": {"eq": grid_square},
            "eo:cloud_cover": {"lt": max_cloud_cover},
        },
        sortby=[{"field": "properties.eo:cloud_cover", "direction": "asc"}],
        limit=5,
    )
    items = list(search.items())
    if not items:
        return None
    return items[0]


def _attempt_mosaic(
    mosaic: MosaicDefinition,
    date: str,
    max_cloud_cover: int,
    valid_pixel_min: float,
    cache: dict[str, Any],
) -> tuple[np.ndarray | None, list[Subtile]]:
    if _cache_get_tile_item_status(cache, date, mosaic.tile_id) == "none":
        return None, list(mosaic.subtiles)
    item = _select_item_for_tile_date(mosaic.tile_id, date, max_cloud_cover)
    if item is None:
        _cache_set_tile_item_status(cache, date, mosaic.tile_id, "none")
        logger.info("No item for tile %s on %s", mosaic.tile_id, date)
        return None, list(mosaic.subtiles)
    _cache_set_tile_item_status(cache, date, mosaic.tile_id, "ok")
    tile_bbox = _asset_proj_bbox(item, "red")
    if tile_bbox is None:
        raise TileReadError(f"Missing proj:bbox for tile {mosaic.tile_id}")

    bands: list[SubtileBands] = []
    for subtile in mosaic.subtiles:
        cached_status = _cache_get_subtile_status(cache, date, subtile)
        if cached_status == "invalid":
            return None, [subtile]
        bbox_utm = subtile_bbox_utm(tile_bbox, subtile)
        red, green, blue = _read_subtile_bands(item, bbox_utm)
        valid_fraction = _valid_pixel_fraction(red, green, blue)
        if valid_fraction < valid_pixel_min:
            _cache_set_subtile_status(cache, date, subtile, "invalid")
            logger.info(
                "Subtile %s%s valid fraction %.3f < %.3f",
                subtile.tile_id,
                subtile.suffix(),
                valid_fraction,
                valid_pixel_min,
            )
            return None, [subtile]
        _cache_set_subtile_status(cache, date, subtile, "valid")
        bands.append(
            SubtileBands(
                subtile=subtile,
                red=red,
                green=green,
                blue=blue,
                valid_fraction=valid_fraction,
            )
        )

    return _mosaic_bands(bands, mosaic), []


def _read_subtile_bands(
    item: object,
    bbox_utm: tuple[float, float, float, float],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    assets = item.assets
    red_asset = assets.get("red")
    green_asset = assets.get("green")
    blue_asset = assets.get("blue")
    if red_asset is None or green_asset is None or blue_asset is None:
        raise TileReadError(f"Missing RGB assets for item {item.id}")
    red = _read_band_native_bbox(red_asset.href, bbox_utm)
    green = _read_band_native_bbox(green_asset.href, bbox_utm)
    blue = _read_band_native_bbox(blue_asset.href, bbox_utm)
    if red is None or green is None or blue is None:
        raise TileReadError(f"Failed to read RGB bands for item {item.id}")
    return red, green, blue


def _valid_pixel_fraction(
    red: np.ndarray,
    green: np.ndarray,
    blue: np.ndarray,
) -> float:
    mask = (red > 0) & (green > 0) & (blue > 0)
    if mask.size == 0:
        return 0.0
    return float(mask.mean())


def _mosaic_bands(
    bands: list[SubtileBands],
    mosaic: MosaicDefinition,
) -> np.ndarray:
    if not bands:
        raise TileReadError("No bands to mosaic")
    tile_height, tile_width = bands[0].red.shape
    height = tile_height * mosaic.height
    width = tile_width * mosaic.width
    red_mosaic = np.zeros((height, width), dtype=np.float32)
    green_mosaic = np.zeros((height, width), dtype=np.float32)
    blue_mosaic = np.zeros((height, width), dtype=np.float32)
    for band in bands:
        row_offset = (mosaic.origin_northing + mosaic.height - 1 - band.subtile.northing) * tile_height
        col_offset = (band.subtile.easting - mosaic.origin_easting) * tile_width
        row_end = row_offset + tile_height
        col_end = col_offset + tile_width
        red_mosaic[row_offset:row_end, col_offset:col_end] = band.red
        green_mosaic[row_offset:row_end, col_offset:col_end] = band.green
        blue_mosaic[row_offset:row_end, col_offset:col_end] = band.blue
    return apply_true_color(red_mosaic, green_mosaic, blue_mosaic, **TRUE_COLOR_DEFAULTS)
