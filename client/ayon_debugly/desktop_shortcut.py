# -*- coding: utf-8 -*-
"""Create desktop shortcut for AYON Staging (Windows .lnk, macOS .app).

Windows: subprocess + PowerShell, no pywin32.

macOS: resolve Desktop via ``NSDesktopDirectory`` (``pyobjc-framework-Cocoa`` /
Foundation) when available; otherwise ``osascript`` (localized folder, no extra
deps); last resort ``~/Desktop`` with a warning (wrong under localized names).
"""
import os
import platform
import shutil
import stat
import subprocess

from ayon_debugly.logger import log

STAGING_ARGS = "--use-staging --debug --verbose DEBUG"
SHORTCUT_NAME_WIN = "AYON Staging.lnk"
SHORTCUT_NAME_MAC = "AYON Staging.app"


def _get_desktop_path_via_osascript():
    """Resolve Desktop using AppleScript (works when folder name is localized)."""
    r = subprocess.run(
        ["osascript", "-e", "POSIX path of (path to desktop folder)"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if r.returncode != 0:
        err = (r.stderr or "").strip()
        raise RuntimeError(err or "osascript failed")
    path = (r.stdout or "").strip().rstrip("\n")
    if not path:
        raise RuntimeError("osascript returned empty path")
    return path


def _get_desktop_path_darwin_foundation():
    """Resolve Desktop via NSFileManager (correct for all UI languages)."""
    from pathlib import Path

    from Foundation import NSFileManager, NSDesktopDirectory, NSUserDomainMask

    fm = NSFileManager.defaultManager()
    result = fm.URLForDirectory_inDomain_appropriateForURL_create_error_(
        NSDesktopDirectory,
        NSUserDomainMask,
        None,
        False,
        None,
    )
    if isinstance(result, tuple):
        url = result[0]
        error = result[1] if len(result) > 1 else None
    else:
        url = result
        error = None

    if error is not None:
        raise RuntimeError(f"Could not resolve Desktop folder: {error}")
    if url is None:
        raise RuntimeError("Could not resolve Desktop folder: URL is None")

    path_str = str(url.path())
    return str(Path(path_str))


def _get_desktop_path_darwin():
    """Desktop path on macOS: Foundation, then osascript, then ~/Desktop."""
    try:
        return _get_desktop_path_darwin_foundation()
    except ImportError:
        log.debug(
            "Foundation (PyObjC) not available; install pyobjc-framework-Cocoa "
            "for native Desktop resolution, or rely on osascript fallback"
        )
    except Exception as e:
        log.warning("NSFileManager Desktop resolution failed: %s", e)

    try:
        return _get_desktop_path_via_osascript()
    except Exception as e:
        log.warning("osascript Desktop resolution failed: %s", e)

    fallback = os.path.expanduser("~/Desktop")
    log.warning(
        "Using ~/Desktop for staging shortcut; wrong if Desktop is localized: %s",
        fallback,
    )
    return fallback


def _get_desktop_path():
    """Return the user's Desktop directory."""
    if platform.system() == "Windows":
        return os.path.join(os.environ.get("USERPROFILE", ""), "Desktop")
    if platform.system() == "Darwin":
        return _get_desktop_path_darwin()
    return os.path.expanduser("~/Desktop")


def _get_ayon_executable():
    """Return AYON executable path from environment."""
    exe = os.environ.get("AYON_EXECUTABLE")
    if not exe or not os.path.exists(exe):
        return None
    return os.path.abspath(exe)


def _get_macos_app_path():
    """From AYON_EXECUTABLE (may be inside .app), return the .app bundle path."""
    exe = _get_ayon_executable()
    if not exe:
        return None
    if exe.endswith(".app"):
        return exe
    path = exe
    while path and path != "/":
        parent = os.path.dirname(path)
        if os.path.basename(parent).endswith(".app"):
            return parent
        path = parent
    return exe


def create_staging_shortcut_windows(addon_root):
    """Create a Windows .lnk shortcut on the Desktop.
    Target: AYON_EXECUTABLE with --use-staging --debug --verbose DEBUG.
    Icon: addon_root/resources/AYON_icon_staging.ico
    """
    exe = _get_ayon_executable()
    if not exe:
        return False, "AYON_EXECUTABLE is not set or path does not exist."

    ico_path = os.path.join(addon_root, "resources", "AYON_icon_staging.ico")
    if not os.path.isfile(ico_path):
        return False, f"Icon not found: {ico_path}"

    desktop = _get_desktop_path()
    if not os.path.isdir(desktop):
        return False, f"Desktop path not found: {desktop}"

    lnk_path = os.path.join(desktop, SHORTCUT_NAME_WIN)
    work_dir = os.path.dirname(exe) or ""

    def _ps_escape(s):
        return (s or "").replace("'", "''")

    ps_script = """
$LnkPath = '%s'
$TargetPath = '%s'
$Arguments = '%s'
$IconLocation = '%s'
$WorkingDirectory = '%s'
$ws = New-Object -ComObject WScript.Shell
$s = $ws.CreateShortcut($LnkPath)
$s.TargetPath = $TargetPath
$s.Arguments = $Arguments
$s.IconLocation = $IconLocation
$s.WorkingDirectory = $WorkingDirectory
$s.Description = 'AYON Launcher (Staging, debug, verbose DEBUG)'
$s.Save()
""" % (
        _ps_escape(lnk_path),
        _ps_escape(exe),
        _ps_escape(STAGING_ARGS),
        _ps_escape(ico_path),
        _ps_escape(work_dir),
    )

    try:
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            check=True,
            capture_output=True,
            timeout=10,
        )
        log.debug("Created Windows shortcut: %s", lnk_path)
        return True, lnk_path
    except subprocess.CalledProcessError as e:
        err = (e.stderr or b"").decode("utf-8", errors="replace").strip()
        log.error("Failed to create Windows shortcut: %s", err or e)
        return False, err or str(e)
    except Exception as e:
        log.error("Failed to create Windows shortcut: %s", e)
        return False, str(e)


def create_staging_shortcut_macos(addon_root):
    """Create a minimal macOS .app on the Desktop that launches AYON with staging args.
    Icon: addon_root/resources/AYON_icon_staging.icns
    """
    app_path_env = _get_macos_app_path()
    if not app_path_env:
        return False, "AYON_EXECUTABLE is not set or path does not exist."

    icns_path = os.path.join(addon_root, "resources", "AYON_icon_staging.icns")
    if not os.path.isfile(icns_path):
        return False, f"Icon not found: {icns_path}"

    desktop = _get_desktop_path()
    if not os.path.isdir(desktop):
        return False, f"Desktop path not found: {desktop}"

    app_path = os.path.join(desktop, SHORTCUT_NAME_MAC)
    if os.path.exists(app_path):
        try:
            shutil.rmtree(app_path)
        except Exception as e:
            return False, f"Could not replace existing shortcut: {e}"

    contents = os.path.join(app_path, "Contents")
    macos_dir = os.path.join(contents, "MacOS")
    resources_dir = os.path.join(contents, "Resources")

    for d in (macos_dir, resources_dir):
        os.makedirs(d, exist_ok=True)

    launcher_script = os.path.join(macos_dir, "launcher")
    launcher_content = (
        "#!/bin/bash\n"
        f'open -na "{app_path_env}" --args --use-staging --debug --verbose DEBUG\n'
    )
    with open(launcher_script, "w", newline="\n") as f:
        f.write(launcher_content)
    os.chmod(launcher_script, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)

    info_plist = os.path.join(contents, "Info.plist")
    plist_content = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>launcher</string>
    <key>CFBundleIconFile</key>
    <string>AYON_icon_staging.icns</string>
    <key>CFBundleIdentifier</key>
    <string>io.ayon.staging</string>
    <key>CFBundleName</key>
    <string>AYON Staging</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
</dict>
</plist>
"""
    with open(info_plist, "w", newline="\n") as f:
        f.write(plist_content)

    dest_icns = os.path.join(resources_dir, "AYON_icon_staging.icns")
    shutil.copy2(icns_path, dest_icns)

    log.debug("Created macOS app shortcut: %s", app_path)
    return True, app_path


def create_staging_desktop_shortcut(addon_root):
    """Create a desktop shortcut for AYON Staging on Windows or macOS.
    Returns (success: bool, message: str). Message is path on success or error text on failure.
    """
    addon_root = os.path.abspath(addon_root)
    system = platform.system()
    if system == "Windows":
        return create_staging_shortcut_windows(addon_root)
    if system == "Darwin":
        return create_staging_shortcut_macos(addon_root)
    return False, f"Desktop shortcut not supported on {system}"
