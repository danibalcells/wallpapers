"""
Island polygons and random bbox generation for Canary Islands.
"""

import random
from typing import Literal
from shapely.geometry import Polygon, Point, box
from shapely.ops import unary_union

IslandName = Literal[
    "tenerife", "fuerteventura", "gran_canaria", "lanzarote",
    "la_palma", "la_gomera", "el_hierro", "la_graciosa"
]

ViewMode = Literal["single", "pair"]

ISLANDS: dict[IslandName, dict] = {
    "tenerife": {
        "area_km2": 2034,
        "polygon": Polygon([
            (-16.971, 27.951), (-16.85, 28.05), (-16.75, 28.08), (-16.65, 28.12),
            (-16.55, 28.18), (-16.45, 28.25), (-16.35, 28.35), (-16.25, 28.42),
            (-16.1, 28.50), (-16.15, 28.55), (-16.20, 28.58), (-16.30, 28.623),
            (-16.45, 28.58), (-16.55, 28.55), (-16.65, 28.50), (-16.75, 28.42),
            (-16.82, 28.35), (-16.88, 28.25), (-16.90, 28.15), (-16.971, 27.951)
        ])
    },
    "fuerteventura": {
        "area_km2": 1659,
        "polygon": Polygon([
            (-14.53, 28.05), (-14.45, 28.08), (-14.38, 28.15), (-14.30, 28.25),
            (-14.22, 28.35), (-14.15, 28.45), (-14.08, 28.55), (-14.00, 28.65),
            (-13.95, 28.72), (-13.85, 28.78), (-13.79, 28.70), (-13.85, 28.60),
            (-13.90, 28.50), (-13.95, 28.40), (-14.02, 28.30), (-14.10, 28.20),
            (-14.20, 28.12), (-14.30, 28.05), (-14.40, 28.03), (-14.53, 28.05)
        ])
    },
    "gran_canaria": {
        "area_km2": 1560,
        "polygon": Polygon([
            (-15.853, 27.725), (-15.80, 27.78), (-15.70, 27.82), (-15.60, 27.85),
            (-15.50, 27.88), (-15.40, 27.92), (-15.335, 28.00), (-15.38, 28.08),
            (-15.45, 28.14), (-15.55, 28.2), (-15.65, 28.15), (-15.75, 28.10),
            (-15.82, 28.02), (-15.853, 27.92), (-15.853, 27.82), (-15.853, 27.725)
        ])
    },
    "lanzarote": {
        "area_km2": 846,
        "polygon": Polygon([
            (-13.90294, 28.8232), (-13.88, 28.90), (-13.78, 28.95), (-13.65, 29.02),
            (-13.55, 29.10), (-13.45, 29.18), (-13.40607, 29.30963), (-13.45, 29.22),
            (-13.55, 29.18), (-13.65, 29.12), (-13.75, 29.05), (-13.85, 28.98),
            (-13.90294, 28.92), (-13.90294, 28.8232)
        ])
    },
    "la_graciosa": {
        "area_km2": 29,
        "polygon": Polygon([
            (-13.91, 29.22), (-13.82, 29.22), (-13.82, 29.31), (-13.91, 29.31),
            (-13.91, 29.22)
        ])
    },
    "la_palma": {
        "area_km2": 708,
        "polygon": Polygon([
            (-18.02, 28.44), (-17.98, 28.52), (-17.92, 28.58), (-17.85, 28.65),
            (-17.78, 28.75), (-17.7, 28.85), (-17.75, 28.87), (-17.80, 28.85),
            (-17.88, 28.78), (-17.95, 28.68), (-18.00, 28.58), (-18.02, 28.44)
        ])
    },
    "la_gomera": {
        "area_km2": 370,
        "polygon": Polygon([
            (-17.3489614, 28.0197564), (-17.30, 28.08), (-17.22, 28.12), (-17.12, 28.15),
            (-17.0983496, 28.18), (-17.0983496, 28.2187038), (-17.15, 28.20), (-17.25, 28.17),
            (-17.32, 28.12), (-17.3489614, 28.0197564)
        ])
    },
    "el_hierro": {
        "area_km2": 269,
        "polygon": Polygon([
            (-18.1611809, 27.6377389), (-18.10, 27.72), (-18.02, 27.76), (-17.92, 27.80),
            (-17.8828091, 27.8498493), (-17.92, 27.82), (-18.02, 27.78), (-18.10, 27.72),
            (-18.1611809, 27.6377389)
        ])
    }
}

