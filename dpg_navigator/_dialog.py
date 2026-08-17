"""Main FileDialog orchestrator for the dpg_navigator package.

Contains the FileDialog class which manages the complete DearPyGui file
dialog including sidebar navigation, file listing, real-time search with
recursive subfolder index, extension filtering, column sorting,
multi-selection, new folder creation, archive browsing (ZIP/7z), and an
optional preview panel supporting images, text, PDF, Word (.docx),
PowerPoint (.pptx), Markdown, HTML, CSV/TSV, Excel (.xlsx), SQLite
databases, fonts (.ttf/.otf), ZIP/7z archives, and syntax-highlighted
source code (via Pygments).
"""
from __future__ import annotations
# MIT licensed

import logging
import os
import time
import uuid
from copy import copy
from typing import Callable

import dearpygui.dearpygui as dpg  # type: ignore[import-untyped]

_log = logging.getLogger(__name__)

from ._types import DialogConfig, DialogMode, StyleVariant, FileEntry, DEFAULT_FILTER_LIST
from ._icons import IconRegistry
from ._filesystem import (
    DirectoryLister,
    DirectoryIndex,
    build_selection_list,
    resolve_archive_selection,
)
from ._preview_registry import ZIP_EXTS, SEVEN_Z_EXTS
from ._preview import PreviewPanel
from ._styles import STYLE_REGISTRY
from ._keyboard import KeyboardMixin
from ._job_manager import JobManager
from . import _platform


from .dialog._state import DialogState
from .dialog._logic import DialogLogic
from .dialog._ui import DialogUIBuilder

from ._types import FileEntry

