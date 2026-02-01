#!/usr/bin/env python3
"""Quick test script for wallpaper setting."""

import logging
import os
import subprocess
import argparse
from pathlib import Path

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

from wallpaper import _set_wallpaper_macos_swift, _enable_macos_all_spaces

def capture_screenshot(output_path: Path) -> bool:
    try:
        subprocess.run(
            ["screencapture", "-x", "-m", "-o", str(output_path)],
            check=True,
            capture_output=True,
            text=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def read_current_wallpaper_path() -> str | None:
    try:
        result = subprocess.run(
            ["osascript", "-e", 'tell application "System Events" to get picture of current desktop'],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() or None
    except subprocess.CalledProcessError:
        return None


def _resolve_image_path(image_arg: str | None, images_dir: Path) -> str:
    if image_arg:
        return image_arg
    if images_dir.exists():
        images = sorted(images_dir.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    else:
        images = []
    if images:
        image_path = str(images[0])
        print(f"Using most recent image from images/: {image_path}")
        return image_path
    print("Usage: python test_wallpaper.py --set-wallpaper [image_path]")
    print(f"No images found in {images_dir}")
    raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Test wallpaper setting behavior")
    parser.add_argument("image_path", nargs="?", help="Path to image file")
    parser.add_argument(
        "--set-wallpaper",
        action="store_true",
        help="Actually set the wallpaper"
    )
    args = parser.parse_args()

    script_dir = Path(__file__).parent
    images_dir = script_dir / "images"
    image_path = _resolve_image_path(args.image_path, images_dir)
    image_path = os.path.abspath(image_path)

    print(f"\nImage: {image_path}\n")

    # success = _set_wallpaper_macos_swift(image_path)
    # if success:
    #     print("✓ Swift binary succeeded")
    # else:
    #     print("✗ Swift binary failed")
    #     raise SystemExit(1)
    # print(f"\n=== Step 2: Enabling 'show on all spaces' via plist ===\n")
    # all_spaces_success = _enable_macos_all_spaces(image_path)
    # if all_spaces_success:
    #     print("✓ All-spaces plist update succeeded")
    # else:
    #     print("✗ All-spaces plist update failed")
    if args.set_wallpaper:
        print("=== Step 1: Setting wallpaper via Swift binary ===")
        success = _set_wallpaper_macos_swift(image_path)
        if success:
            print("✓ Swift binary succeeded")
        else:
            print("✗ Swift binary failed")
            raise SystemExit(1)

        print(f"\n=== Step 2: Enabling 'show on all spaces' via plist ===\n")
        all_spaces_success = _enable_macos_all_spaces(image_path)
        if all_spaces_success:
            print("✓ All-spaces plist update succeeded")
        else:
            print("✗ All-spaces plist update failed")
    else:
        print("Skipping wallpaper set (use --set-wallpaper)")

    current_wallpaper = read_current_wallpaper_path()
    if current_wallpaper:
        print(f"Current desktop picture: {current_wallpaper}")
    else:
        print("Could not read current desktop picture")

    screenshot_path = script_dir / "images" / "wallpaper_check.png"
    if capture_screenshot(screenshot_path):
        print(f"Screenshot saved: {screenshot_path}")
    else:
        print("Screenshot failed")

    print("\n=== Done ===")

if __name__ == "__main__":
    main()
