#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mosaic_reference import format_top_left_subtile
from tiles import Subtile, parse_subtile_suffix
from mosaic_selector import MosaicDefinition, build_mosaics, filter_mosaics_by_land

PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CANDIDATE_LIST = PROJECT_DIR / "data" / "subtile_candidates.json"

DEFAULT_MOSAIC_WIDTH = 4
DEFAULT_MOSAIC_HEIGHT = 3
DEFAULT_MIN_LAND_PER_SUBTILE = 0.05
DEFAULT_MIN_SUBTILES_WITH_LAND = 1


def load_candidates_by_island(
    path: Path,
) -> tuple[dict[str, list[Subtile]], dict[Subtile, float], dict[Subtile, str]]:
    raw = json.loads(path.read_text())
    island_subtiles: dict[str, list[Subtile]] = {}
    land_fractions: dict[Subtile, float] = {}
    subtile_to_island: dict[Subtile, str] = {}

    for island in raw["islands"]:
        name: str = island["name"]
        island_subtiles[name] = []
        for tile in island["tiles"]:
            tile_id: str = tile["tile_id"]
            for entry in tile["subtiles"]:
                easting, northing = parse_subtile_suffix(entry["suffix"])
                subtile = Subtile(tile_id=tile_id, easting=easting, northing=northing)
                island_subtiles[name].append(subtile)
                subtile_to_island[subtile] = name
                lf = entry.get("land_fraction")
                if lf is not None:
                    land_fractions[subtile] = float(lf)

    return island_subtiles, land_fractions, subtile_to_island


def mosaic_key(m: MosaicDefinition) -> str:
    return f"{format_top_left_subtile(m.top_left_subtile)}:{m.width}x{m.height}"


def assign_mosaic_island(
    mosaic: MosaicDefinition,
    subtile_to_island: dict[Subtile, str],
) -> str:
    counts: dict[str, int] = defaultdict(int)
    for subtile in mosaic.subtiles:
        island = subtile_to_island.get(subtile, "unassigned")
        counts[island] += 1
    named = {k: v for k, v in counts.items() if k != "unassigned"}
    if named:
        return max(named, key=lambda k: named[k])
    return "unassigned"


def main() -> None:
    island_subtiles, land_fractions, subtile_to_island = load_candidates_by_island(
        DEFAULT_CANDIDATE_LIST
    )

    all_subtiles: list[Subtile] = []
    for subs in island_subtiles.values():
        all_subtiles.extend(subs)
    all_subtiles = list(dict.fromkeys(all_subtiles))

    all_mosaics = build_mosaics(all_subtiles, DEFAULT_MOSAIC_WIDTH, DEFAULT_MOSAIC_HEIGHT)

    valid_mosaics = filter_mosaics_by_land(
        all_mosaics,
        land_fractions,
        DEFAULT_MIN_LAND_PER_SUBTILE,
        DEFAULT_MIN_SUBTILES_WITH_LAND,
    )

    by_island: dict[str, list[MosaicDefinition]] = defaultdict(list)
    for mosaic in valid_mosaics:
        island = assign_mosaic_island(mosaic, subtile_to_island)
        by_island[island].append(mosaic)

    named_islands = sorted(k for k in by_island if k != "unassigned")
    order = named_islands + (["unassigned"] if "unassigned" in by_island else [])

    print(f"Total candidate subtiles: {len(all_subtiles)}")
    print(f"Total mosaics (before land filter): {len(all_mosaics)}")
    print(f"Valid mosaics (after land filter):  {len(valid_mosaics)}")
    print()

    for island in order:
        mosaics = by_island[island]
        tiles = sorted({m.tile_id for m in mosaics})
        print(f"{'=' * 60}")
        print(f"  {island.upper()} — {len(mosaics)} mosaics (tiles: {', '.join(tiles)})")
        print(f"{'=' * 60}")
        for m in sorted(
            mosaics,
            key=lambda m: (
                m.top_left_subtile.tile_id,
                m.top_left_subtile.easting,
                m.top_left_subtile.northing,
            ),
        ):
            land_count = sum(
                1 for s in m.subtiles
                if land_fractions.get(s, 0.0) >= DEFAULT_MIN_LAND_PER_SUBTILE
            )
            print(f"  {mosaic_key(m):30s}  land subtiles: {land_count}/{len(m.subtiles)}")
        print()


if __name__ == "__main__":
    main()
