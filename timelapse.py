#!/usr/bin/env python3
"""
Timelapse generator for a fixed tile mosaic over a date range.

Usage:
    python timelapse.py --top-left-subtile 28RCS02
    python timelapse.py --top-left-subtile 28RCS02 --days 365 --format gif
    python timelapse.py --top-left-subtile 28RCS02 --start 2024-01-01 --end 2025-01-01
    python timelapse.py --top-left-subtile 28RCS02 --days 90 --format jpg --output frames/
"""

import argparse
import concurrent.futures
import logging
import re
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from PIL import Image

from mosaic_reference import (
    build_mosaic_positions,
    format_top_left_subtile,
    parse_capture_date,
    parse_top_left_subtile,
    shift_top_left_subtile,
)
from mosaic_selector import MosaicDefinition
from sentinel import (
    TileReadError,
    _attempt_mosaic,
    _empty_cache,
    _list_tile_dates,
)

PROJECT_DIR = Path(__file__).parent.resolve()
OUTPUT_DIR = PROJECT_DIR / "timelapses"

DEFAULT_MOSAIC_WIDTH = 4
DEFAULT_MOSAIC_HEIGHT = 3
DEFAULT_CLOUD_COVER = 100
DEFAULT_VALID_PIXEL_MIN = 0.98
DEFAULT_MAX_WORKERS = 4
DEFAULT_FPS = 4
DEFAULT_FORMAT = "mp4"
DEFAULT_DAYS = 365

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logging.getLogger("botocore").setLevel(logging.WARNING)
logging.getLogger("boto3").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("rasterio").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def parse_shape(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d+)x(\d+)", value.strip().lower())
    if not match:
        raise argparse.ArgumentTypeError("Expected shape as WxH, e.g. 4x3")
    w, h = int(match.group(1)), int(match.group(2))
    if not (1 <= w <= 10 and 1 <= h <= 10):
        raise argparse.ArgumentTypeError("Shape dimensions must be 1–10")
    return w, h


def _build_fixed_mosaic(
    top_left: str,
    width: int,
    height: int,
    offset_east: int = 0,
    offset_north: int = 0,
) -> MosaicDefinition:
    subtile = parse_top_left_subtile(top_left)
    subtile = shift_top_left_subtile(subtile, east_offset=offset_east, north_offset=offset_north)
    positions = build_mosaic_positions(subtile, mosaic_width=width, mosaic_height=height)
    return MosaicDefinition(
        tile_id=subtile.tile_id,
        origin_easting=subtile.easting,
        origin_northing=subtile.northing,
        width=width,
        height=height,
        subtiles=tuple(s for s, _, _ in positions),
        top_left_subtile=subtile,
        positions=positions,
    )


def _fetch_frame(
    date: str,
    mosaic: MosaicDefinition,
    max_cloud_cover: int,
    valid_pixel_min: float,
    counter: list[int],
    total: int,
    lock: threading.Lock,
) -> tuple[str, np.ndarray] | None:
    result: tuple[str, np.ndarray] | None = None
    status = "skip"
    try:
        # Fresh cache per thread — no shared mutable state
        rgb, _ = _attempt_mosaic(
            mosaic=mosaic,
            date=date,
            max_cloud_cover=max_cloud_cover,
            valid_pixel_min=valid_pixel_min,
            cache=_empty_cache(),
        )
        if rgb is not None:
            result = (date, rgb)
            status = "ok"
    except TileReadError as exc:
        logger.debug("Date %s TileReadError: %s", date, exc)
    except Exception as exc:
        logger.warning("Date %s unexpected error: %s", date, exc)

    with lock:
        counter[0] += 1
        done = counter[0]
    logger.info("[%d/%d] %s — %s", done, total, date, status)
    return result


def _write_mp4(frames: list[tuple[str, np.ndarray]], output: Path, fps: int) -> None:
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        raise RuntimeError(
            "ffmpeg not found — install it (e.g. brew install ffmpeg) to generate MP4 output"
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        for i, (_, rgb) in enumerate(frames):
            Image.fromarray(rgb).save(tmp / f"frame_{i:04d}.png")
        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(fps),
            "-i", str(tmp / "frame_%04d.png"),
            "-vf", f"fps={fps}",  # force constant frame rate, eliminates ghost final frame
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-crf", "18",
            str(output),
        ]
        subprocess.run(cmd, check=True)


