"""
Sentinel-2 satellite imagery fetching via STAC API.
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from pystac_client import Client
from rasterio.warp import reproject, Resampling
from shapely.geometry import box, shape

logger = logging.getLogger(__name__)

STAC_API_URL = "https://earth-search.aws.element84.com/v1"
COLLECTION = "sentinel-2-l2a"

TRUE_COLOR_DEFAULTS = {
    "max_r": 3.0,
    "mid_r": 0.13,
    "saturation": 1.2,
    "gamma": 1.8,
    "gamma_offset": 0.01,
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
    
    Returns:
        RGB image as uint8 numpy array with shape (height, width, 3)
    """
    rgb = np.dstack([red, green, blue]).astype(np.float64)
    
    logger.info(f"Raw reflectance stats - min: {rgb.min():.4f}, max: {rgb.max():.4f}, mean: {rgb.mean():.4f}")
    
    gain = 2.5
    rgb = rgb * gain
    rgb = np.clip(rgb, 0, 1)
    
    logger.info(f"After gain ({gain}x) - min: {rgb.min():.4f}, max: {rgb.max():.4f}, mean: {rgb.mean():.4f}")
    
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


def fetch_sentinel_image(
    bbox: tuple[float, float, float, float],
    output_path: str,
    resolution: tuple[int, int] = (1920, 1080),
    max_cloud_cover: int = 20,
    days_back: int = 30,
    max_nodata_pct: float = 5.0,
    max_defective_pct: float = 20.0,
    max_degraded_pct: float = 10.0,
    min_bbox_coverage: float = 0.995,
) -> bool:
    """
    Fetch Sentinel-2 L2A image for bbox via Element 84 STAC API (no auth needed).
    
    Args:
        bbox: (west, south, east, north) in WGS84
        output_path: Where to save the PNG
        resolution: Output image dimensions (width, height)
        max_cloud_cover: Maximum cloud coverage percentage (0-100)
        days_back: How far back to search for imagery
    
    Returns:
        True if successful, False if no suitable imagery found
    """
    try:
        client = Client.open(STAC_API_URL)
        
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days_back)
        datetime_range = f"{start_date.strftime('%Y-%m-%d')}/{end_date.strftime('%Y-%m-%d')}"
        
        logger.info(f"Searching for imagery from {datetime_range}")
        
        search = client.search(
            collections=[COLLECTION],
            bbox=bbox,
            datetime=datetime_range,
            query={"eo:cloud_cover": {"lt": max_cloud_cover}},
            sortby=[{"field": "properties.eo:cloud_cover", "direction": "asc"}],
            limit=10
        )
        
        items = list(search.items())
        if not items:
            logger.warning("No imagery found matching criteria")
            return False
        
        item = _select_acceptable_item(
            items,
            bbox=bbox,
            max_nodata_pct=max_nodata_pct,
            max_defective_pct=max_defective_pct,
            max_degraded_pct=max_degraded_pct,
            min_bbox_coverage=min_bbox_coverage,
        )
        if item is None:
            logger.warning("No imagery found matching quality thresholds")
            return False

        logger.info(f"Found image: {item.id}, cloud cover: {item.properties.get('eo:cloud_cover', 'N/A')}%")
        
        red_url = item.assets["red"].href
        green_url = item.assets["green"].href
        blue_url = item.assets["blue"].href
        
        logger.info("Downloading and processing RGB bands...")
        bands = {}
        for band_name, url in [("red", red_url), ("green", green_url), ("blue", blue_url)]:
            logger.debug(f"Fetching {band_name} band")
            band_data = _read_band_as_reflectance(url, bbox, resolution)
            if band_data is None:
                logger.error(f"Failed to read {band_name} band")
                return False
            bands[band_name] = band_data
        
        logger.info("Applying true color processing...")
        rgb = apply_true_color(
            bands["red"],
            bands["green"],
            bands["blue"],
            **TRUE_COLOR_DEFAULTS
        )
        
        img = Image.fromarray(rgb)
        
        if img.size != resolution:
            img = img.resize(resolution, Image.Resampling.LANCZOS)
        
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        img.save(output_path, "PNG", optimize=True)
        logger.info(f"Saved image to {output_path}")
        
        return True
        
    except Exception as e:
        logger.error(f"Error fetching Sentinel imagery: {e}")
        return False


