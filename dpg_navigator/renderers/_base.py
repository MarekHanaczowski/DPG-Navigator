"""Base interfaces for modular preview renderers."""

from __future__ import annotations
from typing import Protocol, Any, Callable
import dearpygui.dearpygui as dpg  # type: ignore[import-untyped]

from .._types import FileEntry
from .._preview_registry import PreviewCapabilities

class PreviewContext:
    """Context passed to renderers, encapsulating the DPG panel and common utilities."""
    def __init__(self, panel_id: int | str, table_wrapper: int | str, config_tag: str, capabilities: PreviewCapabilities):
        self.panel_id = panel_id
        self.table_wrapper = table_wrapper
        self.config_tag = config_tag
        self.capabilities = capabilities
        
        # Callbacks injected by the panel
        self.on_clear: Callable[[], None] = lambda: None
        self.on_show_error: Callable[[str, str], None] = lambda m, d: None
        
        # State shared across renderers, e.g. text pagination or images
        self.image_cache: tuple[int, int, int | str] | None = None
        self.temp_font: int | str | None = None
        self.pptx_texture_tags: list[str] = []
        
    def clear(self) -> None:
        """Clear the preview panel using the injected callback."""
        self.on_clear()

    def show_error(self, message: str, detail: str) -> None:
        """Show an error message in the preview panel."""
        self.on_show_error(message, detail)

class BaseRenderer(Protocol):
    """Protocol for all preview renderers."""
    
    def render(self, entry: FileEntry, ctx: PreviewContext) -> None:
        """Render the entry into the panel."""
        ...
        
    def clear(self) -> None:
        """Clear any state held by this renderer."""
        ...
