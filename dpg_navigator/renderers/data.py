"""Data preview renderer for CSV, Excel, SQLite, and XML."""
import dearpygui.dearpygui as dpg
import csv
import traceback

try:
    import openpyxl
except ImportError:
    openpyxl = None
try:
    import sqlite3
except ImportError:
    sqlite3 = None

from ._base import BaseRenderer, PreviewContext
from .._types import FileEntry
from typing import Callable, Optional, Tuple

class DataRenderer(BaseRenderer):
    def __init__(self, load_text_content_cb: Callable[[str, int], Tuple[Optional[str], bool]]):
        self._load_text_content = load_text_content_cb
        self._current_entry = None
        self._ctx = None

    def render(self, entry: FileEntry, ctx: PreviewContext) -> None:
        self._ctx = ctx
        self._current_entry = entry
        ext = entry.ext
        if ext in ('.csv', '.tsv', '.psv'):
            self._render_csv_preview(entry)
        elif ext in ('.xlsx', '.xlsm'):
            self._render_excel_preview(entry)
        elif ext in ('.sqlite', '.sqlite3', '.db'):
            self._render_sqlite_preview(entry)
        elif ext == '.xml':
            self._render_xml_preview(entry)
        else:
            ctx.show_error("Unsupported data format", f"{ext} is not supported")

    def clear(self) -> None:
        self._current_entry = None
        self._ctx = None

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
    
            try:
                table = parse_csv_table(
                    text,
                    entry.name,
                    max_rows=self._TABLE_MAX_ROWS,
                    max_cols=self._TABLE_MAX_COLS,
                )
            except CsvPreviewError:
                # If CSV parsing fails, fallback to plain text
                self._render_text_preview(entry)
                return
    
            # If the underlying file exceeds the text page size, indicate partial read.
            header_name = entry.name
            if entry.size_bytes is not None and entry.size_bytes > self._TEXT_PREVIEW_MAX_SIZE:
                 limit_str = DirectoryLister.format_size(self._TEXT_PREVIEW_MAX_SIZE)
                 size_str = DirectoryLister.format_size(entry.size_bytes)
                 header_name = f"{entry.name} (Partial: first {limit_str} of {size_str})"
    
            self._render_table_widget(
                header_name, table.headers, table.rows, table.status,
            )
    def _render_excel_preview(self, entry: FileEntry, sheet_name_to_load: str | None = None) -> None:
            """Parse an Excel .xlsx file and display as a native DPG table."""
            if self._panel_id is None:
                return
    
            try:
                table = load_excel_table(
                    entry.full_path,
                    sheet_name=sheet_name_to_load,
                    max_rows=self._TABLE_MAX_ROWS,
                    max_cols=self._TABLE_MAX_COLS,
                    workbook_loader=_load_workbook,
                )
            except ExcelPreviewError:
                self.clear()
                return
    
            def _build_excel_ui():
                if len(table.sheetnames) > 1:
                    with dpg.group(horizontal=True, parent=self._panel_id):
                        dpg.add_text("Sheet:", color=[180, 180, 180])
                        def on_sheet_changed(sender, app_data, user_data):
                            self._render_excel_preview(entry, sheet_name_to_load=app_data)
                        dpg.add_combo(
                            items=table.sheetnames,
                            default_value=table.sheet_name,
                            width=-1,
                            callback=on_sheet_changed
                        )
    
            self._render_table_widget(
                entry.name, table.headers, table.rows, table.status,
                ui_builder=_build_excel_ui
            )
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
    def _render_sqlite_preview(self, entry: FileEntry, table_name_to_load: str | None = None) -> None:
            """Parse a SQLite database file and display a table's contents."""
            if self._panel_id is None:
                return
    
            try:
                table = load_sqlite_table(
                    entry.full_path,
                    table_name=table_name_to_load,
                    max_rows=self._TABLE_MAX_ROWS,
                    max_cols=self._TABLE_MAX_COLS,
                )
            except SQLitePreviewError as e:
                _log.exception("Error reading SQLite database %s", entry.full_path)
                self._render_table_widget(entry.name, [], [], f"Error reading database: {e}")
                return
    
            def _build_db_ui():
                if len(table.tables) > 1:
                    with dpg.group(horizontal=True, parent=self._panel_id):
                        dpg.add_text("Table:", color=[200, 200, 200])
                        dpg.add_combo(
                            items=table.tables,
                            default_value=table.table_name,
                            width=200,
                            callback=lambda s, a, u: self._render_sqlite_preview(entry, a)
                        )
    
            self._render_table_widget(
                entry.name, table.headers, table.rows, table.status,
                ui_builder=_build_db_ui
            )