NEIGHBOR_ISLANDS: dict[IslandName, tuple[IslandName, ...]] = {
    "la_palma": ("la_gomera", "el_hierro"),
    "la_gomera": ("la_palma", "tenerife", "el_hierro"),
    "tenerife": ("la_gomera", "gran_canaria"),
    "gran_canaria": ("tenerife", "lanzarote"),
    "lanzarote": ("gran_canaria", "fuerteventura", "la_graciosa"),
    "la_graciosa": ("lanzarote",),
    "fuerteventura": ("lanzarote",),
    "el_hierro": ("la_palma", "la_gomera"),
}
LATITUDE_KM = 111.0
LONGITUDE_KM_AT_28N = 97.0
MIN_BBOX_WIDTH_KM_SMALL = 15.0
MIN_BBOX_WIDTH_KM_LARGE = 40.0
MAX_BBOX_WIDTH_KM = 90.0
SMALL_WIDTH_ISLANDS: set[IslandName] = {"tenerife", "la_palma"}


def _km_to_degrees(width_km: float, height_km: float) -> tuple[float, float]:
    """Convert km to degrees (lon_delta, lat_delta) at ~28°N latitude."""
    lon_delta = width_km / LONGITUDE_KM_AT_28N
    lat_delta = height_km / LATITUDE_KM
    return lon_delta, lat_delta


def _get_bbox_width_bounds_km(island: IslandName) -> tuple[float, float]:
    if island in SMALL_WIDTH_ISLANDS:
        return MIN_BBOX_WIDTH_KM_SMALL, MAX_BBOX_WIDTH_KM
    return MIN_BBOX_WIDTH_KM_LARGE, MAX_BBOX_WIDTH_KM


def _select_random_island(
    weights: dict[str, float] | None = None,
    temperature: float = 0.0
) -> IslandName:
    """
    Select a random island, with area-based weighting controlled by temperature.
    
    Args:
        weights: Optional custom weights for island selection
        temperature: Controls area weighting (0=uniform, 1=proportional to area)
    """
    islands = list(ISLANDS.keys())
    
    if weights is not None:
        island_weights = [weights.get(name, 1.0) for name in islands]
    else:
        areas = [ISLANDS[name]["area_km2"] for name in islands]
        island_weights = [area ** temperature for area in areas]
    
    return random.choices(islands, weights=island_weights, k=1)[0]


def _calculate_land_coverage(bbox_polygon: Polygon, island_polygon: Polygon) -> float:
    """Calculate what fraction of the bbox is covered by land."""
    intersection = bbox_polygon.intersection(island_polygon)
    return intersection.area / bbox_polygon.area if bbox_polygon.area > 0 else 0


def _calculate_island_coverage(bbox_polygon: Polygon, island_polygon: Polygon) -> float:
    """Calculate what fraction of the island is covered by the bbox."""
    intersection = bbox_polygon.intersection(island_polygon)
    return intersection.area / island_polygon.area if island_polygon.area > 0 else 0


def _calculate_land_coverage_multi(bbox_polygon: Polygon, island_polygons: list[Polygon]) -> float:
    """Calculate what fraction of the bbox is covered by land from multiple islands."""
    combined = unary_union(island_polygons)
    intersection = bbox_polygon.intersection(combined)
    return intersection.area / bbox_polygon.area if bbox_polygon.area > 0 else 0


def _get_combined_bounds(islands: list[IslandName]) -> tuple[float, float, float, float]:
    """Get the bounding box that contains all specified islands."""
    polygons = [ISLANDS[name]["polygon"] for name in islands]
    combined = unary_union(polygons)
    return combined.bounds


def _select_two_random_islands(
    weights: dict[str, float] | None = None,
    temperature: float = 0.0,
    island1: IslandName | None = None,
    island2: IslandName | None = None
) -> tuple[IslandName, IslandName]:
    """
    Select two different random islands, with area-based weighting controlled by temperature.
    
    Args:
        weights: Optional custom weights for island selection
        temperature: Controls area weighting (0=uniform, 1=proportional to area)
    """
    if island1 is not None and island2 is not None:
        if island2 not in NEIGHBOR_ISLANDS[island1]:
            raise ValueError("Island pair must be neighbors")
        return island1, island2

    islands = list(ISLANDS.keys())
    if island1 is None:
        if weights is not None:
            island_weights = [weights.get(name, 1.0) for name in islands]
        else:
            areas = [ISLANDS[name]["area_km2"] for name in islands]
            island_weights = [area ** temperature for area in areas]
        island1 = random.choices(islands, weights=island_weights, k=1)[0]

    neighbors = list(NEIGHBOR_ISLANDS[island1])
    if island2 is not None:
        if island2 not in neighbors:
            raise ValueError("Island pair must be neighbors")
        return island1, island2

    if weights is not None:
        neighbor_weights = [weights.get(name, 1.0) for name in neighbors]
    else:
        neighbor_areas = [ISLANDS[name]["area_km2"] for name in neighbors]
        neighbor_weights = [area ** temperature for area in neighbor_areas]
    island2 = random.choices(neighbors, weights=neighbor_weights, k=1)[0]
    return island1, island2


