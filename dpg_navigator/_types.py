"""Type definitions and constants for the dpg_navigator package.

Defines DialogConfig, DialogMode, StyleVariant, FileEntry, and the default
file extension filter list used by FileDialog.
"""

from __future__ import annotations

# MIT licensed
import os
from dataclasses import dataclass
from enum import Enum, auto
from typing import Protocol


class DialogMode(Enum):
    """Mode of file dialog operation."""

    OPEN_FILES = auto()
    OPEN_DIRS = auto()


class StyleVariant(Enum):
    """Visual style for the sidebar."""

    LABELED = auto()  # Icon + text label, sidebar ~200px
    COMPACT = auto()  # Icon-only buttons, sidebar ~40px


class SelectionCallback(Protocol):
    """Host callback invoked with the list of selected filesystem paths."""

    def __call__(self, paths: list[str]) -> None: ...


def _require_positive_int(name: str, value: object) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{name} must be a positive int")


def _require_extension(name: str, value: str) -> None:
    if not value.startswith(".") or len(value) < 2:
        raise ValueError(f"{name} must be an extension like '.py' or '.*'")


@dataclass(frozen=True)
class FileEntry:
    """Represents a file or directory for display."""

    name: str
    full_path: str
    is_dir: bool
    size_bytes: int | None
    modified_time: float
    is_hidden: bool

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("name must be a non-empty string")
        if self.size_bytes is not None and self.size_bytes < 0:
            raise ValueError("size_bytes cannot be negative")

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
            source code as text).
        trusted_html_preview: Allow raw .html/.htm previews to execute scripts
            and load referenced resources. Disabled by default; Markdown and
            Word previews always use the safe HTML policy.
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
    trusted_html_preview: bool = False
    preview_width: int = 300
    search_subfolders: bool = True
    style: StyleVariant = StyleVariant.LABELED
    custom_dirs: list[tuple[str, str]] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.title, str) or not self.title.strip():
            raise ValueError("title must be a non-empty string")
        if not isinstance(self.tag, str) or not self.tag.strip():
            raise ValueError("tag must be a non-empty string")
        _require_positive_int("width", self.width)
        _require_positive_int("height", self.height)
        _require_positive_int("preview_width", self.preview_width)
        if not isinstance(self.min_size, tuple) or len(self.min_size) != 2:
            raise ValueError("min_size must be a pair of positive ints")
        _require_positive_int("min_size[0]", self.min_size[0])
        _require_positive_int("min_size[1]", self.min_size[1])
        if self.width < self.min_size[0] or self.height < self.min_size[1]:
            raise ValueError("width and height must be greater than or equal to min_size")
        if not isinstance(self.mode, DialogMode):
            raise TypeError("mode must be a DialogMode")
        if not isinstance(self.style, StyleVariant):
            raise TypeError("style must be a StyleVariant")
        if self.default_path is not None and (not isinstance(self.default_path, str) or "\0" in self.default_path):
            raise ValueError("default_path must be a string without NUL")
        if self.filter_list is not None:
            if not isinstance(self.filter_list, list) or not all(isinstance(item, str) for item in self.filter_list):
                raise TypeError("filter_list must be a list of strings or None")
            for ext in self.filter_list:
                _require_extension("filter_list item", ext)
                if ext != ".*" and any(char in ext[1:] for char in "*?["):
                    raise ValueError("filter_list item cannot contain glob metacharacters")
            self.filter_list = [item.lower() for item in self.filter_list]
        if not isinstance(self.file_filter, str):
            raise TypeError("file_filter must be a string")
        _require_extension("file_filter", self.file_filter)
        if self.file_filter != ".*" and any(char in self.file_filter[1:] for char in "*?["):
            raise ValueError("file_filter cannot contain glob metacharacters")
        self.file_filter = self.file_filter.lower()
        if self.filter_list and self.file_filter not in self.filter_list:
            raise ValueError(f"file_filter {self.file_filter!r} is not in filter_list")
        if self.custom_dirs is not None:
            if not isinstance(self.custom_dirs, list):
                raise TypeError("custom_dirs must be a list of (label, path) tuples")
            for item in self.custom_dirs:
                if (
                    not isinstance(item, tuple)
                    or len(item) != 2
                    or not isinstance(item[0], str)
                    or not isinstance(item[1], str)
                    or not item[0].strip()
                    or not item[1].strip()
                    or "\0" in item[1]
                ):
                    raise ValueError("custom_dirs entries must be (non-empty label, non-empty path)")


