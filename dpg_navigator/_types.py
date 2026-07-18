"""Type definitions and constants for the dpg_navigator package.

Defines DialogConfig, DialogMode, StyleVariant, FileEntry, and the default
file extension filter list used by FileDialog.
"""

from __future__ import annotations
# MIT licensed

import os
from dataclasses import dataclass
from enum import Enum, auto


class DialogMode(Enum):
    """Mode of file dialog operation."""
    OPEN_FILES = auto()
    OPEN_DIRS = auto()


class StyleVariant(Enum):
    """Visual style for the sidebar."""
    LABELED = auto()   # Icon + text label, sidebar ~200px
    COMPACT = auto()   # Icon-only buttons, sidebar ~40px


@dataclass(frozen=True)
class FileEntry:
    """Represents a file or directory for display."""
    name: str
    full_path: str
    is_dir: bool
    size_bytes: int | None
    modified_time: float
    is_hidden: bool

    @property
    def ext(self) -> str:
        """Lowercase file extension including the leading dot (e.g. '.csv').

        The preview renderers dispatch on ``entry.ext``; FileEntry never stored
        it as a field (pre- and post-refactor), so it is derived from ``name``
        here — a computed property is frozen-dataclass safe.
        """
        return os.path.splitext(self.name)[1].lower()


@dataclass
class DialogConfig:
    """Configuration for FileDialog.

    Attributes:
        title: Window title bar text.
        tag: Unique DPG identifier. Must differ across instances.
        width: Initial window width in pixels.
        height: Initial window height in pixels.
        min_size: Minimum (width, height) the user can resize to.
        mode: OPEN_FILES shows files and folders; OPEN_DIRS shows only folders.
        default_path: Starting directory (None = current working directory).
        filter_list: Extensions shown in filter combo (None = built-in ~180 exts,
            [] = empty combo).
        file_filter: Initially selected filter value (must be in filter_list).
        show_dir_size: Calculate folder sizes asynchronously (cached 60 s).
        allow_drag: Enable drag-and-drop payloads on file rows.
        multi_selection: Allow Ctrl+click / Ctrl+A multi-select.
        show_shortcuts: Show sidebar with special dirs and drive tree.
        no_resize: Lock the window to its initial size.
        modal: Block interaction with other windows while open.
        show_hidden: Display hidden files (Windows attribute / dot-prefix).
        show_preview: Show the right-side preview panel (images, text, PDF,
            HTML, Word, PPTX, Markdown, CSV, Excel, SQLite, fonts, archives,
            code with Pygments highlighting).
        preview_width: Initial preview panel width in pixels (user-resizable).
        search_subfolders: Enable "Subfolders" checkbox for recursive search
            via background DirectoryIndex.
        style: Sidebar style — LABELED (icon + text, ~200 px, resizable tree)
            or COMPACT (icon-only, ~40 px, tooltips).
        custom_dirs: Extra sidebar shortcuts below the standard locations.
            List of (label, path) tuples, e.g.
            ``[("Projects", "D:/Projects")]``.
    """
    title: str = "File Dialog"
    tag: str = "dpg_navigator"
    width: int = 950
    height: int = 650
    min_size: tuple[int, int] = (460, 320)
    mode: DialogMode = DialogMode.OPEN_FILES
    default_path: str | None = None
    filter_list: list[str] | None = None
    file_filter: str = ".*"
    show_dir_size: bool = False
    allow_drag: bool = True
    multi_selection: bool = True
    show_shortcuts: bool = True
    no_resize: bool = False
    modal: bool = True
    show_hidden: bool = False
    show_preview: bool = False
    preview_width: int = 300
    search_subfolders: bool = True
    style: StyleVariant = StyleVariant.LABELED
    custom_dirs: list[tuple[str, str]] | None = None


# Deduplicated default filter list
DEFAULT_FILTER_LIST = (
    ".*",
    ".3ds", ".3gp",
    ".7z",
    ".aac", ".accdb", ".adoc", ".ai", ".aiff", ".ape", ".apk",
    ".arj", ".asm", ".avi", ".azw", ".azw3",
    ".bak", ".bat", ".bin", ".blend", ".bmp", ".bz2",
    ".c", ".cab", ".clj", ".cmd", ".com", ".config", ".cpp",
    ".cr2", ".cs", ".css", ".csv",
    ".dae", ".dart", ".db", ".dbf", ".deb", ".diff", ".doc",
    ".dockerfile", ".docx", ".drv", ".dwg", ".dxf",
    ".elf", ".env", ".eps", ".epub", ".erl", ".ex", ".exe", ".exs",
    ".f90", ".f95", ".fbx", ".flac", ".flv",
    ".gif", ".glb", ".gltf", ".go", ".groovy", ".gz",
    ".h", ".heic", ".hpp", ".htm", ".html",
    ".ico", ".ics", ".iges", ".ini", ".iso",
    ".jar", ".java", ".jl", ".jpeg", ".jpg", ".js", ".json",
    ".jsx",
    ".key", ".ko", ".kt", ".kts",
    ".lnk", ".lock", ".log", ".lua", ".lz", ".lz4", ".lzo",
    ".m2ts", ".m4a", ".m4v", ".md", ".mdb", ".mid", ".midi",
    ".mkv", ".mlt", ".mobi", ".mov", ".mp3", ".mp4", ".mpeg",
    ".mpg", ".msi", ".mts",
    ".nef", ".nim", ".numbers",
    ".o", ".obj", ".odp", ".ods", ".odt", ".ogg", ".opus",
    ".out", ".ova", ".ovf",
    ".patch", ".pdf", ".php", ".pl", ".ply", ".png", ".pot",
    ".potx", ".ppack", ".pps", ".ppt", ".pptx", ".ps1",
    ".psd", ".py", ".pyl",
    ".qcow2",
    ".r", ".rar", ".raw", ".rb", ".rpm", ".rs", ".rst", ".rtf",
    ".sav", ".scala", ".sh", ".so", ".sql", ".sqlite",
    ".step", ".stl", ".svelte", ".svg", ".swift", ".sys",
    ".tar", ".tex", ".tga", ".tgz", ".tiff", ".tmp",
    ".toml", ".torrent", ".ts", ".tsx", ".txt",
    ".url",
    ".vbs", ".vdi", ".vhd", ".vhdx", ".vmdk", ".vob",
    ".vue",
    ".wasm", ".wav", ".webm", ".webp", ".wma", ".wmv", ".wv",
    ".xls", ".xlsm", ".xlsx", ".xlt", ".xltx", ".xml", ".xz",
    ".yaml", ".yml",
    ".zip", ".zst",
)
