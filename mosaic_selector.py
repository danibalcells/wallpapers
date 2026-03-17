from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Iterable

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
    per_tile: dict[str, set[tuple[int, int]]] = {}
    for subtile in subtiles:
        per_tile.setdefault(subtile.tile_id, set()).add((subtile.easting, subtile.northing))
    mosaics: list[MosaicDefinition] = []
    for tile_id, indices in per_tile.items():
        for origin_e in range(0, 10 - width + 1):
            for origin_n in range(0, 10 - height + 1):
                subtiles_in_rect: list[Subtile] = []
                missing = False
                for dx in range(width):
                    for dy in range(height):
                        easting = origin_e + dx
                        northing = origin_n + dy
                        if (easting, northing) not in indices:
                            missing = True
                            break
                        subtiles_in_rect.append(Subtile(tile_id=tile_id, easting=easting, northing=northing))
                    if missing:
                        break
                if missing:
                    continue
                top_left_subtile = Subtile(
                    tile_id=tile_id,
                    easting=origin_e,
                    northing=origin_n + height - 1,
                )
                positions = tuple(
                    (
                        subtile,
                        subtile.easting - origin_e,
                        top_left_subtile.northing - subtile.northing,
                    )
                    for subtile in subtiles_in_rect
                )
                mosaics.append(
                    MosaicDefinition(
                        tile_id=tile_id,
                        origin_easting=origin_e,
                        origin_northing=origin_n,
                        width=width,
                        height=height,
                        subtiles=tuple(subtiles_in_rect),
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
        if mosaic.tile_id != seed.tile_id:
            continue
        for subtile in mosaic.subtiles:
            if subtile.easting == seed.easting and subtile.northing == seed.northing:
                matches.append(mosaic)
                break
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
