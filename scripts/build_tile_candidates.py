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
from mosaic_selector import build_mosaics, filter_mosaics_by_land
from mosaic_reference import shift_top_left_subtile
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


def _tile_neighbor(tile_id: str, direction: str) -> str:
    if direction == "west":
        return shift_top_left_subtile(Subtile(tile_id=tile_id, easting=0, northing=0), -1, 0).tile_id
    if direction == "east":
        return shift_top_left_subtile(Subtile(tile_id=tile_id, easting=9, northing=0), 1, 0).tile_id
    if direction == "south":
        return shift_top_left_subtile(Subtile(tile_id=tile_id, easting=0, northing=0), 0, -1).tile_id
    if direction == "north":
        return shift_top_left_subtile(Subtile(tile_id=tile_id, easting=0, northing=9), 0, 1).tile_id
    raise ValueError(f"Unsupported direction: {direction}")


def _expand_tile_ids(tile_ids: list[str], halo: int) -> list[str]:
    expanded = set(tile_ids)
    frontier = set(tile_ids)
    for _ in range(max(halo, 0)):
        next_frontier: set[str] = set()
        for tile_id in frontier:
            for direction in ("west", "east", "south", "north"):
                try:
                    neighbor = _tile_neighbor(tile_id, direction)
                except ValueError:
                    continue
                if neighbor not in expanded:
                    next_frontier.add(neighbor)
        expanded.update(next_frontier)
        frontier = next_frontier
        if not frontier:
            break
    return sorted(expanded)


def _compute_subtile_metadata(
    tile_ids: list[str],
    mgrs: MGRS,
    land_union: Polygon,
    islands: dict[IslandName, Polygon],
) -> tuple[
    dict[str, list[IslandName]],
    dict[Subtile, list[IslandName]],
    dict[Subtile, tuple[float, float, float, float]],
    dict[Subtile, float],
]:
    tile_tags: dict[str, list[IslandName]] = {}
    subtile_tags: dict[Subtile, list[IslandName]] = {}
    subtile_bboxes: dict[Subtile, tuple[float, float, float, float]] = {}
    subtile_land_fractions: dict[Subtile, float] = {}

    for tile_id in tile_ids:
        tile_bbox_wgs84 = _tile_bbox_from_mgrs(mgrs, tile_id)
        if tile_bbox_wgs84 is None:
            logger.warning("Failed to parse tile bbox for %s", tile_id)
            continue
        tile_tags[tile_id] = _island_tags(box(*tile_bbox_wgs84), islands)

        for easting in range(10):
            for northing in range(10):
                subtile_bbox_wgs84 = _subtile_bbox_from_mgrs(mgrs, tile_id, easting, northing)
                if subtile_bbox_wgs84 is None:
                    continue
                subtile_polygon = box(*subtile_bbox_wgs84)
                subtile = Subtile(tile_id=tile_id, easting=easting, northing=northing)
                subtile_land_fractions[subtile] = _land_fraction(subtile_polygon, land_union)
                subtile_tags[subtile] = _island_tags(subtile_polygon, islands)
                subtile_bboxes[subtile] = subtile_bbox_wgs84

    return tile_tags, subtile_tags, subtile_bboxes, subtile_land_fractions


def _support_subtiles(
    all_subtiles: list[Subtile],
    land_fractions: dict[Subtile, float],
    support_mosaic_width: int,
    support_mosaic_height: int,
    min_land_per_subtile: float,
    min_land_subtiles_per_mosaic: int,
) -> set[Subtile]:
    support_mosaics = build_mosaics(
        all_subtiles,
        width=support_mosaic_width,
        height=support_mosaic_height,
    )
    valid_support_mosaics = filter_mosaics_by_land(
        support_mosaics,
        land_fractions,
        min_land_per_subtile,
        min_land_subtiles_per_mosaic,
    )
    return {
        subtile
        for mosaic in valid_support_mosaics
        for subtile in mosaic.subtiles
    }


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
        help="Land fraction threshold used to count a subtile as land-bearing when evaluating support mosaics",
    )
    parser.add_argument(
        "--min-land-subtiles-per-mosaic",
        type=int,
        default=1,
        help="Keep support mosaics with at least this many land-bearing subtiles",
    )
    parser.add_argument(
        "--support-shape",
        type=str,
        default="4x3",
        help="Canonical support mosaic shape as WxH; any subtile used by a valid support mosaic is kept",
    )
    parser.add_argument(
        "--tile-halo",
        type=int,
        default=1,
        help="How many macro-tile steps to expand around the base tile list before building support mosaics",
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
    try:
        support_mosaic_width_text, support_mosaic_height_text = args.support_shape.lower().split("x", 1)
        support_mosaic_width = int(support_mosaic_width_text)
        support_mosaic_height = int(support_mosaic_height_text)
    except ValueError as exc:
        raise SystemExit("--support-shape must look like WxH, e.g. 4x3") from exc

    tile_ids = [tile_id.strip() for tile_id in args.tile_ids.split(",") if tile_id.strip()]
    expanded_tile_ids = _expand_tile_ids(tile_ids, args.tile_halo)
    logger.info(
        "Using %d base tiles and %d expanded tiles for %s",
        len(tile_ids),
        len(expanded_tile_ids),
        archipelago_bbox,
    )

    mgrs = MGRS()
    if args.min_tile_land > 0.0:
        filtered_tile_ids: list[str] = []
        for tile_id in expanded_tile_ids:
            tile_bbox_wgs84 = _tile_bbox_from_mgrs(mgrs, tile_id)
            if tile_bbox_wgs84 is None:
                continue
            tile_land = _land_fraction(box(*tile_bbox_wgs84), land_union)
            if tile_land >= args.min_tile_land:
                filtered_tile_ids.append(tile_id)
        expanded_tile_ids = filtered_tile_ids

    tile_tags, subtile_tags, subtile_bboxes, subtile_land_fractions = _compute_subtile_metadata(
        expanded_tile_ids,
        mgrs,
        land_union,
        islands,
    )

    support_subtiles_sorted = sorted(
        subtile_land_fractions.keys(),
        key=lambda subtile: (subtile.tile_id, subtile.easting, subtile.northing),
    )
    selected_subtiles = _support_subtiles(
        support_subtiles_sorted,
        subtile_land_fractions,
        support_mosaic_width=support_mosaic_width,
        support_mosaic_height=support_mosaic_height,
        min_land_per_subtile=args.min_subtile_land,
        min_land_subtiles_per_mosaic=args.min_land_subtiles_per_mosaic,
    )
    valid_tiles = sorted({subtile.tile_id for subtile in selected_subtiles})
    valid_subtiles_sorted = sorted(
        ((subtile, subtile_land_fractions[subtile]) for subtile in selected_subtiles),
        key=lambda item: (item[0].tile_id, item[0].easting, item[0].northing),
    )

    logger.info(
        "Keeping %d tiles and %d subtiles from support shape %dx%d with >= %d land-bearing subtiles",
        len(valid_tiles),
        len(valid_subtiles_sorted),
        support_mosaic_width,
        support_mosaic_height,
        args.min_land_subtiles_per_mosaic,
    )

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