# Deduplicated default filter list
DEFAULT_FILTER_LIST = (
    ".*",
    ".3ds",
    ".3gp",
    ".7z",
    ".aac",
    ".accdb",
    ".adoc",
    ".ai",
    ".aiff",
    ".ape",
    ".apk",
    ".arj",
    ".asm",
    ".avi",
    ".azw",
    ".azw3",
    ".bak",
    ".bat",
    ".bin",
    ".blend",
    ".bmp",
    ".bz2",
    ".c",
    ".cab",
    ".clj",
    ".cmd",
    ".com",
    ".config",
    ".cpp",
    ".cr2",
    ".cs",
    ".css",
    ".csv",
    ".dae",
    ".dart",
    ".db",
    ".dbf",
    ".deb",
    ".diff",
    ".doc",
    ".dockerfile",
    ".docx",
    ".drv",
    ".dwg",
    ".dxf",
    ".elf",
    ".env",
    ".eps",
    ".epub",
    ".erl",
    ".ex",
    ".exe",
    ".exs",
    ".f90",
    ".f95",
    ".fbx",
    ".flac",
    ".flv",
    ".gif",
    ".glb",
    ".gltf",
    ".go",
    ".groovy",
    ".gz",
    ".h",
    ".heic",
    ".hpp",
    ".htm",
    ".html",
    ".ico",
    ".ics",
    ".iges",
    ".ini",
    ".iso",
    ".jar",
    ".java",
    ".jl",
    ".jpeg",
    ".jpg",
    ".js",
    ".json",
    ".jsx",
    ".key",
    ".ko",
    ".kt",
    ".kts",
    ".lnk",
    ".lock",
    ".log",
    ".lua",
    ".lz",
    ".lz4",
    ".lzo",
    ".m2ts",
    ".m4a",
    ".m4v",
    ".md",
    ".mdb",
    ".mid",
    ".midi",
    ".mkv",
    ".mlt",
    ".mobi",
    ".mov",
    ".mp3",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".msi",
    ".mts",
    ".nef",
    ".nim",
    ".numbers",
    ".o",
    ".obj",
    ".odp",
    ".ods",
    ".odt",
    ".ogg",
    ".opus",
    ".out",
    ".ova",
    ".ovf",
    ".patch",
    ".pdf",
    ".php",
    ".pl",
    ".ply",
    ".png",
    ".pot",
    ".potx",
    ".ppack",
    ".pps",
    ".ppt",
    ".pptx",
    ".ps1",
    ".psd",
    ".py",
    ".pyl",
    ".qcow2",
    ".r",
    ".rar",
    ".raw",
    ".rb",
    ".rpm",
    ".rs",
    ".rst",
    ".rtf",
    ".sav",
    ".scala",
    ".sh",
    ".so",
    ".sql",
    ".sqlite",
    ".step",
    ".stl",
    ".svelte",
    ".svg",
    ".swift",
    ".sys",
    ".tar",
    ".tex",
    ".tga",
    ".tgz",
    ".tiff",
    ".tmp",
    ".toml",
    ".torrent",
    ".ts",
    ".tsx",
    ".txt",
    ".url",
    ".vbs",
    ".vdi",
    ".vhd",
    ".vhdx",
    ".vmdk",
    ".vob",
    ".vue",
    ".wasm",
    ".wav",
    ".webm",
    ".webp",
    ".wma",
    ".wmv",
    ".wv",
    ".xls",
    ".xlsm",
    ".xlsx",
    ".xlt",
    ".xltx",
    ".xml",
    ".xz",
    ".yaml",
    ".yml",
    ".zip",
    ".zst",
)
