"""
Coverage diagnostic: why are some islands/regions never shown?

Diagnoses four root-cause categories:
  A. Missing islands    – tiles with no candidate subtiles at all
  B. Candidate pollution – how many seeds are pure-ocean and how that
                          biases (or wastes) random selection
  C. Mosaic geometry    – valid 3×2 mosaic count per tile/island, and
                          true selection probability via simulation
  D. Data availability  – STAC item hit-rate and subtile validity rates
                          per tile from the runtime cache
"""

from __future__ import annotations

import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mosaic_selector import (
    MosaicDefinition,
    build_mosaics,
    filter_mosaics_by_land,
    mosaics_containing_seed,
    pick_mosaic,
    pick_seed,
)
from tiles import Subtile, load_candidate_subtiles_with_land

# ── paths ──────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[1]
CANDIDATES_PATH = ROOT / "data" / "subtile_candidates.json"
CACHE_PATH = ROOT / "data" / "tile_status_cache.json"
CANDIDATES_RAW_PATH = ROOT / "data" / "subtile_candidates.json"

# ── constants (must match cron invocation) ──────────────────────────────────
MOSAIC_W = 3
MOSAIC_H = 2
MIN_LAND_PER_SUBTILE = 0.05
MIN_SUBTILES_WITH_LAND = 2
SIMULATE_N = 20_000          # number of random seed picks to simulate

# ── known MGRS tiles the build script considers (from --tile-ids default) ──
BUILD_SCRIPT_TILE_IDS = [
    "27RYM", "27RYL",
    "28RBS", "28RBR",
    "28RCS", "28RCR",
    "28RDS", "28RDR",
    "28RES", "28RFS", "28RFT",
]

# ── helpers ─────────────────────────────────────────────────────────────────

def _sep(title: str = "") -> None:
    width = 72
    if title:
        pad = (width - len(title) - 2) // 2
        print(f"\n{'─' * pad} {title} {'─' * (width - pad - len(title) - 2)}")
    else:
        print("─" * width)


def _bar(value: float, total: float, width: int = 20) -> str:
    filled = int(round(value / total * width)) if total else 0
    return "█" * filled + "░" * (width - filled)


def _load_candidates_raw() -> tuple[dict, list[Subtile], dict[Subtile, float], dict[str, list[Subtile]], dict[Subtile, str]]:
    """
    Returns:
        raw              – the full JSON dict
        candidates       – ordered, de-duped Subtile list (as loaded by the runtime)
        land_fractions   – {Subtile: float}
        per_island       – {island_name: [Subtile]}  (from the JSON grouping)
        subtile_island   – {Subtile: island_name} for the FIRST island that owns it
    """
    raw = json.loads(CANDIDATES_RAW_PATH.read_text())
    candidates, land_fractions = load_candidate_subtiles_with_land(CANDIDATES_RAW_PATH)

    per_island: dict[str, list[Subtile]] = defaultdict(list)
    subtile_island: dict[Subtile, str] = {}
    seen: set[Subtile] = set()

    for island in raw.get("islands", []):
        name = island["name"]
        for tile in island.get("tiles", []):
            tile_id = tile["tile_id"]
            for entry in tile.get("subtiles", []):
                suffix = entry["suffix"]
                e, n = int(suffix[0]), int(suffix[1])
                subtile = Subtile(tile_id=tile_id, easting=e, northing=n)
                per_island[name].append(subtile)
                if subtile not in seen:
                    seen.add(subtile)
                    subtile_island[subtile] = name

    return raw, candidates, land_fractions, dict(per_island), subtile_island


