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
# MIT licensed

import logging
import os
import threading
import time
import uuid
from typing import Callable

import dearpygui.dearpygui as dpg  # type: ignore[import-untyped]

_log = logging.getLogger(__name__)

from ._types import DialogConfig, DialogMode, StyleVariant, FileEntry, DEFAULT_FILTER_LIST
from ._icons import IconRegistry
from ._filesystem import DirectoryLister, DirectoryIndex, validate_folder_name, build_selection_list
from ._preview_registry import ZIP_EXTS, SEVEN_Z_EXTS
from ._styles import STYLE_REGISTRY
from ._preview import PreviewPanel
from ._keyboard import KeyboardMixin
from . import _platform


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

    _DEFAULT_IMAGE_TRANSPARENCY: int = 100
    """Alpha value (0-255) for hidden file icon tinting."""

    _SIZE_CACHE_TTL: float = 60.0
    """Seconds before a cached directory size is considered stale."""

    _DEEP_SEARCH_DEBOUNCE: float = 0.3
    """Seconds to wait after last keystroke before triggering deep search."""

    _shared_selec_theme: int | None = None
    _shared_size_theme: int | None = None
    _shared_preview_active_theme: int | None = None
    _instance_count: int = 0

    def __init__(
        self,
        callback: Callable | None = None,
        config: DialogConfig | None = None,
        **kwargs,
    ):
        # Build config from kwargs if not provided directly
        if config is not None:
            self._config = config
        else:
            self._config = DialogConfig(**kwargs)

        # Two dialogs sharing a tag (e.g. separate open + save with the default
        # config) crash in dpg.window(tag=...). If the tag is already a live DPG
        # item, switch to a unique one so construction never fails.
        if dpg.does_item_exist(self._config.tag):
            self._config.tag = f"{self._config.tag}_{uuid.uuid4().hex[:8]}"

        self._callback = callback
        self._destroyed = False

        # Resolve default_path at runtime (not at import time)
        self._current_dir = (
            os.path.abspath(self._config.default_path)
            if self._config.default_path else os.getcwd()
        )
        self._home_dir = self._current_dir

        # Resolve filter_list (None → default, explicit [] kept as-is)
        # Use a local copy to avoid mutating shared DialogConfig instances.
        if self._config.filter_list is None:
            self._filter_list = list(DEFAULT_FILTER_LIST)
        else:
            self._filter_list = list(self._config.filter_list)

        # Internal state
        self._current_filter: str = self._config.file_filter
        self._selected_files: list[str] = []
        self._selected_elements: list[int] = []
        self._last_click_time: float = 0
        self._last_clicked_element: int | None = None
        self._focused_row_index: int = -1
        self._row_entries: dict[int, FileEntry] = {}
        self._history: list[str] = []
        self._is_navigating_history: bool = False

        # Preview panel (delegate)
        self._preview = PreviewPanel(
            config_tag=self._config.tag,
            preview_width=self._config.preview_width,
            show=self._config.show_preview,
        )

        # Async directory size state
        self._size_cache: dict[str, tuple[int | None, float]] = {}
        self._pending_size_cells: dict[str, int] = {}
        self._bg_generation: int = 0

        # Background directory index for recursive search
        self._dir_index = DirectoryIndex()
        self._index_generation: int = 0
        self._search_debounce_timer: threading.Timer | None = None
        self._deep_separator_row: int | None = None

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
        self._build_ui()

    # ── Public API ──────────────────────────────────────────────

    def show(self) -> None:
        """Show the file dialog window and navigate to default directory."""
        self._navigate_to(self._current_dir)
        dpg.show_item(self._config.tag)

    def hide(self) -> None:
        """Hide the file dialog window."""
        dpg.hide_item(self._config.tag)

    def destroy(self) -> None:
        """Release all DPG resources (textures, handlers, windows, themes)."""
        if self._destroyed:
            return
        self._destroyed = True
        self._cancel_background_tasks()
        self._preview.destroy()
        self._icons.destroy()
        if hasattr(self, "_key_handler") and dpg.does_item_exist(self._key_handler):
            dpg.delete_item(self._key_handler)
        if dpg.does_item_exist(self._config.tag):
            dpg.delete_item(self._config.tag)

        # Cleanup any temporary files extracted during this session
        DirectoryLister.cleanup_temp_files()

        FileDialog._instance_count -= 1
        if FileDialog._instance_count <= 0:
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

    def _cancel_pending_search(self) -> None:
        """Cancel a scheduled recursive search callback, if any."""
        if self._search_debounce_timer is not None:
            self._search_debounce_timer.cancel()
            self._search_debounce_timer = None

    def _cancel_background_tasks(self) -> None:
        """Invalidate pending size, search, and directory-index work."""
        self._bg_generation += 1
        self._index_generation += 1
        self._dir_index.invalidate()
        self._cancel_pending_search()

    # ── Navigation ──────────────────────────────────────────────

    def _go_back(self) -> None:
        """Navigate to the previous folder in history."""
        if not self._history:
            return
            
        # Current path is at the end, so we need to pop it if it matches current_dir
        if self._history[-1] == self._current_dir and len(self._history) > 1:
            self._history.pop()
            
        if self._history:
            prev_path = self._history.pop()
            self._is_navigating_history = True
            try:
                self._navigate_to(prev_path)
            finally:
                self._is_navigating_history = False

    def _go_up(self) -> None:
        """Navigate to the parent directory."""
        if "|" in self._current_dir:
            parts = self._current_dir.split("|", 1)
            archive_path = parts[0]
            virtual_path = parts[1].strip("/")
            
            if not virtual_path:
                # We are at the root of archive, go to its parent folder
                self._navigate_to(os.path.dirname(archive_path))
            else:
                # Go up inside the archive
                parent_virtual = os.path.dirname(virtual_path).replace("\\", "/")
                if parent_virtual in (".", "/"):
                     parent_virtual = ""
                self._navigate_to(f"{archive_path}|/{parent_virtual}")
        else:
            parent = os.path.dirname(self._current_dir)
            if parent != self._current_dir: # Avoid infinite loop at root
                self._navigate_to(parent)

    def _navigate_to(self, path: str) -> None:
        """Change current directory WITHOUT os.chdir."""
        if "|" in path:
            # Handle virtual archive path
            parts = path.split("|", 1)
            archive_path = parts[0]
            virtual_inner = parts[1].replace("\\", "/").strip("/")
            
            if os.path.isabs(archive_path):
                resolved_archive = os.path.normpath(archive_path)
            else:
                resolved_archive = os.path.normpath(os.path.join(self._current_dir.split("|")[0], archive_path))
                
            if not os.path.isfile(resolved_archive):
                self._show_message(
                    "Path not found",
                    f"The archive '{resolved_archive}' does not exist or is not a file."
                )
                dpg.configure_item(self._path_input, default_value=self._current_dir)
                return
                
            resolved = f"{resolved_archive}|/{virtual_inner}" if virtual_inner else f"{resolved_archive}|/"
            self._current_dir = resolved
            self._refresh_listing()
            return

        if os.path.isabs(path):
            resolved = os.path.normpath(path)
        else:
            resolved = os.path.normpath(os.path.join(self._current_dir, path))

        if not os.path.isdir(resolved):
            self._show_message(
                "Path not found",
                f"The path '{resolved}' does not exist or is not a directory."
            )
            dpg.configure_item(self._path_input, default_value=self._current_dir)
            return

        try:
            # Cheap access/existence probe: opening the dir handle is enough.
            # We deliberately do NOT enumerate here — list_directory does the
            # real work but swallows errors silently, so this probe is what
            # surfaces "Permission denied" to the user.
            with os.scandir(resolved):
                pass
        except PermissionError as e:
            self._show_message(
                "Permission denied",
                f"Cannot open the folder because access is denied.\n\n{e}"
            )
            dpg.configure_item(self._path_input, default_value=self._current_dir)
            return
        except OSError as e:
            self._show_message(
                "Error",
                f"Cannot access the folder.\n\n{e}"
            )
            dpg.configure_item(self._path_input, default_value=self._current_dir)
            return

        self._current_dir = resolved
        
        # Track history
        if not self._is_navigating_history:
            if not self._history or self._history[-1] != resolved:
                self._history.append(resolved)
                # Cap history size
                if len(self._history) > 50:
                    self._history.pop(0)

        self._refresh_listing()
        if self._config.search_subfolders:
            self._start_index_build()

    def _on_path_enter(self, sender, app_data, user_data) -> None:
        """Handle Enter key in the path input field."""
        path = dpg.get_value(sender)
        if path:
            self._navigate_to(path)

    def _on_back(self, sender, app_data, user_data) -> None:
        """Handle click on the '..' row (double-click navigates to parent)."""
        if _platform.is_mod_key_down():
            dpg.set_value(sender, False)
            return

        dpg.set_value(sender, False)
        if self._is_double_click(sender):
            if "|" in self._current_dir:
                parts = self._current_dir.split("|", 1)
                archive = parts[0]
                inner = parts[1].strip("/")
                if not inner:
                    # We are at the root of the archive, fallback to host folder
                    self._navigate_to(os.path.dirname(archive))
                else:
                    parent_inner = os.path.dirname(inner)
                    self._navigate_to(f"{archive}|/{parent_inner}" if parent_inner else f"{archive}|/")
            else:
                self._navigate_to(os.path.dirname(self._current_dir))

    def _is_double_click(self, sender: int) -> bool:
        """Check if this click constitutes a double-click on the same element."""
        current_time = time.time()
        is_double = (
            current_time - self._last_click_time < self.DOUBLE_CLICK_THRESHOLD
            and self._last_clicked_element == sender
        )
        if is_double:
            self._last_click_time = 0
            self._last_clicked_element = None
        else:
            self._last_click_time = current_time
            self._last_clicked_element = sender
        return is_double

    # ── File listing ────────────────────────────────────────────

    def _refresh_listing(self, search_query: str = "") -> None:
        """Re-render the file listing table with current directory contents."""
        self._selected_files.clear()
        self._selected_elements.clear()
        self._last_clicked_element = None
        self._focused_row_index = -1
        self._row_entries.clear()
        self._pending_size_cells.clear()
        self._bg_generation += 1
        self._deep_separator_row = None
        self._cancel_pending_search()
        self._preview.clear()

        if hasattr(self, "_status_label") and dpg.does_item_exist(self._status_label):
            dpg.hide_item(self._status_label)

        dpg.configure_item(self._path_input, default_value=self._current_dir)

        for child in dpg.get_item_children(self._explorer_table, 1):
            dpg.delete_item(child)

        with dpg.table_row(parent=self._explorer_table):
            dpg.add_selectable(
                label="..",
                callback=self._on_back,
                span_columns=True,
                height=self._selec_height,
            )

        entries = DirectoryLister.list_directory(
            self._current_dir,
            show_hidden=self._config.show_hidden,
            dirs_only=(self._config.mode == DialogMode.OPEN_DIRS),
            file_filter=self._current_filter,
            search_query=search_query,
            show_dir_size=False,
        )

        for entry in entries:
            try:
                self._render_entry(entry)
            except Exception:
                _log.debug("Failed to render entry %s", entry.name, exc_info=True)
                continue

        if self._config.show_dir_size:
            self._start_size_computation()

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
            entry = self._row_entries.get(row_id)
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
                    cached = self._size_cache.get(entry.full_path)
                    if cached is not None:
                        size = cached[0]
                return (dir_order, size or 0)
            return (dir_order,)

        sep = self._deep_separator_row
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

    def _render_entry(self, entry: FileEntry, *, relative_label: bool = False) -> None:
        """Render a single file/directory entry as a table row with icon.

        Args:
            entry: The file entry to render.
            relative_label: If True, display relative path instead of name
                (used for deep-search results).
        """
        if entry.is_dir:
            icon_tag = self._icons.get_for_dir()
        else:
            icon_tag = self._icons.get_for_file(entry.name)

        # Label
        if relative_label:
            try:
                label = os.path.relpath(entry.full_path, self._current_dir)
            except ValueError:
                label = entry.full_path
        else:
            label = entry.name

        # Format display values
        display_time = DirectoryLister.format_time(entry.modified_time)
        display_type = "Dir" if entry.is_dir else "File"
        if entry.is_dir and self._config.show_dir_size and not relative_label:
            cached = self._size_cache.get(entry.full_path)
            if cached is not None and time.time() - cached[1] < self._SIZE_CACHE_TTL:
                display_size = DirectoryLister.format_size(cached[0])
            else:
                display_size = "..."
        else:
            display_size = DirectoryLister.format_size(entry.size_bytes)

        tint = (
            [255, 255, 255, self._image_transparency]
            if entry.is_hidden
            else [255, 255, 255, 255]
        )

        kwargs_cell = {
            "callback": self._on_entry_click,
            "span_columns": True,
            "height": self._selec_height,
            "user_data": entry,
        }

        with dpg.table_row(parent=self._explorer_table) as row_id:
            self._row_entries[row_id] = entry

            with dpg.group(horizontal=True):
                if icon_tag:
                    dpg.add_image(icon_tag, tint_color=tint)
                cell_name = dpg.add_selectable(label=label, **kwargs_cell)

            cell_time = dpg.add_selectable(label=display_time, **kwargs_cell)
            cell_type = dpg.add_selectable(label=display_type, **kwargs_cell)
            cell_size = dpg.add_selectable(label=display_size, **kwargs_cell)

            if entry.is_dir and self._config.show_dir_size and display_size == "...":
                self._pending_size_cells[entry.full_path] = cell_size

            dpg.bind_item_theme(cell_name, self._selec_theme)
            dpg.bind_item_theme(cell_time, self._selec_theme)
            dpg.bind_item_theme(cell_type, self._selec_theme)
            dpg.bind_item_theme(cell_size, self._size_theme)

            if self._config.allow_drag:
                drag = dpg.add_drag_payload(
                    parent=cell_name, payload_type=self._payload_type
                )
                if entry.is_dir:
                    folder_icon = self._icons.get("folder")
                    if folder_icon:
                        dpg.add_image(folder_icon, parent=drag)
                elif os.path.splitext(entry.name)[1].lower() in PreviewPanel.preview_image_exts():
                    big_pic = self._icons.get("big_picture")
                    if big_pic:
                        dpg.add_image(big_pic, parent=drag)
                else:
                    doc_icon = self._icons.get("document")
                    if doc_icon:
                        dpg.add_image(doc_icon, parent=drag)

    # ── Click handling ──────────────────────────────────────────

    def _on_entry_click(self, sender, app_data, user_data) -> None:
        """Handle click on a file/directory entry (single and multi-select)."""
        entry: FileEntry = user_data

        if _platform.is_mod_key_down():
            if self._config.multi_selection:
                if dpg.get_value(sender) is True:
                    self._selected_files.append(entry.full_path)
                    self._selected_elements.append(sender)
                else:
                    if entry.full_path in self._selected_files:
                        self._selected_files.remove(entry.full_path)
                    if sender in self._selected_elements:
                        self._selected_elements.remove(sender)
            rows = dpg.get_item_children(self._explorer_table, 1)
            for rid, ent in self._row_entries.items():
                if ent is entry:
                    try:
                        self._focused_row_index = rows.index(rid)
                    except ValueError:
                        pass
                    break
            self._preview.update(entry if dpg.get_value(sender) else None)
            return

        if self._selected_files:
            self._selected_files.clear()
            for elem in self._selected_elements:
                if dpg.does_item_exist(elem):
                    dpg.set_value(elem, False)
            self._selected_elements.clear()
        if (self._last_clicked_element is not None
                and dpg.does_item_exist(self._last_clicked_element)):
            dpg.set_value(self._last_clicked_element, False)

        dpg.set_value(sender, True)

        is_double = self._is_double_click(sender)

        if entry.is_dir:
            if is_double:
                self._navigate_to(entry.full_path)
                return
            if self._config.mode == DialogMode.OPEN_DIRS:
                self._selected_files = [entry.full_path]

        elif not entry.is_dir:
            ext = os.path.splitext(entry.name)[1].lower()
            is_archive = ext in (ZIP_EXTS | SEVEN_Z_EXTS)
            
            if is_archive and is_double:
                self._navigate_to(entry.full_path + "|/")
                return
            
            self._selected_files = [entry.full_path]
            dpg.set_value(self._filename_input, entry.name)
            if is_double:
                # If it's a virtual path (inside archive), extract it first
                if "|" in entry.full_path:
                    # Visual feedback that we are working
                    original_title = dpg.get_item_label(self._config.tag)
                    dpg.set_item_label(self._config.tag, f"{original_title} - Extracting...")
                    try:
                        temp_path = DirectoryLister.extract_from_archive(entry.full_path)
                    finally:
                        if dpg.does_item_exist(self._config.tag):
                            dpg.set_item_label(self._config.tag, original_title)

                    if temp_path:
                        self._selected_files = [temp_path]
                    else:
                        self._show_message(
                            "Extraction Error",
                            f"Could not extract '{entry.name}' from archive.\n"
                            "It might be encrypted or corrupted."
                        )
                        return
                
                self._return_selection()
                return

        rows = dpg.get_item_children(self._explorer_table, 1)
        for rid, ent in self._row_entries.items():
            if ent is entry:
                try:
                    self._focused_row_index = rows.index(rid)
                except ValueError:
                    pass
                break

        self._preview.update(entry)

    # ── Selection & return ──────────────────────────────────────

    def _return_selection(self) -> None:
        """Invoke callback with selected files and hide the dialog."""
        typed_name = dpg.get_value(self._filename_input)
        selection = build_selection_list(
            self._selected_files, typed_name, self._current_dir,
        )

        self.hide()
        if self._callback is not None:
            self._callback(selection)
        self._selected_files.clear()
        self._selected_elements.clear()

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
        self._schedule_search(dpg.get_value(sender))

    def _schedule_search(self, query: str) -> None:
        """(Re)start the debounce timer for a search refresh of *query*."""
        self._cancel_pending_search()

        gen = self._bg_generation
        self._search_debounce_timer = threading.Timer(
            self._DEEP_SEARCH_DEBOUNCE,
            self._run_search,
            args=(query, gen),
        )
        self._search_debounce_timer.daemon = True
        self._search_debounce_timer.start()

    def _run_search(self, query: str, expected_gen: int) -> None:
        """Run the debounced shallow listing refresh and optional deep search."""
        if self._bg_generation != expected_gen:
            return
        with dpg.mutex():
            if self._bg_generation != expected_gen:
                return
            if not dpg.does_item_exist(self._explorer_table):
                return
            self._refresh_listing(search_query=query)

        subfolder_on = (
            self._config.search_subfolders
            and hasattr(self, "_subfolder_checkbox")
            and dpg.get_value(self._subfolder_checkbox)
        )
        if query and subfolder_on and self._dir_index.ready:
            # _refresh_listing bumped _bg_generation; pass the fresh value so the
            # deep-search generation guard does not reject it.
            self._run_deep_search(query, self._bg_generation)

        # A keystroke landing while this refresh ran was dropped: its timer got
        # cancelled by _refresh_listing and its generation snapshot invalidated.
        # If the box now holds a different query, schedule a fresh pass for it.
        if dpg.does_item_exist(self._search_input):
            current_query = dpg.get_value(self._search_input)
            if current_query != query:
                self._schedule_search(current_query)

    def _on_subfolder_toggle(self, sender, app_data, user_data) -> None:
        """Handle subfolder search checkbox toggle."""
        enabled = dpg.get_value(sender)
        if enabled and not self._dir_index.ready:
            self._start_index_build()

    def _on_filter_change(self, sender, app_data, user_data) -> None:
        """Handle file type filter combo selection change."""
        self._current_filter = dpg.get_value(sender)
        self._refresh_listing()

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
            self._create_new_folder(name)

    def _create_new_folder(self, name: str) -> None:
        """Create a new folder in the current directory."""
        error = validate_folder_name(name, self._current_dir)
        if error:
            self._show_message("Error", error)
            return

        new_path = os.path.join(self._current_dir, name)

        try:
            os.makedirs(new_path, exist_ok=False)
            self._refresh_listing()
        except FileExistsError:
            self._show_message("Error", f"Folder '{name}' already exists.")
        except PermissionError:
            self._show_message("Error", f"Permission denied to create '{name}'.")
        except OSError as e:
            self._show_message("Error", f"Cannot create folder.\n\n{e}")

    # ── Async directory size computation ────────────────────────

    def _start_size_computation(self) -> None:
        """Start a background thread to compute pending directory sizes."""
        if not self._pending_size_cells:
            return
        gen = self._bg_generation
        pending = dict(self._pending_size_cells)
        thread = threading.Thread(
            target=self._compute_sizes_bg,
            args=(gen, pending),
            daemon=True,
        )
        thread.start()

    def _compute_sizes_bg(self, generation: int, cells: dict[str, int]) -> None:
        """Background thread: compute directory sizes and update UI cells."""
        for path, cell_id in cells.items():
            if self._bg_generation != generation:
                return
            size = DirectoryLister.compute_dir_size(path)
            self._size_cache[path] = (size, time.time())
            if self._bg_generation != generation:
                return
            with dpg.mutex():
                if dpg.does_item_exist(cell_id):
                    dpg.configure_item(cell_id, label=DirectoryLister.format_size(size))

    # ── Background directory index ─────────────────────────────

    def _start_index_build(self) -> None:
        """Kick off a background thread to (re)build the directory index."""
        self._dir_index.invalidate()
        self._index_generation += 1
        gen = self._index_generation
        thread = threading.Thread(
            target=self._dir_index.build,
            args=(self._current_dir, gen, lambda: self._index_generation),
            daemon=True,
        )
        thread.start()

    def _run_deep_search(self, query: str, expected_gen: int) -> None:
        """Execute a deep search on the background index and append results."""
        if self._bg_generation != expected_gen:
            return
        if not self._dir_index.ready:
            return

        deep_entries = self._dir_index.search(
            query,
            show_hidden=self._config.show_hidden,
            dirs_only=(self._config.mode == DialogMode.OPEN_DIRS),
            file_filter=self._current_filter,
        )
        if not deep_entries:
            return

        with dpg.mutex():
            if self._bg_generation != expected_gen:
                return
            if not dpg.does_item_exist(self._explorer_table):
                return
            current_paths = {e.full_path for e in self._row_entries.values()}
            new_entries = [e for e in deep_entries if e.full_path not in current_paths]
            if not new_entries:
                return
            with dpg.table_row(parent=self._explorer_table) as sep_row:
                dpg.add_selectable(
                    label="--- subfolders ---",
                    span_columns=True,
                    height=self._selec_height,
                    enabled=False,
                )
            self._deep_separator_row = sep_row
            for entry in new_entries:
                try:
                    self._render_entry(entry, relative_label=True)
                except Exception:
                    _log.debug("Failed to render deep-search entry %s", entry.name, exc_info=True)
                    continue

    # ── UI construction ─────────────────────────────────────────

    def _build_ui(self) -> None:
        """Construct the complete DPG widget tree."""
        self._build_themes()
        tag = self._config.tag
        info_px = 56

        with dpg.window(
            label=self._config.title,
            tag=tag,
            no_resize=self._config.no_resize,
            show=False,
            modal=self._config.modal,
            width=self._config.width,
            height=self._config.height,
            min_size=self._config.min_size,
            no_collapse=True,
            pos=(50, 50),
        ):
            with dpg.group(horizontal=True):
                self._build_sidebar(tag, info_px)
                self._build_explorer_area(info_px)
            self._build_bottom_bar()
            self._status_label = dpg.add_text(
                "", color=[255, 80, 80], show=False
            )

        self._build_keyboard_handlers()
        if self._config.show_preview:
            self._preview.build_handlers(tag, self._is_dialog_active)

    def _build_themes(self) -> None:
        """Create shared selectable themes (once, reused across instances)."""
        if FileDialog._shared_selec_theme is None:
            with dpg.theme() as FileDialog._shared_selec_theme:
                with dpg.theme_component(dpg.mvThemeCat_Core):
                    dpg.add_theme_style(
                        dpg.mvStyleVar_SelectableTextAlign, x=0, y=0.5
                    )
        if FileDialog._shared_size_theme is None:
            with dpg.theme() as FileDialog._shared_size_theme:
                with dpg.theme_component(dpg.mvThemeCat_Core):
                    dpg.add_theme_style(
                        dpg.mvStyleVar_SelectableTextAlign, x=1, y=0.5
                    )
        if FileDialog._shared_preview_active_theme is None:
            with dpg.theme() as FileDialog._shared_preview_active_theme:
                with dpg.theme_component(dpg.mvThemeCat_Core):
                    dpg.add_theme_color(
                        dpg.mvThemeCol_Button, (70, 130, 180, 255)
                    )
                    dpg.add_theme_color(
                        dpg.mvThemeCol_ButtonHovered, (80, 145, 200, 255)
                    )
                    dpg.add_theme_color(
                        dpg.mvThemeCol_ButtonActive, (60, 115, 160, 255)
                    )
        self._selec_theme = FileDialog._shared_selec_theme
        self._size_theme = FileDialog._shared_size_theme
        self._preview_btn: int | None = None
        FileDialog._instance_count += 1

    def _build_sidebar(self, tag: str, info_px: int) -> None:
        """Build the sidebar with shortcuts and drives."""
        if not self._config.show_shortcuts:
            return
        sidebar_tag = f"{tag}_shortcut_menu"
        with dpg.child_window(
            tag=sidebar_tag,
            width=self._sidebar.get_width(),
            resizable_x=self._sidebar.is_resizable(),
            height=-info_px,
        ):
            shortcuts = _platform.get_special_dirs()
            drives = _platform.get_drives()
            self._sidebar.render(
                parent=sidebar_tag,
                shortcuts=shortcuts,
                drives=drives,
                icons=self._icons,
                on_navigate=self._navigate_to,
                custom_dirs=self._config.custom_dirs,
            )

    def _build_explorer_area(self, info_px: int) -> None:
        """Build the main explorer area: toolbar, search, table, preview."""
        with dpg.child_window(height=-info_px):
            self._build_toolbar()
            self._build_search_bar()
            self._build_new_folder_bar()
            self._build_explorer_table()

    def _build_toolbar(self) -> None:
        """Build the toolbar row (refresh, back, up, path, preview toggle)."""
        with dpg.group(horizontal=True):
            refresh_icon = self._icons.get("refresh")
            if refresh_icon:
                btn = dpg.add_image_button(
                    refresh_icon,
                    callback=lambda s, ad, ud: self._refresh_listing(),
                )
                with dpg.tooltip(btn):
                    dpg.add_text("Refresh (F5)")

            back_icon = self._icons.get("back")
            if back_icon:
                btn = dpg.add_image_button(
                    back_icon,
                    callback=lambda s, ad, ud: self._go_back(),
                )
                with dpg.tooltip(btn):
                    dpg.add_text("Back")

            up_icon = self._icons.get("up")
            if up_icon:
                btn = dpg.add_image_button(
                    up_icon,
                    callback=lambda s, ad, ud: self._go_up(),
                )
                with dpg.tooltip(btn):
                    dpg.add_text("Up (Alt+Up)")

            self._path_input = dpg.add_input_text(
                hint="Path",
                on_enter=True,
                callback=self._on_path_enter,
                default_value=self._current_dir,
                width=-40 if self._config.show_preview else -1,
            )
            if self._config.show_preview:
                preview_icon = self._icons.get("picture")
                if preview_icon:
                    self._preview_btn = dpg.add_image_button(
                        preview_icon,
                        callback=lambda s, ad, ud: self._on_preview_toggle(),
                    )
                else:
                    self._preview_btn = dpg.add_button(
                        label="P",
                        callback=lambda s, ad, ud: self._on_preview_toggle(),
                    )
                with dpg.tooltip(self._preview_btn):
                    dpg.add_text("Preview")
                if self._preview.visible:
                    dpg.bind_item_theme(
                        self._preview_btn,
                        FileDialog._shared_preview_active_theme,
                    )

    def _build_search_bar(self) -> None:
        """Build the search input row with new-folder button and optional subfolder checkbox."""
        with dpg.group(horizontal=True):
            add_folder_icon = self._icons.get("add_folder")
            if add_folder_icon:
                btn = dpg.add_image_button(
                    add_folder_icon,
                    callback=lambda s, ad, ud: self._show_new_folder_dialog(),
                )
                with dpg.tooltip(btn):
                    dpg.add_text("New folder")
            search_icon = self._icons.get("search")
            if search_icon:
                dpg.add_image(search_icon)
            self._search_input = dpg.add_input_text(
                hint="Search files",
                callback=self._on_search,
                width=-120 if self._config.search_subfolders else -1,
            )
            if self._config.search_subfolders:
                self._subfolder_checkbox = dpg.add_checkbox(
                    label="Subfolders",
                    default_value=True,
                    callback=self._on_subfolder_toggle,
                )
                with dpg.tooltip(self._subfolder_checkbox):
                    dpg.add_text("Search in subfolders")

    def _build_new_folder_bar(self) -> None:
        """Build the inline new-folder input bar (hidden by default)."""
        with dpg.group(
            horizontal=True, show=False
        ) as self._new_folder_group:
            add_folder_small = self._icons.get("mini_folder")
            if add_folder_small:
                dpg.add_image(add_folder_small)
            self._new_folder_input = dpg.add_input_text(
                hint="New folder name",
                on_enter=True,
                callback=self._on_new_folder_confirm,
                width=-150,
            )
            dpg.add_button(
                label="Create",
                callback=lambda s, ad, ud: self._on_new_folder_confirm(s, ad, ud),
            )
            dpg.add_button(
                label="Cancel",
                callback=lambda s, ad, ud: dpg.hide_item(self._new_folder_group),
            )

    def _build_explorer_table(self) -> None:
        """Build the explorer table and optional preview panel."""
        with dpg.group(horizontal=True):
            table_width = (
                -(self._config.preview_width + 8)
                if self._config.show_preview
                else -1
            )
            with dpg.child_window(
                width=table_width,
                height=-1,
                resizable_x=self._config.show_preview,
            ) as table_wrapper:
                with dpg.table(
                    height=-1,
                    width=-1,
                    resizable=True,
                    policy=dpg.mvTable_SizingStretchProp,
                    borders_innerV=True,
                    reorderable=True,
                    hideable=True,
                    scrollX=True,
                    scrollY=True,
                    sortable=True,
                    callback=self._on_sort,
                ) as self._explorer_table:
                    dpg.add_table_column(label="Name", init_width_or_weight=100)
                    dpg.add_table_column(label="Date", init_width_or_weight=50)
                    dpg.add_table_column(label="Type", init_width_or_weight=10)
                    dpg.add_table_column(label="Size", init_width_or_weight=10)

            if self._config.show_preview:
                with dpg.child_window(
                    width=-1, height=-1,
                    no_scroll_with_mouse=True,
                ) as preview_panel:
                    dpg.add_text("Preview", color=[128, 128, 128])
                self._preview.attach(table_wrapper, preview_panel)
            else:
                self._preview.attach(table_wrapper, None)

    def _build_bottom_bar(self) -> None:
        """Build filename input, filter combo, and OK/Cancel buttons."""
        with dpg.group(horizontal=True):
            dpg.add_text("File name:")
            self._filename_input = dpg.add_input_text(
                hint="",
                on_enter=True,
                callback=lambda s, ad, ud: self._on_ok(s, ad, ud),
                width=-250,
            )
            dpg.add_combo(
                items=self._filter_list,
                callback=self._on_filter_change,
                default_value=self._current_filter,
                width=-1,
            )

        with dpg.table(
            header_row=False,
            policy=dpg.mvTable_SizingStretchProp,
            borders_innerV=False,
            borders_outerV=False,
            borders_innerH=False,
            borders_outerH=False,
            pad_outerX=False,
        ):
            dpg.add_table_column()
            dpg.add_table_column(width_fixed=True)
            dpg.add_table_column(width_fixed=True)
            with dpg.table_row():
                dpg.add_spacer()
                btn_ok = dpg.add_button(
                    label="  Open  ",
                    callback=self._on_ok,
                )
                with dpg.tooltip(btn_ok):
                    dpg.add_text("Confirm selection (Enter)")
                btn_cancel = dpg.add_button(
                    label=" Cancel ",
                    callback=self._on_cancel,
                )
                with dpg.tooltip(btn_cancel):
                    dpg.add_text("Close dialog (Esc)")
