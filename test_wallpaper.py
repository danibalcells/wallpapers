#!/usr/bin/env python3
"""Quick test script for wallpaper setting."""

import sys
import logging
import os
from pathlib import Path

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

from wallpaper import _set_wallpaper_macos_swift, _enable_macos_all_spaces

def main():
    script_dir = Path(__file__).parent
    images_dir = script_dir / "images"
    
    if len(sys.argv) > 1:
        image_path = sys.argv[1]
    else:
        if images_dir.exists():
            images = sorted(images_dir.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
        else:
            images = []
        
        if images:
            image_path = str(images[0])
            print(f"Using most recent image from images/: {image_path}")
        else:
            print("Usage: python test_wallpaper.py <image_path>")
            print(f"No images found in {images_dir}")
            sys.exit(1)
    
    image_path = os.path.abspath(image_path)
    
    print(f"\n=== Step 1: Setting wallpaper via Swift binary ===")
    print(f"Image: {image_path}\n")
    
    success = _set_wallpaper_macos_swift(image_path)
    
    if success:
        print("✓ Swift binary succeeded")
    else:
        print("✗ Swift binary failed")
        sys.exit(1)
    
    print(f"\n=== Step 2: Enabling 'show on all spaces' via plist ===\n")
    
    all_spaces_success = _enable_macos_all_spaces(image_path)
    
    if all_spaces_success:
        print("✓ All-spaces plist update succeeded")
    else:
        print("✗ All-spaces plist update failed")
    
    print("\n=== Done ===")

if __name__ == "__main__":
    main()
