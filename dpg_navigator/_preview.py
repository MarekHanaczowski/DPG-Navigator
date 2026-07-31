"""Modular Preview Panel component for the file dialog."""
from __future__ import annotations  # PEP 604/585 in signatures need this on py3.8/3.9

import dearpygui.dearpygui as dpg  # type: ignore[import-untyped]
from typing import Optional, Callable

from ._types import FileEntry, DialogConfig
from ._preview_registry import (
    PILLOW_EXTRA_EXTS,
    STB_IMAGE_EXTS,
    PreviewCapabilities,
    PreviewKind,
    resolve_preview_kind,
)
from .renderers._base import PreviewContext, BaseRenderer
from .renderers.image import ImageRenderer
from .renderers.text import TextRenderer
from .renderers.data import DataRenderer
from .renderers.archive import ArchiveRenderer
from .renderers.document import DocumentRenderer

class PreviewPanel:
    """The new modular preview panel implementation."""
    
    _TEXT_PREVIEW_MAX_SIZE = 100 * 1024  # 100 KB

    @staticmethod
    def preview_image_exts() -> frozenset[str]:
        return STB_IMAGE_EXTS | PILLOW_EXTRA_EXTS
    
    def __init__(self, config: DialogConfig, preview_width: int, show: bool):
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
            capabilities=self._preview_capabilities()
        )
        
        self._renderers: dict[PreviewKind, BaseRenderer] = {
            PreviewKind.IMAGE: ImageRenderer(),
            PreviewKind.TEXT: TextRenderer(self._load_text_content, self.update),
            PreviewKind.CODE: TextRenderer(self._load_text_content, self.update),
            PreviewKind.CSV: DataRenderer(self._load_text_content),
            PreviewKind.EXCEL: DataRenderer(self._load_text_content),
            PreviewKind.SQLITE: DataRenderer(self._load_text_content),
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
        """Determines what backends are available. Hardcoded defaults for demo."""
        # Using the same available functions as _preview.py
        from ._pdf import pdf_available
        from ._html import html_available, chrome_available
        from ._preview_archive import seven_zip_available
        from ._preview_word import word_available
        from ._availability import mammoth_available, pptx_available
        
        # Determine markdown availability
        try:
            import markdown  # type: ignore[import-untyped]
            markdown_available = True
        except ImportError:
            markdown_available = False
            
        try:
            from pygments import highlight  # type: ignore[import-untyped]
            pygments_available = True
        except ImportError:
            pygments_available = False
            
        try:
            import openpyxl  # type: ignore[import-untyped]
            excel_available = True
        except ImportError:
            excel_available = False

        # PreviewCapabilities fields (see _preview_registry): pdf, word, mammoth,
        # pptx, markdown, excel, pygments, seven_z. It has no html/chrome fields
        # — HTML routing is unconditional on extension, so html_available()/
        # chrome_available() are not part of the capability set.
        return PreviewCapabilities(
            pdf=pdf_available(),
            word=word_available(), mammoth=mammoth_available(), pptx=pptx_available(),
            markdown=markdown_available, excel=excel_available, pygments=pygments_available,
            seven_z=seven_zip_available(),
        )

    def attach(self, table_wrapper: int, panel_id: int | None) -> None:
        self._table_wrapper = table_wrapper
        self._panel_id = panel_id
        if self._panel_id:
            self.ctx.panel_id = self._panel_id
        if self._table_wrapper:
            self.ctx.table_wrapper = self._table_wrapper
            
    def toggle(self, explorer_table: int) -> None:
        if not self._panel_id:
            return
        self._show = not self._show
        dpg.configure_item(self._panel_id, show=self._show)
        self.layout()

    def layout(self) -> None:
        """Called on resize to readjust the preview panel layout."""
        if not self._panel_id or not self._show:
            return
            
    def on_resize(self, sender, app_data, user_data) -> None:
        self.layout()

    def clear(self) -> None:
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
        if not self._panel_id or not self._show:
            return
            
        if entry is None or entry.is_dir:
            self._current_entry = None
            self.clear()
            return

        if self._current_entry != entry:
            self._text_encoding = None

        self._current_entry = entry
        self.ctx.on_clear = self.clear
        self.ctx.on_show_error = self._show_preview_error
        
        # Clear previous state
        self.clear()
        
        # Hardcoded extensions for now
        image_exts = frozenset({".png", ".jpg", ".jpeg", ".bmp"})
        kind = resolve_preview_kind(
            entry.name,
            capabilities=self.ctx.capabilities,
            image_extensions=image_exts,
        )
        
        renderer = self._renderers.get(kind)
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
            
            if not raw_bytes:
                return "", False

            if seek_offset > 0 and self._text_encoding:
                return raw_bytes.decode(self._text_encoding, errors="replace"), False
                
            try:
                text = raw_bytes.decode("utf-8-sig")
                self._text_encoding = "utf-8-sig"
                return text, False
            except UnicodeDecodeError:
                pass

            has_bom = raw_bytes.startswith((b'\\xff\\xfe', b'\\xfe\\xff'))
            is_utf16_likely = has_bom
            if not is_utf16_likely and len(raw_bytes) >= 4:
                sample = raw_bytes[:1024]
                nulls_even = sample[0::2].count(b'\\x00')
                nulls_odd = sample[1::2].count(b'\\x00')
                if (nulls_even > len(sample)//4 or nulls_odd > len(sample)//4):
                    is_utf16_likely = True

            if is_utf16_likely:
                try:
                    text = raw_bytes.decode("utf-16")
                    self._text_encoding = "utf-16"
                    return text, False
                except UnicodeDecodeError:
                    pass
            
            check_size = min(len(raw_bytes), 8192)
            if b"\\x00" in raw_bytes[:check_size]:
                return None, True
                
            try:
                text = raw_bytes.decode("cp1250")
                self._text_encoding = "cp1250"
                return text, False
            except UnicodeDecodeError:
                self._text_encoding = "cp1250"
                return raw_bytes.decode("cp1250", errors="replace"), False
                
        except (OSError, PermissionError):
            return None, False

    def build_handlers(self, dialog_tag: str, is_active_fn: Callable[[], bool]) -> None:
        """Register global handlers if needed."""
        pass
        
    def shutdown(self) -> None:
        self.clear()

    def destroy(self) -> None:
        """Release resources held by the preview panel (alias for shutdown).

        FileDialog.cleanup() calls destroy(); kept as the panel's public
        teardown name (the monolith used destroy()).
        """
        self.shutdown()

    @property
    def visible(self) -> bool:
        """Whether the preview panel is currently shown (tracked by toggle)."""
        return self._show

    def on_mouse_wheel(self, sender, app_data, user_data) -> None:
        """Route mouse-wheel scroll to the active renderer if it handles it.

        Registered as a global wheel handler by the keyboard mixin. Only the
        active renderer (when the panel is visible and hovered) gets the event;
        renderers that don't implement on_mouse_wheel simply ignore it.

        PDF page navigation is implemented by DocumentRenderer; renderers that
        do not expose on_mouse_wheel simply ignore the event.
        """
        if self._panel_id is None or not self._show:
            return
        if not dpg.does_item_exist(self._panel_id) or not dpg.is_item_hovered(self._panel_id):
            return
        handler = getattr(self._active_renderer, "on_mouse_wheel", None)
        if callable(handler):
            handler(sender, app_data, user_data)
