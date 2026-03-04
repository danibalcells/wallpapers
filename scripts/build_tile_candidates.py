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


def _has_neighbor_land(
    grid: dict[tuple[int, int], float],
    easting: int,
    northing: int,
    threshold: float,
) -> bool:
    for de in (-1, 0, 1):
        for dn in (-1, 0, 1):
            if de == 0 and dn == 0:
                continue
            if grid.get((easting + de, northing + dn), 0.0) >= threshold:
                return True
    return False


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
    parser.add_argument(
        "--min-tile-land", type=float, default=0.0,
        help="Minimum land fraction for a 100km tile to be processed at all (default 0.0 = process all tiles)",
    )
    parser.add_argument(
        "--min-subtile-land", type=float, default=0.05,
        help="A 10km subtile is included if its own land fraction OR any 8-connected neighbour's "
             "land fraction meets this threshold",
    )
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

    mgrs = MGRS()
    tile_tags: dict[str, list[IslandName]] = {}
    subtile_tags: dict[Subtile, list[IslandName]] = {}
    subtile_bboxes: dict[Subtile, tuple[float, float, float, float]] = {}

    # Pass 1: compute land fractions for every subtile in every qualifying tile.
    # A tile is only skipped here if --min-tile-land > 0 AND the whole tile has
    # less land than that threshold.  The default (0.0) processes all tiles.
    TileGrid = dict[tuple[int, int], float]
    per_tile_grid: dict[str, TileGrid] = {}

    for tile_id in tile_ids:
        tile_bbox_wgs84 = _tile_bbox_from_mgrs(mgrs, tile_id)
        if tile_bbox_wgs84 is None:
            logger.warning("Failed to parse tile bbox for %s", tile_id)
            continue
        tile_polygon = box(*tile_bbox_wgs84)
        if args.min_tile_land > 0.0:
            tile_land = _land_fraction(tile_polygon, land_union)
            if tile_land < args.min_tile_land:
                logger.info("Skipping tile %s (tile land %.3f < %.3f)", tile_id, tile_land, args.min_tile_land)
                continue
        tile_tags[tile_id] = _island_tags(tile_polygon, islands)

        grid: TileGrid = {}
        for easting in range(10):
            for northing in range(10):
                subtile_bbox_wgs84 = _subtile_bbox_from_mgrs(mgrs, tile_id, easting, northing)
                if subtile_bbox_wgs84 is None:
                    continue
                subtile_polygon = box(*subtile_bbox_wgs84)
                land = _land_fraction(subtile_polygon, land_union)
                grid[(easting, northing)] = land
                subtile_tags[Subtile(tile_id=tile_id, easting=easting, northing=northing)] = (
                    _island_tags(subtile_polygon, islands)
                )
                subtile_bboxes[Subtile(tile_id=tile_id, easting=easting, northing=northing)] = subtile_bbox_wgs84
        per_tile_grid[tile_id] = grid

    # Pass 2: apply the neighbour-aware subtile filter.
    # A subtile is included when its own land fraction OR any 8-connected
    # neighbour within the same 100km tile meets --min-subtile-land.
    valid_tiles: list[str] = []
    valid_subtiles_sorted: list[tuple[Subtile, float]] = []

    for tile_id in sorted(per_tile_grid.keys()):
        grid = per_tile_grid[tile_id]
        tile_has_candidate = False
        for (e, n) in sorted(grid.keys()):
            own_land = grid[(e, n)]
            if own_land >= args.min_subtile_land or _has_neighbor_land(grid, e, n, args.min_subtile_land):
                subtile = Subtile(tile_id=tile_id, easting=e, northing=n)
                valid_subtiles_sorted.append((subtile, own_land))
                tile_has_candidate = True
        if tile_has_candidate:
            valid_tiles.append(tile_id)

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
            subtiles_list = tiles.setdefault(subtile.tile_id, [])
            subtiles_list.append(entry)

    for tiles in island_tiles.values():
        for tile_id, subtiles_list in tiles.items():
            tiles[tile_id] = sorted(subtiles_list, key=lambda item: item["suffix"])

    _write_tiles(args.tiles_out, valid_tiles, tile_tags)
    _write_candidates(args.subtiles_out, island_tiles)


if __name__ == "__main__":
    main()
