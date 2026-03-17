#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mosaic_reference import format_top_left_subtile
from tiles import Subtile, parse_subtile_suffix, load_candidate_subtiles_with_land
from mosaic_selector import build_mosaics, filter_mosaics, filter_mosaics_by_land

PROJECT_DIR = Path(__file__).resolve().parent.parent
CANDIDATE_LIST = PROJECT_DIR / "data" / "subtile_candidates.json"
CACHE_PATH = PROJECT_DIR / "data" / "tile_status_cache.json"

WIDTH, HEIGHT = 3, 2
MIN_LAND = 0.05
MIN_LAND_SUBTILES = 2


def mosaic_key(tile) -> str:
    return f"{format_top_left_subtile(tile.top_left_subtile)}:{tile.width}x{tile.height}"


def main() -> None:
    candidates, land_fractions = load_candidate_subtiles_with_land(CANDIDATE_LIST)
    mosaics = build_mosaics(candidates, WIDTH, HEIGHT)
    mosaics = filter_mosaics_by_land(mosaics, land_fractions, MIN_LAND, MIN_LAND_SUBTILES)
    print(f"Valid mosaics after land filter: {len(mosaics)}")

    cache = json.loads(CACHE_PATH.read_text())
    tile_dates = cache.get("tile_dates", {})
    subtile_cache = cache.get("subtiles", {})
    used_mosaics = cache.get("mosaics", {})

    all_tiles = sorted({s.tile_id for s in candidates})
    dates = sorted(tile_dates.keys(), reverse=True)

    for date in dates:
        print(f"\n{'='*70}")
        print(f"  DATE: {date}")
        print(f"{'='*70}")

        td = tile_dates.get(date, {})
        for tile_id in all_tiles:
            status = td.get(tile_id, {}).get("item", "(not cached)")
            print(f"  {tile_id}: item={status}")

        none_tiles = {t for t in all_tiles if td.get(t, {}).get("item") == "none"}
        invalid_from_cache: set[Subtile] = set()
        sd = subtile_cache.get(date, {})
        for tile_id, subs in sd.items():
            for suffix, status in subs.items():
                if status == "invalid":
                    e, n = parse_subtile_suffix(suffix)
                    invalid_from_cache.add(Subtile(tile_id=tile_id, easting=e, northing=n))

        if invalid_from_cache:
            print(f"\n  Subtiles cached as invalid: {len(invalid_from_cache)}")
            for s in sorted(invalid_from_cache, key=lambda s: (s.tile_id, s.easting, s.northing)):
                print(f"    {s.tile_id}{s.suffix()}")

        used = set(used_mosaics.get(date, []))
        if used:
            print(f"\n  Mosaics already used: {len(used)}")
            for m in sorted(used):
                print(f"    {m}")

        seeds_in_none_tiles = [s for s in candidates if s.tile_id in none_tiles]
        seeds_in_ok_tiles = [s for s in candidates if s.tile_id not in none_tiles and td.get(s.tile_id, {}).get("item") == "ok"]
        seeds_uncached = [s for s in candidates if td.get(s.tile_id, {}).get("item") is None]

        print(f"\n  Candidate subtiles by tile status:")
        print(f"    In 'none' tiles (will be burned one-by-one): {len(seeds_in_none_tiles)}")
        print(f"    In 'ok' tiles:                               {len(seeds_in_ok_tiles)}")
        print(f"    In uncached tiles:                           {len(seeds_uncached)}")

        sim_invalid = set(invalid_from_cache)
        for s in candidates:
            if s.tile_id in none_tiles:
                sim_invalid.add(s)

        after_none = filter_mosaics(mosaics, sim_invalid)
        after_used = [m for m in after_none if mosaic_key(m) not in used]

        print(f"\n  Mosaics surviving after removing 'none' tile subtiles + cached invalid: {len(after_none)}")
        print(f"  Mosaics surviving after also removing used: {len(after_used)}")

        if after_used:
            by_tile = defaultdict(int)
            for m in after_used:
                by_tile[m.tile_id] += 1
            for t in sorted(by_tile):
                print(f"    {t}: {by_tile[t]} mosaics")
        else:
            print(f"  >>> ALL MOSAICS EXHAUSTED — nothing to try without re-checking STAC <<<")


if __name__ == "__main__":
    main()
