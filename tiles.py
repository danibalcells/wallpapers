from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path


class CandidateListError(RuntimeError):
    pass


@dataclass(frozen=True)
class Subtile:
    tile_id: str
    easting: int
    northing: int

    def suffix(self) -> str:
        return f"{self.easting}{self.northing}"


def parse_tile_id(tile_id: str) -> tuple[int, str, str]:
    if len(tile_id) != 5:
        raise ValueError("Expected MGRS 100km tile id like 28RBS")
    utm_zone = int(tile_id[:2])
    latitude_band = tile_id[2]
    grid_square = tile_id[3:]
    return utm_zone, latitude_band, grid_square


def parse_subtile_suffix(suffix: str) -> tuple[int, int]:
    if len(suffix) != 2 or not suffix.isdigit():
        raise ValueError("Expected 2-digit subtile suffix")
    return int(suffix[0]), int(suffix[1])


def load_candidate_subtiles(path: Path) -> list[Subtile]:
    if not path.exists():
        raise CandidateListError(f"Candidate list file not found: {path}")
    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise CandidateListError(f"Invalid JSON in candidate list: {exc}") from exc
    parsed: list[Subtile] = []
    if not isinstance(raw, dict):
        raise CandidateListError("Candidate list must be an object")
    if "islands" in raw:
        islands = raw.get("islands")
        if not isinstance(islands, list):
            raise CandidateListError("Candidate list islands must be a list")
        for island in islands:
            if not isinstance(island, dict):
                raise CandidateListError("Candidate list islands must be objects")
            tiles = island.get("tiles")
            if not isinstance(tiles, list):
                raise CandidateListError("Candidate list tiles must be a list")
            for tile in tiles:
                if not isinstance(tile, dict):
                    raise CandidateListError("Candidate list tiles must be objects")
                tile_id = tile.get("tile_id")
                subtiles = tile.get("subtiles")
                if not isinstance(tile_id, str) or not isinstance(subtiles, list):
                    raise CandidateListError("Candidate list tiles require tile_id and subtiles")
                for entry in subtiles:
                    if not isinstance(entry, dict):
                        raise CandidateListError("Candidate list subtiles must be objects")
                    suffix = entry.get("suffix")
                    if not isinstance(suffix, str):
                        raise CandidateListError("Candidate list subtiles require suffix")
                    easting, northing = parse_subtile_suffix(suffix)
                    parsed.append(Subtile(tile_id=tile_id, easting=easting, northing=northing))
    elif "subtiles" in raw:
        subtiles = raw.get("subtiles")
        if not isinstance(subtiles, list):
            raise CandidateListError("Candidate list subtiles must be a list")
        for entry in subtiles:
            if not isinstance(entry, dict):
                raise CandidateListError("Candidate list entries must be objects")
            tile_id = entry.get("tile_id")
            suffix = entry.get("suffix")
            if not isinstance(tile_id, str) or not isinstance(suffix, str):
                raise CandidateListError("Candidate list entries require tile_id and suffix")
            easting, northing = parse_subtile_suffix(suffix)
            parsed.append(Subtile(tile_id=tile_id, easting=easting, northing=northing))
    else:
        raise CandidateListError("Candidate list must include islands or subtiles")
    parsed = list(dict.fromkeys(parsed))
    if not parsed:
        raise CandidateListError("Candidate list is empty")
    return parsed


def subtile_bbox_utm(
    tile_bbox_utm: tuple[float, float, float, float],
    subtile: Subtile,
) -> tuple[float, float, float, float]:
    minx, miny, _, _ = tile_bbox_utm
    subtile_size_m = 10_000.0
    west = minx + subtile.easting * subtile_size_m
    south = miny + subtile.northing * subtile_size_m
    east = west + subtile_size_m
    north = south + subtile_size_m
    return west, south, east, north
