"""Document preview renderer for HTML, Markdown, PDF, Word, and PPTX."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import dearpygui.dearpygui as dpg  # type: ignore[import-untyped]

from .._availability import (
    _DocxDocument,
    _mammoth,
    _markdown,
    _PILImage,
    _Presentation,
)
from .._filesystem import DirectoryLister
from .._html import HTMLRenderer, PreparedHTML, chrome_available, prepare_html_file, prepare_html_string
from .._optional import require_optional
from .._pdf import PDFRenderer
from .._preview_limits import (
    PREVIEW_TEXT_CHUNK_BYTES,
    decode_preview_rgba_bytes,
    ooxml_exceeds_preview_limit,
)
from .._preview_presentation import PresentationDocument, PresentationPreviewError, load_presentation
from .._preview_word import WordDocument, WordPreviewError, WordTable, load_word_document
from .._types import FileEntry
from ._base import BackgroundRenderer, PreviewContext, PreviewFinish, PreviewJob, error_finish, run_preview_job

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


class DocumentRenderer(BackgroundRenderer):
    """Render HTML, Markdown, PDF, Word, and PowerPoint previews."""

    _TEXT_PREVIEW_MAX_SIZE: int = PREVIEW_TEXT_CHUNK_BYTES
    """Maximum file size in bytes to attempt text preview (256 KB)."""

    _STATUS_HEIGHT: int = 42
    """Height in pixels reserved for status/page labels below preview."""

    def __init__(self, load_text_content_cb: Callable[[str, int], tuple[str | None, bool]]) -> None:
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
        run_preview_job(self.prepare(entry, ctx))

    def prepare(self, entry: FileEntry, ctx: PreviewContext) -> PreviewJob:
        """Return the worker job for *entry* (DearPyGui thread).

        Reading, Markdown/mammoth conversion, HTML sanitizing and PPTX image
        decoding run in the job. PDF opens in the finish step: pypdfium2
        renders straight into a DearPyGui texture.
        """
        ext = entry.ext
        if ext in (".html", ".htm"):
            if not chrome_available():
                # HTML backend unavailable — either the Python packages are missing
                # or no Chrome/Chromium binary is resolvable. Routing always picks
                # HTML for .html/.htm, so degrade to raw-text rendering instead of
                # leaving the previous preview on screen (or hanging on a render).
                return self._text_job(entry, ctx)
            trusted = ctx.trusted_html_preview
            return lambda: self._load_html(entry, ctx, trusted)
        if ext in (".md", ".markdown"):
            if not chrome_available():
                return self._text_job(entry, ctx)
            return lambda: self._load_markdown(entry, ctx)
        if ext == ".pdf":
            return lambda: lambda: self._show_pdf(entry, ctx)
        if ext in (".docx", ".doc"):
            if ctx.capabilities.mammoth and chrome_available():
                return lambda: self._load_word_html(entry, ctx)
            return lambda: self._load_word_text(entry, ctx)
        if ext == ".pptx":
            panel_w = 0
            if ctx.panel_id is not None:
                panel_w, _ = dpg.get_item_rect_size(ctx.panel_id)
            max_img_w = max(100, int(panel_w) - 40)
            return lambda: self._load_pptx(entry, ctx, max_img_w)
        return lambda: lambda: ctx.show_error("Unsupported document", f"{ext} is not supported")

    def _bind(self, entry: FileEntry, ctx: PreviewContext) -> bool:
        """Attach a finish step to *ctx*. False when there is no panel."""
        self._ctx = ctx
        self._current_entry = entry
        return ctx.panel_id is not None

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

    # ── Plain-text fallback ───────────────────────────────────

    def _text_job(self, entry: FileEntry, ctx: PreviewContext) -> PreviewJob:
        """Job for the plain-text fallback when the HTML backend is unavailable."""

        def job() -> PreviewFinish:
            text, is_bin = self._load_text_content(entry.full_path, 0)
            return lambda: self._show_text(entry, ctx, text, is_bin)

        return job

    def _show_text(self, entry: FileEntry, ctx: PreviewContext, text: str | None, is_bin: bool) -> None:
        """Finish: show the raw file text (or a binary notice)."""
        if not self._bind(entry, ctx):
            return

        ctx.image_cache = None
        dpg.delete_item(ctx.panel_id, children_only=True)
        tex_tag = f"_preview_tex_{ctx.config_tag}"
        if dpg.does_item_exist(tex_tag):
            dpg.delete_item(tex_tag)

        if is_bin:
            dpg.add_text(
                f"Binary file: {entry.name}",
                color=[128, 128, 128],
                parent=ctx.panel_id,
            )
            dpg.add_text(
                "(No text preview available)",
                color=[100, 100, 100],
                parent=ctx.panel_id,
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
            parent=ctx.panel_id,
        )
        dpg.add_separator(parent=ctx.panel_id)
        with dpg.child_window(parent=ctx.panel_id, height=-1, width=-1):
            dpg.add_text(text, wrap=0)

    # ── HTML, Markdown, and mammoth Word ──────────────────────

    def _load_html(self, entry: FileEntry, ctx: PreviewContext, trusted: bool) -> PreviewFinish:
        """Worker: read and sanitize an HTML file (or keep it raw when trusted)."""
        prepared = prepare_html_file(entry.full_path, trusted=trusted)
        return lambda: self._show_prepared_html(entry, ctx, prepared)

    def _show_prepared_html(
        self,
        entry: FileEntry,
        ctx: PreviewContext,
        prepared: PreparedHTML,
        *,
        header: str = "",
    ) -> None:
        """Finish: start the Chrome Headless render of a prepared document."""
        if not self._bind(entry, ctx):
            return
        if self._html is None:
            self._html = HTMLRenderer(ctx.config_tag)
        self._clear_for_html()
        dims = self._html_panel_size()
        if dims is None:
            return
        render_w, render_h = dims
        if header:
            dpg.add_text(header, color=[180, 180, 255], parent=ctx.panel_id)
        if not self._html.open_prepared(
            prepared,
            render_w,
            render_h,
            on_complete=self._on_html_render_done,
            on_resize_complete=self._on_html_resize_done,
        ):
            dpg.add_text(
                "Cannot preview this file",
                color=[128, 128, 128],
                parent=ctx.panel_id,
            )
            if prepared.error:
                dpg.add_text(prepared.error, color=[128, 128, 128], parent=ctx.panel_id)
            return
        self._show_html_widgets()

    def _show_cannot_preview(
        self, entry: FileEntry, ctx: PreviewContext, message: str = "Cannot preview this file"
    ) -> None:
        """Finish: replace the panel content with a grey notice."""
        if not self._bind(entry, ctx):
            return
        self._clear_for_html()
        dpg.add_text(message, color=[128, 128, 128], parent=ctx.panel_id)

    def _on_html_render_done(self) -> None:
        """Called by HTMLRenderer from its mutex-serialized frame poll."""
        if (
            self._html_status_label is not None
            and dpg.does_item_exist(self._html_status_label)
            and self._html is not None
        ):
            dpg.set_value(self._html_status_label, self._html.status_text)

    def _on_html_resize_done(self) -> None:
        """Called from the frame poll when a resize recreates the texture."""
        if self._ctx is None or self._ctx.panel_id is None or self._html is None:
            return
        dpg.delete_item(self._ctx.panel_id, children_only=True)
        self._show_html_widgets()

    def _load_markdown(self, entry: FileEntry, ctx: PreviewContext) -> PreviewFinish:
        """Worker: read Markdown, convert it to HTML, and sanitize the result."""
        md_text, is_bin = self._load_text_content(entry.full_path, 0)
        if is_bin:
            return lambda: self._show_cannot_preview(entry, ctx, f"Binary file: {entry.name}")
        if md_text is None:
            return error_finish(ctx, "Preview failed", "Cannot read file")

        try:
            md = require_optional(_markdown, "markdown")
            md_html_raw = md.markdown(
                md_text,
                extensions=["tables", "fenced_code"],
            )
        except Exception as e:
            message = str(e)
            return lambda: ctx.show_error("Preview failed", message)

        # Add truncation label if needed
        header = ""
        if entry.size_bytes is not None and entry.size_bytes > self._TEXT_PREVIEW_MAX_SIZE:
            limit_str = DirectoryLister.format_size(self._TEXT_PREVIEW_MAX_SIZE)
            size_str = DirectoryLister.format_size(entry.size_bytes)
            header = f"{entry.name} (Partial: first {limit_str} of {size_str})"

        prepared = prepare_html_string(md_html_raw, css=_MARKDOWN_CSS, wrapper_class="md-wrapper")
        return lambda: self._show_prepared_html(entry, ctx, prepared, header=header)

    def _show_pdf(self, entry: FileEntry, ctx: PreviewContext) -> None:
        """Finish: open a PDF and display its first page in the preview panel."""
        if self._bind(entry, ctx):
            self._show_pdf_from_path(entry.full_path)

    def on_resize(self, sender: Any, app_data: Any, user_data: Any) -> None:
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

    def on_mouse_wheel(self, sender: Any, app_data: Any, user_data: Any) -> None:
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

    def _load_word_html(self, entry: FileEntry, ctx: PreviewContext) -> PreviewFinish:
        """Worker: convert a Word document with mammoth and sanitize the HTML."""
        if ooxml_exceeds_preview_limit(entry.full_path):
            return lambda: self._show_cannot_preview(entry, ctx)

        # Convert .docx -> HTML via mammoth
        try:
            with open(entry.full_path, "rb") as f:
                mammoth = require_optional(_mammoth, "mammoth")
                result = mammoth.convert_to_html(f)
            docx_html = result.value
        except Exception:
            return lambda: self._show_cannot_preview(entry, ctx)

        prepared = prepare_html_string(docx_html, css=_MAMMOTH_CSS, wrapper_class="mammoth-wrapper")
        return lambda: self._show_prepared_html(entry, ctx, prepared)

    def _load_word_text(self, entry: FileEntry, ctx: PreviewContext) -> PreviewFinish:
        """Worker: extract styled paragraphs and tables with python-docx."""
        try:
            document = load_word_document(
                entry.full_path,
                document_loader=_DocxDocument,
            )
        except WordPreviewError as e:
            return error_finish(ctx, "Preview failed", str(e) or "Cannot read document")
        return lambda: self._show_word_text(entry, ctx, document)

    def _show_word_text(self, entry: FileEntry, ctx: PreviewContext, document: WordDocument) -> None:
        """Display styled text extracted from a .docx file.

        Paragraphs are color-coded by style: headings in blue tones,
        bold/italic runs inline-colored, list items indented, tables
        rendered with header highlighting.
        """
        if not self._bind(entry, ctx) or self._ctx is None:
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

    def _load_pptx(self, entry: FileEntry, ctx: PreviewContext, max_img_w: int) -> PreviewFinish:
        """Worker: extract slides and decode images at the width they are shown."""
        try:
            presentation = load_presentation(
                entry.full_path,
                presentation_loader=_Presentation,
            )
        except PresentationPreviewError as e:
            return error_finish(ctx, "Preview failed", str(e) or "Cannot read presentation")

        images: dict[tuple[int, int], tuple[int, int, Any]] = {}
        if _PILImage is not None:
            for slide_idx, slide in enumerate(presentation.slides):
                for shape_idx, shape in enumerate(slide.shapes):
                    if shape.image_blob is None:
                        continue
                    try:
                        images[(slide_idx, shape_idx)] = decode_preview_rgba_bytes(
                            shape.image_blob,
                            max_width=max_img_w,
                        )
                    except Exception:
                        _log.debug("Failed to decode PPTX inline image", exc_info=True)
        return lambda: self._show_pptx(entry, ctx, presentation, images, max_img_w)

    def _show_pptx(
        self,
        entry: FileEntry,
        ctx: PreviewContext,
        presentation: PresentationDocument,
        images: dict[tuple[int, int], tuple[int, int, Any]],
        max_img_w: int,
    ) -> None:
        """Display text and pre-decoded images from a .pptx."""
        if not self._bind(entry, ctx) or self._ctx is None:
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

                for shape_idx, shape in enumerate(slide.shapes):
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
                    if shape.image_blob is not None:
                        decoded = images.get((slide_idx, shape_idx))
                        if decoded is not None:
                            try:
                                img_w, img_h, raw = decoded
                                scale = min(max_img_w / img_w, 1.0) if img_w else 1.0
                                disp_w = max(1, int(img_w * scale))
                                disp_h = max(1, int(img_h * scale))
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
