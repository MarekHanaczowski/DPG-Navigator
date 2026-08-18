"""Base interfaces for modular preview renderers."""

from __future__ import annotations

from typing import Callable, Protocol

import dearpygui.dearpygui as dpg  # type: ignore[import-untyped]

from .._preview_registry import PreviewCapabilities
from .._types import FileEntry


class PreviewContext:
    """Context passed to renderers, encapsulating the DPG panel and common utilities."""

    def __init__(
        self, panel_id: int | str, table_wrapper: int | str, config_tag: str, capabilities: PreviewCapabilities
    ):
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


class TableRenderMixin:
    """Shared native-DPG table renderer for tabular previews.

    ``DataRenderer`` and ``ArchiveRenderer`` both use this mixin. Including
    classes must set ``self._ctx`` to a ``PreviewContext`` in ``render()``
    before calling any helper here.
    """

    _STATUS_HEIGHT: int = 42
    _ctx: PreviewContext | None

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
        ctx = self._ctx
        if ctx is None or ctx.panel_id is None:
            return

        ctx.image_cache = None
        dpg.delete_item(ctx.panel_id, children_only=True)
        tex_tag = f"_preview_tex_{ctx.config_tag}"
        if dpg.does_item_exist(tex_tag):
            dpg.delete_item(tex_tag)

        dpg.add_text(
            entry_name,
            color=[180, 180, 255],
            parent=ctx.panel_id,
        )
        dpg.add_separator(parent=ctx.panel_id)

        if not headers and not rows:
            dpg.add_text(
                status_text or "No data",
                color=[128, 128, 128],
                parent=ctx.panel_id,
            )
            return

        header_color = [180, 220, 180]
        cell_color = [210, 210, 210]

        bottom_margin = self._STATUS_HEIGHT + 4
        if ui_builder is not None:
            bottom_margin += 30

        with dpg.child_window(
            parent=ctx.panel_id,
            height=-bottom_margin,
            width=-1,
        ), dpg.table(
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

        dpg.add_spacer(height=2, parent=ctx.panel_id)

        if ui_builder is not None:
            ui_builder()

        dpg.add_text(
            status_text,
            color=[180, 180, 180],
            parent=ctx.panel_id,
        )
