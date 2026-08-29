"""Modular preview panel for the file dialog.

Routes a ``FileEntry`` through ``resolve_preview_kind()`` to a
``BaseRenderer``. Text decoding (BOM / UTF-16 / binary) lives here so
tests can cover it without a live renderer.
"""

from __future__ import annotations  # PEP 604/585 in signatures need this on py3.8/3.9

from typing import Any, Callable

import dearpygui.dearpygui as dpg  # type: ignore[import-untyped]

from ._preview_limits import PREVIEW_TEXT_CHUNK_BYTES
from ._preview_registry import (
    PILLOW_EXTRA_EXTS,
    STB_IMAGE_EXTS,
    PreviewCapabilities,
    PreviewKind,
    resolve_preview_kind,
)
from ._types import DialogConfig, FileEntry
from .renderers._base import BaseRenderer, PreviewContext
from .renderers.archive import ArchiveRenderer
from .renderers.data import DataRenderer
from .renderers.document import DocumentRenderer
from .renderers.font import FontRenderer
from .renderers.image import ImageRenderer
from .renderers.text import TextRenderer

_UTF16_LE_BOM = b"\xff\xfe"
_UTF16_BE_BOM = b"\xfe\xff"
_NUL = b"\x00"


def _strip_bom(text: str) -> str:
    """Drop a leading U+FEFF left behind by UTF-32 codecs."""
    return text[1:] if text.startswith("\ufeff") else text


def decode_preview_bytes(
    raw_bytes: bytes,
    *,
    known_encoding: str | None = None,
) -> tuple[str | None, bool, str | None]:
    """Decode a file fragment for the text preview.

    Returns ``(text, is_binary, encoding)``. Binary fragments return
    ``(None, True, None)``. Empty input returns ``("", False, None)``.
    """
    if not raw_bytes:
        return "", False, None

    if known_encoding:
        return (
            raw_bytes.decode(known_encoding, errors="replace"),
            False,
            known_encoding,
        )

    try:
        return raw_bytes.decode("utf-8-sig"), False, "utf-8-sig"
    except UnicodeDecodeError:
        pass

    if raw_bytes.startswith(b"\x00\x00\xfe\xff"):
        try:
            return _strip_bom(raw_bytes.decode("utf-32-be")), False, "utf-32-be"
        except UnicodeDecodeError:
            pass
    if raw_bytes.startswith(b"\xff\xfe\x00\x00"):
        try:
            return _strip_bom(raw_bytes.decode("utf-32-le")), False, "utf-32-le"
        except UnicodeDecodeError:
            pass
    if raw_bytes.startswith((_UTF16_LE_BOM, _UTF16_BE_BOM)):
        try:
            return raw_bytes.decode("utf-16"), False, "utf-16"
        except UnicodeDecodeError:
            pass

    check_size = min(len(raw_bytes), 8192)
    if _NUL in raw_bytes[:check_size]:
        return None, True, None

    try:
        return raw_bytes.decode("cp1250"), False, "cp1250"
    except UnicodeDecodeError:
        return raw_bytes.decode("cp1250", errors="replace"), False, "cp1250"