def _read_band_as_reflectance(
    url: str,
    bbox: tuple[float, float, float, float],
    target_resolution: tuple[int, int]
) -> np.ndarray | None:
    """
    Read a band from a COG URL, extracting only the bbox area.
    
    Args:
        url: URL to the Cloud Optimized GeoTIFF
        bbox: (west, south, east, north) in WGS84
        target_resolution: Target (width, height) for the output
    
    Returns:
        Float array with reflectance values (0-1 scale), or None on failure.
        Sentinel-2 L2A values are stored as uint16 with scale factor 10000.
    """
    try:
        west, south, east, north = bbox
        target_width, target_height = target_resolution
        
        with rasterio.open(url) as src:
            dst_crs = "EPSG:4326"
            
            out_transform = rasterio.transform.from_bounds(
                west, south, east, north, target_width, target_height
            )
            
            data = np.zeros((target_height, target_width), dtype=np.float32)
            
            reproject(
                source=rasterio.band(src, 1),
                destination=data,
                src_transform=src.transform,
                src_crs=src.crs,
                dst_transform=out_transform,
                dst_crs=dst_crs,
                resampling=Resampling.cubic
            )
            
            reflectance = data / 10000.0
            
            return reflectance
            
    except Exception as e:
        logger.error(f"Error reading band from {url}: {e}")
        return None


def _select_acceptable_item(
    items: list,
    bbox: tuple[float, float, float, float],
    max_nodata_pct: float,
    max_defective_pct: float,
    max_degraded_pct: float,
    min_bbox_coverage: float,
) -> object | None:
    bbox_coverage = None
    for item in items:
        nodata = item.properties.get("s2:nodata_pixel_percentage")
        defective = item.properties.get("s2:saturated_defective_pixel_percentage")
        degraded = item.properties.get("s2:degraded_msi_data_percentage")
        bbox_coverage = _bbox_coverage_fraction(item, bbox)

        logger.info(
            "Item %s quality stats: nodata=%s defective=%s degraded=%s bbox_coverage=%s",
            item.id,
            "N/A" if nodata is None else f"{nodata:.2f}%",
            "N/A" if defective is None else f"{defective:.2f}%",
            "N/A" if degraded is None else f"{degraded:.2f}%",
            "N/A" if bbox_coverage is None else f"{bbox_coverage * 100:.2f}%",
        )

        if bbox_coverage is not None and bbox_coverage < min_bbox_coverage:
            logger.info(
                "Rejecting %s (bbox coverage %.2f%% < %.2f%%)",
                item.id,
                bbox_coverage * 100,
                min_bbox_coverage * 100,
            )
            continue
        if nodata is not None and nodata > max_nodata_pct:
            logger.info(
                "Rejecting %s (nodata %.2f%% > %.2f%%)",
                item.id,
                nodata,
                max_nodata_pct,
            )
            continue
        if defective is not None and defective > max_defective_pct:
            logger.info(
                "Rejecting %s (defective %.2f%% > %.2f%%)",
                item.id,
                defective,
                max_defective_pct,
            )
            continue
        if degraded is not None and degraded > max_degraded_pct:
            logger.info(
                "Rejecting %s (degraded %.2f%% > %.2f%%)",
                item.id,
                degraded,
                max_degraded_pct,
            )
            continue
        logger.info("Selected item %s", item.id)
        return item
    return None


def _bbox_coverage_fraction(
    item: object,
    bbox: tuple[float, float, float, float],
) -> float | None:
    geometry = getattr(item, "geometry", None)
    if not geometry:
        return None
    try:
        item_polygon = shape(geometry)
    except Exception as exc:
        logger.info("Failed to parse item geometry: %s", exc)
        return None
    if item_polygon.is_empty:
        return None
    bbox_polygon = box(*bbox)
    if bbox_polygon.area <= 0:
        return None
    intersection = item_polygon.intersection(bbox_polygon)
    return intersection.area / bbox_polygon.area


def search_available_imagery(
    bbox: tuple[float, float, float, float],
    max_cloud_cover: int = 20,
    days_back: int = 30,
    limit: int = 10
) -> list[dict]:
    """
    Search for available Sentinel-2 imagery without downloading.
    
    Returns a list of dicts with image metadata.
    """
    try:
        client = Client.open(STAC_API_URL)
        
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days_back)
        datetime_range = f"{start_date.strftime('%Y-%m-%d')}/{end_date.strftime('%Y-%m-%d')}"
        
        search = client.search(
            collections=[COLLECTION],
            bbox=bbox,
            datetime=datetime_range,
            query={"eo:cloud_cover": {"lt": max_cloud_cover}},
            sortby=[{"field": "datetime", "direction": "desc"}],
            limit=limit
        )
        
        results = []
        for item in search.items():
            results.append({
                "id": item.id,
                "datetime": item.datetime.isoformat() if item.datetime else None,
                "cloud_cover": item.properties.get("eo:cloud_cover"),
                "bbox": item.bbox
            })
        
        return results
        
    except Exception as e:
        logger.error(f"Error searching imagery: {e}")
        return []