class FileDialog(KeyboardMixin):
    """Customizable file dialog for DearPyGui.

    Features sidebar navigation (labeled or compact), file listing with
    column sorting, real-time search with recursive subfolder index,
    extension filtering, keyboard navigation (Up/Down/Enter/Esc/F5),
    multi-selection with Ctrl+click/Ctrl+A, drag-and-drop payloads,
    new folder creation, async directory size calculation, archive
    browsing (ZIP/7z), and an optional preview panel supporting:

    - Images (stb_image + Pillow fallback)
    - Text files with encoding detection (UTF-8/UTF-16/CP1250)
    - PDF pages (pypdfium2 + mouse wheel paging, LRU cache)
    - Word documents (mammoth + Chrome or python-docx fallback)
    - PowerPoint slides (python-pptx text + image extraction)
    - Markdown (rendered via markdown lib + Chrome Headless)
    - HTML (html2image + Chrome Headless, scrollable viewport)
    - CSV/TSV (native DPG table with delimiter detection)
    - Excel .xlsx (openpyxl, sheet switching)
    - SQLite databases (read-only table browsing)
    - Fonts .ttf/.otf (live glyph preview)
    - ZIP/7z archives (file list with compression ratios)
    - Source code (Pygments syntax highlighting)

    Args:
        callback: Function called with list of selected file paths on OK.
        config: DialogConfig instance for full configuration.
        **kwargs: Individual config options (alternative to passing config).

    Example::

        fd = FileDialog(callback=my_handler, default_path="..",
                        show_preview=True)
        fd.show()
        # ... later:
        fd.destroy()
    """

    DOUBLE_CLICK_THRESHOLD: float = 0.5
    """Maximum seconds between clicks to register a double-click."""

    _DEFAULT_SELECTABLE_HEIGHT: int = 16
    """Default height in pixels for selectable table rows."""

    # Attribute type declarations: `state`/`ui` are assigned in __init__ but
    # referenced earlier (self.ui inside a callback lambda) so mypy needs the
    # types up front; `_preview_btn`/`_new_folder_group` are DPG item tags set
    # externally by DialogUIBuilder (dialog/_ui.py) on this instance.
    state: DialogState
    ui: DialogUIBuilder
    _preview_btn: int | str | None = None
    _new_folder_group: int | str | None = None

    _DEFAULT_IMAGE_TRANSPARENCY: int = 100
    """Alpha value (0-255) for hidden file icon tinting."""

    _SIZE_CACHE_TTL: float = 60.0
    """Seconds before a cached directory size is considered stale."""

    _DEEP_SEARCH_DEBOUNCE: float = 0.3
    """Seconds to wait after last keystroke before triggering deep search."""

    _MAX_ARCHIVE_EXTRACT_SIZE: int = 512 * 1024 * 1024
    """Anti-bomb ceiling (bytes) for extracting a selected archive member.

    Selecting a file inside an archive is a deliberate action, so this is a
    generous cap that still rejects a member declaring an absurd expanded size
    (a decompression bomb) rather than the small text-preview limit."""

    _shared_selec_theme: int | None = None
    _shared_size_theme: int | None = None
    _shared_preview_active_theme: int | None = None
    _instance_count: int = 0

    def __init__(
        self,
        config: DialogConfig | Callable | None = None,
        callback: Callable | None = None,
        **kwargs,
    ):
        # Support old signature FileDialog(callback, config) or FileDialog(callback=on_select)
        # by checking if the first positional argument is callable.
        if config is not None and (callable(config) or not isinstance(config, DialogConfig)):
            callback = config
            config = None

        # Build config from kwargs if not provided directly.
        # Copy shared configs so tag uniquification cannot mutate the caller's object.
        if config is not None:
            self._config = copy(config)
        else:
            self._config = DialogConfig(**kwargs)

        # Two dialogs sharing a tag (e.g. separate open + save with the default
        # config) crash in dpg.window(tag=...). If the tag is already a live DPG
        # item, switch to a unique one so construction never fails.
        if dpg.does_item_exist(self._config.tag):
            self._config.tag = f"{self._config.tag}_{uuid.uuid4().hex[:8]}"

        self._callback = callback
        self._destroyed = False
        self.state = DialogState()

        # Resolve default_path at runtime (not at import time)
        self.state.current_dir = (
            os.path.abspath(self._config.default_path)
            if self._config.default_path else os.getcwd()
        )
        self._home_dir = self.state.current_dir

        # Resolve filter_list (None → default, explicit [] kept as-is)
        # Use a local copy to avoid mutating shared DialogConfig instances.
        if self._config.filter_list is None:
            self._filter_list = list(DEFAULT_FILTER_LIST)
        else:
            self._filter_list = list(self._config.filter_list)

        # Modular State & Logic
        self.state.current_filter = self._config.file_filter
        
        self.logic = DialogLogic(
            state=self.state,
            config=self._config,
            refresh_ui_cb=self._safe_refresh_ui,
            show_error_cb=self._show_message,
            update_path_input_cb=self._safe_update_path_input,
            update_size_cell_cb=self._safe_update_size_cell,
        )

        self._preview = PreviewPanel(
            config=self._config,
            preview_width=self._config.preview_width,
            show=self._config.show_preview,
        )

        # (Moved to DialogState and DialogLogic)

        # Selectable height for table rows
        self._selec_height = self._DEFAULT_SELECTABLE_HEIGHT
        self._image_transparency = self._DEFAULT_IMAGE_TRANSPARENCY

        # Drag payload type
        self._payload_type = f"ws_{self._config.tag}"

        # Initialize icons
        images_dir = os.path.join(os.path.dirname(__file__), "images")
        self._icons = IconRegistry(self._config.tag, images_dir)
        self._icons.load_all()

        # Initialize sidebar renderer
        sidebar_cls = STYLE_REGISTRY.get(self._config.style)
        if sidebar_cls is None:
            sidebar_cls = STYLE_REGISTRY[StyleVariant.LABELED]
        self._sidebar = sidebar_cls()

        # Build UI (does NOT navigate — that happens in show())
        self.ui = DialogUIBuilder(self, self.state, self.logic, self._config)
        self.ui._build_ui()

    # ── Compatibility adapters for KeyboardMixin ────────────────

    @property
    def _size_cache(self) -> dict[str, tuple[int | None, float]]:
        return self.state.size_cache

    @_size_cache.setter
    def _size_cache(self, value: dict[str, tuple[int | None, float]]) -> None:
        self.state.size_cache = value

    @property
    def _dir_index(self) -> DirectoryIndex:
        return self.logic._dir_index

    @_dir_index.setter
    def _dir_index(self, value: DirectoryIndex) -> None:
        self.logic._dir_index = value

    @property
    def _selected_files(self) -> list[str]:
        return self.state.selected_files

    @_selected_files.setter
    def _selected_files(self, value: list[str]) -> None:
        self.state.selected_files = value

    @property
    def _selected_elements(self) -> list[int]:
        return self.state.selected_elements

    @_selected_elements.setter
    def _selected_elements(self, value: list[int]) -> None:
        self.state.selected_elements = value

    @property
    def _row_entries(self) -> dict[int, FileEntry]:
        return self.state.row_entries

    @_row_entries.setter
    def _row_entries(self, value: dict[int, FileEntry]) -> None:
        self.state.row_entries = value

    @property
    def _current_dir(self) -> str:
        return self.state.current_dir

    @_current_dir.setter
    def _current_dir(self, value: str) -> None:
        self.state.current_dir = value

    @property
    def _focused_row_index(self) -> int:
        return self.state.focused_row_index

    @_focused_row_index.setter
    def _focused_row_index(self, value: int) -> None:
        self.state.focused_row_index = value

    @property
    def _last_clicked_element(self) -> int | None:
        return self.state.last_clicked_element

    @_last_clicked_element.setter
    def _last_clicked_element(self, value: int | None) -> None:
        self.state.last_clicked_element = value

    def _navigate_to(self, path: str) -> None:
        self.logic.navigate_to(path)

    def _refresh_listing(self, search_query: str = "") -> None:
        self.logic.refresh_listing(search_query)

    def _start_index_build(self) -> None:
        self.logic.start_index_build()

    def _safe_refresh_ui(self, entries) -> None:
        """Marshal UI refresh onto the DPG thread via mutex."""
        if self._destroyed:
            return
        with dpg.mutex():
            if self._destroyed or not hasattr(self, "ui"):
                return
            self.ui._render_entries_list(entries)

    def _safe_update_path_input(self, path: str) -> None:
        if self._destroyed or not hasattr(self, "_path_input"):
            return
        with dpg.mutex():
            if self._destroyed or not dpg.does_item_exist(self._path_input):
                return
            dpg.configure_item(self._path_input, default_value=path)

    def _safe_update_size_cell(self, path: str, txt: str) -> None:
        if self._destroyed:
            return
        with dpg.mutex():
            if self._destroyed:
                return
            cell = self.state.pending_size_cells.get(path)
            if cell is not None and dpg.does_item_exist(cell):
                dpg.configure_item(cell, label=txt)

    # ── Public API ──────────────────────────────────────────────

    def show(self) -> None:
        """Show the file dialog window and navigate to default directory."""
        self.logic.navigate_to(self.state.current_dir)
        dpg.show_item(self._config.tag)

    def hide(self) -> None:
        """Hide the file dialog window."""
        dpg.hide_item(self._config.tag)

    def destroy(self) -> None:
        """Release all DPG resources (textures, handlers, windows, themes)."""
        if self._destroyed:
            return
        self._destroyed = True
        self.logic.cancel_background_tasks()
        self._preview.destroy()
        self._icons.destroy()
        if hasattr(self, "_key_handler") and dpg.does_item_exist(self._key_handler):
            dpg.delete_item(self._key_handler)
        if dpg.does_item_exist(self._config.tag):
            dpg.delete_item(self._config.tag)

        FileDialog._instance_count = max(0, FileDialog._instance_count - 1)
        if FileDialog._instance_count <= 0:
            JobManager.shutdown(wait=True, timeout=2.0)
            # The extraction temp dir is shared across all dialogs, so only
            # wipe it once the last instance is gone — otherwise closing one
            # dialog would delete preview files another is still using.
            DirectoryLister.cleanup_temp_files()
            try:
                from ._html import HTMLRenderer
                HTMLRenderer.shutdown_shared()
            except Exception:
                _log.debug("HTMLRenderer shutdown failed", exc_info=True)
            for attr in ("_shared_selec_theme", "_shared_size_theme", "_shared_preview_active_theme"):
                theme_id = getattr(FileDialog, attr)
                if theme_id is not None and dpg.does_item_exist(theme_id):
                    dpg.delete_item(theme_id)
                setattr(FileDialog, attr, None)
            FileDialog._instance_count = 0

    def change_callback(self, callback: Callable) -> None:
        """Change the callback function. Does NOT modify the OK button directly."""
        self._callback = callback

    def __enter__(self):
        """Enter context manager; returns the FileDialog instance."""
        return self

    def __exit__(self, *args):
        """Exit context manager; calls destroy() to release DPG resources."""
        self.destroy()



    # ── Navigation ──────────────────────────────────────────────




    def _on_path_enter(self, sender, app_data, user_data) -> None:
        """Handle Enter key in the path input field."""
        path = dpg.get_value(sender)
        if path:
            self.logic.navigate_to(path)

    def _on_back(self, sender, app_data, user_data) -> None:
        """Handle click on the '..' row (double-click navigates to parent)."""
        if _platform.is_mod_key_down():
            dpg.set_value(sender, False)
            return

        dpg.set_value(sender, False)
        if self._is_double_click(sender):
            if "|" in self.state.current_dir:
                parts = self.state.current_dir.split("|", 1)
                archive = parts[0]
                inner = parts[1].strip("/")
                if not inner:
                    # We are at the root of the archive, fallback to host folder
                    self.logic.navigate_to(os.path.dirname(archive))
                else:
                    parent_inner = os.path.dirname(inner)
                    self.logic.navigate_to(f"{archive}|/{parent_inner}" if parent_inner else f"{archive}|/")
            else:
                self.logic.navigate_to(os.path.dirname(self.state.current_dir))

    def _is_double_click(self, sender: int) -> bool:
        """Check if this click constitutes a double-click on the same element."""
        current_time = time.time()
        is_double = (
            current_time - self.state.last_click_time < self.DOUBLE_CLICK_THRESHOLD
            and self.state.last_clicked_element == sender
        )
        if is_double:
            self.state.last_click_time = 0
            self.state.last_clicked_element = None
        else:
            self.state.last_click_time = current_time
            self.state.last_clicked_element = sender
        return is_double

    # ── File listing ────────────────────────────────────────────


    def _on_sort(self, sender, sort_specs, user_data) -> None:
        """Sort table rows by clicked column header.

        Directories are always kept above files. The ".." back row
        stays pinned at the top regardless of sort order.  The deep
        search separator row (if present) stays between local and
        deep results — only the rows within each group are sorted.
        """
        if not sort_specs:
            return

        column_id, direction = sort_specs[0]
        columns = dpg.get_item_children(sender, 0)
        col_index = columns.index(column_id)

        rows = dpg.get_item_children(sender, 1)
        if len(rows) <= 1:
            return

        back_row = rows[0]
        data_rows = rows[1:]

        reverse = direction < 0

        def sort_key(row_id):
            entry = self.state.row_entries.get(row_id)
            if entry is None:
                return (0,)
            dir_order = 0 if entry.is_dir else 1
            if col_index == 0:
                return (dir_order, entry.name.lower())
            elif col_index == 1:
                return (dir_order, entry.modified_time)
            elif col_index == 2:
                return (dir_order, not entry.is_dir)
            elif col_index == 3:
                size = entry.size_bytes
                if size is None and entry.is_dir:
                    cached = self.state.size_cache.get(entry.full_path)
                    if cached is not None:
                        size = cached[0]
                return (dir_order, size or 0)
            return (dir_order,)

        sep = self.state.deep_separator_row
        if sep is not None and sep in data_rows:
            sep_idx = data_rows.index(sep)
            local_rows = data_rows[:sep_idx]
            deep_rows = data_rows[sep_idx + 1:]
            local_rows.sort(key=sort_key, reverse=reverse)
            deep_rows.sort(key=sort_key, reverse=reverse)
            ordered = [back_row] + local_rows + [sep] + deep_rows
        else:
            data_rows.sort(key=sort_key, reverse=reverse)
            ordered = [back_row] + data_rows

        dpg.reorder_items(sender, 1, ordered)

    # ── Click handling ──────────────────────────────────────────

    def _on_entry_click(self, sender, app_data, user_data) -> None:
        """Handle click on a file/directory entry (single and multi-select)."""
        entry: FileEntry = user_data

        if _platform.is_mod_key_down():
            if self._config.multi_selection:
                if dpg.get_value(sender) is True:
                    self.state.selected_files.append(entry.full_path)
                    self.state.selected_elements.append(sender)
                else:
                    if entry.full_path in self.state.selected_files:
                        self.state.selected_files.remove(entry.full_path)
                    if sender in self.state.selected_elements:
                        self.state.selected_elements.remove(sender)
            rows = dpg.get_item_children(self._explorer_table, 1)
            for rid, ent in self.state.row_entries.items():
                if ent is entry:
                    try:
                        self.state.focused_row_index = rows.index(rid)
                    except ValueError:
                        pass
                    break
            self._preview.update(entry if dpg.get_value(sender) else None)
            return

        if self.state.selected_files:
            self.state.selected_files.clear()
            for elem in self.state.selected_elements:
                if dpg.does_item_exist(elem):
                    dpg.set_value(elem, False)
            self.state.selected_elements.clear()
        if (self.state.last_clicked_element is not None
                and dpg.does_item_exist(self.state.last_clicked_element)):
            dpg.set_value(self.state.last_clicked_element, False)

        dpg.set_value(sender, True)

        is_double = self._is_double_click(sender)

        if entry.is_dir:
            if is_double:
                self.logic.navigate_to(entry.full_path)
                return
            if self._config.mode == DialogMode.OPEN_DIRS:
                self.state.selected_files = [entry.full_path]

        elif not entry.is_dir:
            ext = os.path.splitext(entry.name)[1].lower()
            is_archive = ext in (ZIP_EXTS | SEVEN_Z_EXTS)
            
            if is_archive and is_double:
                self.logic.navigate_to(entry.full_path + "|/")
                return
            
            self.state.selected_files = [entry.full_path]
            dpg.set_value(self._filename_input, entry.name)
            if is_double:
                self._return_selection()
                return

        rows = dpg.get_item_children(self._explorer_table, 1)
        for rid, ent in self.state.row_entries.items():
            if ent is entry:
                try:
                    self.state.focused_row_index = rows.index(rid)
                except ValueError:
                    pass
                break

        self._preview.update(entry)

    # ── Selection & return ──────────────────────────────────────

    def _return_selection(self) -> None:
        """Invoke callback with selected files and hide the dialog.

        Archive virtual paths (``archive|/inner``) are extracted to the
        session temp dir first. Extraction failure leaves the dialog open.
        """
        typed_name = dpg.get_value(self._filename_input)
        selection = build_selection_list(
            self.state.selected_files, typed_name, self.state.current_dir,
        )

        needs_extract = any("|" in path for path in selection)
        original_title = None
        if needs_extract and dpg.does_item_exist(self._config.tag):
            original_title = dpg.get_item_label(self._config.tag)
            dpg.set_item_label(
                self._config.tag, f"{original_title} - Extracting...",
            )
        try:
            resolved, failed_name = resolve_archive_selection(
                selection, max_size=self._MAX_ARCHIVE_EXTRACT_SIZE,
            )
        finally:
            if original_title is not None and dpg.does_item_exist(self._config.tag):
                dpg.set_item_label(self._config.tag, original_title)

        if failed_name is not None:
            self._show_message(
                "Extraction Error",
                f"Could not extract '{failed_name}' from archive.\n"
                "It might be encrypted, corrupted, or larger than the "
                "extraction limit.",
            )
            return

        self.hide()
        if self._callback is not None:
            self._callback(resolved)
        self.state.selected_files.clear()
        self.state.selected_elements.clear()

    def _on_ok(self, sender, app_data, user_data) -> None:
        """Handle OK button click — returns current selection."""
        self._return_selection()

    def _on_cancel(self, sender, app_data, user_data) -> None:
        """Handle Cancel button click — hides dialog without callback."""
        self.hide()

    # ── Search & filter ─────────────────────────────────────────

    def _on_search(self, sender, app_data, user_data) -> None:
        """Handle search field input — debounced to avoid per-keystroke rescans.

        Listing the directory (os.scandir + stat per entry) on every keystroke
        freezes the UI on large folders. Both the shallow listing and the
        recursive subfolder search are deferred until the user pauses typing.
        """
        self.logic.trigger_search(dpg.get_value(sender))

    def _on_subfolder_toggle(self, sender, app_data, user_data) -> None:
        """Handle subfolder search checkbox toggle."""
        self.logic.set_search_subfolders(bool(dpg.get_value(sender)))

    def _on_filter_change(self, sender, app_data, user_data) -> None:
        """Handle file type filter combo selection change."""
        self.state.current_filter = dpg.get_value(sender)
        self.logic.refresh_listing()

    # ── Preview toggle ──────────────────────────────────────────

    def _on_preview_toggle(self) -> None:
        """Toggle preview panel and update button theme."""
        self._preview.toggle(self._explorer_table)
        if self._preview_btn is not None and dpg.does_item_exist(self._preview_btn):
            if self._preview.visible:
                dpg.bind_item_theme(
                    self._preview_btn,
                    FileDialog._shared_preview_active_theme,
                )
            else:
                dpg.bind_item_theme(self._preview_btn, 0)

    # ── Message box ─────────────────────────────────────────────

    def _show_message(self, title: str, message: str) -> None:
        """Show an error message in the dialog."""
        if self._config.modal:
            if hasattr(self, "_status_label") and dpg.does_item_exist(self._status_label):
                status_text = f"{title}: {message}"
                dpg.set_value(self._status_label, status_text)
                dpg.show_item(self._status_label)
            else:
                _log.warning("FileDialog: %s: %s", title, message)
            return

        with dpg.mutex():
            vp_w = dpg.get_viewport_client_width()
            vp_h = dpg.get_viewport_client_height()
            with dpg.window(label=title, no_close=True, modal=True) as modal_id:
                dpg.add_text(message)
                with dpg.group(horizontal=True):
                    dpg.add_button(
                        label="Ok",
                        width=-1,
                        callback=lambda s, ad, ud: dpg.delete_item(modal_id),
                    )
        dpg.split_frame()
        w = dpg.get_item_width(modal_id)
        h = dpg.get_item_height(modal_id)
        dpg.set_item_pos(modal_id, [vp_w // 2 - w // 2, vp_h // 2 - h // 2])

    # ── New folder ───────────────────────────────────────────────

    def _show_new_folder_dialog(self) -> None:
        """Toggle the inline new-folder input bar."""
        if dpg.is_item_shown(self._new_folder_group):
            dpg.hide_item(self._new_folder_group)
        else:
            dpg.set_value(self._new_folder_input, "")
            dpg.show_item(self._new_folder_group)
            dpg.focus_item(self._new_folder_input)

    def _on_new_folder_confirm(self, sender, app_data, user_data) -> None:
        """Handle new folder input confirmation."""
        name = dpg.get_value(self._new_folder_input)
        dpg.hide_item(self._new_folder_group)
        if name:
            self.logic._create_new_folder(name)
