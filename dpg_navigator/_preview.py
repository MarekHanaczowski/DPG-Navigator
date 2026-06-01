"""Preview panel component for the file dialog.

Handles file preview rendering for multiple formats:

- Images (stb_image native + Pillow fallback for WebP/TIFF/HEIC/SVG)
- Text files with encoding detection (UTF-8/UTF-16/CP1250) and paging
- PDF pages (pypdfium2 + numpy, LRU cache, mouse wheel navigation)
- Word .docx (mammoth + Chrome HTML render, or python-docx text fallback)
- PowerPoint .pptx (python-pptx text + inline image extraction)
- Markdown (markdown lib + Chrome Headless rendered preview)
- HTML (html2image + Chrome Headless, scrollable viewport)
- CSV/TSV (native DPG table, stdlib csv with delimiter detection)
- Excel .xlsx (openpyxl, sheet switching via combo)
- SQLite databases (read-only table browsing with table switching)
- Fonts .ttf/.otf (live glyph preview with pangrams)
- ZIP/7z archives (file list table with compression ratios, click-to-preview)
- XML (pretty-printed via minidom)
- Source code (Pygments syntax highlighting via Chrome Headless)

Also manages panel toggle/resize logic and delegates to PDFRenderer
and HTMLRenderer for GPU-accelerated raw_texture rendering.
"""
# MIT licensed

import array
import csv
import io
import logging
import os
import shutil
import tempfile
import xml.dom.minidom
import zipfile
import sqlite3

import dearpygui.dearpygui as dpg

_log = logging.getLogger(__name__)

try:
    from PIL import Image as _PILImage
except ImportError:
    _PILImage = None

try:
    from docx import Document as _DocxDocument
except ImportError:
    _DocxDocument = None

try:
    import mammoth as _mammoth
except ImportError:
    _mammoth = None

try:
    from pptx import Presentation as _Presentation
except ImportError:
    _Presentation = None

try:
    import markdown as _markdown
except ImportError:
    _markdown = None

try:
    from openpyxl import load_workbook as _load_workbook
except ImportError:
    _load_workbook = None

try:
    from pygments import highlight as _highlight
    from pygments.lexers import get_lexer_for_filename as _get_lexer
    from pygments.formatters import HtmlFormatter as _HtmlFormatter
    from pygments.util import ClassNotFound as _ClassNotFound
except ImportError:
    _highlight = None

try:
    import py7zr as _py7zr
except ImportError:
    _py7zr = None

from ._types import FileEntry
from ._filesystem import DirectoryLister
from ._pdf import PDFRenderer, pdf_available
from ._html import HTMLRenderer, html_available


def word_available() -> bool:
    """Return True if Word text-extraction dependencies are installed."""
    return _DocxDocument is not None


def mammoth_available() -> bool:
    """Return True if mammoth + html2image Word preview is available."""
    return _mammoth is not None and html_available()


def pptx_available() -> bool:
    """Return True if PowerPoint preview dependencies are installed."""
    return _Presentation is not None


def markdown_available() -> bool:
    """Return True if rendered Markdown preview is available."""
    return _markdown is not None and html_available()


def excel_available() -> bool:
    """Return True if Excel (.xlsx) preview dependencies are installed."""
    return _load_workbook is not None


def pygments_available() -> bool:
    """Return True if Pygments code highlighting dependencies are installed."""
    return _highlight is not None and html_available()


def py7zr_available() -> bool:
    """Return True if py7zr dependencies are installed for .7z support."""
    return _py7zr is not None

# CSS for mammoth-generated HTML (dark theme matching DPG dialog)
_MAMMOTH_CSS = """
body {
    font-family: 'Segoe UI', Calibri, Arial, sans-serif;
    font-size: 14px;
    line-height: 1.6;
    color: #e0e0e0;
    background-color: #1a1a1a;
    margin: 0;
    padding: 0;
}
.mammoth-wrapper {
    padding: 20px 30px;
    word-wrap: break-word;
}
h1 { font-size: 24px; color: #64c8ff; border-bottom: 1px solid #333; padding-bottom: 6px; }
h2 { font-size: 20px; color: #82d2e6; }
h3 { font-size: 17px; color: #a0c8d2; }
h4 { font-size: 15px; color: #b4c3c8; }
p { margin: 6px 0; }
strong, b { color: #ffffc8; }
em, i { color: #c8d2ff; }
table { border-collapse: collapse; width: 100%; margin: 10px 0; }
th, td { border: 1px solid #444; padding: 6px 10px; text-align: left; }
th { background-color: #2a3a2a; color: #b4dcb4; }
td { background-color: #222; }
ul, ol { padding-left: 24px; }
li { margin: 3px 0; }
a { color: #6cb4ff; }
img { max-width: 100%; height: auto; }
"""

# CSS for markdown-rendered HTML (dark theme, code blocks, blockquotes)
_MARKDOWN_CSS = """
body {
    font-family: 'Segoe UI', Calibri, Arial, sans-serif;
    font-size: 14px;
    line-height: 1.6;
    color: #e0e0e0;
    background-color: #1a1a1a;
    margin: 0;
    padding: 0;
}
.md-wrapper {
    padding: 20px 30px;
    max-width: 100%;
    word-wrap: break-word;
}
h1 { font-size: 28px; color: #64c8ff; border-bottom: 2px solid #333; padding-bottom: 8px; margin-top: 24px; }
h2 { font-size: 22px; color: #82d2e6; border-bottom: 1px solid #333; padding-bottom: 6px; margin-top: 20px; }
h3 { font-size: 18px; color: #a0c8d2; margin-top: 16px; }
h4 { font-size: 15px; color: #b4c3c8; }
h5 { font-size: 14px; color: #c0c8cc; }
p { margin: 8px 0; }
strong, b { color: #ffffc8; }
em, i { color: #d0d0ff; }
a { color: #6cb6ff; text-decoration: none; }
code {
    background: #2d2d2d;
    color: #e6db74;
    padding: 2px 6px;
    border-radius: 3px;
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 13px;
}
pre {
    background: #2d2d2d;
    border: 1px solid #444;
    border-radius: 6px;
    padding: 12px 16px;
    overflow-x: auto;
    margin: 12px 0;
}
pre code { background: none; padding: 0; font-size: 13px; }
blockquote {
    border-left: 4px solid #555;
    margin: 12px 0;
    padding: 8px 16px;
    color: #aaa;
    background: #222;
}
ul, ol { padding-left: 24px; margin: 8px 0; }
li { margin: 4px 0; }
table { border-collapse: collapse; margin: 12px 0; width: 100%; }
th, td { border: 1px solid #444; padding: 8px 12px; text-align: left; }
th { background: #2d2d2d; color: #82d2e6; }
tr:nth-child(even) { background: #222; }
hr { border: none; border-top: 1px solid #444; margin: 20px 0; }
del { color: #888; }
img { max-width: 100%; height: auto; }
"""