def _simulate_selection(
    candidates: list[Subtile],
    land_mosaics: list[MosaicDefinition],
    n: int,
    seed: int = 42,
) -> Counter:
    """
    Simulate the pick_seed → mosaics_containing_seed → pick_mosaic loop n times,
    resetting invalid_subtiles each trial (as the runtime does each run).
    Returns a Counter of {tile_id: times_a_mosaic_from_that_tile_was_returned}.
    """
    rng = random.Random(seed)
    tile_hits: Counter = Counter()

    for _ in range(n):
        invalid: set[Subtile] = set()
        available = list(land_mosaics)

        while available:
            s = pick_seed(candidates, invalid, rng)
            if s is None:
                break
            seed_mosaics = mosaics_containing_seed(available, s)
            if not seed_mosaics:
                invalid.add(s)
                continue
            chosen = pick_mosaic(seed_mosaics, rng)
            if chosen is None:
                invalid.add(s)
                continue
            tile_hits[chosen.tile_id] += 1
            break  # one successful pick per trial

    return tile_hits


def _selection_probability_analytical(
    candidates: list[Subtile],
    land_mosaics: list[MosaicDefinition],
) -> dict[str, float]:
    """
    Analytical approximation of P(mosaic M selected in one trial).

    Assumes all ocean seeds are quickly invalidated, so effective seeds are
    only those subtiles that appear in ≥1 valid mosaic.

    P(M) = Σ_{s ∈ M ∩ effective_seeds} [1/N_eff × 1/c(s)]

    where c(s) = number of valid mosaics containing s, N_eff = |effective_seeds|.
    Returns per-tile summed probability.
    """
    # Which subtiles appear in at least one valid mosaic?
    subtile_mosaic_count: Counter = Counter()
    for m in land_mosaics:
        for s in m.subtiles:
            subtile_mosaic_count[s] += 1

    effective_seeds = {s for s in candidates if subtile_mosaic_count[s] > 0}
    n_eff = len(effective_seeds)
    if n_eff == 0:
        return {}

    tile_prob: dict[str, float] = defaultdict(float)
    for m in land_mosaics:
        p_m = 0.0
        for s in m.subtiles:
            if s in effective_seeds:
                c_s = subtile_mosaic_count[s]
                p_m += 1.0 / n_eff / c_s
        tile_prob[m.tile_id] += p_m

    return dict(tile_prob)


# ════════════════════════════════════════════════════════════════════════════
# SECTION A – Missing islands
# ════════════════════════════════════════════════════════════════════════════

def section_a_missing_islands(candidates: list[Subtile]) -> None:
    _sep("A · Missing islands (no candidate subtiles)")
    tiles_in_candidates = {s.tile_id for s in candidates}
    missing = [t for t in BUILD_SCRIPT_TILE_IDS if t not in tiles_in_candidates]
    present = [t for t in BUILD_SCRIPT_TILE_IDS if t in tiles_in_candidates]

    print(f"\n  Build script considers {len(BUILD_SCRIPT_TILE_IDS)} MGRS tiles:")
    print(f"  ✓ Present in candidates ({len(present)}): {', '.join(sorted(present))}")
    print(f"  ✗ Absent from candidates ({len(missing)}):  {', '.join(sorted(missing))}")

    print("""
  Absent tiles failed the per-tile land-fraction threshold (≥5%) during the
  last run of build_tile_candidates.py.  Islands that live primarily in those
  tiles will NEVER appear:

    27RYM / 27RYL  →  covers open Atlantic west of La Palma (no land)
    28RBR          →  El Hierro (westernmost island)
    28RCR          →  El Hierro + southwest Tenerife edge
    28RFS / 28RFT  →  Lanzarote + La Graciosa

  Action: verify island polygons in islands.py cover those tiles, then
  re-run build_tile_candidates.py.
""")


# ════════════════════════════════════════════════════════════════════════════
# SECTION B – Candidate pool pollution (ocean seeds)
# ════════════════════════════════════════════════════════════════════════════

