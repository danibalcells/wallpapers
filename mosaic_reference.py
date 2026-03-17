from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from tiles import Subtile, parse_subtile_suffix


IMAGE_NAME_RE = re.compile(
    r"^canary_mosaic_(?P<date>\d{8})_(?P<tile>[0-9]{2}[A-Z][A-Z]{2}\d{2})_(?P<timestamp>\d{8}_\d{6})$"
)


@dataclass(frozen=True)
class ManualMosaicReference:
    date: str | None
    top_left_subtile: Subtile


MGRS_EASTING_SETS = ("ABCDEFGH", "JKLMNPQR", "STUVWXYZ")
MGRS_NORTHING_ODD = "ABCDEFGHJKLMNPQRSTUV"
MGRS_NORTHING_EVEN = "FGHJKLMNPQRSTUVABCDE"


def parse_top_left_subtile(value: str) -> Subtile:
    text = value.strip().upper()
    if len(text) != 7:
        raise ValueError("Expected top-left subtile like 28RCS02")
    tile_id = text[:5]
    easting, northing = parse_subtile_suffix(text[5:])
    return Subtile(tile_id=tile_id, easting=easting, northing=northing)


def format_top_left_subtile(subtile: Subtile) -> str:
    return f"{subtile.tile_id}{subtile.suffix()}"


def parse_capture_date(value: str) -> str:
    text = value.strip()
    if re.fullmatch(r"\d{8}", text):
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text
    raise ValueError("Expected date as YYYY-MM-DD or YYYYMMDD")


def parse_image_reference(value: str | Path) -> ManualMosaicReference:
    name = Path(value).stem
    match = IMAGE_NAME_RE.fullmatch(name)
    if match is None:
        raise ValueError(
            "Expected image filename like canary_mosaic_20260315_28RCS02_20260317_003024.png"
        )
    date = parse_capture_date(match.group("date"))
    top_left_subtile = parse_top_left_subtile(match.group("tile"))
    return ManualMosaicReference(date=date, top_left_subtile=top_left_subtile)


def _easting_letters_for_zone(zone: int) -> str:
    return MGRS_EASTING_SETS[(zone - 1) % len(MGRS_EASTING_SETS)]


def _northing_letters_for_zone(zone: int) -> str:
    return MGRS_NORTHING_ODD if zone % 2 == 1 else MGRS_NORTHING_EVEN


def _step_tile_east_west(tile_id: str, step: int) -> str:
    zone = int(tile_id[:2])
    band = tile_id[2]
    easting_letter = tile_id[3]
    northing_letter = tile_id[4]
    current_easting_letters = _easting_letters_for_zone(zone)
    current_northing_letters = _northing_letters_for_zone(zone)
    northing_index = current_northing_letters.index(northing_letter)
    easting_index = current_easting_letters.index(easting_letter) + step
    if 0 <= easting_index < len(current_easting_letters):
        return f"{zone:02d}{band}{current_easting_letters[easting_index]}{northing_letter}"

    next_zone = zone + step
    if not 1 <= next_zone <= 60:
        raise ValueError("Shifted tile leaves the supported UTM zone range")
    next_easting_letters = _easting_letters_for_zone(next_zone)
    next_northing_letters = _northing_letters_for_zone(next_zone)
    next_easting_letter = next_easting_letters[0] if step > 0 else next_easting_letters[-1]
    next_northing_letter = next_northing_letters[northing_index]
    return f"{next_zone:02d}{band}{next_easting_letter}{next_northing_letter}"


def _step_tile_north_south(tile_id: str, step: int) -> str:
    zone = int(tile_id[:2])
    band = tile_id[2]
    easting_letter = tile_id[3]
    northing_letter = tile_id[4]
    northing_letters = _northing_letters_for_zone(zone)
    northing_index = northing_letters.index(northing_letter) + step
    if not 0 <= northing_index < len(northing_letters):
        raise ValueError(
            "Shifted tile leaves the supported local MGRS northing range; "
            "latitude-band wrap is not implemented"
        )
    return f"{zone:02d}{band}{easting_letter}{northing_letters[northing_index]}"


