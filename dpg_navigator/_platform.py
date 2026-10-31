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

# Imported unconditionally (cheap) so the Linux XDG path can be exercised
# with mocks on any host OS.
import stat
import subprocess

_INVALID_FILE_ATTRIBUTES = -1
_FILE_ATTRIBUTE_HIDDEN = 0x2
_UF_HIDDEN: int = getattr(stat, "UF_HIDDEN", 0x00008000)
"""macOS ``chflags hidden`` bit in ``st_flags``."""
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


def _user_dirs_file(home: str) -> str:
    """Return the path of ``user-dirs.dirs`` (``$XDG_CONFIG_HOME`` aware)."""
    config_home = os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
    return os.path.join(config_home, "user-dirs.dirs")


def _read_user_dirs(home: str) -> dict[str, str]:
    """Parse ``user-dirs.dirs`` into ``{"DOWNLOAD": "/home/u/Pobrane", ...}``.

    The file is a shell fragment written by ``xdg-user-dirs-update``. Per its
    format, each value is double-quoted and is either ``$HOME/...`` or an
    absolute path; backslash escapes ``"``, ``$``, and ``\\``. Anything else is
    ignored rather than evaluated.
    """
    result: dict[str, str] = {}
    try:
        with open(_user_dirs_file(home), encoding="utf-8") as handle:
            lines = handle.readlines()
    except (OSError, UnicodeDecodeError):
        return result
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not (key.startswith("XDG_") and key.endswith("_DIR")):
            continue
        value = value.strip()
        if len(value) < 2 or value[0] != '"' or value[-1] != '"':
            continue
        value = value[1:-1]
        unescaped: list[str] = []
        i = 0
        while i < len(value):
            ch = value[i]
            if ch == "\\" and i + 1 < len(value):
                i += 1
                ch = value[i]
            unescaped.append(ch)
            i += 1
        path = "".join(unescaped)
        if path == "$HOME" or path.startswith("$HOME/"):
            path = home + path[len("$HOME") :]
        elif not path.startswith("/"):
            continue
        result[key[len("XDG_") : -len("_DIR")]] = path
    return result


def _is_home(path: str, home: str) -> bool:
    """True when *path* is the home directory itself.

    ``xdg-user-dirs`` resolves a disabled or unset entry to ``$HOME``; a
    sidebar "Downloads" shortcut that opens the home folder is wrong, so such
    results are discarded.
    """
    try:
        return os.path.normpath(path).rstrip("/") == os.path.normpath(home).rstrip("/")
    except (TypeError, ValueError):
        return False


def _get_xdg_dir(name: str) -> str | None:
    """Get XDG user directory path on Linux (handles non-English locales).

    Reads ``user-dirs.dirs`` first (no subprocess), then falls back to the
    ``xdg-user-dir`` command. A result equal to ``$HOME`` means "not
    configured" and is rejected, as is a path that does not exist.
    """
    if name in _xdg_cache:
        return _xdg_cache[name]
    xdg_key = _XDG_NAME_MAP.get(name, name.upper())
    home = os.path.expanduser("~")
    resolved: str | None = None

    candidate = _read_user_dirs(home).get(xdg_key)
    if candidate and not _is_home(candidate, home) and os.path.isdir(candidate):
        resolved = candidate

    if resolved is None:
        try:
            result = subprocess.run(["xdg-user-dir", xdg_key], capture_output=True, text=True, timeout=2)
            if result.returncode == 0:
                path = result.stdout.strip()
                if path and not _is_home(path, home) and os.path.isdir(path):
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
    elif _SYSTEM == "Darwin":
        # Finder hides entries flagged with ``chflags hidden`` (UF_HIDDEN),
        # e.g. ~/Library. lstat so a visible symlink is judged by itself.
        try:
            flags = getattr(os.lstat(filepath), "st_flags", 0)
        except (OSError, ValueError):
            return False
        return bool(flags & _UF_HIDDEN)
    return False


def get_file_time(filepath: str) -> float:
    """Return file modification time (consistent cross-platform).

    Uses st_mtime instead of getctime because ctime means different things
    on Windows (creation time) vs Linux/macOS (inode change time).
    """
    return os.stat(filepath).st_mtime