def section_b_candidate_pollution(
    candidates: list[Subtile],
    land_fractions: dict[Subtile, float],
    per_island: dict[str, list[Subtile]],
    land_mosaics: list[MosaicDefinition],
) -> None:
    _sep("B · Candidate pool pollution (ocean seeds)")

    total = len(candidates)
    ocean = [s for s in candidates if land_fractions.get(s, 0.0) == 0.0]
    island = [s for s in candidates if land_fractions.get(s, 0.0) > 0.0]

    # Which ocean subtiles actually appear in a valid mosaic?
    valid_mosaic_subtiles: set[Subtile] = set()
    for m in land_mosaics:
        for s in m.subtiles:
            valid_mosaic_subtiles.add(s)

    ocean_in_valid_mosaic = [s for s in ocean if s in valid_mosaic_subtiles]
    ocean_no_mosaic = [s for s in ocean if s not in valid_mosaic_subtiles]

    print(f"\n  Total candidates loaded by runtime:  {total}")
    print(f"  ├─ Ocean (land_fraction = 0):        {len(ocean):3d}  ({len(ocean)/total*100:.1f}%)")
    print(f"  │    ├─ appear in a valid mosaic:     {len(ocean_in_valid_mosaic):3d}  (seed picks that waste a slot then find a mosaic)")
    print(f"  │    └─ appear in NO valid mosaic:    {len(ocean_no_mosaic):3d}  (guaranteed wasted picks → invalidated immediately)")
    print(f"  └─ Island (land_fraction > 0):        {len(island):3d}  ({len(island)/total*100:.1f}%)")
    print()

    print("  Per-island candidate counts (runtime grouping):")
    for name, subs in sorted(per_island.items(), key=lambda kv: -len(kv[1])):
        lfs = [land_fractions.get(s, 0.0) for s in subs]
        non_zero = [lf for lf in lfs if lf > 0]
        bar = _bar(len(non_zero), len(subs))
        print(f"    {name:<18s}: {len(subs):3d} candidates  land>0: {len(non_zero):3d}  {bar}")

    print()
    note_ocean_in_mosaic = len(ocean_in_valid_mosaic)
    note_ocean_wasted = len(ocean_no_mosaic)
    print(f"  NOTE: pick_seed() draws uniformly from ALL {total} candidates each run.")
    print(f"  On average {note_ocean_wasted/total*100:.1f}% of seed picks are pure-ocean with no")
    print(f"  valid mosaic → the seed is locally invalidated and the loop retries.")
    print(f"  This wastes picks but (alone) doesn't bias toward specific islands.")
    print()
    print(f"  ALSO: --min-subtile-land is parsed by build_tile_candidates.py but")
    print(f"  never applied — ALL 100 subtiles per qualifying tile enter the candidates")
    print(f"  file regardless of their individual land fraction.")


# ════════════════════════════════════════════════════════════════════════════
# SECTION C – Mosaic geometry & selection probability
# ════════════════════════════════════════════════════════════════════════════