class PreviewPanel:
    """Route selected files to the appropriate DearPyGui preview renderer.

    ``PreviewKind.CODE`` shares ``TextRenderer`` (monospace text).
    Mouse wheel and left-button drag are forwarded to the active renderer
    when the pane is hovered (image zoom/pan, PDF paging, HTML scroll).
    """

    _TEXT_PREVIEW_MAX_SIZE = PREVIEW_TEXT_CHUNK_BYTES

    @staticmethod
    def preview_image_exts() -> frozenset[str]:
        """Return image extensions supported by the image preview path."""
        return STB_IMAGE_EXTS | PILLOW_EXTRA_EXTS

    def __init__(self, config: DialogConfig, preview_width: int, show: bool) -> None:
        self._config = config
        self._config_tag = config.tag
        self._saved_width = preview_width
        self._show = show

        self._panel_id: int | None = None
        self._table_wrapper: int | None = None
        self._current_entry: FileEntry | None = None

        self._text_encoding: str | None = None

        self.ctx = PreviewContext(
            panel_id=0,
            table_wrapper=0,
            config_tag=self._config_tag,
            capabilities=self._preview_capabilities(),
            trusted_html_preview=config.trusted_html_preview,
        )

        self._renderers: dict[PreviewKind, BaseRenderer] = {
            PreviewKind.IMAGE: ImageRenderer(),
            PreviewKind.FONT: FontRenderer(),
            PreviewKind.TEXT: TextRenderer(self._load_text_content, self.update),
            PreviewKind.CODE: TextRenderer(self._load_text_content, self.update),
            PreviewKind.CSV: DataRenderer(self._load_text_content),
            PreviewKind.EXCEL: DataRenderer(self._load_text_content),
            PreviewKind.SQLITE: DataRenderer(self._load_text_content),
            PreviewKind.XML: DataRenderer(self._load_text_content),
            PreviewKind.ZIP: ArchiveRenderer(self.update),
            PreviewKind.SEVEN_Z: ArchiveRenderer(self.update),
            PreviewKind.HTML: DocumentRenderer(self._load_text_content),
            PreviewKind.MARKDOWN: DocumentRenderer(self._load_text_content),
            PreviewKind.PDF: DocumentRenderer(self._load_text_content),
            PreviewKind.WORD: DocumentRenderer(self._load_text_content),
            PreviewKind.PPTX: DocumentRenderer(self._load_text_content),
        }

        self._active_renderer: BaseRenderer | None = None

    def _preview_capabilities(self) -> PreviewCapabilities:
        """Probe optional preview backends available in the current environment."""
        from ._availability import (
            excel_available,
            mammoth_available,
            markdown_available,
            pptx_available,
            pygments_available,
        )
        from ._pdf import pdf_available
        from ._preview_archive import seven_zip_available
        from ._preview_word import word_available

        # PreviewCapabilities fields (see _preview_registry): pdf, word, mammoth,
        # pptx, markdown, excel, pygments, seven_z. It has no html/chrome fields
        # — HTML routing is unconditional on extension, so html_available()/
        # chrome_available() are not part of the capability set.
        return PreviewCapabilities(
            pdf=pdf_available(),
            word=word_available(),
            mammoth=mammoth_available(),
            pptx=pptx_available(),
            markdown=markdown_available(),
            excel=excel_available(),
            pygments=pygments_available(),
            seven_z=seven_zip_available(),
        )

    def attach(self, table_wrapper: int, panel_id: int | None) -> None:
        """Attach the preview panel and explorer wrapper item IDs."""
        self._table_wrapper = table_wrapper
        self._panel_id = panel_id
        if self._panel_id:
            self.ctx.panel_id = self._panel_id
        if self._table_wrapper:
            self.ctx.table_wrapper = self._table_wrapper

    def toggle(self, explorer_table: int) -> None:
        """Show or hide the preview child window."""
        if not self._panel_id:
            return
        self._show = not self._show
        dpg.configure_item(self._panel_id, show=self._show)
        self.layout()

    def layout(self) -> None:
        """Ask the active renderer to re-layout its content after a resize."""
        if not self._panel_id or not self._show:
            return
        handler = getattr(self._active_renderer, "on_resize", None)
        if callable(handler):
            handler(None, None, None)

    def on_resize(self, sender: Any, app_data: Any, user_data: Any) -> None:
        """Forward a DearPyGui resize event to the active renderer."""
        if not self._panel_id or not self._show:
            return
        handler = getattr(self._active_renderer, "on_resize", None)
        if callable(handler):
            handler(sender, app_data, user_data)

    def _preview_hovered(self) -> bool:
        """True when the preview pane is shown and the cursor is over it."""
        if self._panel_id is None or not self._show:
            return False
        return bool(dpg.does_item_exist(self._panel_id) and dpg.is_item_hovered(self._panel_id))

    def on_mouse_down(self, sender: Any, app_data: Any, user_data: Any) -> None:
        """Start a renderer drag (image pan) when the pane is hovered."""
        if not self._preview_hovered():
            return
        handler = getattr(self._active_renderer, "on_mouse_down", None)
        if callable(handler):
            handler(sender, app_data, user_data)

    def on_mouse_drag(self, sender: Any, app_data: Any, user_data: Any) -> None:
        """Continue a renderer-specific drag started on the preview pane."""
        handler = getattr(self._active_renderer, "on_mouse_drag", None)
        if callable(handler):
            handler(sender, app_data, user_data)

    def on_mouse_up(self, sender: Any, app_data: Any, user_data: Any) -> None:
        """End a renderer-specific drag."""
        handler = getattr(self._active_renderer, "on_mouse_up", None)
        if callable(handler):
            handler(sender, app_data, user_data)

    def clear(self) -> None:
        """Clear the panel and release the active renderer's state."""
        if self._panel_id:
            dpg.delete_item(self._panel_id, children_only=True)
        if self._active_renderer:
            self._active_renderer.clear()
            self._active_renderer = None

    def _show_preview_error(self, message: str, detail: str) -> None:
        self.clear()
        if self._panel_id:
            dpg.add_text(message, color=[255, 100, 100], parent=self._panel_id)
            dpg.add_text(detail, color=[200, 200, 200], parent=self._panel_id)

    def update(self, entry: FileEntry | None) -> None:
        """Route a selected file to its active preview renderer."""
        if not self._panel_id or not self._show:
            return

        if entry is None or entry.is_dir:
            self._current_entry = None
            self.clear()
            return

        if self._current_entry is None or self._current_entry.full_path != entry.full_path:
            self._text_encoding = None

        kind = resolve_preview_kind(
            entry.name,
            capabilities=self.ctx.capabilities,
            image_extensions=self.preview_image_exts(),
        )
        renderer = self._renderers.get(kind)
        same_path = (
            self._current_entry is not None
            and entry.full_path == self._current_entry.full_path
            and self._active_renderer is renderer
            and renderer is not None
        )
        if same_path:
            if self._panel_id:
                dpg.delete_item(self._panel_id, children_only=True)
        else:
            self.clear()

        self._current_entry = entry
        self.ctx.on_clear = self.clear
        self.ctx.on_show_error = self._show_preview_error

        if renderer:
            self._active_renderer = renderer
            renderer.render(entry, self.ctx)
        else:
            dpg.add_text(f"Unsupported preview: {kind.name}", color=[150, 150, 150], parent=self._panel_id)

    def _load_text_content(self, path: str, seek_offset: int = 0) -> tuple[str | None, bool]:
        """Read a file fragment as text with encoding detection and binary check."""
        try:
            with open(path, "rb") as f:
                if seek_offset > 0:
                    f.seek(seek_offset)
                raw_bytes = f.read(self._TEXT_PREVIEW_MAX_SIZE)

            known = self._text_encoding if seek_offset > 0 else None
            text, is_bin, encoding = decode_preview_bytes(
                raw_bytes,
                known_encoding=known,
            )
            if encoding is not None:
                self._text_encoding = encoding
            return text, is_bin
        except (OSError, PermissionError):
            return None, False

    def build_handlers(self, dialog_tag: str, is_active_fn: Callable[[], bool]) -> None:
        """Keep the compatibility hook; global handlers live on KeyboardMixin."""

    def shutdown(self) -> None:
        """Clear the active renderer and release preview-owned resources."""
        self.clear()

    def destroy(self) -> None:
        """Release preview resources during :meth:`FileDialog.destroy`."""
        self.shutdown()

    @property
    def visible(self) -> bool:
        """Whether the preview panel is currently shown (tracked by toggle)."""
        return self._show

    def on_mouse_wheel(self, sender: Any, app_data: Any, user_data: Any) -> None:
        """Route the mouse wheel to the active renderer when the pane is hovered.

        Image preview zooms toward the cursor; PDF changes page; HTML
        scrolls its viewport. Renderers without ``on_mouse_wheel`` ignore it.
        """
        if self._panel_id is None or not self._show:
            return
        if not dpg.does_item_exist(self._panel_id) or not dpg.is_item_hovered(self._panel_id):
            return
        handler = getattr(self._active_renderer, "on_mouse_wheel", None)
        if callable(handler):
            handler(sender, app_data, user_data)