def _write_gif(frames: list[tuple[str, np.ndarray]], output: Path, fps: int) -> None:
    images = [Image.fromarray(rgb) for _, rgb in frames]
    duration_ms = max(1, round(1000 / fps))
    images[0].save(
        output,
        save_all=True,
        append_images=images[1:],
        duration=duration_ms,
        loop=0,
        optimize=False,
    )


def _write_jpeg_frames(
    frames: list[tuple[str, np.ndarray]],
    output_dir: Path,
    quality: int,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for date, rgb in frames:
        Image.fromarray(rgb).save(output_dir / f"frame_{date}.jpg", "JPEG", quality=quality)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a timelapse from Sentinel-2 imagery for a fixed tile mosaic"
    )
    parser.add_argument(
        "--top-left-subtile",
        required=True,
        metavar="SUBTILE",
        help="Top-left (NW) subtile of the mosaic, e.g. 28RCS02",
    )
    parser.add_argument(
        "--shape",
        type=parse_shape,
        default=None,
        metavar="WxH",
        help=f"Mosaic shape in 10km subtiles (default: {DEFAULT_MOSAIC_WIDTH}x{DEFAULT_MOSAIC_HEIGHT})",
    )
    parser.add_argument(
        "--mosaic-width",
        type=int,
        metavar="N",
        help=f"Mosaic width in subtiles (default: {DEFAULT_MOSAIC_WIDTH})",
    )
    parser.add_argument(
        "--mosaic-height",
        type=int,
        metavar="N",
        help=f"Mosaic height in subtiles (default: {DEFAULT_MOSAIC_HEIGHT})",
    )
    parser.add_argument(
        "--offset-east",
        type=int,
        default=0,
        metavar="N",
        help="Shift top-left subtile east (+) or west (-) by N subtiles",
    )
    parser.add_argument(
        "--offset-north",
        type=int,
        default=0,
        metavar="N",
        help="Shift top-left subtile north (+) or south (-) by N subtiles",
    )

    date_group = parser.add_mutually_exclusive_group()
    date_group.add_argument(
        "--days",
        type=int,
        metavar="N",
        help=f"Search N days back from today (default: {DEFAULT_DAYS})",
    )
    date_group.add_argument(
        "--start",
        type=str,
        metavar="DATE",
        help="Start date (YYYY-MM-DD or YYYYMMDD); use with optional --end",
    )
    parser.add_argument(
        "--end",
        type=str,
        metavar="DATE",
        default=None,
        help="End date (YYYY-MM-DD or YYYYMMDD); defaults to today",
    )

    parser.add_argument(
        "--cloud-cover",
        type=int,
        default=DEFAULT_CLOUD_COVER,
        metavar="PCT",
        help=f"Max cloud cover %% (default: {DEFAULT_CLOUD_COVER})",
    )
    parser.add_argument(
        "--valid-pixel-min",
        type=float,
        default=DEFAULT_VALID_PIXEL_MIN,
        metavar="F",
        help=f"Minimum valid pixel fraction per subtile (default: {DEFAULT_VALID_PIXEL_MIN})",
    )
    parser.add_argument(
        "--format",
        choices=["mp4", "gif", "jpg"],
        default=DEFAULT_FORMAT,
        help=f"Output format: mp4 (default), gif, or jpg (individual frames)",
    )
    parser.add_argument(
        "--fps",
        type=int,
        default=DEFAULT_FPS,
        metavar="N",
        help=f"Frames per second for mp4/gif animation (default: {DEFAULT_FPS})",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=DEFAULT_MAX_WORKERS,
        metavar="N",
        help=f"Max concurrent fetch workers (default: {DEFAULT_MAX_WORKERS})",
    )
    parser.add_argument(
        "--jpeg-quality",
        type=int,
        default=90,
        metavar="Q",
        help="JPEG quality 1–95 (default: 90; only used with --format jpg)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        metavar="PATH",
        help="Output path — file for mp4/gif, directory for jpg (auto-named if omitted)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Resolve mosaic shape
    if args.shape is not None:
        mosaic_width, mosaic_height = args.shape
    else:
        mosaic_width = args.mosaic_width or DEFAULT_MOSAIC_WIDTH
        mosaic_height = args.mosaic_height or DEFAULT_MOSAIC_HEIGHT

    # Resolve date range (end defaults to today)
    try:
        end_date = parse_capture_date(args.end or datetime.now().strftime("%Y-%m-%d"))
    except ValueError as exc:
        parser.error(f"Invalid --end date: {exc}")

    if args.start is not None:
        try:
            start_date = parse_capture_date(args.start)
        except ValueError as exc:
            parser.error(f"Invalid --start date: {exc}")
    else:
        days = args.days or DEFAULT_DAYS
        start_date = (
            datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=days - 1)
        ).strftime("%Y-%m-%d")

    if start_date >= end_date:
        parser.error("--start must be before --end")

    # Build the fixed mosaic
    try:
        mosaic = _build_fixed_mosaic(
            args.top_left_subtile,
            mosaic_width,
            mosaic_height,
            offset_east=args.offset_east,
            offset_north=args.offset_north,
        )
    except ValueError as exc:
        parser.error(str(exc))

    top_left_label = format_top_left_subtile(mosaic.top_left_subtile)
    logger.info(
        "Timelapse: %s %dx%d from %s to %s",
        top_left_label, mosaic_width, mosaic_height, start_date, end_date,
    )

    # Query STAC API for all dates in range.
    # days_back is measured from now so we always cover the full start_date.
    tile_ids = sorted({s.tile_id for s in mosaic.subtiles})
    days_back_from_now = (datetime.now() - datetime.strptime(start_date, "%Y-%m-%d")).days + 1
    logger.info(
        "Querying STAC API across %d tile(s), searching %d days back...",
        len(tile_ids), days_back_from_now,
    )
    all_dates = _list_tile_dates(
        tile_ids=tile_ids,
        days_back=days_back_from_now,
        max_cloud_cover=args.cloud_cover,
        max_items_per_tile=10_000,
    )
    dates = sorted(d for d in all_dates if start_date <= d <= end_date)

    if not dates:
        logger.error("No imagery dates found between %s and %s", start_date, end_date)
        sys.exit(1)

    logger.info(
        "Found %d dates — fetching frames with %d workers...",
        len(dates), args.max_workers,
    )

    # Parallel frame fetch
    counter: list[int] = [0]
    lock = threading.Lock()
    results: list[tuple[str, np.ndarray]] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        future_to_date = {
            executor.submit(
                _fetch_frame,
                date,
                mosaic,
                args.cloud_cover,
                args.valid_pixel_min,
                counter,
                len(dates),
                lock,
            ): date
            for date in dates
        }
        for future in concurrent.futures.as_completed(future_to_date):
            frame = future.result()
            if frame is not None:
                results.append(frame)

    frames = sorted(results, key=lambda x: x[0])

    if not frames:
        logger.error("No frames successfully fetched")
        sys.exit(1)

    logger.info("%d/%d frames fetched successfully", len(frames), len(dates))

    # Resolve output path
    fmt = args.format
    if args.output:
        output = args.output
    else:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = {"mp4": ".mp4", "gif": ".gif", "jpg": ""}[fmt]
        name = f"timelapse_{top_left_label}_{start_date}_{end_date}_{timestamp}{suffix}"
        output = OUTPUT_DIR / name

    # Write output
    if fmt == "mp4":
        output.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Writing MP4 → %s", output)
        try:
            _write_mp4(frames, output, args.fps)
        except RuntimeError as exc:
            logger.error("%s", exc)
            sys.exit(1)
    elif fmt == "gif":
        output.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Writing GIF → %s", output)
        _write_gif(frames, output, args.fps)
    else:
        logger.info("Writing %d JPEG frames → %s/", len(frames), output)
        _write_jpeg_frames(frames, output, quality=args.jpeg_quality)

    logger.info("Done! %d frames written.", len(frames))


if __name__ == "__main__":
    main()
