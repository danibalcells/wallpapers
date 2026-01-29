"""
Cross-platform desktop wallpaper setting.
"""

import logging
import os
import platform
import subprocess

logger = logging.getLogger(__name__)


def set_wallpaper(image_path: str) -> bool:
    """
    Set desktop wallpaper.
    
    Args:
        image_path: Path to the image file
    
    Returns:
        True on success, False on failure
    """
    image_path = os.path.abspath(image_path)
    
    if not os.path.exists(image_path):
        logger.error(f"Image file not found: {image_path}")
        return False
    
    system = platform.system()
    
    if system == "Darwin":
        return _set_wallpaper_macos(image_path)
    elif system == "Linux":
        return _set_wallpaper_linux(image_path)
    elif system == "Windows":
        return _set_wallpaper_windows(image_path)
    else:
        logger.error(f"Unsupported OS: {system}")
        return False


def _set_wallpaper_macos(image_path: str) -> bool:
    """Set wallpaper on macOS using multiple methods for compatibility."""
    
    if _set_wallpaper_macos_swift(image_path):
        return True
    
    if _set_wallpaper_macos_appkit(image_path):
        return True
    
    if _set_wallpaper_macos_applescript(image_path):
        return True
    
    if _set_wallpaper_macos_desktoppr(image_path):
        return True
    
    logger.error("All macOS wallpaper methods failed")
    return False


def _set_wallpaper_macos_swift(image_path: str) -> bool:
    """Set wallpaper using compiled Swift binary (works on macOS Sequoia+)."""
    swift_binary = os.path.expanduser("~/.local/bin/set_wallpaper_swift")
    
    if not os.path.exists(swift_binary):
        logger.debug("Swift wallpaper binary not found, will try to compile")
        if not _compile_swift_wallpaper_binary(swift_binary):
            return False
    
    try:
        subprocess.run(
            [swift_binary, image_path],
            check=True,
            capture_output=True,
            text=True
        )
        logger.info("Wallpaper set successfully via Swift binary")
        
        _enable_macos_all_spaces(image_path)
        
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        logger.debug(f"Swift binary method failed: {e}")
        return False


def _enable_macos_all_spaces(image_path: str) -> bool:
    """
    Update macOS wallpaper plist to enable 'show on all spaces'.
    
    On macOS Sequoia+, setting wallpaper via NSWorkspace only affects the current
    space and unchecks 'show on all spaces'. This function updates the Index.plist
    to propagate the wallpaper to AllSpacesAndDisplays, effectively re-enabling
    the 'show on all spaces' behavior.
    """
    import plistlib
    from pathlib import Path
    
    plist_path = Path.home() / "Library/Application Support/com.apple.wallpaper/Store/Index.plist"
    
    if not plist_path.exists():
        logger.debug(f"Wallpaper plist not found: {plist_path}")
        return False
    
    try:
        with open(plist_path, 'rb') as f:
            data = plistlib.load(f)
        
        desktop_entry = None
        displays = data.get('Displays', {})
        for display_data in displays.values():
            if 'Desktop' in display_data:
                desktop_entry = display_data['Desktop']
                break
        
        if not desktop_entry:
            desktop_entry = data.get('SystemDefault', {}).get('Desktop')
        
        if not desktop_entry:
            logger.debug("Could not find Desktop entry in wallpaper plist")
            return False
        
        if 'AllSpacesAndDisplays' not in data:
            data['AllSpacesAndDisplays'] = {}
        
        data['AllSpacesAndDisplays']['Desktop'] = desktop_entry
        data['AllSpacesAndDisplays']['Type'] = 'all'
        
        file_url = f"file://{image_path}"
        if 'Content' in desktop_entry and 'Choices' in desktop_entry['Content']:
            for choice in desktop_entry['Content']['Choices']:
                if 'Files' in choice:
                    choice['Files'] = [{'relative': file_url}]
        
        with open(plist_path, 'wb') as f:
            plistlib.dump(data, f)
        
        logger.debug("Updated wallpaper plist for all-spaces support")
        return True
        
    except Exception as e:
        logger.debug(f"Failed to update wallpaper plist: {e}")
        return False


