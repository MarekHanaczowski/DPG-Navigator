"""Cross-platform abstractions for the dpg_navigator package.

Provides functions for drive enumeration, special directory discovery,
hidden file detection, modifier key state, and file timestamp retrieval.
Works on Windows, Linux, and macOS.
"""

from __future__ import annotations

# MIT licensed
import os
import platform
from typing import Any

import dearpygui.dearpygui as dpg  # type: ignore[import-untyped]
import psutil  # type: ignore[import-untyped]

ctypes: Any = None
winreg: Any = None
if os.name == "nt":
    import ctypes as _ctypes
    import winreg as _winreg

    ctypes = _ctypes
    winreg = _winreg

_SYSTEM = platform.system()  # "Windows" / "Linux" / "Darwin"

# Map user-facing names to the keys expected by xdg-user-dir(1).
_XDG_NAME_MAP = {
    "Downloads": "DOWNLOAD",
    "Desktop": "DESKTOP",
    "Pictures": "PICTURES",
    "Documents": "DOCUMENTS",
    "Music": "MUSIC",
    "Videos": "VIDEOS",
}

if _SYSTEM == "Linux":
    import subprocess

_INVALID_FILE_ATTRIBUTES = -1
_FILE_ATTRIBUTE_HIDDEN = 0x2
_xdg_cache: dict[str, str | None] = {}
_special_dirs_cache: tuple[str, str, dict[str, str]] | None = None


def get_drives() -> list[str]:
    """Return list of mounted drives/volumes (cross-platform)."""
    try:
        partitions = psutil.disk_partitions()
        drives = []
        for part in partitions:
            mount = part.mountpoint
            if not mount:
                continue
            try:
                if not os.path.isdir(mount):
                    continue
            except OSError:
                continue
            drives.append(mount)
    except (OSError, PermissionError, RuntimeError):
        drives = []

    if _SYSTEM == "Darwin":
        try:
            for vol in os.listdir("/Volumes"):
                vol_path = os.path.join("/Volumes", vol)
                if vol_path not in drives:
                    drives.append(vol_path)
        except OSError:
            pass
    # Linux: psutil.disk_partitions() is sufficient — no /dev/ scanning

    return drives


def get_special_dirs() -> dict[str, str]:
    """Return map {display_name: path} of special user directories.

    Only returns directories that actually exist on disk.
    """
    global _special_dirs_cache
    home = os.path.expanduser("~")
    if _special_dirs_cache is not None and _special_dirs_cache[0] == _SYSTEM and _special_dirs_cache[1] == home:
        return dict(_special_dirs_cache[2])
    dirs: dict[str, str] = {"Home": home}

    names = ("Desktop", "Downloads", "Pictures", "Documents", "Music", "Videos")

    if _SYSTEM == "Linux":
        for name in names:
            dirs[name] = _get_xdg_dir(name) or os.path.join(home, name)
    elif _SYSTEM == "Darwin":
        macos_mapping = {"Videos": "Movies"}
        for name in names:
            real_name = macos_mapping.get(name, name)
            dirs[name] = os.path.join(home, real_name)
    elif _SYSTEM == "Windows":
        _SHELL_FOLDER_MAP = {
            "Desktop": "Desktop",
            "Downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
            "Pictures": "My Pictures",
            "Documents": "Personal",
            "Music": "My Music",
            "Videos": "My Video",
        }
        for name in names:
            reg_name = _SHELL_FOLDER_MAP.get(name)
            if reg_name:
                try:
                    with winreg.OpenKey(
                        winreg.HKEY_CURRENT_USER,
                        r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
                    ) as key:
                        raw_path, _ = winreg.QueryValueEx(key, reg_name)
                        dirs[name] = os.path.expandvars(raw_path)
                except (OSError, FileNotFoundError):
                    dirs[name] = os.path.join(home, name)
            else:
                dirs[name] = os.path.join(home, name)
    else:
        # Unknown platform: fall back to conventional home subdirectories.
        for name in names:
            dirs[name] = os.path.join(home, name)

    # Filter to only existing directories
    filtered = {k: v for k, v in dirs.items() if v and os.path.isdir(v)}
    _special_dirs_cache = (_SYSTEM, home, filtered)
    return dict(filtered)


def _get_xdg_dir(name: str) -> str | None:
    """Get XDG user directory path on Linux (handles non-English locales)."""
    if name in _xdg_cache:
        return _xdg_cache[name]
    xdg_key = _XDG_NAME_MAP.get(name, name.upper())
    resolved: str | None = None
    try:
        result = subprocess.run(["xdg-user-dir", xdg_key], capture_output=True, text=True, timeout=2)
        if result.returncode == 0:
            path = result.stdout.strip()
            if path and os.path.isdir(path):
                resolved = path
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError, UnicodeDecodeError):
        pass
    _xdg_cache[name] = resolved
    return resolved


def is_mod_key_down() -> bool:
    """Check if modifier key is held: Command on macOS, Ctrl on others."""
    if _SYSTEM == "Darwin":
        return bool(dpg.is_key_down(dpg.mvKey_LSuper) or dpg.is_key_down(dpg.mvKey_RSuper))
    return bool(dpg.is_key_down(dpg.mvKey_LControl) or dpg.is_key_down(dpg.mvKey_RControl))


def is_hidden(filepath: str) -> bool:
    """Check if a file/directory is hidden (cross-platform)."""
    stripped = filepath.rstrip("\\/")
    if os.name == "nt":
        if len(stripped) == 2 and stripped[1] == ":":
            return False
    elif stripped == "":
        return False
    name = os.path.basename(stripped) or stripped
    if name.startswith("."):
        return True
    if os.name == "nt":
        try:
            attrs = ctypes.windll.kernel32.GetFileAttributesW(str(filepath))
            if attrs != _INVALID_FILE_ATTRIBUTES:
                return bool(_FILE_ATTRIBUTE_HIDDEN & attrs)
        except (AttributeError, OSError, ValueError):
            pass
    return False


def get_file_time(filepath: str) -> float:
    """Return file modification time (consistent cross-platform).

    Uses st_mtime instead of getctime because ctime means different things
    on Windows (creation time) vs Linux/macOS (inode change time).
    """
    return os.stat(filepath).st_mtime
