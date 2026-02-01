#!/usr/bin/env python3
"""Generate map URLs from a bbox string."""

from __future__ import annotations

import argparse
import re
import urllib.parse


def _parse_bbox(bbox_text: str) -> tuple[float, float, float, float]:
    matches = re.findall(r"-?\d+(?:\.\d+)?", bbox_text)
    if len(matches) != 4:
        raise ValueError("Expected 4 numeric values for bbox (west, south, east, north)")
    west, south, east, north = (float(value) for value in matches)
    if west >= east or south >= north:
        raise ValueError("Invalid bbox ordering; expected west < east and south < north")
    return west, south, east, north


def _osm_url(bbox: tuple[float, float, float, float]) -> str:
    west, south, east, north = bbox
    bbox_param = ",".join(f"{value:.6f}" for value in (west, south, east, north))
    query = urllib.parse.urlencode({"bbox": bbox_param})
    return f"https://www.openstreetmap.org/?{query}"


def _google_maps_url(bbox: tuple[float, float, float, float]) -> str:
    west, south, east, north = bbox
    southwest = f"{south:.6f},{west:.6f}"
    northeast = f"{north:.6f},{east:.6f}"
    return f"https://www.google.com/maps/dir/{southwest}/{northeast}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate Google Maps and OpenStreetMap URLs from a bbox string"
    )
    parser.add_argument(
        "bbox",
        help="Bounding box string like '(west, south, east, north)'"
    )
    args = parser.parse_args()
    bbox = _parse_bbox(args.bbox)
    print("OpenStreetMap:")
    print(_osm_url(bbox))
    print("\nGoogle Maps:")
    print(_google_maps_url(bbox))


if __name__ == "__main__":
    main()
