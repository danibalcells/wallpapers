from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Iterable

from mosaic_reference import build_mosaic_positions
from tiles import Subtile


@dataclass(frozen=True)
class MosaicDefinition:
    tile_id: str
    origin_easting: int
    origin_northing: int
    width: int
    height: int
    subtiles: tuple[Subtile, ...]
    top_left_subtile: Subtile
    positions: tuple[tuple[Subtile, int, int], ...]


def build_mosaics(
    subtiles: Iterable[Subtile],
    width: int,
    height: int,
) -> list[MosaicDefinition]:
    if width < 1 or height < 1 or width > 10 or height > 10:
        raise ValueError("Mosaic width and height must be between 1 and 10")
    subtile_set = set(subtiles)
    mosaics: list[MosaicDefinition] = []
    for top_left_subtile in sorted(
        subtile_set,
        key=lambda subtile: (subtile.tile_id, subtile.easting, subtile.northing),
    ):
        positions = build_mosaic_positions(
            top_left_subtile=top_left_subtile,
            mosaic_width=width,
            mosaic_height=height,
        )
        subtiles_in_rect = tuple(subtile for subtile, _, _ in positions)
        if any(subtile not in subtile_set for subtile in subtiles_in_rect):
            continue
        mosaics.append(
            MosaicDefinition(
                tile_id=top_left_subtile.tile_id,
                origin_easting=top_left_subtile.easting,
                origin_northing=top_left_subtile.northing,
                width=width,
                height=height,
                subtiles=subtiles_in_rect,
                top_left_subtile=top_left_subtile,
                positions=positions,
            )
        )
    return mosaics


def mosaics_containing_seed(
    mosaics: Iterable[MosaicDefinition],
    seed: Subtile,
) -> list[MosaicDefinition]:
    matches: list[MosaicDefinition] = []
    for mosaic in mosaics:
        if seed in mosaic.subtiles:
            matches.append(mosaic)
    return matches


def filter_mosaics(
    mosaics: Iterable[MosaicDefinition],
    invalid_subtiles: set[Subtile],
) -> list[MosaicDefinition]:
    filtered: list[MosaicDefinition] = []
    for mosaic in mosaics:
        if any(subtile in invalid_subtiles for subtile in mosaic.subtiles):
            continue
        filtered.append(mosaic)
    return filtered


def filter_mosaics_by_land(
    mosaics: Iterable[MosaicDefinition],
    land_fractions: dict[Subtile, float],
    min_land_per_subtile: float,
    min_subtiles_with_land: int,
) -> list[MosaicDefinition]:
    filtered: list[MosaicDefinition] = []
    for mosaic in mosaics:
        count = sum(
            1 for subtile in mosaic.subtiles
            if land_fractions.get(subtile, 0.0) >= min_land_per_subtile
        )
        if count >= min_subtiles_with_land:
            filtered.append(mosaic)
    return filtered


def pick_seed(
    candidates: list[Subtile],
    invalid_subtiles: set[Subtile],
    rng: random.Random,
) -> Subtile | None:
    available = [subtile for subtile in candidates if subtile not in invalid_subtiles]
    if not available:
        return None
    return rng.choice(available)


def pick_mosaic(
    mosaics: list[MosaicDefinition],
    rng: random.Random,
) -> MosaicDefinition | None:
    if not mosaics:
        return None
    return rng.choice(mosaics)
