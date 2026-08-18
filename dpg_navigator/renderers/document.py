"""Document preview renderer for HTML, Markdown, PDF, Word, and PPTX."""

from __future__ import annotations  # PEP 604/585 in signatures need this on py3.8/3.9

import array
import io
import logging
from typing import Callable

import dearpygui.dearpygui as dpg  # type: ignore[import-untyped]

try:
    import bleach
except ImportError:
    bleach = None  # type: ignore[assignment]

from .._availability import (
    _DocxDocument,
    _mammoth,
    _markdown,
    _np,
    _PILImage,
    _Presentation,
)
from .._filesystem import DirectoryLister
from .._html import HTMLRenderer, chrome_available
from .._pdf import PDFRenderer
from .._preview_presentation import PresentationPreviewError, load_presentation
from .._preview_word import WordPreviewError, WordTable, load_word_document
from .._types import FileEntry
from ._base import BaseRenderer, PreviewContext

_log = logging.getLogger(__name__)

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


class DocumentRenderer(BaseRenderer):
    """Render HTML, Markdown, PDF, Word, and PowerPoint previews."""

    _TEXT_PREVIEW_MAX_SIZE: int = 256 * 1024
    """Maximum file size in bytes to attempt text preview (256 KB)."""

    _STATUS_HEIGHT: int = 42
    """Height in pixels reserved for status/page labels below preview."""

    def __init__(self, load_text_content_cb: Callable[[str, int], tuple[str | None, bool]]):
        self._load_text_content = load_text_content_cb
        self._current_entry: FileEntry | None = None
        self._ctx: PreviewContext | None = None

        # Sub-renderers (delegates) — created lazily at first use, once the
        # render-time config_tag is available on the context.
        self._html: HTMLRenderer | None = None
        self._pdf: PDFRenderer | None = None

        # Widget references owned by this renderer
        self._html_image_id: int | str | None = None
        self._html_status_label: int | str | None = None
        self._pdf_image_id: int | str | None = None
        self._pdf_page_label: int | str | None = None

    def render(self, entry: FileEntry, ctx: PreviewContext) -> None:
        """Render a document using the backend selected by its extension."""
        self._ctx = ctx
        self._current_entry = entry
        ext = entry.ext
        if ext in (".html", ".htm"):
            self._render_html_preview(entry)
        elif ext == ".md":
            self._render_markdown_preview(entry)
        elif ext == ".pdf":
            self._render_pdf_preview(entry)
        elif ext in (".docx", ".doc"):
            if self._ctx.capabilities.mammoth and chrome_available():
                self._render_word_html_preview(entry)
            else:
                self._render_word_preview(entry)
        elif ext == ".pptx":
            self._render_pptx_preview(entry)
        else:
            ctx.show_error("Unsupported document", f"{ext} is not supported")

    def clear(self) -> None:
        """Close active heavy backends and clear the preview state."""
        if self._html is not None:
            self._html.close()
        if self._pdf is not None:
            self._pdf.close()
        self._clear_for_html()
        self._html = None
        self._pdf = None
        self._current_entry = None
        self._ctx = None

    # ── HTML preview helpers ──────────────────────────────────

    def _clear_for_html(self) -> None:
        """Clear panel and reset HTML widget refs for HTML-based previews."""
        self._html_image_id = None
        self._html_status_label = None
        if self._ctx is None or self._ctx.panel_id is None:
            return
        self._ctx.image_cache = None
        dpg.delete_item(self._ctx.panel_id, children_only=True)
        tex_tag = f"_preview_tex_{self._ctx.config_tag}"
        if dpg.does_item_exist(tex_tag):
            dpg.delete_item(tex_tag)

    def _html_panel_size(self) -> tuple[int, int] | None:
        """Return (render_w, render_h) or None if panel is too small."""
        if self._ctx is None or self._ctx.panel_id is None:
            return None
        panel_w, panel_h = dpg.get_item_rect_size(self._ctx.panel_id)
        if panel_w <= 0 or panel_h <= 0:
            return None
        render_h = max(1, int(panel_h) - self._STATUS_HEIGHT)
        render_w = max(1, int(panel_w))
        return render_w, render_h

    def _show_html_widgets(self) -> None:
        """Create image + status label widgets for current HTML render."""
        if self._ctx is None or self._ctx.panel_id is None or self._html is None:
            return
        self._html_image_id = dpg.add_image(
            self._html.tex_id,
            parent=self._ctx.panel_id,
        )
        self._html_status_label = dpg.add_text(
            self._html.status_text,
            color=[180, 180, 180],
            parent=self._ctx.panel_id,
        )

    def _render_text_preview(self, entry: FileEntry) -> None:
        """Fallback plain-text rendering when the HTML backend is unavailable."""
        if self._ctx is None or self._ctx.panel_id is None:
            return

        text, is_bin = self._load_text_content(entry.full_path, 0)

        self._ctx.image_cache = None
        dpg.delete_item(self._ctx.panel_id, children_only=True)
        tex_tag = f"_preview_tex_{self._ctx.config_tag}"
        if dpg.does_item_exist(tex_tag):
            dpg.delete_item(tex_tag)

        if is_bin:
            dpg.add_text(
                f"Binary file: {entry.name}",
                color=[128, 128, 128],
                parent=self._ctx.panel_id,
            )
            dpg.add_text(
                "(No text preview available)",
                color=[100, 100, 100],
                parent=self._ctx.panel_id,
            )
            return
        if text is None:
            self.clear()
            return
        if not text.strip():
            text = "(No text content or only whitespace in this fragment)"

        dpg.add_text(
            entry.name,
            color=[180, 180, 255],
            parent=self._ctx.panel_id,
        )
        dpg.add_separator(parent=self._ctx.panel_id)
        with dpg.child_window(parent=self._ctx.panel_id, height=-1, width=-1):
            dpg.add_text(text, wrap=0)

    def _render_html_preview(self, entry: FileEntry) -> None:
        """Open an HTML file and start background Chrome Headless rendering."""
        if self._ctx is None or self._ctx.panel_id is None:
            return
        if self._html is None:
            self._html = HTMLRenderer(self._ctx.config_tag)
        if not chrome_available():
            # HTML backend unavailable — either the Python packages are missing
            # or no Chrome/Chromium binary is resolvable. Routing always picks
            # HTML for .html/.htm, so degrade to raw-text rendering instead of
            # leaving the previous preview on screen (or hanging on a render).
            self._render_text_preview(entry)
            return
        self._clear_for_html()
        dims = self._html_panel_size()
        if dims is None:
            return
        render_w, render_h = dims
        if not self._html.open(
            entry.full_path,
            render_w,
            render_h,
            on_complete=self._on_html_render_done,
            on_resize_complete=self._on_html_resize_done,
        ):
            dpg.add_text(
                "Cannot preview this file",
                color=[128, 128, 128],
                parent=self._ctx.panel_id,
            )
            return
        self._show_html_widgets()

    def _on_html_render_done(self) -> None:
        """Called by HTMLRenderer inside dpg.mutex() when render completes."""
        if (
            self._html_status_label is not None
            and dpg.does_item_exist(self._html_status_label)
            and self._html is not None
        ):
            dpg.set_value(self._html_status_label, self._html.status_text)

    def _on_html_resize_done(self) -> None:
        """Called inside dpg.mutex() when debounced resize recreates texture."""
        if self._ctx is None or self._ctx.panel_id is None or self._html is None:
            return
        dpg.delete_item(self._ctx.panel_id, children_only=True)
        self._show_html_widgets()

    def _render_markdown_preview(self, entry: FileEntry) -> None:
        """Render a Markdown file via markdown lib + Chrome Headless."""
        if self._ctx is None or self._ctx.panel_id is None:
            return
        if self._html is None:
            self._html = HTMLRenderer(self._ctx.config_tag)
        self._clear_for_html()

        # Read and convert Markdown -> HTML
        md_text, is_bin = self._load_text_content(entry.full_path, 0)
        if is_bin:
            dpg.add_text(
                f"Binary file: {entry.name}",
                color=[128, 128, 128],
                parent=self._ctx.panel_id,
            )
            return
        if md_text is None:
            self.clear()
            return

        try:
            md_html_raw = _markdown.markdown(
                md_text,
                extensions=["tables", "fenced_code"],
            )
            if bleach is not None:
                md_html = bleach.clean(
                    md_html_raw,
                    tags=[
                        "h1",
                        "h2",
                        "h3",
                        "h4",
                        "h5",
                        "h6",
                        "p",
                        "a",
                        "ul",
                        "ol",
                        "li",
                        "strong",
                        "em",
                        "code",
                        "pre",
                        "blockquote",
                        "table",
                        "thead",
                        "tbody",
                        "tr",
                        "th",
                        "td",
                        "br",
                        "hr",
                        "div",
                        "span",
                        "img",
                    ],
                )
            else:
                md_html = md_html_raw
        except Exception as e:
            self._ctx.show_error("Preview failed", str(e))
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
                parent=self._ctx.panel_id,
            )

        if not self._html.open_string(
            full_html,
            render_w,
            render_h,
            on_complete=self._on_html_render_done,
            on_resize_complete=self._on_html_resize_done,
        ):
            self.clear()
            return
        self._show_html_widgets()

    def _render_pdf_preview(self, entry: FileEntry) -> None:
        """Open a PDF and display its first page in the preview panel."""
        self._show_pdf_from_path(entry.full_path)

    def on_resize(self, sender, app_data, user_data) -> None:
        """Re-layout the active HTML or PDF preview after a panel resize."""
        dims = self._html_panel_size()
        if dims is None:
            return
        render_w, render_h = dims

        if self._html is not None and self._html.is_open:
            self._html.on_resize(render_w, render_h)
            return

        if self._pdf is None or not self._pdf.is_open:
            return
        page_info = self._pdf.on_resize(render_w, render_h)
        if page_info is None or self._ctx is None or self._ctx.panel_id is None:
            return

        dpg.delete_item(self._ctx.panel_id, children_only=True)
        if self._pdf.tex_id is not None:
            self._pdf_image_id = dpg.add_image(
                self._pdf.tex_id,
                parent=self._ctx.panel_id,
            )
        self._pdf_page_label = dpg.add_text(
            f"Page {page_info[0] + 1} / {page_info[1]}",
            color=[180, 180, 180],
            parent=self._ctx.panel_id,
        )

    def on_mouse_wheel(self, sender, app_data, user_data) -> None:
        """Scroll HTML previews or navigate PDF pages with the mouse wheel."""
        try:
            delta = float(app_data)
        except (TypeError, ValueError):
            return
        if delta == 0:
            return

        if self._html is not None and self._html.is_open:
            self._html.on_scroll(delta)
            if self._html_status_label is not None and dpg.does_item_exist(self._html_status_label):
                dpg.set_value(self._html_status_label, self._html.status_text)
            return

        if self._pdf is None or not self._pdf.is_open:
            return
        page_info = self._pdf.prev_page() if delta > 0 else self._pdf.next_page()
        if self._pdf_page_label is not None and dpg.does_item_exist(self._pdf_page_label):
            dpg.set_value(
                self._pdf_page_label,
                f"Page {page_info[0] + 1} / {page_info[1]}",
            )

    def _show_pdf_from_path(self, path: str) -> None:
        """Core PDF rendering — shared by PDF files and Word conversions."""
        if self._ctx is None or self._ctx.panel_id is None:
            return
        if self._pdf is None:
            self._pdf = PDFRenderer(self._ctx.config_tag)

        # Clear existing content and reset stale widget references
        self._ctx.image_cache = None
        self._pdf_image_id = None
        self._pdf_page_label = None
        dpg.delete_item(self._ctx.panel_id, children_only=True)
        tex_tag = f"_preview_tex_{self._ctx.config_tag}"
        if dpg.does_item_exist(tex_tag):
            dpg.delete_item(tex_tag)

        panel_w, panel_h = dpg.get_item_rect_size(self._ctx.panel_id)
        if panel_w <= 0 or panel_h <= 0:
            return

        render_h = max(1, int(panel_h) - self._STATUS_HEIGHT)
        render_w = max(1, int(panel_w))

        if not self._pdf.open(path, render_w, render_h):
            dpg.add_text(
                "Cannot preview this file",
                color=[128, 128, 128],
                parent=self._ctx.panel_id,
            )
            return

        page_info = self._pdf.show_page(0)

        self._pdf_image_id = dpg.add_image(
            self._pdf.tex_id,
            parent=self._ctx.panel_id,
        )

        self._pdf_page_label = dpg.add_text(
            f"Page {page_info[0] + 1} / {page_info[1]}",
            color=[180, 180, 180],
            parent=self._ctx.panel_id,
        )

    def _render_word_html_preview(self, entry: FileEntry) -> None:
        """Render a Word document via mammoth (HTML) + Chrome Headless."""
        if self._ctx is None or self._ctx.panel_id is None:
            return
        if self._html is None:
            self._html = HTMLRenderer(self._ctx.config_tag)
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
                parent=self._ctx.panel_id,
            )
            return

        # Wrap in styled HTML document
        html_content = (
            '<!DOCTYPE html><html><head><meta charset="utf-8">'
            f"<style>{_MAMMOTH_CSS}</style>"
            "</head><body>"
            f'<div class="mammoth-wrapper">{docx_html}</div>'
            "</body></html>"
        )

        dims = self._html_panel_size()
        if dims is None:
            return
        render_w, render_h = dims
        if not self._html.open_string(
            html_content,
            render_w,
            render_h,
            on_complete=self._on_html_render_done,
            on_resize_complete=self._on_html_resize_done,
        ):
            dpg.add_text(
                "Cannot preview this file",
                color=[128, 128, 128],
                parent=self._ctx.panel_id,
            )
            return
        self._show_html_widgets()

    def _render_word_preview(self, entry: FileEntry) -> None:
        """Extract styled text from a .docx file and display in preview panel.

        Paragraphs are color-coded by style: headings in blue tones,
        bold/italic runs inline-colored, list items indented, tables
        rendered with header highlighting.
        """
        if self._ctx is None or self._ctx.panel_id is None:
            return

        try:
            document = load_word_document(
                entry.full_path,
                document_loader=_DocxDocument,
            )
        except WordPreviewError:
            self.clear()
            return

        self._ctx.image_cache = None
        dpg.delete_item(self._ctx.panel_id, children_only=True)
        tex_tag = f"_preview_tex_{self._ctx.config_tag}"
        if dpg.does_item_exist(tex_tag):
            dpg.delete_item(tex_tag)

        dpg.add_text(
            entry.name,
            color=[180, 180, 255],
            parent=self._ctx.panel_id,
        )
        dpg.add_separator(parent=self._ctx.panel_id)

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

        with dpg.child_window(parent=self._ctx.panel_id, height=-1, width=-1):
            for block in document.blocks:
                # ── Table ──
                if isinstance(block, WordTable):
                    dpg.add_spacer(height=4)
                    for i, row in enumerate(block.rows):
                        line = " | ".join(row)
                        color = table_header_color if i == 0 else table_cell_color
                        dpg.add_text(line, wrap=0, color=color)
                    dpg.add_spacer(height=4)
                    continue

                # ── Paragraph ──
                text = block.text
                if not text.strip():
                    dpg.add_spacer(height=4)
                    continue

                style_name = block.style_name

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
                runs = block.runs
                has_mixed = len(runs) > 1 and any(r.bold or r.italic for r in runs if r.text)

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

    def _render_pptx_preview(self, entry: FileEntry) -> None:
        """Extract text and images from a .pptx and display styled content."""
        if self._ctx is None or self._ctx.panel_id is None:
            return

        try:
            presentation = load_presentation(
                entry.full_path,
                presentation_loader=_Presentation,
            )
        except PresentationPreviewError:
            self.clear()
            return

        self._ctx.image_cache = None

        dpg.delete_item(self._ctx.panel_id, children_only=True)
        tex_tag = f"_preview_tex_{self._ctx.config_tag}"
        if dpg.does_item_exist(tex_tag):
            dpg.delete_item(tex_tag)

        dpg.add_text(
            entry.name,
            color=[180, 180, 255],
            parent=self._ctx.panel_id,
        )
        dpg.add_separator(parent=self._ctx.panel_id)

        panel_w, _ = dpg.get_item_rect_size(self._ctx.panel_id)
        max_img_w = max(100, int(panel_w) - 40)

        total_slides = len(presentation.slides)
        slide_header_color = [100, 200, 255]
        bold_color = [255, 255, 200]
        italic_color = [200, 210, 255]
        bold_italic_color = [255, 220, 180]
        normal_color = [210, 210, 210]
        table_header_color = [180, 220, 180]
        table_cell_color = [170, 190, 170]
        notes_color = [140, 140, 140]
        pptx_tex_idx = 0

        with dpg.child_window(parent=self._ctx.panel_id, height=-1, width=-1):
            for slide_idx, slide in enumerate(presentation.slides):
                if slide_idx > 0:
                    dpg.add_spacer(height=8)

                dpg.add_text(
                    f"--- Slide {slide_idx + 1} / {total_slides} ---",
                    color=slide_header_color,
                )

                for shape in slide.shapes:
                    # Table
                    if shape.table is not None:
                        dpg.add_spacer(height=4)
                        for i, row in enumerate(shape.table.rows):
                            line = " | ".join(row)
                            color = table_header_color if i == 0 else table_cell_color
                            dpg.add_text(line, wrap=0, color=color)
                        dpg.add_spacer(height=4)
                        continue

                    # Image
                    if shape.image_blob is not None and _PILImage is not None:
                        try:
                            pil_img = _PILImage.open(io.BytesIO(shape.image_blob))
                            img_rgba = pil_img.convert("RGBA")
                            pil_img.close()
                            img_w, img_h = img_rgba.size
                            scale = min(max_img_w / img_w, 1.0)
                            disp_w = int(img_w * scale)
                            disp_h = int(img_h * scale)
                            if _np is not None:
                                arr = _np.frombuffer(img_rgba.tobytes(), dtype=_np.uint8).astype(
                                    _np.float32
                                ) / _np.float32(255.0)
                                raw = array.array("f", arr.tobytes())
                            else:
                                raw = array.array(
                                    "f",
                                    (b / 255.0 for b in img_rgba.tobytes()),
                                )
                            img_rgba.close()
                            pptx_tex_tag = f"_pptx_tex_{self._ctx.config_tag}_{pptx_tex_idx}"
                            pptx_tex_idx += 1
                            self._ctx.pptx_texture_tags.append(pptx_tex_tag)
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
                            _log.debug("Failed to render PPTX inline image", exc_info=True)
                        # Also show text if shape has both image and text
                        if not shape.paragraphs:
                            continue

                    # Text frame
                    if not shape.paragraphs:
                        continue

                    for paragraph in shape.paragraphs:
                        text = paragraph.text
                        if not text.strip():
                            continue

                        level = paragraph.level
                        indent = "  " * level
                        prefix = f"{indent}- " if level > 0 else ""

                        runs = paragraph.runs
                        has_mixed = len(runs) > 1 and any(r.bold or r.italic for r in runs if r.text)

                        if has_mixed:
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
                            if runs and all(r.bold for r in runs if r.text.strip()):
                                color = bold_color
                            elif runs and all(r.italic for r in runs if r.text.strip()):
                                color = italic_color
                            else:
                                color = normal_color
                            dpg.add_text(
                                prefix + text,
                                wrap=0,
                                color=color,
                            )

                # Speaker notes
                if slide.notes:
                    dpg.add_spacer(height=2)
                    dpg.add_text(
                        f"[Notes: {slide.notes}]",
                        wrap=0,
                        color=notes_color,
                    )
