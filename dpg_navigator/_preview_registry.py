"""Preview format registry and routing helpers.

Keeps extension groups and renderer selection independent from DearPyGui so
the routing contract can be tested without a GUI context.
"""

from __future__ import annotations

# MIT licensed
import os
from dataclasses import dataclass
from enum import Enum, auto

STB_IMAGE_EXTS: frozenset[str] = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".bmp",
        ".tga",
        ".gif",
        ".psd",
        ".hdr",
        ".pic",
        ".pgm",
        ".ppm",
        ".pnm",
    }
)

PILLOW_EXTRA_EXTS: frozenset[str] = frozenset(
    {
        ".webp",
        ".tiff",
        ".tif",
        ".ico",
        ".heic",
        ".heif",
        ".avif",
        ".svg",
        ".dds",
        ".pcx",
        ".eps",
    }
)

PDF_EXTS: frozenset[str] = frozenset({".pdf"})
WORD_EXTS: frozenset[str] = frozenset({".docx"})
PPTX_EXTS: frozenset[str] = frozenset({".pptx"})
MD_EXTS: frozenset[str] = frozenset({".md", ".markdown"})
HTML_EXTS: frozenset[str] = frozenset({".html", ".htm"})
CSV_EXTS: frozenset[str] = frozenset({".csv", ".tsv"})
EXCEL_EXTS: frozenset[str] = frozenset({".xlsx", ".xlsm"})
XML_EXTS: frozenset[str] = frozenset({".xml", ".ui", ".uvprojx", ".vcxproj", ".csproj"})
ZIP_EXTS: frozenset[str] = frozenset({".zip", ".whl", ".egg", ".jar", ".apk"})
SEVEN_Z_EXTS: frozenset[str] = frozenset({".7z"})
FONT_EXTS: frozenset[str] = frozenset({".ttf", ".otf"})
DB_EXTS: frozenset[str] = frozenset({".db", ".sqlite", ".sqlite3", ".dat"})

CODE_EXTS: frozenset[str] = frozenset(
    {
        ".py",
        ".pyw",
        ".pyi",
        ".pyl",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".mjs",
        ".cjs",
        ".json",
        ".jsonl",
        ".json5",
        ".css",
        ".scss",
        ".sass",
        ".less",
        ".yaml",
        ".yml",
        ".toml",
        ".env",
        ".c",
        ".h",
        ".cpp",
        ".hpp",
        ".cc",
        ".cxx",
        ".cs",
        ".java",
        ".kt",
        ".kts",
        ".scala",
        ".groovy",
        ".go",
        ".rs",
        ".swift",
        ".dart",
        ".lua",
        ".rb",
        ".pl",
        ".pm",
        ".r",
        ".jl",
        ".ex",
        ".exs",
        ".sql",
        ".graphql",
        ".gql",
        ".dockerfile",
        ".makefile",
        ".cmake",
        ".diff",
        ".patch",
    }
)

TEXT_PREVIEW_EXTS: frozenset[str] = (
    frozenset(
        {
            ".txt",
            ".log",
            ".csv",
            ".tsv",
            ".ini",
            ".cfg",
            ".conf",
            ".bat",
            ".cmd",
            ".sh",
            ".bash",
            ".zsh",
            ".ps1",
            ".xml",
            ".html",
            ".htm",
            ".xhtml",
            ".md",
            ".rst",
            ".adoc",
            ".tex",
            ".gitignore",
            ".gitattributes",
            ".editorconfig",
            ".lock",
        }
    )
    | CODE_EXTS
)


class PreviewKind(Enum):
    """Renderer selected for a preview entry."""

    NONE = auto()
    HTML = auto()
    MARKDOWN = auto()
    CSV = auto()
    EXCEL = auto()
    SQLITE = auto()
    FONT = auto()
    XML = auto()
    CODE = auto()  # monospace text; extra gates routing, not highlighting
    TEXT = auto()
    PDF = auto()
    ZIP = auto()
    SEVEN_Z = auto()
    IMAGE = auto()
    WORD = auto()
    PPTX = auto()


@dataclass(frozen=True)
class PreviewCapabilities:
    """Optional preview backends available in the current environment."""

    markdown: bool = False
    excel: bool = False
    pygments: bool = False
    pdf: bool = False
    seven_z: bool = False
    word: bool = False
    mammoth: bool = False
    pptx: bool = False


def html_active_extensions(capabilities: PreviewCapabilities) -> frozenset[str]:
    """Return extensions that keep an active HTML renderer open.

    Source-code files are not included: they use the text preview, not Chrome.
    """
    extensions = HTML_EXTS
    if capabilities.mammoth:
        extensions |= WORD_EXTS
    if capabilities.markdown:
        extensions |= MD_EXTS
    return extensions


def resolve_preview_kind(
    filename: str,
    *,
    capabilities: PreviewCapabilities,
    image_extensions: frozenset[str],
) -> PreviewKind:
    """Choose a renderer while preserving the established fallback order."""
    ext = os.path.splitext(filename)[1].lower()

    if ext in HTML_EXTS:
        return PreviewKind.HTML
    if capabilities.markdown and ext in MD_EXTS:
        return PreviewKind.MARKDOWN
    if ext in CSV_EXTS:
        return PreviewKind.CSV
    if capabilities.excel and ext in EXCEL_EXTS:
        return PreviewKind.EXCEL
    if ext in DB_EXTS:
        return PreviewKind.SQLITE
    if ext in FONT_EXTS:
        return PreviewKind.FONT
    if ext in XML_EXTS:
        return PreviewKind.XML
    # Source code: extension-based, or well-known extensionless filenames
    # (e.g. "Dockerfile", "Makefile") resolved via their dotted registry entry.
    if capabilities.pygments and (ext in CODE_EXTS or (not ext and f".{filename.lower()}" in CODE_EXTS)):
        return PreviewKind.CODE
    if ext in TEXT_PREVIEW_EXTS:
        return PreviewKind.TEXT
    if not ext:
        name = filename.lower()
        key = name if name.startswith(".") else f".{name}"
        if key in TEXT_PREVIEW_EXTS:
            return PreviewKind.TEXT
    if capabilities.pdf and ext in PDF_EXTS:
        return PreviewKind.PDF
    if ext in ZIP_EXTS:
        return PreviewKind.ZIP
    if capabilities.seven_z and ext in SEVEN_Z_EXTS:
        return PreviewKind.SEVEN_Z
    if ext in image_extensions:
        return PreviewKind.IMAGE
    if capabilities.word and ext in WORD_EXTS:
        return PreviewKind.WORD
    if capabilities.pptx and ext in PPTX_EXTS:
        return PreviewKind.PPTX
    return PreviewKind.NONE