def _compile_swift_wallpaper_binary(output_path: str) -> bool:
    """Compile the Swift wallpaper setter on-demand."""
    swift_code = '''
import Cocoa

let args = CommandLine.arguments
guard args.count > 1 else {
    fputs("Usage: set_wallpaper <image_path>\\n", stderr)
    exit(1)
}

let imagePath = args[1]
let imageURL = URL(fileURLWithPath: imagePath)

let workspace = NSWorkspace.shared
var success = true
for screen in NSScreen.screens {
    do {
        try workspace.setDesktopImageURL(imageURL, for: screen, options: [:])
    } catch {
        fputs("Error: \\(error)\\n", stderr)
        success = false
    }
}
exit(success ? 0 : 1)
'''
    
    try:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        with open("/tmp/set_wallpaper.swift", "w") as f:
            f.write(swift_code)
        
        result = subprocess.run(
            ["swiftc", "/tmp/set_wallpaper.swift", "-o", output_path],
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            logger.debug(f"Swift compilation failed: {result.stderr}")
            return False
        
        os.chmod(output_path, 0o755)
        logger.info(f"Compiled Swift wallpaper binary to {output_path}")
        return True
        
    except Exception as e:
        logger.debug(f"Failed to compile Swift binary: {e}")
        return False


def _set_wallpaper_macos_desktoppr(image_path: str) -> bool:
    """Set wallpaper using desktoppr (if installed). Note: may not work on macOS 15+."""
    try:
        subprocess.run(
            ["desktoppr", image_path],
            check=True,
            capture_output=True,
            text=True
        )
        logger.info("Wallpaper set successfully via desktoppr")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def _set_wallpaper_macos_appkit(image_path: str) -> bool:
    """Set wallpaper using Python AppKit (PyObjC)."""
    try:
        from AppKit import NSWorkspace, NSScreen
        from Foundation import NSURL
        
        file_url = NSURL.fileURLWithPath_(image_path)
        workspace = NSWorkspace.sharedWorkspace()
        
        for screen in NSScreen.screens():
            workspace.setDesktopImageURL_forScreen_options_error_(
                file_url, screen, {}, None
            )
        
        logger.info("Wallpaper set successfully via AppKit")
        return True
    except ImportError:
        logger.debug("PyObjC not available")
        return False
    except Exception as e:
        logger.debug(f"AppKit method failed: {e}")
        return False


def _set_wallpaper_macos_applescript(image_path: str) -> bool:
    """Set wallpaper via AppleScript (legacy method)."""
    script = f'''
    tell application "System Events"
        tell every desktop
            set picture to "{image_path}"
        end tell
    end tell
    '''
    try:
        subprocess.run(
            ["osascript", "-e", script],
            check=True,
            capture_output=True,
            text=True
        )
        logger.info("Wallpaper set successfully via AppleScript")
        return True
    except subprocess.CalledProcessError as e:
        logger.debug(f"AppleScript method failed: {e.stderr}")
        return False


def _set_wallpaper_linux(image_path: str) -> bool:
    """
    Set wallpaper on Linux - tries multiple desktop environments.
    """
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    session = os.environ.get("DESKTOP_SESSION", "").lower()
    
    if "gnome" in desktop or "ubuntu" in desktop or "gnome" in session:
        if _set_wallpaper_gnome(image_path):
            return True
    
    if "kde" in desktop or "plasma" in desktop:
        if _set_wallpaper_kde(image_path):
            return True
    
    if "xfce" in desktop:
        if _set_wallpaper_xfce(image_path):
            return True
    
    if "mate" in desktop:
        if _set_wallpaper_mate(image_path):
            return True
    
    if "cinnamon" in desktop:
        if _set_wallpaper_cinnamon(image_path):
            return True
    
    if _set_wallpaper_feh(image_path):
        return True
    
    if _set_wallpaper_gnome(image_path):
        return True
    
    logger.error("Failed to set wallpaper - no supported desktop environment found")
    return False


def _set_wallpaper_gnome(image_path: str) -> bool:
    """Set wallpaper on GNOME."""
    try:
        subprocess.run([
            "gsettings", "set", "org.gnome.desktop.background",
            "picture-uri", f"file://{image_path}"
        ], check=True, capture_output=True)
        
        subprocess.run([
            "gsettings", "set", "org.gnome.desktop.background",
            "picture-uri-dark", f"file://{image_path}"
        ], check=True, capture_output=True)
        
        logger.info("Wallpaper set successfully on GNOME")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def _set_wallpaper_kde(image_path: str) -> bool:
    """Set wallpaper on KDE Plasma."""
    script = f'''
    var allDesktops = desktops();
    for (var i = 0; i < allDesktops.length; i++) {{
        var d = allDesktops[i];
        d.wallpaperPlugin = "org.kde.image";
        d.currentConfigGroup = ["Wallpaper", "org.kde.image", "General"];
        d.writeConfig("Image", "file://{image_path}");
    }}
    '''
    try:
        subprocess.run([
            "qdbus", "org.kde.plasmashell", "/PlasmaShell",
            "org.kde.PlasmaShell.evaluateScript", script
        ], check=True, capture_output=True)
        logger.info("Wallpaper set successfully on KDE Plasma")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def _set_wallpaper_xfce(image_path: str) -> bool:
    """Set wallpaper on XFCE."""
    try:
        result = subprocess.run([
            "xfconf-query", "-c", "xfce4-desktop", "-l"
        ], capture_output=True, text=True, check=True)
        
        for line in result.stdout.splitlines():
            if "last-image" in line or "image-path" in line:
                subprocess.run([
                    "xfconf-query", "-c", "xfce4-desktop",
                    "-p", line.strip(), "-s", image_path
                ], check=True, capture_output=True)
        
        logger.info("Wallpaper set successfully on XFCE")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def _set_wallpaper_mate(image_path: str) -> bool:
    """Set wallpaper on MATE."""
    try:
        subprocess.run([
            "gsettings", "set", "org.mate.background",
            "picture-filename", image_path
        ], check=True, capture_output=True)
        logger.info("Wallpaper set successfully on MATE")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def _set_wallpaper_cinnamon(image_path: str) -> bool:
    """Set wallpaper on Cinnamon."""
    try:
        subprocess.run([
            "gsettings", "set", "org.cinnamon.desktop.background",
            "picture-uri", f"file://{image_path}"
        ], check=True, capture_output=True)
        logger.info("Wallpaper set successfully on Cinnamon")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def _set_wallpaper_feh(image_path: str) -> bool:
    """Set wallpaper using feh (works on many window managers)."""
    try:
        subprocess.run(
            ["feh", "--bg-fill", image_path],
            check=True,
            capture_output=True
        )
        logger.info("Wallpaper set successfully using feh")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def _set_wallpaper_windows(image_path: str) -> bool:
    """Set wallpaper on Windows via ctypes."""
    try:
        import ctypes
        
        SPI_SETDESKWALLPAPER = 0x0014
        SPIF_UPDATEINIFILE = 0x01
        SPIF_SENDCHANGE = 0x02
        
        result = ctypes.windll.user32.SystemParametersInfoW(
            SPI_SETDESKWALLPAPER,
            0,
            image_path,
            SPIF_UPDATEINIFILE | SPIF_SENDCHANGE
        )
        
        if result:
            logger.info("Wallpaper set successfully on Windows")
            return True
        else:
            logger.error("SystemParametersInfoW returned False")
            return False
            
    except Exception as e:
        logger.error(f"Failed to set wallpaper on Windows: {e}")
        return False
