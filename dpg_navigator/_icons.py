"""Icon registry for the dpg_navigator package.

Manages loading and lookup of PNG icon textures used in the file dialog UI.
Maps file extensions to icon names via EXTENSION_MAP and provides O(1)
lookup through _EXT_LOOKUP.
"""

from __future__ import annotations
# MIT licensed

import logging
import os

import dearpygui.dearpygui as dpg  # type: ignore[import-untyped]

_log = logging.getLogger(__name__)

# All icon names matching files in images/ directory
ICON_NAMES = [
    "add_folder", "app", "back", "big_picture",
    "config", "database", "desktop", "document",
    "documents", "downloads",
    "folder", "gears", "hd", "home", "iso",
    "link", "markdown", "mini_document",
    "mini_folder", "music", "music_note", "object",
    "pdf", "picture", "picture_folder", "presentation",
    "python", "refresh", "script", "search", "spreadsheet",
    "text", "up", "url", "vector", "video", "videos", "web",
    "word", "zip",
]

# Mapping: tuple of file extensions -> icon name
EXTENSION_MAP: dict[tuple[str, ...], str] = {
    # System / binary libraries
    (".dll", ".a", ".o", ".so", ".ko", ".sys", ".drv"): "gears",
    # Images
    (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".webp",
     ".ico", ".tga", ".raw", ".cr2", ".nef", ".heic"): "picture",
    # Executables
    (".msi", ".exe", ".bat", ".bin", ".elf", ".com", ".out", ".apk"): "app",
    # Disc images
    (".iso",): "iso",
    # Archives
    (".zip", ".rar", ".deb", ".rpm", ".tar.gz", ".tar", ".gz", ".bz2",
     ".xz", ".lzo", ".lz4", ".7z", ".ppack", ".tgz", ".cab",
     ".zst", ".lz", ".arj"): "zip",
    # Python
    (".py", ".pyo", ".pyw", ".pyi", ".pyc", ".pyz", ".pyd"): "python",
    # Code / scripts
    (".c", ".js", ".cs", ".cpp", ".h", ".hpp", ".sh", ".pyl", ".rs",
     ".vbs", ".cmd", ".java", ".go", ".swift", ".ts", ".rb", ".pl",
     ".php", ".lua", ".dart", ".r", ".ps1", ".asm",
     ".kt", ".kts", ".scala", ".jl", ".ex", ".exs", ".erl", ".clj",
     ".nim", ".groovy", ".f90", ".f95",
     ".tsx", ".jsx", ".vue", ".svelte", ".wasm"): "script",
    # Web markup
    (".html", ".htm", ".xml", ".css"): "web",
    # Databases
    (".sql", ".db", ".dbf", ".mdb", ".accdb", ".sqlite"): "database",
    # URLs / shortcuts
    (".url",): "url",
    (".lnk",): "link",
    # Plain text
    (".txt", ".rtf", ".log", ".csv", ".patch", ".diff"): "text",
    # Config / data
    (".json", ".ini", ".yaml", ".yml", ".config", ".toml",
     ".env", ".lock"): "config",
    # Markup / documentation
    (".md", ".rst", ".tex", ".adoc"): "markdown",
    # Audio
    (".mp3", ".ogg", ".wav", ".flac", ".aac", ".m4a", ".wma",
     ".aiff", ".mid", ".midi", ".opus", ".ape", ".wv"): "music_note",
    # Video
    (".mp4", ".mov", ".mkv", ".avi", ".wmv", ".flv", ".webm",
     ".mpeg", ".mpg", ".3gp", ".m4v", ".vob", ".m2ts", ".mts"): "video",
    # 3D models / CAD
    (".obj", ".fbx", ".blend", ".stl", ".3ds", ".dae", ".ply",
     ".glb", ".gltf", ".step", ".iges", ".dwg", ".dxf"): "object",
    # Vector graphics
    (".svg", ".ai", ".eps", ".psd"): "vector",
    # PDF / eBooks
    (".pdf", ".epub", ".mobi", ".azw", ".azw3"): "pdf",
    # Rich documents (Word, ODT)
    (".doc", ".docx", ".odt"): "word",
    # Spreadsheets
    (".xls", ".xlsx", ".xlsm", ".xlt", ".xltx", ".ods",
     ".numbers"): "spreadsheet",
    # Presentations
    (".ppt", ".pptx", ".pot", ".potx", ".odp", ".key"): "presentation",
}

# Flat reverse index: ".ext" -> icon_name, for O(1) lookup
_EXT_LOOKUP: dict[str, str] = {}
for _exts, _icon in EXTENSION_MAP.items():
    for _ext in _exts:
        _EXT_LOOKUP[_ext] = _icon


class IconRegistry:
    """Manages DPG texture loading and lookup for file dialog icons.

    Loads PNG icons from an images directory into DPG static textures
    and provides O(1) file-extension-to-icon mapping via the pre-built
    ``_EXT_LOOKUP`` dictionary (supports double extensions like .tar.gz).
    """

    def __init__(self, tag_prefix: str, images_dir: str):
        self._tags: dict[str, str] = {}
        self._tag_prefix = tag_prefix
        self._images_dir = images_dir
        if not os.path.isdir(images_dir):
            _log.warning("Icon images directory does not exist: %s", images_dir)

    def load_all(self) -> None:
        """Load all icons from images/ directory into DPG texture registry."""
        with dpg.texture_registry():
            for name in ICON_NAMES:
                path = os.path.join(self._images_dir, f"{name}.png")
                try:
                    w, h, _, data = dpg.load_image(path)
                    tag = f"{self._tag_prefix}_ico_{name}"
                    dpg.add_static_texture(
                        width=w, height=h, default_value=data, tag=tag
                    )
                    self._tags[name] = tag
                except Exception:
                    _log.warning("Failed to load icon '%s' from %s", name, path)

    def get(self, name: str) -> str | None:
        """Return DPG texture tag for an icon name, or None if not loaded."""
        return self._tags.get(name)

    def get_for_file(self, filename: str) -> str:
        """Return the appropriate icon tag for a given filename.

        Uses a pre-built extension lookup dictionary for O(1) matching.
        Falls back to checking double extensions (e.g., .tar.gz).
        """
        lower = filename.lower()
        ext = os.path.splitext(lower)[1]
        icon_name = _EXT_LOOKUP.get(ext)
        if icon_name is None and ext:
            # Check double extensions like .tar.gz
            stem_part = lower[: -len(ext)]
            stem_ext = os.path.splitext(stem_part)[1]
            if stem_ext:
                icon_name = _EXT_LOOKUP.get(stem_ext + ext)
        if icon_name:
            tag = self._tags.get(icon_name)
            if tag:
                return tag
        return self._tags.get("mini_document", "")

    def get_for_dir(self) -> str:
        """Return the icon tag for directories."""
        return self._tags.get("mini_folder", "")

    def destroy(self) -> None:
        """Remove all loaded textures from DPG."""
        for tag in self._tags.values():
            if dpg.does_item_exist(tag):
                dpg.delete_item(tag)
        self._tags.clear()