def generate_random_bbox_pair(
    island1: IslandName | None = None,
    island2: IslandName | None = None,
    min_island_coverage: float = 0.3,
    min_padding_ratio: float = 0.1,
    max_padding_ratio: float = 0.4,
    max_attempts: int = 100,
    island_weights: dict[str, float] | None = None,
    island_selection_temperature: float = 0.0,
    aspect_ratio: tuple[int, int] = (16, 9)
) -> tuple[tuple[float, float, float, float], tuple[IslandName, IslandName]]:
    """
    Generate a random bounding box showing a pairing of two islands.
    
    The bbox contains both islands with variable padding around them.
    
    Args:
        island1: First island, or None for random selection
        island2: Second island, or None for random selection
        min_island_coverage: Minimum fraction of each island covered by bbox (0-1)
        min_padding_ratio: Minimum extra padding as ratio of combined bounds
        max_padding_ratio: Maximum extra padding as ratio of combined bounds
        max_attempts: Maximum attempts to find valid bbox
        island_weights: Optional custom weights for island selection
        island_selection_temperature: Controls area-based weighting (0=uniform, 1=proportional to area)
        aspect_ratio: Target aspect ratio as (width, height), e.g. (16, 9)
    
    Returns:
        Tuple of (bbox, (island1, island2)) where bbox is (west, south, east, north) in WGS84
    """
    island1, island2 = _select_two_random_islands(
        weights=island_weights,
        temperature=island_selection_temperature,
        island1=island1,
        island2=island2
    )

    combined_minx, combined_miny, combined_maxx, combined_maxy = _get_combined_bounds([island1, island2])
    combined_width = combined_maxx - combined_minx
    combined_height = combined_maxy - combined_miny
    combined_center_x = (combined_minx + combined_maxx) / 2
    combined_center_y = (combined_miny + combined_maxy) / 2
    
    island_polygons = [ISLANDS[island1]["polygon"], ISLANDS[island2]["polygon"]]
    
    ar_width, ar_height = aspect_ratio
    
    for _ in range(max_attempts):
        padding_ratio = random.uniform(min_padding_ratio, max_padding_ratio)
        padded_width = combined_width * (1 + padding_ratio)
        padded_height = combined_height * (1 + padding_ratio)

        if padded_width / padded_height > ar_width / ar_height:
            bbox_width = padded_width
            bbox_height = bbox_width * (ar_height / ar_width)
        else:
            bbox_height = padded_height
            bbox_width = bbox_height * (ar_width / ar_height)

        west = combined_center_x - bbox_width / 2
        east = combined_center_x + bbox_width / 2
        south = combined_center_y - bbox_height / 2
        north = combined_center_y + bbox_height / 2

        bbox_polygon = box(west, south, east, north)
        island_coverages = [
            _calculate_island_coverage(bbox_polygon, island_polygons[0]),
            _calculate_island_coverage(bbox_polygon, island_polygons[1]),
        ]
        if all(coverage >= min_island_coverage for coverage in island_coverages):
            return (west, south, east, north), (island1, island2)

    padding_ratio = max_padding_ratio
    padded_width = combined_width * (1 + padding_ratio)
    padded_height = combined_height * (1 + padding_ratio)
    if padded_width / padded_height > ar_width / ar_height:
        bbox_width = padded_width
        bbox_height = bbox_width * (ar_height / ar_width)
    else:
        bbox_height = padded_height
        bbox_width = bbox_height * (ar_width / ar_height)

    west = combined_center_x - bbox_width / 2
    east = combined_center_x + bbox_width / 2
    south = combined_center_y - bbox_height / 2
    north = combined_center_y + bbox_height / 2

    return (west, south, east, north), (island1, island2)


