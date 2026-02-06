from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from mgrs import MGRS
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from islands import IslandName, get_island_polygons, get_island_union
from tiles import Subtile

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def _land_fraction(bbox_polygon: Polygon, land_union: Polygon) -> float:
    if bbox_polygon.area <= 0:
        return 0.0
    intersection = bbox_polygon.intersection(land_union)
    return intersection.area / bbox_polygon.area


def _archipelago_bbox(polygons: list[Polygon]) -> tuple[float, float, float, float]:
    return unary_union(polygons).bounds


def _tile_bbox_from_mgrs(mgrs: MGRS, tile_id: str) -> tuple[float, float, float, float] | None:
    try:
        south_lat, west_lon = mgrs.toLatLon(f"{tile_id}0000000000")
        north_lat, east_lon = mgrs.toLatLon(f"{tile_id}9999999999")
    except Exception:
        return None
    west = min(west_lon, east_lon)
    east = max(west_lon, east_lon)
    south = min(south_lat, north_lat)
    north = max(south_lat, north_lat)
    return west, south, east, north


def _subtile_bbox_from_mgrs(
    mgrs: MGRS,
    tile_id: str,
    easting: int,
    northing: int,
) -> tuple[float, float, float, float] | None:
    if not 0 <= easting <= 9 or not 0 <= northing <= 9:
        return None
    try:
        easting_min = f"{easting * 10_000:05d}"
        northing_min = f"{northing * 10_000:05d}"
        easting_max = f"{min(easting * 10_000 + 9_999, 99_999):05d}"
        northing_max = f"{min(northing * 10_000 + 9_999, 99_999):05d}"
        south_lat, west_lon = mgrs.toLatLon(f"{tile_id}{easting_min}{northing_min}")
        north_lat, east_lon = mgrs.toLatLon(f"{tile_id}{easting_max}{northing_max}")
    except Exception:
        return None
    west = min(west_lon, east_lon)
    east = max(west_lon, east_lon)
    south = min(south_lat, north_lat)
    north = max(south_lat, north_lat)
    return west, south, east, north


def _island_tags(
    bbox_polygon: Polygon,
    islands: dict[IslandName, Polygon],
) -> list[IslandName]:
    tags: list[IslandName] = []
    for name, polygon in islands.items():
        if polygon.intersects(bbox_polygon):
            tags.append(name)
    return sorted(tags)


def _bounds_url(bbox: tuple[float, float, float, float]) -> str:
    west, south, east, north = bbox
    return (
        "https://opencagedata.com/tools/bounds-finder#"
        f"{west:.5f},{south:.5f},{east:.5f},{north:.5f}"
    )


def _subtile_mgrs(tile_id: str, suffix: str) -> str:
    return f"{tile_id}{suffix}"


def _write_candidates(
    path: Path,
    island_tiles: dict[str, dict[str, list[dict[str, object]]]],
) -> None:
    payload = {
        "version": 2,
        "islands": [
            {
                "name": island,
                "tiles": [
                    {"tile_id": tile_id, "tile_mgrs": tile_id, "subtiles": subtiles}
                    for tile_id, subtiles in sorted(tiles.items())
                ],
            }
            for island, tiles in sorted(island_tiles.items())
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))