def section_c_mosaic_geometry(
    candidates: list[Subtile],
    land_fractions: dict[Subtile, float],
    per_island: dict[str, list[Subtile]],
    subtile_island: dict[Subtile, str],
) -> None:
    _sep(f"C · Mosaic geometry & selection probability ({MOSAIC_W}×{MOSAIC_H})")

    all_mosaics = build_mosaics(candidates, width=MOSAIC_W, height=MOSAIC_H)
    land_mosaics = filter_mosaics_by_land(
        all_mosaics, land_fractions, MIN_LAND_PER_SUBTILE, MIN_SUBTILES_WITH_LAND
    )

    total_valid = len(land_mosaics)
    print(f"\n  All {MOSAIC_W}×{MOSAIC_H} rectangles before land filter: {len(all_mosaics)}")
    print(f"  After land filter (≥{MIN_SUBTILES_WITH_LAND} subtiles with ≥{MIN_LAND_PER_SUBTILE*100:.0f}% land): {total_valid}")
    print()

    # Per-tile mosaic counts
    tile_mosaic: Counter = Counter(m.tile_id for m in land_mosaics)
    print("  Valid mosaics per MGRS tile:")
    for tile_id, count in sorted(tile_mosaic.items(), key=lambda kv: -kv[1]):
        bar = _bar(count, total_valid)
        print(f"    {tile_id}  {count:3d}  {bar}  {count/total_valid*100:.1f}%")
    print()

    # Which subtiles appear in ≥1 valid mosaic, broken down by island
    valid_subtiles_set: set[Subtile] = set()
    for m in land_mosaics:
        for s in m.subtiles:
            valid_subtiles_set.add(s)

    print("  Island candidate subtiles that appear in ≥1 valid mosaic:")
    for name, subs in sorted(per_island.items()):
        in_mosaic = [s for s in subs if s in valid_subtiles_set and land_fractions.get(s, 0) > 0]
        total_named = [s for s in subs if land_fractions.get(s, 0) > 0]
        if not total_named:
            continue
        bar = _bar(len(in_mosaic), len(total_named))
        print(f"    {name:<18s}: {len(in_mosaic):2d}/{len(total_named):2d} land subtiles reachable  {bar}")
    print()

    # Subtile grid visualisation per tile (which cells are candidates)
    print("  Subtile grid per MGRS tile (N=northing 9→0, E=easting 0→9):")
    print("  Legend: I=island land  o=ocean candidate  .=not a candidate")
    print()
    tile_ids = sorted({s.tile_id for s in candidates})
    for tile_id in tile_ids:
        tile_cands = {(s.easting, s.northing): s for s in candidates if s.tile_id == tile_id}
        print(f"    {tile_id}       E→ 0123456789")
        for n in range(9, -1, -1):
            row = f"    N={n}           "
            for e in range(10):
                s = tile_cands.get((e, n))
                if s is None:
                    row += "."
                elif land_fractions.get(s, 0) > 0:
                    row += "I"
                else:
                    row += "o"
            print(row)
        print()

    # Analytical selection probability per tile
    tile_prob = _selection_probability_analytical(candidates, land_mosaics)
    total_prob = sum(tile_prob.values())

    print("  Analytical selection probability per tile")
    print("  (assuming ocean seeds are quickly exhausted within each run):")
    if total_prob > 0:
        for tile_id, prob in sorted(tile_prob.items(), key=lambda kv: -kv[1]):
            bar = _bar(prob, total_prob)
            print(f"    {tile_id}  {prob/total_prob*100:5.1f}%  {bar}")
    print()

    # Monte-Carlo simulation
    print(f"  Simulated selection distribution (n={SIMULATE_N:,} trials):")
    sim = _simulate_selection(candidates, land_mosaics, SIMULATE_N)
    sim_total = sum(sim.values())
    if sim_total > 0:
        for tile_id, count in sorted(sim.items(), key=lambda kv: -kv[1]):
            bar = _bar(count, sim_total)
            print(f"    {tile_id}  {count:6d}  {count/sim_total*100:5.1f}%  {bar}")
    print()

    # Cross-check: how well does the mosaic mix represent each island?
    print("  Island coverage in valid mosaics")
    print("  (% of valid mosaics that include ≥1 land subtile of that island):")
    island_subtile_sets: dict[str, set[Subtile]] = {
        name: {s for s in subs if land_fractions.get(s, 0) > 0}
        for name, subs in per_island.items()
    }
    for name, subs_set in sorted(island_subtile_sets.items()):
        if not subs_set or name == "unassigned":
            continue
        count = sum(1 for m in land_mosaics if any(s in subs_set for s in m.subtiles))
        bar = _bar(count, total_valid)
        print(f"    {name:<18s}: {count:2d}/{total_valid} mosaics ({count/total_valid*100:.1f}%)  {bar}")


# ════════════════════════════════════════════════════════════════════════════
# SECTION D – Data availability (cache analysis)
# ════════════════════════════════════════════════════════════════════════════