class PreviewPanel:
    """Manages the optional preview panel in the file dialog.

    Routes files by extension to specialised renderers:

    - **Images**: stb_image (native DPG) or Pillow fallback; scaled to
      fit with preserved aspect ratio, centered in panel.
    - **Text**: encoding-detected (UTF-8/UTF-16/CP1250) with paged
      navigation for large files (256 KB chunks).
    - **PDF**: pypdfium2 pages rendered into raw_texture with LRU cache
      (10 pages) and background prefetch of neighboring pages.
    - **Word .docx**: mammoth + Chrome Headless for pixel-perfect HTML,
      or python-docx styled text extraction as fallback.
    - **PowerPoint .pptx**: python-pptx slide text + inline images with
      bold/italic coloring, tables, and speaker notes.
    - **Markdown**: markdown lib -> HTML -> Chrome Headless rendered.
    - **HTML**: html2image + Chrome Headless with scrollable viewport,
      overflow detection, auto-trim, and responsive resize.
    - **CSV/TSV**: native DPG table with csv.Sniffer delimiter detection.
    - **Excel .xlsx**: openpyxl read-only with sheet switching combo.
    - **SQLite**: read-only table browsing with table switching combo.
    - **Fonts .ttf/.otf**: live glyph preview (pangrams, Polish chars).
    - **ZIP/7z**: file list table with compression ratios; click a row
      to extract and preview the file.
    - **XML**: pretty-printed via minidom before display.
    - **Source code**: Pygments syntax highlighting rendered via Chrome.

    Delegates rendering to :class:`PDFRenderer` and :class:`HTMLRenderer`
    for raw_texture-based GPU rendering with background threads.
    """

    _STB_IMAGE_EXTS: frozenset[str] = frozenset({
        ".png", ".jpg", ".jpeg", ".bmp", ".tga",
        ".gif", ".psd", ".hdr", ".pic", ".pgm", ".ppm", ".pnm",
    })
    """Image extensions that DPG can load natively via stb_image."""

    _PILLOW_EXTRA_EXTS: frozenset[str] = frozenset({
        ".webp", ".tiff", ".tif", ".ico", ".heic", ".heif",
        ".avif", ".svg", ".dds", ".pcx", ".eps",
    })
    """Extra image extensions supported only when Pillow is installed."""

    _PDF_EXTS: frozenset[str] = frozenset({".pdf"})
    """PDF extensions supported when pypdfium2 + numpy are installed."""

    _WORD_EXTS: frozenset[str] = frozenset({".docx"})
    """Word extensions supported when python-docx is installed."""

    _PPTX_EXTS: frozenset[str] = frozenset({".pptx"})
    """PowerPoint extensions supported when python-pptx is installed."""

    _MD_EXTS: frozenset[str] = frozenset({".md", ".markdown"})
    """Markdown extensions rendered via markdown + Chrome when available."""

    _HTML_EXTS: frozenset[str] = frozenset({".html", ".htm"})
    """HTML extensions supported when html2image + numpy + Pillow are installed."""

    _CSV_EXTS: frozenset[str] = frozenset({".csv", ".tsv"})
    """CSV/TSV extensions rendered as native DPG tables."""

    _EXCEL_EXTS: frozenset[str] = frozenset({".xlsx"})
    """Excel extensions supported when openpyxl is installed."""

    _XML_EXTS: frozenset[str] = frozenset({".xml", ".ui", ".uvprojx", ".vcxproj", ".csproj"})
    """XML extensions that get formatted (pretty-printed) before viewing."""

    _ZIP_EXTS: frozenset[str] = frozenset({".zip", ".whl", ".egg", ".jar", ".apk"})
    """ZIP archive extensions that get previewed as a file list table."""

    _7Z_EXTS: frozenset[str] = frozenset({".7z"})
    """7-Zip archive extensions that get previewed as a file list table."""

    _FONT_EXTS: frozenset[str] = frozenset({".ttf", ".otf"})
    """Font extensions supported for live preview."""

    _DB_EXTS: frozenset[str] = frozenset({".db", ".sqlite", ".sqlite3", ".dat"})
    """SQLite database extensions supported for table browsing."""

    _TABLE_MAX_ROWS: int = 200
    """Maximum data rows to show in CSV/Excel table preview."""

    _TABLE_MAX_COLS: int = 50
    """Maximum columns to show in CSV/Excel table preview."""

    _CODE_EXTS: frozenset[str] = frozenset({
        ".py", ".pyw", ".pyi", ".pyl",
        ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
        ".json", ".jsonl", ".json5",
        ".css", ".scss", ".sass", ".less",
        ".yaml", ".yml", ".toml", ".env",
        ".c", ".h", ".cpp", ".hpp", ".cc", ".cxx",
        ".cs", ".java", ".kt", ".kts", ".scala", ".groovy",
        ".go", ".rs", ".swift", ".dart", ".lua",
        ".rb", ".pl", ".pm", ".r", ".jl", ".ex", ".exs",
        ".sql", ".graphql", ".gql",
        ".dockerfile", ".makefile", ".cmake",
        ".diff", ".patch",
    })
    """Extensions to be highlighted as code if Pygments is installed."""

    _TEXT_PREVIEW_EXTS: frozenset[str] = frozenset({
        ".txt", ".log", ".csv", ".tsv", ".ini", ".cfg", ".conf",
        ".bat", ".cmd", ".sh", ".bash", ".zsh", ".ps1",
        ".xml", ".html", ".htm", ".xhtml",
        ".md", ".rst", ".adoc", ".tex",
        ".gitignore", ".gitattributes", ".editorconfig",
        ".lock",
    }) | _CODE_EXTS
    """File extensions treated as plain text for preview."""

    _TEXT_PREVIEW_MAX_SIZE: int = 256 * 1024
    """Maximum file size in bytes to attempt text preview (256 KB)."""

    _STATUS_HEIGHT: int = 42
    """Height in pixels reserved for status/page labels below preview."""

    @classmethod
    def preview_image_exts(cls) -> frozenset[str]:
        """Return the set of image extensions supported for preview."""
        if _PILImage is not None:
            return cls._STB_IMAGE_EXTS | cls._PILLOW_EXTRA_EXTS
        return cls._STB_IMAGE_EXTS

    @staticmethod
    def load_image_pillow(path: str) -> tuple[int, int, "array.array[float]"]:
        """Load an image via Pillow and return (width, height, rgba_floats).

        Converts any Pillow-supported format to RGBA float data that
        DPG can use for a dynamic texture.
        """
        img = _PILImage.open(path)
        img = img.convert("RGBA")
        w, h = img.size
        raw = img.tobytes()
        data = array.array("f", (b / 255.0 for b in raw))
        return w, h, data

    def __init__(self, config_tag: str, preview_width: int, show: bool):
        self._config_tag = config_tag
        self._saved_width = preview_width
        self._visible = show

        # DPG widget IDs (set by attach())
        self._panel_id: int | None = None
        self._table_wrapper: int | None = None
        self._handler: int | None = None

        # Image cache and layout tracking
        self._image_cache: tuple[int, int, "array.array[float]"] | None = None
        self._last_size: tuple[float, float] = (0, 0)

        # PDF renderer (delegate)
        self._pdf: PDFRenderer | None = (
            PDFRenderer(config_tag) if pdf_available() else None
        )
        self._pdf_image_id: int | None = None
        self._pdf_page_label: int | None = None

        # HTML renderer (delegate)
        self._html: HTMLRenderer | None = (
            HTMLRenderer(config_tag) if html_available() else None
        )
        self._html_image_id: int | None = None
        self._html_status_label: int | None = None

        # Callback to check dialog visibility (set by build_handlers)
        self._is_active_fn = None
        
        # Paged text/code/xml/markdown preview
        self._text_offset: int = 0
        self._text_encoding: str | None = None
        self._current_entry: FileEntry | None = None

        # Font preview tracking
        self._temp_font: int | None = None

    @property
    def visible(self) -> bool:
        return self._visible

    @property
    def panel_id(self) -> int | None:
        return self._panel_id

    @property
    def table_wrapper(self) -> int | None:
        return self._table_wrapper

    @property
    def saved_width(self) -> int:
        return self._saved_width

    def attach(self, table_wrapper: int, panel_id: int) -> None:
        """Attach to DPG widget IDs created during _build_ui."""
        self._table_wrapper = table_wrapper
        self._panel_id = panel_id

    def build_handlers(self, dialog_tag: str, is_active_fn) -> None:
        """Create the item_resize_handler for the preview panel.

        The mouse_drag_handler (for resizable_x drags) must be created
        separately inside the global handler_registry context.
        """
        self._is_active_fn = is_active_fn
        with dpg.item_handler_registry() as self._handler:
            dpg.add_item_resize_handler(callback=self.on_resize)
        dpg.bind_item_handler_registry(dialog_tag, self._handler)

    # ── Toggle ─────────────────────────────────────────────────

    def toggle(self, explorer_table: int) -> None:
        """Toggle the preview panel visibility.

        Recreates ``_table_wrapper`` each time because DPG's ``resizable_x``
        stores an internal width override that persists even after
        ``resizable_x=False`` — ``configure_item(width=...)`` is then
        permanently ignored.  Recreating the child_window with fresh
        settings avoids this; the explorer table is preserved via
        ``dpg.move_item()``.
        """
        if self._panel_id is None or self._table_wrapper is None:
            return
        self._visible = not self._visible
        parent_group = dpg.get_item_parent(self._table_wrapper)

        if self._visible:
            new_wrapper = dpg.add_child_window(
                parent=parent_group,
                before=self._panel_id,
                width=-(self._saved_width + 8),
                height=-1,
                resizable_x=True,
            )
            dpg.move_item(explorer_table, parent=new_wrapper)
            dpg.delete_item(self._table_wrapper)
            self._table_wrapper = new_wrapper
            dpg.show_item(self._panel_id)
            self._last_size = (0, 0)
        else:
            pw, _ = dpg.get_item_rect_size(self._panel_id)
            if pw > 0:
                self._saved_width = int(pw)
            dpg.hide_item(self._panel_id)
            new_wrapper = dpg.add_child_window(
                parent=parent_group,
                before=self._panel_id,
                width=-1,
                height=-1,
            )
            dpg.move_item(explorer_table, parent=new_wrapper)
            dpg.delete_item(self._table_wrapper)
            self._table_wrapper = new_wrapper

    # ── Clear ──────────────────────────────────────────────────

    def clear(self) -> None:
        """Clear the preview panel and delete any loaded preview texture."""
        if self._panel_id is None:
            return
        if self._pdf is not None and self._pdf.is_open:
            self._pdf.close()
        self._pdf_image_id = None
        self._pdf_page_label = None
        if self._html is not None and self._html.is_open:
            self._html.close()
        self._html_image_id = None
        self._html_status_label = None
        self._image_cache = None
        if self._temp_font is not None:
            if dpg.does_item_exist(self._temp_font):
                dpg.delete_item(self._temp_font)
            self._temp_font = None
        dpg.delete_item(self._panel_id, children_only=True)
        tex_tag = f"_preview_tex_{self._config_tag}"
        if dpg.does_item_exist(tex_tag):
            dpg.delete_item(tex_tag)
        dpg.add_text("Preview", color=[128, 128, 128], parent=self._panel_id)

    # ── HTML preview helpers ──────────────────────────────────

    def _clear_for_html(self) -> None:
        """Clear panel and reset HTML widget refs for HTML-based previews."""
        self._image_cache = None
        self._html_image_id = None
        self._html_status_label = None
        dpg.delete_item(self._panel_id, children_only=True)
        tex_tag = f"_preview_tex_{self._config_tag}"
        if dpg.does_item_exist(tex_tag):
            dpg.delete_item(tex_tag)

    def _html_panel_size(self) -> tuple[int, int] | None:
        """Return (render_w, render_h) or None if panel is too small."""
        panel_w, panel_h = dpg.get_item_rect_size(self._panel_id)
        if panel_w <= 0 or panel_h <= 0:
            return None
        render_h = max(1, int(panel_h) - self._STATUS_HEIGHT)
        render_w = max(1, int(panel_w))
        return render_w, render_h

    def _show_html_widgets(self) -> None:
        """Create image + status label widgets for current HTML render."""
        self._html_image_id = dpg.add_image(
            self._html.tex_id,
            parent=self._panel_id,
        )
        self._html_status_label = dpg.add_text(
            self._html.status_text,
            color=[180, 180, 180],
            parent=self._panel_id,
        )

    def _load_text_content(self, path: str, seek_offset: int = 0) -> tuple[str | None, bool]:
        """Read a file fragment as text with encoding detection and binary check.

        This method attempts to detect the correct text encoding (UTF-8, UTF-16, CP1250)
        and prevents rendering of binary files. For paged previews (offset > 0), 
        it reuses the encoding detected at the start of the file.

        Args:
            path: Absolute path to the file.
            seek_offset: Byte offset to start reading from.

        Returns:
            A tuple of (decoded_text, is_binary). 
            'decoded_text' is None if an error occurred or the file is binary.
            'is_binary' is True if null bytes were detected (non-textual content).
        """
        try:
            with open(path, "rb") as f:
                if seek_offset > 0:
                    f.seek(seek_offset)
                raw_bytes = f.read(self._TEXT_PREVIEW_MAX_SIZE)
            
            if not raw_bytes:
                return "", False

            # If we already have a detected encoding and we are at an offset, reuse it.
            if seek_offset > 0 and self._text_encoding:
                return raw_bytes.decode(self._text_encoding, errors="replace"), False

            # --- Detection Phase (seek_offset == 0 or no encoding yet) ---
            
            # Try UTF-8-sig first (handles BOM)
            try:
                text = raw_bytes.decode("utf-8-sig")
                self._text_encoding = "utf-8-sig"
                return text, False
            except UnicodeDecodeError:
                pass

            # Try UTF-16 ONLY if starts with BOM or smells like UTF-16 (many nulls)
            has_bom = raw_bytes.startswith((b'\xff\xfe', b'\xfe\xff'))
            is_utf16_likely = has_bom
            if not is_utf16_likely and len(raw_bytes) >= 4:
                # Heuristic: check first 1KB for null byte distribution
                sample = raw_bytes[:1024]
                nulls_even = sample[0::2].count(b'\x00')
                nulls_odd = sample[1::2].count(b'\x00')
                # If one set of positions is mostly nulls, it's likely UTF-16
                if (nulls_even > len(sample)//4 or nulls_odd > len(sample)//4):
                    is_utf16_likely = True

            if is_utf16_likely:
                try:
                    text = raw_bytes.decode("utf-16")
                    self._text_encoding = "utf-16"
                    return text, False
                except UnicodeDecodeError:
                    pass
            
            # Binary check: if contains null bytes and didn't decode as UTF-16
            check_size = min(len(raw_bytes), 8192)
            if b"\x00" in raw_bytes[:check_size]:
                return None, True
                
            # Try CP1250 (Polish fallback)
            try:
                text = raw_bytes.decode("cp1250")
                self._text_encoding = "cp1250"
                return text, False
            except UnicodeDecodeError:
                # Last resort replacement
                self._text_encoding = "cp1250"
                return raw_bytes.decode("cp1250", errors="replace"), False
                
        except (OSError, PermissionError):
            return None, False

    # ── Main routing ──────────────────────────────────────────

    def update(self, entry: FileEntry | None) -> None:
        """Load a file for preview.

        Routing order: HTML -> Markdown (rendered) -> CSV/TSV (table) ->
        Excel (table) -> text -> PDF -> Word (mammoth or python-docx) ->
        PowerPoint -> image.
        HTML, Markdown, and CSV/TSV are checked before text because they
        are also in _TEXT_PREVIEW_EXTS.
        """
        if self._panel_id is None or not self._visible:
            return

        if entry is None or entry.is_dir:
            self._current_entry = None
            self._text_offset = 0
            self.clear()
            return

        # Reset offset and encoding if file changed
        if self._current_entry is None or self._current_entry.full_path != entry.full_path:
            self._text_offset = 0
            self._text_encoding = None
        self._current_entry = entry

        if "|" in entry.full_path:
            self._handle_virtual_archive_preview(entry)
            return

        ext = os.path.splitext(entry.name)[1].lower()

        # Close PDF if switching away from PDF preview
        if (self._pdf is not None and self._pdf.is_open
                and ext not in self._PDF_EXTS):
            self._pdf.close()
            self._pdf_image_id = None
            self._pdf_page_label = None

        # Close HTML if switching away from HTML/Word-mammoth/Markdown/Code preview
        html_active_exts = self._HTML_EXTS
        if self._html is not None and mammoth_available():
            html_active_exts = html_active_exts | self._WORD_EXTS
        if self._html is not None and markdown_available():
            html_active_exts = html_active_exts | self._MD_EXTS
        if self._html is not None and pygments_available():
            html_active_exts = html_active_exts | self._CODE_EXTS
        if (self._html is not None and self._html.is_open
                and ext not in html_active_exts):
            self._html.close()
            self._html_image_id = None
            self._html_status_label = None

        # Route to specific renderer
        if ext in self._HTML_EXTS:
            self._render_html_preview(entry)
        elif markdown_available() and ext in self._MD_EXTS:
            self._render_markdown_preview(entry)
        elif ext in self._CSV_EXTS:
            self._render_csv_preview(entry)
        elif excel_available() and ext in self._EXCEL_EXTS:
            self._render_excel_preview(entry)
        elif ext in self._DB_EXTS:
            self._render_sqlite_preview(entry)
        elif ext in self._FONT_EXTS:
            self._render_font_preview(entry)
        elif ext in self._XML_EXTS:
            self._render_xml_preview(entry)
        elif pygments_available() and ext in self._CODE_EXTS:
            self._render_code_preview(entry)
        elif ext in self._TEXT_PREVIEW_EXTS or (not ext and entry.name.lower() in self._TEXT_PREVIEW_EXTS):
            self._render_text_preview(entry)
        elif pdf_available() and ext in self._PDF_EXTS:
            self._render_pdf_preview(entry)
        elif ext in self._ZIP_EXTS:
            self._render_zip_preview(entry)
        elif py7zr_available() and ext in self._7Z_EXTS:
            self._render_7z_preview(entry)
        elif ext in self.preview_image_exts():
            self._render_image_preview(entry)
        elif word_available() and ext in self._WORD_EXTS:
            self._render_word_preview(entry)
        elif pptx_available() and ext in self._PPTX_EXTS:
            self._render_pptx_preview(entry)
        else:
            self.clear()

    def _render_image_preview(self, entry: FileEntry) -> None:
        """Load and display an image file using DPG or Pillow."""
        if self._panel_id is None:
            return

        ext = os.path.splitext(entry.name)[1].lower()
        use_pillow = ext not in self._STB_IMAGE_EXTS

        if use_pillow:
            try:
                img_w, img_h, data = self.load_image_pillow(entry.full_path)
            except Exception:
                self.clear()
                return
        else:
            try:
                img_w, img_h, _, data = dpg.load_image(entry.full_path)
            except Exception:
                try:
                    with tempfile.NamedTemporaryFile(
                        delete=False, suffix=ext,
                    ) as tmp:
                        tmp_path = tmp.name
                    try:
                        shutil.copy2(entry.full_path, tmp_path)
                        img_w, img_h, _, data = dpg.load_image(tmp_path)
                    finally:
                        os.unlink(tmp_path)
                except Exception:
                    self.clear()
                    return

        self._image_cache = (img_w, img_h, data)
        self.layout()


    def _handle_virtual_archive_preview(self, entry: FileEntry) -> None:
        """Extract virtual archive file to temp and preview it."""
        try:
            extracted_path = DirectoryLister.extract_from_archive(
                entry.full_path,
                max_size=self._TEXT_PREVIEW_MAX_SIZE,
                allow_large_extensions=self._PDF_EXTS,
            )
            if extracted_path and os.path.exists(extracted_path):
                stat = os.stat(extracted_path)
                virtual_entry = FileEntry(
                    name=entry.name,
                    full_path=extracted_path,
                    is_dir=False,
                    size_bytes=stat.st_size,
                    modified_time=stat.st_mtime,
                    is_hidden=False,
                )
                self.update(virtual_entry)
            else:
                self.clear()
        except Exception:
            self.clear()


    # ── HTML preview ────────────────────────────────────────────

    def _render_html_preview(self, entry: FileEntry) -> None:
        """Open an HTML file and start background Chrome Headless rendering."""
        if self._panel_id is None or self._html is None:
            return
        self._clear_for_html()
        dims = self._html_panel_size()
        if dims is None:
            return
        render_w, render_h = dims
        if not self._html.open(
            entry.full_path, render_w, render_h,
            on_complete=self._on_html_render_done,
            on_resize_complete=self._on_html_resize_done,
        ):
            dpg.add_text(
                "Cannot preview this file",
                color=[128, 128, 128],
                parent=self._panel_id,
            )
            return
        self._show_html_widgets()

    def _on_html_render_done(self) -> None:
        """Called by HTMLRenderer inside dpg.mutex() when render completes."""
        if (self._html_status_label is not None
                and dpg.does_item_exist(self._html_status_label)
                and self._html is not None):
            dpg.set_value(self._html_status_label, self._html.status_text)

    def _on_html_resize_done(self) -> None:
        """Called inside dpg.mutex() when debounced resize recreates texture."""
        if self._panel_id is None or self._html is None:
            return
        dpg.delete_item(self._panel_id, children_only=True)
        self._show_html_widgets()

    # ── Markdown rendered preview (markdown + Chrome) ──────────

    def _render_markdown_preview(self, entry: FileEntry) -> None:
        """Render a Markdown file via markdown lib + Chrome Headless."""
        if self._panel_id is None or self._html is None:
            return
        self._clear_for_html()

        # Read and convert Markdown -> HTML
        md_text, is_bin = self._load_text_content(entry.full_path, self._text_offset)
        if is_bin:
            dpg.add_text(
                f"Binary file: {entry.name}",
                color=[128, 128, 128],
                parent=self._panel_id,
            )
            return
        if md_text is None:
            self.clear()
            return

        try:
            md_html = _markdown.markdown(
                md_text, extensions=["tables", "fenced_code"],
            )
        except Exception:
            self.clear()
            return

        dims = self._html_panel_size()
        if dims is None:
            return
        render_w, render_h = dims
        
        # Wrapped HTML with Monokai-ish style
        full_html = f"<html><head><style>{_MARKDOWN_CSS}</style></head><body><div class='md-wrapper'>{md_html}</div></body></html>"

        # Add truncation label if needed
        if entry.size_bytes is not None and entry.size_bytes > self._TEXT_PREVIEW_MAX_SIZE:
             limit_str = DirectoryLister.format_size(self._TEXT_PREVIEW_MAX_SIZE)
             size_str = DirectoryLister.format_size(entry.size_bytes)
             dpg.add_text(
                 f"{entry.name} (Partial: first {limit_str} of {size_str})",
                 color=[180, 180, 255],
                 parent=self._panel_id,
             )

        if not self._html.open_string(
            full_html, render_w, render_h,
            on_complete=self._on_html_render_done,
            on_resize_complete=self._on_html_resize_done,
        ):
            self.clear()
            return
        self._show_html_widgets()

    # ── Table preview (CSV / Excel) ──────────────────────────────

    def _render_table_widget(
        self,
        entry_name: str,
        headers: list[str],
        rows: list[list[str]],
        status_text: str,
        ui_builder=None,
        row_click_callback=None,
    ) -> None:
        """Render tabular data as a native DPG table in the preview panel."""
        if self._panel_id is None:
            return

        self._image_cache = None
        dpg.delete_item(self._panel_id, children_only=True)
        tex_tag = f"_preview_tex_{self._config_tag}"
        if dpg.does_item_exist(tex_tag):
            dpg.delete_item(tex_tag)

        dpg.add_text(
            entry_name,
            color=[180, 180, 255],
            parent=self._panel_id,
        )
        dpg.add_separator(parent=self._panel_id)

        if not headers and not rows:
            dpg.add_text(
                status_text or "No data",
                color=[128, 128, 128],
                parent=self._panel_id,
            )
            return

        header_color = [180, 220, 180]
        cell_color = [210, 210, 210]

        bottom_margin = self._STATUS_HEIGHT + 4
        if ui_builder is not None:
            bottom_margin += 30

        with dpg.child_window(
            parent=self._panel_id,
            height=-bottom_margin,
            width=-1,
        ):
            with dpg.table(
                header_row=False,
                borders_innerH=True,
                borders_innerV=True,
                borders_outerH=True,
                borders_outerV=True,
                scrollX=True,
                scrollY=True,
                freeze_rows=1,
                resizable=True,
                policy=dpg.mvTable_SizingFixedFit,
            ):
                # Pre-calculate column widths to prevent vertical text wrapping 
                # (DPG calculates FixedFit based on first visible row)
                col_widths = []
                for i in range(len(headers)):
                    max_len = len(str(headers[i]))
                    for row_data in rows:
                        if i < len(row_data) and row_data[i] is not None:
                            max_len = max(max_len, len(str(row_data[i])))
                    # Avg character width is ~8 pixels, +20 for padding
                    col_widths.append(min(400, max_len * 8 + 20))

                for w in col_widths:
                    dpg.add_table_column(init_width_or_weight=w)

                # Header row (manually colored)
                with dpg.table_row():
                    for col_name in headers:
                        dpg.add_text(col_name, wrap=0, color=header_color)

                # Data rows
                for r_idx, row_data in enumerate(rows):
                    with dpg.table_row():
                        for c_idx, cell_val in enumerate(row_data):
                            if c_idx == 0 and row_click_callback is not None:
                                dpg.add_selectable(
                                    label=cell_val,
                                    callback=row_click_callback,
                                    user_data=r_idx,
                                    span_columns=False,
                                )
                            else:
                                dpg.add_text(cell_val, wrap=0, color=cell_color)
                        for _ in range(len(headers) - len(row_data)):
                            dpg.add_text("", color=cell_color)

        dpg.add_spacer(height=2, parent=self._panel_id)

        if ui_builder is not None:
            ui_builder()

        dpg.add_text(
            status_text,
            color=[180, 180, 180],
            parent=self._panel_id,
        )

    def _render_csv_preview(self, entry: FileEntry) -> None:
        """Parse a CSV/TSV file and display as a native DPG table."""
        if self._panel_id is None:
            return

        text, is_bin = self._load_text_content(entry.full_path)
        if is_bin:
            self._render_binary_warning(entry)
            return
        if text is None:
            self.clear()
            return

        ext = os.path.splitext(entry.name)[1].lower()
        f = io.StringIO(text)

        try:
            if ext == ".tsv":
                delimiter = "\t"
                dialect = None
            else:
                sample = text[:8192]
                try:
                    dialect = csv.Sniffer().sniff(sample)
                except csv.Error:
                    dialect = None
                delimiter = dialect.delimiter if dialect else ","

            reader = (csv.reader(f, dialect) if dialect
                      else csv.reader(f, delimiter=delimiter))

            all_rows: list[list[str]] = []
            total_rows = 0
            max_cols = 0
            for row in reader:
                total_rows += 1
                if len(all_rows) < self._TABLE_MAX_ROWS + 1:
                    all_rows.append(row[:self._TABLE_MAX_COLS])
                max_cols = max(max_cols, len(row))
        except Exception:
            # If CSV parsing fails, fallback to plain text
            self._render_text_preview(entry)
            return

        if not all_rows:
            self._render_table_widget(entry.name, [], [], "Empty file")
            return

        headers = all_rows[0]
        data_rows = all_rows[1:]
        total_data = total_rows - 1
        display_cols = min(max_cols, self._TABLE_MAX_COLS)

        while len(headers) < display_cols:
            headers.append(f"Col{len(headers) + 1}")

        parts = [f"{total_data} rows \u00d7 {max_cols} cols"]
        
        # If the underlying file was larger than 1MB, indicate partial read
        header_name = entry.name
        if entry.size_bytes is not None and entry.size_bytes > self._TEXT_PREVIEW_MAX_SIZE:
             limit_str = DirectoryLister.format_size(self._TEXT_PREVIEW_MAX_SIZE)
             size_str = DirectoryLister.format_size(entry.size_bytes)
             header_name = f"{entry.name} (Partial: first {limit_str} of {size_str})"

        truncated = []
        if len(data_rows) < total_data:
            truncated.append(f"first {len(data_rows)} rows")
        if display_cols < max_cols:
            truncated.append(f"first {display_cols} cols")
        if truncated:
            parts.append(f"(showing {', '.join(truncated)})")

        self._render_table_widget(
            header_name, headers, data_rows, " | ".join(parts),
        )

    def _render_excel_preview(self, entry: FileEntry, sheet_name_to_load: str | None = None) -> None:
        """Parse an Excel .xlsx file and display as a native DPG table."""
        if self._panel_id is None:
            return

        try:
            wb = _load_workbook(
                entry.full_path, read_only=True, data_only=True,
            )
        except Exception:
            self.clear()
            return

        try:
            sheetnames = wb.sheetnames
            ws = None

            if sheet_name_to_load and sheet_name_to_load in sheetnames:
                ws = wb[sheet_name_to_load]
            elif sheetnames:
                ws = wb.active if wb.active is not None else wb[sheetnames[0]]

            if ws is None:
                wb.close()
                self._render_table_widget(
                    entry.name, [], [], "No sheets found",
                )
                return

            sheet_name = ws.title

            def _build_excel_ui():
                if len(sheetnames) > 1:
                    with dpg.group(horizontal=True, parent=self._panel_id):
                        dpg.add_text("Sheet:", color=[180, 180, 180])
                        def on_sheet_changed(sender, app_data, user_data):
                            self._render_excel_preview(entry, sheet_name_to_load=app_data)
                        dpg.add_combo(
                            items=sheetnames,
                            default_value=sheet_name,
                            width=-1,
                            callback=on_sheet_changed
                        )
            all_rows: list[list[str]] = []
            total_rows = 0
            max_cols = 0

            for row in ws.iter_rows(values_only=True):
                total_rows += 1
                str_row = [
                    str(cell) if cell is not None else ""
                    for cell in row[:self._TABLE_MAX_COLS]
                ]
                if len(all_rows) < self._TABLE_MAX_ROWS + 1:
                    all_rows.append(str_row)
                max_cols = max(max_cols, len(row))
        finally:
            wb.close()

        if not all_rows:
            self._render_table_widget(
                entry.name, [], [],
                f"Sheet: {sheet_name} | Empty sheet",
                ui_builder=_build_excel_ui
            )
            return

        headers = all_rows[0]
        data_rows = all_rows[1:]
        total_data = total_rows - 1
        display_cols = min(max_cols, self._TABLE_MAX_COLS)

        while len(headers) < display_cols:
            headers.append(f"Col{len(headers) + 1}")

        parts = [f"Sheet: {sheet_name}",
                 f"{total_data} rows \u00d7 {max_cols} cols"]
        truncated = []
        if len(data_rows) < total_data:
            truncated.append(f"first {len(data_rows)} rows")
        if display_cols < max_cols:
            truncated.append(f"first {display_cols} cols")
        if truncated:
            parts.append(f"(showing {', '.join(truncated)})")

        self._render_table_widget(
            entry.name, headers, data_rows, " | ".join(parts),
            ui_builder=_build_excel_ui
        )

    # ── XML preview ────────────────────────────────────────────

    def _render_xml_preview(self, entry: FileEntry) -> None:
        """Parse an XML file and display its pretty-printed contents."""
        if self._panel_id is None:
            return

        raw_text, is_bin = self._load_text_content(entry.full_path, self._text_offset)
        if is_bin:
            self._render_binary_warning(entry)
            return
        if raw_text is None:
            self.clear()
            return

        # Format XML
        try:
            parsed = xml.dom.minidom.parseString(raw_text)
            formatted_text = parsed.toprettyxml(indent="    ")
            # Minidom often adds awkward blank lines, so we clean them up
            text = "\n".join(line for line in formatted_text.splitlines() if line.strip())
        except Exception:
            # If parsing fails (invalid XML), fallback to raw text
            text = raw_text

        if not text:
            text = "(No identifiable XML or text content in this fragment)"

        self._image_cache = None
        dpg.delete_item(self._panel_id, children_only=True)
        tex_tag = f"_preview_tex_{self._config_tag}"
        if dpg.does_item_exist(tex_tag):
            dpg.delete_item(tex_tag)

        # Label info
        if entry.size_bytes is not None and entry.size_bytes > self._TEXT_PREVIEW_MAX_SIZE:
            self._render_text_navigation(entry)
        else:
            dpg.add_text(
                entry.name,
                color=[180, 180, 255],
                parent=self._panel_id,
            )

        dpg.add_separator(parent=self._panel_id)
        with dpg.child_window(parent=self._panel_id, height=-1, width=-1):
            dpg.add_text(text, wrap=0)

    # ── Code Highlighting preview ───────────────────────────────

    def _render_code_preview(self, entry: FileEntry) -> None:
        """Render source code with syntax highlighting using Pygments into HTML."""
        if self._panel_id is None or self._html is None:
            return

        # Read text
        code_text, is_bin = self._load_text_content(entry.full_path, self._text_offset)
        if is_bin:
            self._render_binary_warning(entry)
            return
        if code_text is None:
            self.clear()
            return


        # Get the right lexer, fallback to Python if unknown
        try:
            lexer = _get_lexer(entry.name)
        except _ClassNotFound:
            import pygments.lexers as _lexers
            lexer = _lexers.get_lexer_by_name("python")

        # HTML formatting using monokai style
        formatter = _HtmlFormatter(style="monokai", full=True, csslinebreaks=True, prestyles="margin: 0; padding: 15px;")
        html_result = _highlight(code_text, lexer, formatter)

        # Basic styling fixes for background + scrollbars
        html_result = html_result.replace("</style>", 
        """
        body { 
            margin: 0; 
            padding: 0; 
            background-color: #272822; /* Monokai background */ 
            color: #f8f8f2; 
        }
        pre { font-family: 'Consolas', 'Courier New', monospace; font-size: 14px; }
        ::-webkit-scrollbar { width: 10px; height: 10px; }
        ::-webkit-scrollbar-track { background: #1e1e1e; }
        ::-webkit-scrollbar-thumb { background: #555; }
        ::-webkit-scrollbar-thumb:hover { background: #777; }
        </style>""")

        self._clear_for_html()
        
        # Add truncation label and navigation if needed
        if entry.size_bytes is not None and entry.size_bytes > self._TEXT_PREVIEW_MAX_SIZE:
             self._render_text_navigation(entry)

        dims = self._html_panel_size()
        if dims is None:
            return
        render_w, render_h = dims
        if not self._html.open_string(
            html_result, render_w, render_h,
            on_complete=self._on_html_render_done,
            on_resize_complete=self._on_html_resize_done,
        ):
            self._render_text_preview(entry)
            return
        self._show_html_widgets()

    # ── ZIP Archive preview ────────────────────────────────────

    def _render_zip_preview(self, entry: FileEntry) -> None:
        """Parse a ZIP archive and display its contents as a native DPG table."""
        if self._panel_id is None:
            return

        all_rows: list[list[str]] = []
        total_files = 0
        total_uncompressed = 0
        total_compressed = 0

        try:
            with zipfile.ZipFile(entry.full_path, 'r') as zf:
                info_list = zf.infolist()
                total_files = len(info_list)

                # Need to gracefully handle massively stuffed zip files
                # sort by size descending and take top N rows
                info_list.sort(key=lambda x: x.file_size, reverse=True)

                for info in info_list:
                    total_uncompressed += info.file_size
                    total_compressed += info.compress_size
                    
                    if len(all_rows) < self._TABLE_MAX_ROWS:
                        ratio = 0.0
                        if info.file_size > 0:
                            ratio = ((info.file_size - info.compress_size) / info.file_size) * 100.0
                            
                        all_rows.append([
                            info.filename,
                            DirectoryLister.format_size(info.file_size),
                            DirectoryLister.format_size(info.compress_size),
                            f"{ratio:.1f}%",
                            f"{info.date_time[0]}-{info.date_time[1]:02d}-{info.date_time[2]:02d}"
                        ])
        except (OSError, PermissionError, zipfile.BadZipFile):
            self.clear()
            return
        except RuntimeError as e:
            if "password" in str(e).lower():
                self._render_table_widget(entry.name, [], [], "Encrypted ZIP archive (Password required)")
            else:
                self.clear()
            return


        if not all_rows:
            self._render_table_widget(
                entry.name, [], [], "Empty archive",
            )
            return

        headers = ["Filename", "Size", "Packed", "Ratio", "Date"]

        parts = []
        parts.append(f"{total_files} files")
        if total_files > self._TABLE_MAX_ROWS:
            parts.append(f"(showing largest {self._TABLE_MAX_ROWS})")
            
        parts.append(f"| Extracted: {DirectoryLister.format_size(total_uncompressed)}")
        
        self._render_table_widget(
            entry.name, headers, all_rows, " ".join(parts),
            row_click_callback=lambda s, a, u: self._on_zip_item_clicked(entry.full_path, all_rows[u][0])
        )

    def _on_zip_item_clicked(self, archive_path: str, internal_path: str) -> None:
        """Extract a single file from a ZIP archive and preview it."""
        try:
            virtual_path = f"{archive_path}|/{internal_path}"
            extracted_path = DirectoryLister.extract_from_archive(virtual_path)
            
            if extracted_path:
                stat = os.stat(extracted_path)
                virtual_entry = FileEntry(
                    name=f"[{os.path.basename(archive_path)}] {os.path.basename(internal_path)}",
                    full_path=extracted_path,
                    is_dir=False,
                    size_bytes=stat.st_size,
                    modified_time=stat.st_mtime,
                    is_hidden=False,
                )
                self.update(virtual_entry)
        except Exception:
            pass

    # ── 7-Zip Archive preview ──────────────────────────────────

    def _render_7z_preview(self, entry: FileEntry) -> None:
        """Parse a 7z archive and display its contents as a native DPG table."""
        if self._panel_id is None:
            return

        all_rows: list[list[str]] = []
        total_files = 0
        total_uncompressed = 0
        total_compressed = 0

        try:
            with _py7zr.SevenZipFile(entry.full_path, mode='r') as z:
                info_list = z.list()
                total_files = len(info_list)

                # Need to gracefully handle massively stuffed 7z files
                # sort by size descending and take top N rows
                info_list.sort(key=lambda x: x.uncompressed if x.uncompressed else 0, reverse=True)

                for info in info_list:
                    # Py7zr FileInfo objects have 'filename', 'uncompressed', 'compressed', 'creationtime'
                    uc_size = info.uncompressed if info.uncompressed else 0
                    c_size = info.compressed if info.compressed else 0
                    
                    total_uncompressed += uc_size
                    total_compressed += c_size
                    
                    if len(all_rows) < self._TABLE_MAX_ROWS:
                        ratio = 0.0
                        if uc_size > 0:
                            ratio = ((uc_size - c_size) / uc_size) * 100.0
                            
                        # Format datetime safely
                        date_str = ""
                        if info.creationtime:
                            date_str = info.creationtime.strftime("%Y-%m-%d")
                            
                        all_rows.append([
                            info.filename,
                            DirectoryLister.format_size(uc_size),
                            DirectoryLister.format_size(c_size),
                            f"{ratio:.1f}%",
                            date_str
                        ])
        except (OSError, PermissionError):
            self.clear()
            return
        except Exception as e:
            # Handle encrypted or other py7zr errors
            msg = str(e)
            if "password" in msg.lower() or "encrypted" in msg.lower():
                self._render_table_widget(entry.name, [], [], "Encrypted 7z archive (Password required)")
            else:
                self.clear()
            return

        if not all_rows:
            self._render_table_widget(
                entry.name, [], [], "Empty 7z archive",
            )
            return

        headers = ["Filename", "Size", "Packed", "Ratio", "Date"]
        
        parts = []
        parts.append(f"{total_files} files")
        if total_files > self._TABLE_MAX_ROWS:
            parts.append(f"(showing largest {self._TABLE_MAX_ROWS})")
            
        parts.append(f"| Extracted: {DirectoryLister.format_size(total_uncompressed)}")
        
        self._render_table_widget(
            entry.name, headers, all_rows, " ".join(parts),
            row_click_callback=lambda s, a, u: self._on_7z_item_clicked(entry.full_path, all_rows[u][0])
        )

    def _on_7z_item_clicked(self, archive_path: str, internal_path: str) -> None:
        """Extract a single file from a 7z archive and preview it."""
        try:
            virtual_path = f"{archive_path}|/{internal_path}"
            extracted_path = DirectoryLister.extract_from_archive(virtual_path)
            
            if extracted_path:
                stat = os.stat(extracted_path)
                virtual_entry = FileEntry(
                    name=f"[{os.path.basename(archive_path)}] {os.path.basename(internal_path)}",
                    full_path=extracted_path,
                    is_dir=False,
                    size_bytes=stat.st_size,
                    modified_time=stat.st_mtime,
                    is_hidden=False,
                )
                self.update(virtual_entry)
        except Exception:
            pass


    # ── Text preview ───────────────────────────────────────────

    def _render_text_preview(self, entry: FileEntry) -> None:
        """Read a text file and display its contents in the preview panel."""
        if self._panel_id is None:
            return

        text, is_bin = self._load_text_content(entry.full_path, self._text_offset)
        if is_bin:
            self._render_binary_warning(entry)
            return
        if text is None:
            self.clear()
            return

        if not text.strip():
            text = "(No text content or only whitespace in this fragment)"

        self._image_cache = None
        dpg.delete_item(self._panel_id, children_only=True)
        tex_tag = f"_preview_tex_{self._config_tag}"
        if dpg.does_item_exist(tex_tag):
            dpg.delete_item(tex_tag)

        # Label info
        if entry.size_bytes is not None and entry.size_bytes > self._TEXT_PREVIEW_MAX_SIZE:
            self._render_text_navigation(entry)
        else:
            dpg.add_text(
                entry.name,
                color=[180, 180, 255],
                parent=self._panel_id,
            )
        dpg.add_separator(parent=self._panel_id)
        with dpg.child_window(parent=self._panel_id, height=-1, width=-1):
            dpg.add_text(text, wrap=0)

    def _render_binary_warning(self, entry: FileEntry) -> None:
        """Show a warning message in the panel when a file appears to be binary.
        
        Args:
            entry: The file entry representing the binary file.
        """
        if self._temp_font is not None:
            if dpg.does_item_exist(self._temp_font):
                dpg.delete_item(self._temp_font)
            self._temp_font = None

        dpg.delete_item(self._panel_id, children_only=True)
        tex_tag = f"_preview_tex_{self._config_tag}"
        if dpg.does_item_exist(tex_tag):
            dpg.delete_item(tex_tag)
        dpg.add_text(
            f"Binary file: {entry.name}",
            color=[128, 128, 128],
            parent=self._panel_id,
        )
        dpg.add_text(
            "(No text preview available)",
            color=[100, 100, 100],
            parent=self._panel_id,
        )

    def _render_text_navigation(self, entry: FileEntry) -> None:
        """Add navigation buttons and range label for paged text preview.

        Provides [<] and [>] buttons to navigate large files in chunks defined by
        _TEXT_PREVIEW_MAX_SIZE. Displays current byte range in MB.

        Args:
            entry: The file entry being previewed.
        """
        mb = 1024 * 1024
        start_mb = self._text_offset / mb
        end_mb = min(
            (self._text_offset + self._TEXT_PREVIEW_MAX_SIZE) / mb,
            entry.size_bytes / mb,
        )
        total_mb = entry.size_bytes / mb
        
        info = f"{start_mb:.2f}-{end_mb:.2f} of {total_mb:.2f} MB"
        
        with dpg.group(horizontal=True, parent=self._panel_id):
            dpg.add_text(entry.name, color=[180, 180, 255])
            dpg.add_spacer(width=4)
            
            # Prev button
            dpg.add_button(
                label="<", 
                width=24, 
                callback=self._on_text_page_change, 
                user_data=-1,
                enabled=(self._text_offset > 0)
            )
            
            # Info label
            dpg.add_text(info, color=[200, 200, 200])
            
            # Next button
            dpg.add_button(
                label=">", 
                width=24, 
                callback=self._on_text_page_change, 
                user_data=1,
                enabled=(self._text_offset + self._TEXT_PREVIEW_MAX_SIZE < entry.size_bytes)
            )

    def _on_text_page_change(self, sender, app_data, user_data: int) -> None:
        """Handle page change events from [<] and [>] buttons.

        Args:
            sender: The DPG item that triggered the callback.
            app_data: DPG app data (unused).
            user_data: Navigation direction (-1 for previous, 1 for next).
        """
        if self._current_entry is None:
            return
            
        new_offset = self._text_offset + (user_data * self._TEXT_PREVIEW_MAX_SIZE)
        if 0 <= new_offset < self._current_entry.size_bytes:
            self._text_offset = new_offset
            self.update(self._current_entry)

    def _render_font_preview(self, entry: FileEntry) -> None:
        """Display a live preview of a font file (.ttf, .otf)."""
        if self._panel_id is None:
            return

        self._image_cache = None
        if self._temp_font is not None:
            if dpg.does_item_exist(self._temp_font):
                dpg.delete_item(self._temp_font)
            self._temp_font = None

        dpg.delete_item(self._panel_id, children_only=True)

        try:
            # Load font into temporary registry
            with dpg.font_registry():
                # We use a large size for the preview
                font_id = dpg.add_font(entry.full_path, 24)
                # Basic Latin and Latin-1
                dpg.add_font_range(0x0020, 0x00FF, parent=font_id)
                # Latin Extended-A (Polish characters)
                dpg.add_font_range(0x0100, 0x017F, parent=font_id)
                
            self._temp_font = font_id
        except Exception as e:
            dpg.add_text(f"Error loading font: {e}", color=[255, 100, 100], parent=self._panel_id)
            return

        dpg.add_text(f"Font Preview: {entry.name}", color=[180, 180, 255], parent=self._panel_id)
        dpg.add_separator(parent=self._panel_id)

        with dpg.child_window(parent=self._panel_id, height=-1, width=-1) as font_win:
             dpg.bind_item_font(font_win, self._temp_font)
             
             dpg.add_text("PANGRAM (ALL CHARS):")
             dpg.add_text("THE QUICK BROWN FOX JUMPS OVER THE LAZY DOG")
             dpg.add_text("the quick brown fox jumps over the lazy dog")
             dpg.add_spacer(height=10)
             
             dpg.add_text("POLSKIE ZNAKI (POLISH CHARS):")
             dpg.add_text("zażółć gęślą jaźń")
             dpg.add_text("ZAŻÓŁĆ GĘŚLĄ JAŹŃ")
             dpg.add_spacer(height=10)
             
             dpg.add_text("NUMBERS & SYMBOLS:")
             dpg.add_text("0123456789")
             dpg.add_text("!@#$%^&*()_+-=[]{}|;':\",./<>?")
             dpg.add_spacer(height=10)
             
             dpg.add_text("LOREM IPSUM:")
             dpg.add_text("Lorem ipsum dolor sit amet, consectetur adipiscing elit.")
             dpg.add_text("Sed do eiusmod tempor incididunt ut labore et dolore.")

    def _render_sqlite_preview(self, entry: FileEntry, table_name_to_load: str | None = None) -> None:
        """Parse a SQLite database file and display a table's contents."""
        if self._panel_id is None:
            return

        try:
            db_path = entry.full_path.replace("\\", "/")
            conn = sqlite3.connect(f"file:///{db_path}?mode=ro", uri=True, timeout=5)
            cursor = conn.cursor()
            
            # Get list of tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = [row[0] for row in cursor.fetchall()]
            
            if not tables:
                conn.close()
                self._render_table_widget(entry.name, [], [], "No tables found")
                return
                
            table_name = table_name_to_load if table_name_to_load in tables else tables[0]
            
            # Use double quotes for identifier escaping to prevent SQL injection.
            # Identifiers like table names cannot be parameterized in sqlite3.
            safe_table_name = table_name.replace('"', '""')
            
            # Get columns
            cursor.execute(f'PRAGMA table_info("{safe_table_name}");')
            columns = [info[1] for info in cursor.fetchall()]
            
            # Get rows (limited)
            cursor.execute(f'SELECT * FROM "{safe_table_name}" LIMIT {self._TABLE_MAX_ROWS};')
            data_rows = [list(map(str, row)) for row in cursor.fetchall()]
            
            # Count total rows for info
            cursor.execute(f'SELECT COUNT(*) FROM "{safe_table_name}";')
            total_rows = cursor.fetchone()[0]
            
            conn.close()
        except Exception as e:
            _log.exception("Error reading SQLite database %s", entry.full_path)
            self._render_table_widget(entry.name, [], [], f"Error reading database: {e}")
            return

        def _build_db_ui():
            if len(tables) > 1:
                with dpg.group(horizontal=True, parent=self._panel_id):
                    dpg.add_text("Table:", color=[200, 200, 200])
                    dpg.add_combo(
                        items=tables,
                        default_value=table_name,
                        width=200,
                        callback=lambda s, a, u: self._render_sqlite_preview(entry, a)
                    )

        info = f"Table: {table_name} | {total_rows} total rows"
        if total_rows > self._TABLE_MAX_ROWS:
            info += f" (showing first {self._TABLE_MAX_ROWS})"
            
        self._render_table_widget(
            entry.name, columns, data_rows, info,
            ui_builder=_build_db_ui
        )

    # ── PDF preview ─────────────────────────────────────────────

    def _render_pdf_preview(self, entry: FileEntry) -> None:
        """Open a PDF and display its first page in the preview panel."""
        self._show_pdf_from_path(entry.full_path)

    def _show_pdf_from_path(self, path: str) -> None:
        """Core PDF rendering — shared by PDF files and Word conversions."""
        if self._panel_id is None or self._pdf is None:
            return

        # Clear existing content and reset stale widget references
        self._image_cache = None
        self._pdf_image_id = None
        self._pdf_page_label = None
        dpg.delete_item(self._panel_id, children_only=True)
        tex_tag = f"_preview_tex_{self._config_tag}"
        if dpg.does_item_exist(tex_tag):
            dpg.delete_item(tex_tag)

        panel_w, panel_h = dpg.get_item_rect_size(self._panel_id)
        if panel_w <= 0 or panel_h <= 0:
            return

        render_h = max(1, int(panel_h) - self._STATUS_HEIGHT)
        render_w = max(1, int(panel_w))

        if not self._pdf.open(path, render_w, render_h):
            dpg.add_text(
                "Cannot preview this file",
                color=[128, 128, 128],
                parent=self._panel_id,
            )
            return

        page_info = self._pdf.show_page(0)

        self._pdf_image_id = dpg.add_image(
            self._pdf.tex_id,
            parent=self._panel_id,
        )

        self._pdf_page_label = dpg.add_text(
            f"Page {page_info[0] + 1} / {page_info[1]}",
            color=[180, 180, 180],
            parent=self._panel_id,
        )

    # ── Word HTML preview (mammoth + Chrome) ─────────────────────

    def _render_word_html_preview(self, entry: FileEntry) -> None:
        """Render a Word document via mammoth (HTML) + Chrome Headless."""
        if self._panel_id is None or self._html is None:
            return
        self._clear_for_html()

        # Convert .docx -> HTML via mammoth
        try:
            with open(entry.full_path, "rb") as f:
                result = _mammoth.convert_to_html(f)
            docx_html = result.value
        except Exception:
            dpg.add_text(
                "Cannot preview this file",
                color=[128, 128, 128],
                parent=self._panel_id,
            )
            return

        # Wrap in styled HTML document
        html_content = (
            '<!DOCTYPE html><html><head><meta charset="utf-8">'
            f'<style>{_MAMMOTH_CSS}</style>'
            '</head><body>'
            f'<div class="mammoth-wrapper">{docx_html}</div>'
            '</body></html>'
        )

        dims = self._html_panel_size()
        if dims is None:
            return
        render_w, render_h = dims
        if not self._html.open_string(
            html_content, render_w, render_h,
            on_complete=self._on_html_render_done,
            on_resize_complete=self._on_html_resize_done,
        ):
            dpg.add_text(
                "Cannot preview this file",
                color=[128, 128, 128],
                parent=self._panel_id,
            )
            return
        self._show_html_widgets()

    # ── Word preview (python-docx text extraction) ──────────────

    def _render_word_preview(self, entry: FileEntry) -> None:
        """Extract styled text from a .docx file and display in preview panel.

        Paragraphs are color-coded by style: headings in blue tones,
        bold/italic runs inline-colored, list items indented, tables
        rendered with header highlighting.
        """
        if self._panel_id is None:
            return

        try:
            doc = _DocxDocument(entry.full_path)
        except Exception:
            self.clear()
            return

        self._image_cache = None
        dpg.delete_item(self._panel_id, children_only=True)
        tex_tag = f"_preview_tex_{self._config_tag}"
        if dpg.does_item_exist(tex_tag):
            dpg.delete_item(tex_tag)

        dpg.add_text(
            entry.name,
            color=[180, 180, 255],
            parent=self._panel_id,
        )
        dpg.add_separator(parent=self._panel_id)

        heading_colors = {
            "title": [255, 200, 100],
            "subtitle": [220, 190, 140],
            "heading 1": [100, 200, 255],
            "heading 2": [130, 210, 230],
            "heading 3": [160, 200, 210],
            "heading 4": [180, 195, 200],
        }
        bold_color = [255, 255, 200]
        italic_color = [200, 210, 255]
        bold_italic_color = [255, 220, 180]
        normal_color = [210, 210, 210]
        table_header_color = [180, 220, 180]
        table_cell_color = [170, 190, 170]

        # Get blocks in document order (paragraphs + tables)
        try:
            blocks = doc.iter_inner_content()
        except AttributeError:
            blocks = doc.paragraphs

        with dpg.child_window(parent=self._panel_id, height=-1, width=-1):
            for block in blocks:
                # ── Table ──
                if hasattr(block, 'rows'):
                    dpg.add_spacer(height=4)
                    for i, row in enumerate(block.rows):
                        cells = [c.text.strip() for c in row.cells]
                        line = " | ".join(cells)
                        color = table_header_color if i == 0 else table_cell_color
                        dpg.add_text(line, wrap=0, color=color)
                    dpg.add_spacer(height=4)
                    continue

                # ── Paragraph ──
                para = block
                text = para.text
                if not text.strip():
                    dpg.add_spacer(height=4)
                    continue

                style_name = ""
                if para.style and para.style.name:
                    style_name = para.style.name.lower()

                # Heading detection
                heading_color = None
                for key, col in heading_colors.items():
                    if style_name.startswith(key):
                        heading_color = col
                        break

                # List prefix
                prefix = ""
                if "list" in style_name:
                    prefix = "  - "

                # Extra spacing before headings
                if style_name.startswith(("heading", "title")):
                    dpg.add_spacer(height=6)

                if heading_color:
                    dpg.add_text(prefix + text, wrap=0, color=heading_color)
                    continue

                # Check for mixed inline formatting
                runs = list(para.runs)
                has_mixed = (
                    len(runs) > 1
                    and any(r.bold or r.italic for r in runs if r.text)
                )

                if has_mixed:
                    # Per-run coloring in horizontal group
                    with dpg.group(horizontal=True):
                        if prefix:
                            dpg.add_text(prefix, color=normal_color)
                        for run in runs:
                            if not run.text:
                                continue
                            if run.bold and run.italic:
                                rc = bold_italic_color
                            elif run.bold:
                                rc = bold_color
                            elif run.italic:
                                rc = italic_color
                            else:
                                rc = normal_color
                            dpg.add_text(run.text, color=rc)
                else:
                    # Uniform paragraph
                    if runs and all(r.bold for r in runs if r.text.strip()):
                        color = bold_color
                    elif runs and all(r.italic for r in runs if r.text.strip()):
                        color = italic_color
                    else:
                        color = normal_color
                    dpg.add_text(prefix + text, wrap=0, color=color)

    # ── PowerPoint preview (python-pptx text extraction) ──────────

    def _render_pptx_preview(self, entry: FileEntry) -> None:
        """Extract text and images from a .pptx and display styled content."""
        if self._panel_id is None:
            return

        try:
            prs = _Presentation(entry.full_path)
        except Exception:
            self.clear()
            return

        self._image_cache = None
        dpg.delete_item(self._panel_id, children_only=True)
        tex_tag = f"_preview_tex_{self._config_tag}"
        if dpg.does_item_exist(tex_tag):
            dpg.delete_item(tex_tag)

        dpg.add_text(
            entry.name,
            color=[180, 180, 255],
            parent=self._panel_id,
        )
        dpg.add_separator(parent=self._panel_id)

        panel_w, _ = dpg.get_item_rect_size(self._panel_id)
        max_img_w = max(100, int(panel_w) - 40)

        total_slides = len(prs.slides)
        slide_header_color = [100, 200, 255]
        bold_color = [255, 255, 200]
        italic_color = [200, 210, 255]
        bold_italic_color = [255, 220, 180]
        normal_color = [210, 210, 210]
        table_header_color = [180, 220, 180]
        table_cell_color = [170, 190, 170]
        notes_color = [140, 140, 140]
        pptx_tex_idx = 0

        with dpg.child_window(parent=self._panel_id, height=-1, width=-1):
            for slide_idx, slide in enumerate(prs.slides):
                if slide_idx > 0:
                    dpg.add_spacer(height=8)

                dpg.add_text(
                    f"--- Slide {slide_idx + 1} / {total_slides} ---",
                    color=slide_header_color,
                )

                for shape in slide.shapes:
                    # Table
                    if shape.has_table:
                        dpg.add_spacer(height=4)
                        for i, row in enumerate(shape.table.rows):
                            cells = [c.text.strip() for c in row.cells]
                            line = " | ".join(cells)
                            color = (
                                table_header_color if i == 0
                                else table_cell_color
                            )
                            dpg.add_text(line, wrap=0, color=color)
                        dpg.add_spacer(height=4)
                        continue

                    # Image
                    if (shape.shape_type is not None
                            and hasattr(shape, "image")
                            and _PILImage is not None):
                        try:
                            blob = shape.image.blob
                            pil_img = _PILImage.open(io.BytesIO(blob))
                            pil_img = pil_img.convert("RGBA")
                            img_w, img_h = pil_img.size
                            scale = min(max_img_w / img_w, 1.0)
                            disp_w = int(img_w * scale)
                            disp_h = int(img_h * scale)
                            raw = (
                                list(
                                    b / 255.0
                                    for b in pil_img.tobytes()
                                )
                            )
                            pptx_tex_tag = (
                                f"_pptx_tex_{self._config_tag}"
                                f"_{pptx_tex_idx}"
                            )
                            pptx_tex_idx += 1
                            if dpg.does_item_exist(pptx_tex_tag):
                                dpg.delete_item(pptx_tex_tag)
                            with dpg.texture_registry():
                                dpg.add_static_texture(
                                    width=img_w,
                                    height=img_h,
                                    default_value=raw,
                                    tag=pptx_tex_tag,
                                )
                            dpg.add_spacer(height=4)
                            dpg.add_image(
                                pptx_tex_tag,
                                width=disp_w,
                                height=disp_h,
                            )
                            dpg.add_spacer(height=4)
                        except Exception:
                            pass
                        # Also show text if shape has both image and text
                        if not shape.has_text_frame:
                            continue

                    # Text frame
                    if not shape.has_text_frame:
                        continue

                    for para in shape.text_frame.paragraphs:
                        text = para.text
                        if not text.strip():
                            continue

                        level = para.level or 0
                        indent = "  " * level
                        prefix = f"{indent}- " if level > 0 else ""

                        runs = list(para.runs)
                        has_mixed = (
                            len(runs) > 1
                            and any(
                                r.font.bold or r.font.italic
                                for r in runs if r.text
                            )
                        )

                        if has_mixed:
                            with dpg.group(horizontal=True):
                                if prefix:
                                    dpg.add_text(prefix, color=normal_color)
                                for run in runs:
                                    if not run.text:
                                        continue
                                    if run.font.bold and run.font.italic:
                                        rc = bold_italic_color
                                    elif run.font.bold:
                                        rc = bold_color
                                    elif run.font.italic:
                                        rc = italic_color
                                    else:
                                        rc = normal_color
                                    dpg.add_text(run.text, color=rc)
                        else:
                            if runs and all(
                                r.font.bold for r in runs if r.text.strip()
                            ):
                                color = bold_color
                            elif runs and all(
                                r.font.italic for r in runs if r.text.strip()
                            ):
                                color = italic_color
                            else:
                                color = normal_color
                            dpg.add_text(
                                prefix + text, wrap=0, color=color,
                            )

                # Speaker notes
                try:
                    notes_slide = slide.notes_slide
                    if notes_slide and notes_slide.notes_text_frame:
                        notes_text = notes_slide.notes_text_frame.text.strip()
                        if notes_text:
                            dpg.add_spacer(height=2)
                            dpg.add_text(
                                f"[Notes: {notes_text}]",
                                wrap=0,
                                color=notes_color,
                            )
                except Exception:
                    pass

    # ── Mouse wheel (HTML scroll / PDF pages) ─────────────────

    def on_mouse_wheel(self, sender, app_data, user_data) -> None:
        """Handle mouse wheel scroll for HTML scrolling and PDF page navigation."""
        if self._panel_id is None or not self._visible:
            return
        if self._is_active_fn and not self._is_active_fn():
            return
        if not dpg.is_item_hovered(self._panel_id):
            return

        # HTML scroll
        if self._html is not None and self._html.is_open:
            self._html.on_scroll(app_data)
            if (self._html_status_label is not None
                    and dpg.does_item_exist(self._html_status_label)):
                dpg.set_value(
                    self._html_status_label, self._html.status_text,
                )
            return

        # PDF page navigation
        if self._pdf is None or not self._pdf.is_open:
            return

        if app_data > 0:
            page_info = self._pdf.prev_page()
        else:
            page_info = self._pdf.next_page()

        if (self._pdf_page_label is not None
                and dpg.does_item_exist(self._pdf_page_label)):
            dpg.set_value(
                self._pdf_page_label,
                f"Page {page_info[0] + 1} / {page_info[1]}",
            )

    # ── Image layout ───────────────────────────────────────────

    def layout(self) -> None:
        """Render cached image data in the preview panel.

        Scales the image to fit the panel while preserving aspect ratio
        (never upscales beyond 1:1), then centres it both vertically and
        horizontally with padding.
        """
        if self._panel_id is None or self._image_cache is None:
            return

        img_w, img_h, data = self._image_cache

        panel_w, panel_h = dpg.get_item_rect_size(self._panel_id)
        if panel_w <= 0 or panel_h <= 0 or img_w <= 0 or img_h <= 0:
            return

        self._last_size = (panel_w, panel_h)

        padding = 16
        avail_w = panel_w - padding
        avail_h = panel_h - padding
        scale = min(avail_w / img_w, avail_h / img_h, 1.0)
        display_w = int(img_w * scale)
        display_h = int(img_h * scale)

        dpg.delete_item(self._panel_id, children_only=True)
        tex_tag = f"_preview_tex_{self._config_tag}"
        if dpg.does_item_exist(tex_tag):
            dpg.delete_item(tex_tag)

        with dpg.texture_registry():
            dpg.add_static_texture(
                width=img_w, height=img_h, default_value=data, tag=tex_tag,
            )

        v_offset = max(0, (avail_h - display_h) // 2)
        h_offset = max(0, (avail_w - display_w) // 2)

        if v_offset > 0:
            dpg.add_spacer(height=v_offset, parent=self._panel_id)
        with dpg.group(horizontal=True, parent=self._panel_id):
            if h_offset > 0:
                dpg.add_spacer(width=h_offset)
            dpg.add_image(tex_tag, width=display_w, height=display_h)

    # ── Resize handler ─────────────────────────────────────────

    def on_resize(self, sender, app_data, user_data) -> None:
        """Re-layout preview content when the panel size changes."""
        if self._panel_id is None:
            return
        if self._is_active_fn and not self._is_active_fn():
            return
        if not self._visible:
            return
        panel_w, panel_h = dpg.get_item_rect_size(self._panel_id)
        if (panel_w, panel_h) == self._last_size:
            return
        self._last_size = (panel_w, panel_h)

        # HTML resize path (fully debounced — _on_html_resize_done rebuilds)
        if self._html is not None and self._html.is_open:
            render_h = max(1, int(panel_h) - self._STATUS_HEIGHT)
            render_w = max(1, int(panel_w))
            self._html.on_resize(render_w, render_h)
            return

        # PDF resize path
        if self._pdf is not None and self._pdf.is_open:
            render_h = max(1, int(panel_h) - self._STATUS_HEIGHT)
            render_w = max(1, int(panel_w))
            page_info = self._pdf.on_resize(render_w, render_h)
            if page_info is None:
                return  # size unchanged, existing image widget is fine
            # Rebuild panel — texture was recreated so old image widget
            # references a stale DPG internal texture ID.
            dpg.delete_item(self._panel_id, children_only=True)
            self._pdf_image_id = dpg.add_image(
                self._pdf.tex_id,
                parent=self._panel_id,
            )
            self._pdf_page_label = dpg.add_text(
                f"Page {page_info[0] + 1} / {page_info[1]}",
                color=[180, 180, 180],
                parent=self._panel_id,
            )
            return

        # Image resize path
        if self._image_cache is not None:
            self.layout()

    # ── Destroy ────────────────────────────────────────────────

    def destroy(self) -> None:
        """Release DPG resources owned by the preview panel."""
        if self._pdf is not None:
            self._pdf.close()
        self._pdf_image_id = None
        self._pdf_page_label = None
        if self._html is not None:
            self._html.close()
        self._html_image_id = None
        self._html_status_label = None
        save_id = f"_fd_config_{self._config_tag}"
        if dpg.does_item_exist(save_id):
            dpg.delete_item(save_id)
        
        if self._temp_font is not None:
            if dpg.does_item_exist(self._temp_font):
                dpg.delete_item(self._temp_font)
            self._temp_font = None

        self._image_cache = None