def _write_tiles(
    path: Path,
    tile_ids: list[str],
    tags: dict[str, list[IslandName]],
) -> None:
    payload = {
        "version": 1,
        "tiles": [{"tile_id": tile_id, "islands": tags.get(tile_id, [])} for tile_id in tile_ids],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description="Build candidate tile/subtile lists from island polygons")
    parser.add_argument("--min-tile-land", type=float, default=0.05)
    parser.add_argument("--min-subtile-land", type=float, default=0.05)
    parser.add_argument("--tiles-out", type=Path, default=Path("data/tile_candidates.json"))
    parser.add_argument("--subtiles-out", type=Path, default=Path("data/subtile_candidates.json"))
    parser.add_argument(
        "--tile-ids",
        type=str,
        default="27RYM,27RYL,28RBS,28RBR,28RCS,28RCR,28RDS,28RDR,28RES,28RFS,28RFT",
        help="Comma-separated MGRS 100km tile ids to consider",
    )
    args = parser.parse_args()

    islands = get_island_polygons()
    land_union = get_island_union()
    archipelago_bbox = _archipelago_bbox(list(islands.values()))

    tile_ids = [tile_id.strip() for tile_id in args.tile_ids.split(",") if tile_id.strip()]
    logger.info("Using %d base tiles for %s", len(tile_ids), archipelago_bbox)

    valid_tiles: list[str] = []
    valid_subtiles: list[Subtile] = []
    tile_tags: dict[str, list[IslandName]] = {}
    subtile_tags: dict[Subtile, list[IslandName]] = {}
    subtile_bboxes: dict[Subtile, tuple[float, float, float, float]] = {}
    mgrs = MGRS()

    for tile_id in tile_ids:
        tile_bbox_wgs84 = _tile_bbox_from_mgrs(mgrs, tile_id)
        if tile_bbox_wgs84 is None:
            logger.warning("Failed to parse tile bbox for %s", tile_id)
            continue
        tile_polygon = box(*tile_bbox_wgs84)
        tile_land = _land_fraction(tile_polygon, land_union)
        if tile_land < args.min_tile_land:
            continue
        valid_tiles.append(tile_id)
        tile_tags[tile_id] = _island_tags(tile_polygon, islands)
        for easting in range(10):
            for northing in range(10):
                subtile = Subtile(tile_id=tile_id, easting=easting, northing=northing)
                subtile_bbox_wgs84 = _subtile_bbox_from_mgrs(mgrs, tile_id, easting, northing)
                if subtile_bbox_wgs84 is None:
                    continue
                subtile_polygon = box(*subtile_bbox_wgs84)
                subtile_land = _land_fraction(subtile_polygon, land_union)
                valid_subtiles.append((subtile, subtile_land))
                subtile_tags[subtile] = _island_tags(subtile_polygon, islands)
                subtile_bboxes[subtile] = subtile_bbox_wgs84

    valid_tiles = sorted(set(valid_tiles))
    valid_subtiles_unique: dict[Subtile, float] = {}
    for subtile, land in valid_subtiles:
        if subtile not in valid_subtiles_unique:
            valid_subtiles_unique[subtile] = land
    valid_subtiles_sorted = sorted(valid_subtiles_unique.items(), key=lambda item: (item[0].tile_id, item[0].easting, item[0].northing))
    logger.info("Keeping %d tiles and %d subtiles", len(valid_tiles), len(valid_subtiles_sorted))

    island_tiles: dict[str, dict[str, list[dict[str, object]]]] = {}
    for subtile, land_fraction in valid_subtiles_sorted:
        tags = subtile_tags.get(subtile, [])
        if not tags:
            tags = ["unassigned"]
        bbox = subtile_bboxes[subtile]
        entry = {
            "suffix": subtile.suffix(),
            "bbox": [bbox[0], bbox[1], bbox[2], bbox[3]],
            "bounds_url": _bounds_url(bbox),
            "subtile_mgrs": _subtile_mgrs(subtile.tile_id, subtile.suffix()),
            "land_fraction": round(land_fraction, 4),
        }
        for tag in tags:
            tiles = island_tiles.setdefault(tag, {})
            subtiles = tiles.setdefault(subtile.tile_id, [])
            subtiles.append(entry)

    for tiles in island_tiles.values():
        for tile_id, subtiles in tiles.items():
            tiles[tile_id] = sorted(subtiles, key=lambda item: item["suffix"])

    _write_tiles(args.tiles_out, valid_tiles, tile_tags)
    _write_candidates(args.subtiles_out, island_tiles)


if __name__ == "__main__":
    main()
