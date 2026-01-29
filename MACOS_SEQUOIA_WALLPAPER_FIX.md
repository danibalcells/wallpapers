# macOS Sequoia Wallpaper Fix

## The Problem

On **macOS 15 (Sequoia)**, programmatically setting wallpapers using traditional methods no longer works correctly. Tools like `desktoppr`, AppleScript, and even `NSWorkspace.setDesktopImageURL()` appear to succeed (return exit code 0) but:

1. The **visual wallpaper doesn't change**
2. The **"Show on all Spaces" checkbox gets unchecked** in System Settings
3. Subsequent attempts to change the wallpaper fail silently until the checkbox is manually re-checked

## Root Cause

Apple completely redesigned the wallpaper system in macOS Sonoma and Sequoia:

### Old System (pre-Sonoma)
- Wallpaper stored in `~/Library/Application Support/Dock/desktoppicture.db` (SQLite)
- `com.apple.desktop` preferences domain
- Single wallpaper API via `NSWorkspace`

### New System (Sequoia)
- Wallpaper managed by `WallpaperAgent` process
- Configuration stored in `~/Library/Application Support/com.apple.wallpaper/Store/Index.plist`
- Modular extension system (`com.apple.wallpaper.extension.*`)
- Separate settings for each Space and Display
- New `AllSpacesAndDisplays` plist section controls "Show on all Spaces"

The legacy APIs (`desktoppr`, AppleScript, `NSWorkspace`) still update the old metadata layers, but the visual wallpaper is controlled by the new `WallpaperAgent` system. When `setDesktopImageURL()` is called, it:
1. Sets the wallpaper for the **current space only**
2. Removes the wallpaper from `AllSpacesAndDisplays`
3. This unchecks "Show on all Spaces" in the UI

## The Solution

### Step 1: Use Swift Binary for Setting Wallpaper

The `NSWorkspace.setDesktopImageURL()` API still works for setting the wallpaper on the current space, but it must be called directly (not through legacy wrappers). We compile a small Swift binary:

```swift
import Cocoa

let imagePath = CommandLine.arguments[1]
let imageURL = URL(fileURLWithPath: imagePath)
let workspace = NSWorkspace.shared

for screen in NSScreen.screens {
    try workspace.setDesktopImageURL(imageURL, for: screen, options: [:])
}
```

### Step 2: Update Index.plist for All-Spaces Support

After setting the wallpaper, we modify the `Index.plist` to add the `Desktop` entry to the `AllSpacesAndDisplays` section. This effectively re-enables "Show on all Spaces":

```python
import plistlib
from pathlib import Path

plist_path = Path.home() / "Library/Application Support/com.apple.wallpaper/Store/Index.plist"

with open(plist_path, 'rb') as f:
    data = plistlib.load(f)

# Get Desktop entry from Displays or SystemDefault
desktop_entry = data['Displays'][display_id]['Desktop']

# Add to AllSpacesAndDisplays
data['AllSpacesAndDisplays']['Desktop'] = desktop_entry

with open(plist_path, 'wb') as f:
    plistlib.dump(data, f)
```

## Index.plist Structure

```
Index.plist
├── AllSpacesAndDisplays
│   ├── Desktop (← we add this)
│   │   └── Content → Choices → Files → [wallpaper path]
│   ├── Idle (screensaver)
│   └── Type: "idle" | "all"
├── Displays
│   └── {display-uuid}
│       ├── Desktop
│       └── Idle
├── Spaces
│   └── {space-uuid}
│       ├── Default
│       │   ├── Desktop
│       │   └── Idle
│       └── Displays
└── SystemDefault
    ├── Desktop
    └── Idle
```

## Key Findings

| Discovery | Details |
|-----------|---------|
| `desktoppr` reports success | Exit code 0, but wallpaper doesn't visually change |
| `com.apple.wallpaper` plist | Contains `SystemWallpaperURL` but it's not authoritative |
| Legacy APIs update metadata only | Finder and desktoppr see the "new" wallpaper, but display shows old one |
| `WallpaperAgent` controls visuals | Must be running; auto-restarts when killed |
| "Show on all Spaces" = `AllSpacesAndDisplays.Desktop` | When this section has a Desktop entry, wallpaper shows everywhere |

## Files Modified

- **`wallpaper.py`**: Added `_set_wallpaper_macos_swift()` and `_enable_macos_all_spaces()` functions
- **`~/.local/bin/set_wallpaper_swift`**: Compiled Swift binary for setting wallpaper

## Testing

After applying this fix, wallpaper changes should:
1. ✅ Visually update immediately
2. ✅ Work on repeated runs without manual intervention
3. ✅ Apply to all Spaces

## References

- [desktoppr GitHub](https://github.com/scriptingosx/desktoppr)
- [Stack Overflow: setDesktopImageURL only affects current space](https://stackoverflow.com/questions/46052546/)
- Wallpaper plist location: `~/Library/Application Support/com.apple.wallpaper/Store/Index.plist`
- WallpaperAgent: `/System/Library/CoreServices/WallpaperAgent.app`
