"""Text and code preview renderers."""

import dearpygui.dearpygui as dpg  # type: ignore[import-untyped]

from ._base import BaseRenderer, PreviewContext
from .._types import FileEntry
from typing import Callable, Tuple, Optional

class TextRenderer(BaseRenderer):
    _TEXT_PREVIEW_MAX_SIZE = 100 * 1024  # 100 KB chunks

    def __init__(self, load_text_content_cb: Callable[[str, int], Tuple[Optional[str], bool]], request_update_cb: Callable[[FileEntry], None]):
        self._load_text_content = load_text_content_cb
        self._request_update = request_update_cb
        self._text_offset = 0
        self._current_entry = None

    def render(self, entry: FileEntry, ctx: PreviewContext) -> None:
        if self._current_entry is None or self._current_entry.full_path != entry.full_path:
            self._text_offset = 0
            self._current_entry = entry

        text, is_bin = self._load_text_content(entry.full_path, self._text_offset)
        if is_bin:
            self._render_binary_warning(entry, ctx)
            return
        if text is None:
            ctx.clear()
            return

        if not text.strip():
            text = "(No text content or only whitespace in this fragment)"

        ctx.image_cache = None
        dpg.delete_item(ctx.panel_id, children_only=True)
        tex_tag = f"_preview_tex_{ctx.config_tag}"
        if dpg.does_item_exist(tex_tag):
            dpg.delete_item(tex_tag)

        if entry.size_bytes is not None and entry.size_bytes > self._TEXT_PREVIEW_MAX_SIZE:
            self._render_text_navigation(entry, ctx)
        else:
            dpg.add_text(
                entry.name,
                color=[180, 180, 255],
                parent=ctx.panel_id,
            )
        dpg.add_separator(parent=ctx.panel_id)
        with dpg.child_window(parent=ctx.panel_id, height=-1, width=-1):
            dpg.add_text(text, wrap=0)

    def _render_binary_warning(self, entry: FileEntry, ctx: PreviewContext) -> None:
        if ctx.temp_font is not None:
            if dpg.does_item_exist(ctx.temp_font):
                dpg.delete_item(ctx.temp_font)
            ctx.temp_font = None

        dpg.delete_item(ctx.panel_id, children_only=True)
        tex_tag = f"_preview_tex_{ctx.config_tag}"
        if dpg.does_item_exist(tex_tag):
            dpg.delete_item(tex_tag)
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

    def _render_text_navigation(self, entry: FileEntry, ctx: PreviewContext) -> None:
        if entry.size_bytes is None:
            dpg.add_text(entry.name, color=[180, 180, 255], parent=ctx.panel_id)
            return

        size_bytes = entry.size_bytes
        mb = 1024 * 1024
        start_mb = self._text_offset / mb
        end_mb = min(
            (self._text_offset + self._TEXT_PREVIEW_MAX_SIZE) / mb,
            size_bytes / mb,
        )
        total_mb = size_bytes / mb
        
        info = f"{start_mb:.2f}-{end_mb:.2f} of {total_mb:.2f} MB"
        
        with dpg.group(horizontal=True, parent=ctx.panel_id):
            dpg.add_text(entry.name, color=[180, 180, 255])
            dpg.add_spacer(width=4)
            
            dpg.add_button(
                label="<", 
                width=24, 
                callback=self._on_text_page_change, 
                user_data=-1,
                enabled=(self._text_offset > 0)
            )
            
            dpg.add_text(info, color=[200, 200, 200])
            
            dpg.add_button(
                label=">", 
                width=24, 
                callback=self._on_text_page_change, 
                user_data=1,
                enabled=(self._text_offset + self._TEXT_PREVIEW_MAX_SIZE < size_bytes)
            )

    def _on_text_page_change(self, sender, app_data, user_data: int) -> None:
        if self._current_entry is None or self._current_entry.size_bytes is None:
            return

        new_offset = self._text_offset + (user_data * self._TEXT_PREVIEW_MAX_SIZE)
        if 0 <= new_offset < self._current_entry.size_bytes:
            self._text_offset = new_offset
            self._request_update(self._current_entry)

    def clear(self) -> None:
        pass
