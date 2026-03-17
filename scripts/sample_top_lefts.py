#!/usr/bin/env python3
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import (
    DEFAULT_CANDIDATE_LIST,
    DEFAULT_MIN_LAND_PER_SUBTILE,
    DEFAULT_MIN_SUBTILES_WITH_LAND,
    DEFAULT_MOSAIC_HEIGHT,
    DEFAULT_MOSAIC_WIDTH,
    PROJECT_DIR,
    load_config,
    parse_shape,
    save_default_config,
)
from mosaic_reference import format_top_left_subtile
from mosaic_selector import (
    build_mosaics,
    filter_mosaics_by_land,
    mosaics_containing_seed,
    pick_mosaic,
    pick_seed,
)
from tiles import CandidateListError, load_candidate_subtiles_with_land


def _resolve_candidate_list(candidate_list_arg: Path | None, prefs: dict) -> Path:
    candidate_list = candidate_list_arg or Path(
        prefs.get("candidate_list", str(DEFAULT_CANDIDATE_LIST))
    )
    if not candidate_list.is_absolute():
        candidate_list = PROJECT_DIR / candidate_list
    return candidate_list


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sample top-left subtiles using the normal pre-fetch selection logic"
    )
    parser.add_argument("--runs", type=int, default=50, help="How many samples to print")
    parser.add_argument(
        "--candidate-list",
        type=Path,
        help="Path to candidate subtile list JSON",
    )
    parser.add_argument(
        "--shape",
        type=parse_shape,
        help=f"Mosaic shape WxH (default: {DEFAULT_MOSAIC_WIDTH}x{DEFAULT_MOSAIC_HEIGHT})",
    )
    parser.add_argument(
        "--min-land-per-subtile",
        type=float,
        help=f"Minimum land fraction per subtile to count as 'has land' (default: {DEFAULT_MIN_LAND_PER_SUBTILE})",
    )
    parser.add_argument(
        "--min-subtiles-with-land",
        type=int,
        help=f"Minimum number of subtiles with land required per mosaic (default: {DEFAULT_MIN_SUBTILES_WITH_LAND})",
    )
    parser.add_argument(
        "--island",
        type=str,
        metavar="NAME",
        help="Restrict sampling to mosaics touching a single island bucket from the candidate list",
    )
    parser.add_argument(
        "--seed",
        type=int,
        help="Random seed for reproducible sampling",
    )
    args = parser.parse_args()

    save_default_config()
    config = load_config()
    prefs = config.get("preferences", {})

    candidate_list = _resolve_candidate_list(args.candidate_list, prefs)
    if args.shape is None:
        mosaic_width = prefs.get("mosaic_width", DEFAULT_MOSAIC_WIDTH)
        mosaic_height = prefs.get("mosaic_height", DEFAULT_MOSAIC_HEIGHT)
    else:
        mosaic_width, mosaic_height = args.shape
    min_land_per_subtile = (
        args.min_land_per_subtile
        if args.min_land_per_subtile is not None
        else prefs.get("min_land_per_subtile", DEFAULT_MIN_LAND_PER_SUBTILE)
    )
    min_subtiles_with_land = (
        args.min_subtiles_with_land
        if args.min_subtiles_with_land is not None
        else prefs.get("min_subtiles_with_land", DEFAULT_MIN_SUBTILES_WITH_LAND)
    )

    try:
        candidates, land_fractions = load_candidate_subtiles_with_land(candidate_list)
    except CandidateListError as exc:
        raise SystemExit(str(exc)) from exc

    mosaics = build_mosaics(candidates, width=mosaic_width, height=mosaic_height)
    if land_fractions:
        mosaics = filter_mosaics_by_land(
            mosaics,
            land_fractions,
            min_land_per_subtile,
            min_subtiles_with_land,
        )
    if args.island:
        try:
            island_subtiles, _ = load_candidate_subtiles_with_land(
                candidate_list,
                island_filter=args.island,
            )
        except CandidateListError as exc:
            raise SystemExit(str(exc)) from exc
        island_set = set(island_subtiles)
        mosaics = [mosaic for mosaic in mosaics if any(subtile in island_set for subtile in mosaic.subtiles)]
        candidates = [subtile for subtile in candidates if subtile in island_set]

    if not mosaics:
        raise SystemExit("No valid mosaics available for the requested settings")

    rng = random.Random(args.seed)
    invalid_subtiles = set()

    for _ in range(args.runs):
        seed = pick_seed(candidates, invalid_subtiles, rng)
        if seed is None:
            raise SystemExit("No candidate seed subtiles available")
        seed_mosaics = mosaics_containing_seed(mosaics, seed)
        chosen = pick_mosaic(seed_mosaics, rng)
        if chosen is None:
            raise SystemExit(f"No mosaics available containing seed {seed.tile_id}{seed.suffix()}")
        print(format_top_left_subtile(chosen.top_left_subtile))


if __name__ == "__main__":
    main()