def generate_random_bbox(
    island: IslandName | None = None,
    bbox_size_km: float | None = None,
    min_land_coverage: float = 0.3,
    max_attempts: int = 50,
    island_weights: dict[str, float] | None = None,
    island_selection_temperature: float = 0.0,
    aspect_ratio: tuple[int, int] = (16, 9)
) -> tuple[tuple[float, float, float, float], str]:
    """
    Generate a random bounding box within a Canary Island.
    
    Args:
        island: Specific island name, or None for random selection
        bbox_size_km: Height of bbox in km (width calculated from aspect ratio). If None,
            width is sampled per-island and height is derived from aspect ratio.
        min_land_coverage: Minimum fraction of land in bbox (0-1)
        max_attempts: Maximum attempts to find valid bbox
        island_weights: Optional custom weights for island selection
        island_selection_temperature: Controls area-based weighting (0=uniform, 1=proportional to area)
        aspect_ratio: Target aspect ratio as (width, height), e.g. (16, 9)
    
    Returns:
        Tuple of (bbox, island_name) where bbox is (west, south, east, north) in WGS84
    
    Raises:
        ValueError: If no valid bbox found after max_attempts
    """
    selected_island = island or _select_random_island(island_weights, island_selection_temperature)
    island_data = ISLANDS[selected_island]
    island_polygon = island_data["polygon"]
    
    if bbox_size_km is None:
        min_width_km, max_width_km = _get_bbox_width_bounds_km(selected_island)
        width_km = random.uniform(min_width_km, max_width_km)
        height_km = width_km * (aspect_ratio[1] / aspect_ratio[0])
    else:
        height_km = bbox_size_km
        width_km = bbox_size_km * (aspect_ratio[0] / aspect_ratio[1])
    
    lon_delta, lat_delta = _km_to_degrees(width_km, height_km)
    half_lon = lon_delta / 2
    half_lat = lat_delta / 2
    
    minx, miny, maxx, maxy = island_polygon.bounds
    
    for _ in range(max_attempts):
        center_lon = random.uniform(minx + half_lon, maxx - half_lon)
        center_lat = random.uniform(miny + half_lat, maxy - half_lat)
        center_point = Point(center_lon, center_lat)
        
        if not island_polygon.contains(center_point):
            continue
        
        west = center_lon - half_lon
        east = center_lon + half_lon
        south = center_lat - half_lat
        north = center_lat + half_lat
        
        bbox_polygon = box(west, south, east, north)
        land_coverage = _calculate_land_coverage(bbox_polygon, island_polygon)
        
        if land_coverage >= min_land_coverage:
            return (west, south, east, north), selected_island
    
    west = center_lon - half_lon
    east = center_lon + half_lon
    south = center_lat - half_lat
    north = center_lat + half_lat
    return (west, south, east, north), selected_island


def generate_random_view(
    mode: ViewMode | None = None,
    single_mode_probability: float = 0.5,
    island: IslandName | None = None,
    bbox_size_km: float | None = None,
    min_land_coverage_single: float = 0.3,
    min_island_coverage_pair: float = 0.3,
    min_padding_ratio_pair: float = 0.1,
    max_padding_ratio_pair: float = 0.4,
    max_attempts: int = 100,
    island_weights: dict[str, float] | None = None,
    island_selection_temperature: float = 0.0,
    aspect_ratio: tuple[int, int] = (16, 9)
) -> tuple[tuple[float, float, float, float], IslandName | tuple[IslandName, IslandName], ViewMode]:
    """
    Generate a random view, choosing between single island and island pair modes.
    
    Args:
        mode: Force "single" or "pair" mode, or None for random selection
        single_mode_probability: Probability of choosing single mode when mode is None
        island: Specific island for single mode (ignored in pair mode)
        bbox_size_km: Height of bbox in km for single mode. If None, width is
            sampled per-island and height is derived from aspect ratio.
        min_land_coverage_single: Minimum land coverage for single mode
        min_island_coverage_pair: Minimum island coverage for pair mode
        min_padding_ratio_pair: Min padding ratio for pair mode
        max_padding_ratio_pair: Max padding ratio for pair mode
        max_attempts: Maximum attempts to find valid bbox
        island_weights: Optional custom weights for island selection
        island_selection_temperature: Controls area-based weighting (0=uniform, 1=proportional to area)
        aspect_ratio: Target aspect ratio as (width, height)
    
    Returns:
        Tuple of (bbox, islands, mode) where:
        - bbox is (west, south, east, north) in WGS84
        - islands is IslandName for single mode or tuple of two IslandNames for pair mode
        - mode is "single" or "pair"
    """
    if mode is None:
        mode = "single" if random.random() < single_mode_probability else "pair"
    
    if mode == "single":
        bbox, selected_island = generate_random_bbox(
            island=island,
            bbox_size_km=bbox_size_km,
            min_land_coverage=min_land_coverage_single,
            max_attempts=max_attempts,
            island_weights=island_weights,
            island_selection_temperature=island_selection_temperature,
            aspect_ratio=aspect_ratio
        )
        return bbox, selected_island, "single"
    else:
        bbox, (island1, island2) = generate_random_bbox_pair(
            min_island_coverage=min_island_coverage_pair,
            min_padding_ratio=min_padding_ratio_pair,
            max_padding_ratio=max_padding_ratio_pair,
            max_attempts=max_attempts,
            island_weights=island_weights,
            island_selection_temperature=island_selection_temperature,
            aspect_ratio=aspect_ratio
        )
        return bbox, (island1, island2), "pair"


def get_island_bounds(island: IslandName) -> tuple[float, float, float, float]:
    """Get the bounding box of an island polygon."""
    return ISLANDS[island]["polygon"].bounds


def get_all_islands_union() -> Polygon:
    """Get the union of all island polygons."""
    return unary_union([data["polygon"] for data in ISLANDS.values()])