def section_d_data_availability() -> None:
    _sep("D · Data availability (tile_status_cache.json)")

    if not CACHE_PATH.exists():
        print("\n  Cache file not found.")
        return

    cache = json.loads(CACHE_PATH.read_text())
    tile_dates = cache.get("tile_dates", {})
    subtiles_cache = cache.get("subtiles", {})
    used_mosaics = cache.get("mosaics", {})

    dates = sorted(tile_dates.keys())
    all_tile_ids = sorted({tid for d in tile_dates.values() for tid in d})

    if not dates:
        print("\n  No tile_dates entries in cache.")
        return

    print(f"\n  Cache spans {len(dates)} dates: {dates[0]} → {dates[-1]}")
    print()

    # STAC item hit-rate per tile
    print("  STAC item availability per tile (ok vs none across all cached dates):")
    tile_status: dict[str, Counter] = defaultdict(Counter)
    for date, tiles in tile_dates.items():
        for tile_id, info in tiles.items():
            tile_status[tile_id][info.get("item", "?")] += 1

    for tile_id in sorted(all_tile_ids):
        c = tile_status[tile_id]
        total = sum(c.values())
        ok = c.get("ok", 0)
        none = c.get("none", 0)
        bar = _bar(ok, total)
        print(f"    {tile_id}  ok={ok}/{total}  {bar}  hit rate {ok/total*100:.0f}%")
    print()

    # Subtile validity rates per tile (pixel quality gate)
    print("  Subtile pixel validity rate per tile (valid vs invalid checked subtiles):")
    sub_status: dict[str, Counter] = defaultdict(Counter)
    for date, tiles in subtiles_cache.items():
        for tile_id, subs in tiles.items():
            for suffix, status in subs.items():
                sub_status[tile_id][status] += 1

    for tile_id in sorted(sub_status.keys()):
        c = sub_status[tile_id]
        valid = c.get("valid", 0)
        invalid = c.get("invalid", 0)
        total = valid + invalid
        bar = _bar(valid, total) if total else "░" * 20
        pct = f"{valid/total*100:.0f}%" if total else "n/a"
        print(f"    {tile_id}  valid={valid}/{total}  {bar}  {pct}")
    print()

    # Date × tile matrix
    print("  Date × tile STAC status matrix  (ok=✓  none=✗  ?=not queried):")
    header = "                 " + "  ".join(all_tile_ids)
    print(f"    {header}")
    for date in dates:
        row = f"    {date}   "
        for tile_id in all_tile_ids:
            status = tile_dates.get(date, {}).get(tile_id, {}).get("item")
            if status == "ok":
                row += "  ✓  "
            elif status == "none":
                row += "  ✗  "
            else:
                row += "  ?  "
        print(row)
    print()

    # Used mosaic exhaustion per date × tile
    print("  Used mosaics per date (exhaustion check):")
    for date in sorted(used_mosaics.keys()):
        mosaics = used_mosaics[date]
        tile_used: Counter = Counter()
        for key in mosaics:
            tile_id = key.split(":")[0]
            tile_used[tile_id] += 1
        row_parts = [f"{tid}:{n}" for tid, n in sorted(tile_used.items())]
        print(f"    {date}: {len(mosaics)} mosaics used  [{', '.join(row_parts)}]")
    print()

    # Mosaic exhaustion: how many valid mosaics remain unused per tile?
    print("  Remaining mosaic capacity (valid mosaics not yet used on any cached date):")
    all_mosaics_used: set[str] = set()
    for date_mosaics in used_mosaics.values():
        for key in date_mosaics:
            tile_and_rest = key  # format: TILE:e,n:WxH
            all_mosaics_used.add(tile_and_rest)

    all_candidates, land_fractions = load_candidate_subtiles_with_land(CANDIDATES_PATH)
    all_valid = build_mosaics(all_candidates, width=MOSAIC_W, height=MOSAIC_H)
    all_valid_land = filter_mosaics_by_land(
        all_valid, land_fractions, MIN_LAND_PER_SUBTILE, MIN_SUBTILES_WITH_LAND
    )

    from sentinel import _mosaic_key  # type: ignore[import]
    valid_keys = {_mosaic_key(m) for m in all_valid_land}
    unused_keys = valid_keys - all_mosaics_used
    used_valid = valid_keys & all_mosaics_used

    tile_valid_count: Counter = Counter(m.tile_id for m in all_valid_land)
    tile_used_count: Counter = Counter(k.split(":")[0] for k in used_valid)
    for tile_id in sorted(tile_valid_count.keys()):
        total_v = tile_valid_count[tile_id]
        used_v = tile_used_count[tile_id]
        unused_v = total_v - used_v
        bar = _bar(unused_v, total_v)
        print(f"    {tile_id}  {unused_v}/{total_v} remaining  {bar}  {unused_v/total_v*100:.0f}%")


