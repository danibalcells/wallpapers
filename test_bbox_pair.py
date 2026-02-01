#!/usr/bin/env python3
"""Test script for pair-mode bounding boxes."""

import argparse
import random
from dataclasses import dataclass
from typing import Iterable

from shapely.geometry import box
from shapely.ops import unary_union

from islands import generate_random_bbox_pair, ISLANDS, IslandName, NEIGHBOR_ISLANDS


@dataclass(frozen=True)
class BboxCheckResult:
    ok: bool
    reason: str
    islands: tuple[IslandName, IslandName]
    bbox: tuple[float, float, float, float]
    island_coverages: tuple[float, float]
    aspect_ratio: float


def _island_coverages(
    bbox: tuple[float, float, float, float],
    islands: Iterable[IslandName]
) -> tuple[float, float]:
    bbox_polygon = box(*bbox)
    coverages: list[float] = []
    for island in islands:
        polygon = ISLANDS[island]["polygon"]
        intersection = bbox_polygon.intersection(polygon)
        if polygon.area <= 0:
            coverages.append(0.0)
        else:
            coverages.append(intersection.area / polygon.area)
    if len(coverages) != 2:
        raise ValueError("Expected exactly two islands for coverage check")
    return coverages[0], coverages[1]


def _bbox_aspect_ratio(bbox: tuple[float, float, float, float]) -> float:
    west, south, east, north = bbox
    width = east - west
    height = north - south
    if height <= 0:
        return 0.0
    return width / height


def _bbox_covers_islands(bbox: tuple[float, float, float, float], islands: Iterable[IslandName]) -> bool:
    bbox_polygon = box(*bbox)
    for island in islands:
        polygon = ISLANDS[island]["polygon"]
        if not bbox_polygon.covers(polygon):
            return False
    return True


def check_bbox_pair(
    bbox: tuple[float, float, float, float],
    islands: tuple[IslandName, IslandName],
    min_island_coverage: float,
    aspect_ratio: tuple[int, int],
    aspect_ratio_tolerance: float
) -> BboxCheckResult:
    west, south, east, north = bbox
    if west >= east or south >= north:
        return BboxCheckResult(False, "invalid_bbox_bounds", islands, bbox, (0.0, 0.0), 0.0)

    if islands[1] not in NEIGHBOR_ISLANDS[islands[0]]:
        coverages = _island_coverages(bbox, islands)
        ratio = _bbox_aspect_ratio(bbox)
        return BboxCheckResult(False, "non_neighbor_pair", islands, bbox, coverages, ratio)

    if not _bbox_covers_islands(bbox, islands):
        coverages = _island_coverages(bbox, islands)
        ratio = _bbox_aspect_ratio(bbox)
        return BboxCheckResult(False, "bbox_not_covering_islands", islands, bbox, coverages, ratio)

    coverages = _island_coverages(bbox, islands)
    if min(coverages) < min_island_coverage:
        ratio = _bbox_aspect_ratio(bbox)
        return BboxCheckResult(False, "island_coverage_too_low", islands, bbox, coverages, ratio)

    target_ratio = aspect_ratio[0] / aspect_ratio[1]
    actual_ratio = _bbox_aspect_ratio(bbox)
    if actual_ratio <= 0 or abs(actual_ratio - target_ratio) > aspect_ratio_tolerance:
        return BboxCheckResult(False, "aspect_ratio_off", islands, bbox, coverages, actual_ratio)

    return BboxCheckResult(True, "ok", islands, bbox, coverages, actual_ratio)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate pair-mode bbox generation")
    parser.add_argument("--samples", type=int, default=200)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--min-island-coverage", type=float, default=0.3)
    parser.add_argument("--min-padding", type=float, default=0.1)
    parser.add_argument("--max-padding", type=float, default=0.4)
    parser.add_argument("--aspect", nargs=2, type=int, default=(16, 9))
    parser.add_argument("--aspect-tolerance", type=float, default=0.02)
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    failures: list[BboxCheckResult] = []
    for _ in range(args.samples):
        bbox, islands = generate_random_bbox_pair(
            min_island_coverage=args.min_island_coverage,
            min_padding_ratio=args.min_padding,
            max_padding_ratio=args.max_padding,
            aspect_ratio=tuple(args.aspect)
        )
        result = check_bbox_pair(
            bbox=bbox,
            islands=islands,
            min_island_coverage=args.min_island_coverage,
            aspect_ratio=tuple(args.aspect),
            aspect_ratio_tolerance=args.aspect_tolerance
        )
        if not result.ok:
            failures.append(result)

    print(f"Samples: {args.samples}")
    print(f"Failures: {len(failures)}")
    if failures:
        reasons: dict[str, int] = {}
        for failure in failures:
            reasons[failure.reason] = reasons.get(failure.reason, 0) + 1
        print("Failure reasons:")
        for reason, count in sorted(reasons.items(), key=lambda item: item[1], reverse=True):
            print(f"  {reason}: {count}")
        print("\nFailure examples:")
        target_ratio = args.aspect[0] / args.aspect[1]
        prioritized = [f for f in failures if f.reason == "island_coverage_too_low"]
        examples = (prioritized + [f for f in failures if f.reason != "island_coverage_too_low"])[:5]
        for idx, example in enumerate(examples, start=1):
            min_cover = min(example.island_coverages) * 100
            print(f"  {idx}. reason: {example.reason}")
            print(f"     islands: {example.islands}")
            print(f"     bbox: {example.bbox}")
            print(f"     island_coverage_min: {min_cover:.2f}% (min {args.min_island_coverage * 100:.2f}%)")
            print(f"     aspect_ratio: {example.aspect_ratio:.4f} (target {target_ratio:.4f})")


if __name__ == "__main__":
    main()