def _step_subtile(subtile: Subtile, direction: str) -> Subtile:
    if direction == "east":
        if subtile.easting < 9:
            return Subtile(tile_id=subtile.tile_id, easting=subtile.easting + 1, northing=subtile.northing)
        return Subtile(tile_id=_step_tile_east_west(subtile.tile_id, 1), easting=0, northing=subtile.northing)
    if direction == "west":
        if subtile.easting > 0:
            return Subtile(tile_id=subtile.tile_id, easting=subtile.easting - 1, northing=subtile.northing)
        return Subtile(tile_id=_step_tile_east_west(subtile.tile_id, -1), easting=9, northing=subtile.northing)
    if direction == "north":
        if subtile.northing < 9:
            return Subtile(tile_id=subtile.tile_id, easting=subtile.easting, northing=subtile.northing + 1)
        return Subtile(tile_id=_step_tile_north_south(subtile.tile_id, 1), easting=subtile.easting, northing=0)
    if direction == "south":
        if subtile.northing > 0:
            return Subtile(tile_id=subtile.tile_id, easting=subtile.easting, northing=subtile.northing - 1)
        return Subtile(tile_id=_step_tile_north_south(subtile.tile_id, -1), easting=subtile.easting, northing=9)
    raise ValueError(f"Unsupported direction: {direction}")


def shift_top_left_subtile(
    subtile: Subtile,
    east_offset: int,
    north_offset: int,
) -> Subtile:
    shifted = subtile
    for _ in range(abs(east_offset)):
        shifted = _step_subtile(shifted, "east" if east_offset > 0 else "west")
    for _ in range(abs(north_offset)):
        shifted = _step_subtile(shifted, "north" if north_offset > 0 else "south")
    return shifted


def build_mosaic_positions(
    top_left_subtile: Subtile,
    mosaic_width: int,
    mosaic_height: int,
) -> tuple[tuple[Subtile, int, int], ...]:
    positions: list[tuple[Subtile, int, int]] = []
    row_start = top_left_subtile
    for row in range(mosaic_height):
        current = row_start
        for col in range(mosaic_width):
            positions.append((current, col, row))
            if col + 1 < mosaic_width:
                current = _step_subtile(current, "east")
        if row + 1 < mosaic_height:
            row_start = _step_subtile(row_start, "south")
    return tuple(positions)


def origin_from_top_left_subtile(top_left_subtile: Subtile, mosaic_height: int) -> Subtile:
    origin_northing = top_left_subtile.northing - (mosaic_height - 1)
    if origin_northing < 0:
        raise ValueError("Top-left subtile is too far south for the requested mosaic height")
    return Subtile(
        tile_id=top_left_subtile.tile_id,
        easting=top_left_subtile.easting,
        northing=origin_northing,
    )


def resolve_manual_selection(
    top_left_subtile: str | None,
    from_image: str | None,
    offset_east: int,
    offset_north: int,
    exact_date: str | None,
) -> tuple[str | None, str | None]:
    if top_left_subtile and from_image:
        raise ValueError("Use either --top-left-subtile or --from-image, not both")
    if top_left_subtile is None and from_image is None:
        if offset_east != 0 or offset_north != 0:
            raise ValueError("Offsets require --top-left-subtile or --from-image")
        return None, parse_capture_date(exact_date) if exact_date is not None else None

    reference_date: str | None = None
    if top_left_subtile is not None:
        subtile = parse_top_left_subtile(top_left_subtile)
    else:
        reference = parse_image_reference(from_image or "")
        subtile = reference.top_left_subtile
        reference_date = reference.date

    resolved_date = parse_capture_date(exact_date) if exact_date is not None else reference_date
    return format_top_left_subtile(subtile), resolved_date