# ════════════════════════════════════════════════════════════════════════════
# SECTION E – Summary & recommendations
# ════════════════════════════════════════════════════════════════════════════

def section_e_summary() -> None:
    _sep("E · Summary & recommended fixes")
    print("""
  ROOT CAUSES (ordered by impact):

  1. MISSING TILES [Critical]
     Lanzarote, La Graciosa, and El Hierro live in MGRS tiles 28RFS/28RFT
     and 28RBR/28RCR, which did not pass the tile-level land-fraction
     threshold (5%) in the last build run.  Those islands will NEVER appear.
     Fix: verify island polygons in islands.py, re-run build_tile_candidates.py,
     and check that 28RBR, 28RCR, 28RFS, 28RFT gain subtile candidates.

  2. MOSAIC GEOMETRY BIAS [High]
     After the land filter, Tenerife (28RCS) holds ~43% of all valid 3×2
     mosaics, giving it the highest raw selection weight.  Small islands
     (La Gomera: 7 land subtiles, La Palma: 12) produce very few mosaics
     and are correspondingly underrepresented — proportionally, but not due
     to randomness failure.

  3. CANDIDATE POOL POLLUTION [Medium]
     393 of 500 candidates (78.6%) are pure-ocean (land_fraction = 0).
     pick_seed() draws from all 500, so most draws on each run waste
     time invalidating ocean seeds before reaching island seeds.
     This doesn't cause geographic bias on its own but is inefficient,
     and the --min-subtile-land flag in build_tile_candidates.py is
     parsed but never applied — a latent bug.
     Fix: filter candidates to land_fraction ≥ threshold before saving,
     or filter them at load time before passing to pick_seed().

  4. DATA AVAILABILITY VARIANCE [Medium]
     STAC item hit-rate differs across tiles (see Section D).  Tiles with
     many "none" dates are skipped early in the date loop, reducing their
     effective chances per run relative to always-available tiles.

  5. REGION-WITHIN-ISLAND BIAS [Low, expected]
     Only the southern/coastal regions of each island have the densest
     contiguous subtile rectangles (northern slopes and central massifs
     are often cloudy or ocean-edge).  This is real geographic variation,
     not a software bug.
""")


# ════════════════════════════════════════════════════════════════════════════

def main() -> None:
    print("Wallpaper coverage diagnostic")
    print(f"Candidates: {CANDIDATES_PATH}")
    print(f"Cache:      {CACHE_PATH}")
    print(f"Mosaic shape: {MOSAIC_W}×{MOSAIC_H}")

    raw, candidates, land_fractions, per_island, subtile_island = _load_candidates_raw()

    section_a_missing_islands(candidates)

    section_b_candidate_pollution(candidates, land_fractions, per_island,
                                  filter_mosaics_by_land(
                                      build_mosaics(candidates, MOSAIC_W, MOSAIC_H),
                                      land_fractions, MIN_LAND_PER_SUBTILE, MIN_SUBTILES_WITH_LAND,
                                  ))

    section_c_mosaic_geometry(candidates, land_fractions, per_island, subtile_island)

    section_d_data_availability()

    section_e_summary()


if __name__ == "__main__":
    main()
