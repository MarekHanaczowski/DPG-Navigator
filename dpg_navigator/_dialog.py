"""Main FileDialog orchestrator for the dpg_navigator package.

Contains the FileDialog class which manages the complete DearPyGui file
dialog including sidebar navigation, file listing, real-time search with
recursive subfolder index, extension filtering, column sorting,
multi-selection, new folder creation, archive browsing (ZIP/7z), and an
optional preview panel supporting images, text, PDF, Word (.docx),
PowerPoint (.pptx), Markdown, HTML, CSV/TSV, Excel (.xlsx), SQLite
databases, fonts (.ttf/.otf), ZIP/7z archives, and source code as
plain text.
"""

from __future__ import annotations

# MIT licensed
import logging
import os
import threading
import time
import uuid
from copy import copy
from typing import Any, overload

import dearpygui.dearpygui as dpg  # type: ignore[import-untyped]

_log = logging.getLogger(__name__)

from . import _platform
from ._filesystem import (
    DirectoryIndex,
    DirectoryLister,
    build_selection_list,
    is_archive_virtual_path,
    resolve_archive_selection,
)
from ._icons import IconRegistry
from ._job_manager import JobManager
from ._keyboard import KeyboardMixin
from ._preview import PreviewPanel
from ._preview_limits import ARCHIVE_EXTRACT_MAX_BYTES
from ._preview_registry import SEVEN_Z_EXTS, ZIP_EXTS
from ._styles import STYLE_REGISTRY
from ._types import (
    DEFAULT_FILTER_LIST,
    DialogConfig,
    DialogMode,
    FileEntry,
    SelectionCallback,
    StyleVariant,
)
from .dialog._logic import DialogLogic
from .dialog._state import DialogState
from .dialog._ui import DialogUIBuilder


class FileDialog(KeyboardMixin):
    """Customizable file dialog for DearPyGui.

    Features sidebar navigation (labeled or compact), file listing with
    column sorting, real-time search with recursive subfolder index,
    extension filtering, keyboard navigation (Up/Down/Enter/Esc/F5/Alt+Up),
    multi-selection with Ctrl+click/Ctrl+A, drag-and-drop payloads,
    new folder creation, async directory size calculation, archive
    browsing (ZIP/7z), and an optional preview panel supporting:

    - Images (stb_image + Pillow; fit-to-pane, cursor-anchored zoom, LMB pan)
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
    - Source code (monospace text preview)

    Args:
        callback: Called with a ``list[str]`` of selected paths on OK.
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
    _pending_sidebar_drives: tuple[str, list[str]] | None
    _awaiting_sidebar_drives: bool
    _pending_listing: list[FileEntry] | None

    _DEFAULT_IMAGE_TRANSPARENCY: int = 100
    """Alpha value (0-255) for hidden file icon tinting."""

    _SIZE_CACHE_TTL: float = 60.0
    """Seconds before a cached directory size is considered stale."""

    _DEEP_SEARCH_DEBOUNCE: float = 0.3
    """Seconds to wait after last keystroke before triggering deep search."""

    _MAX_ARCHIVE_EXTRACT_SIZE: int = ARCHIVE_EXTRACT_MAX_BYTES
    """Anti-bomb ceiling (bytes) for extracting a selected archive member.

    Selecting a file inside an archive is a deliberate action, so this is a
    generous cap that still rejects a member declaring an absurd expanded size
    (a decompression bomb) rather than the small text-preview limit."""

    _shared_selec_theme: int | None = None
    _shared_size_theme: int | None = None
    _shared_preview_active_theme: int | None = None
    _instance_count: int = 0
    _selec_theme: Any = None
    _size_theme: Any = None
    _status_label: Any = None
    _subfolder_checkbox: Any = None
    # Drive lists computed on a worker; widget updates run on the DPG thread.
    _ui_lock: threading.Lock = threading.Lock()
    _sidebar_poll_targets: list[FileDialog] = []
    _sidebar_poll_armed: bool = False

    @overload
    def __init__(
        self,
        config: DialogConfig,
        callback: SelectionCallback | None = None,
    ) -> None: ...

    @overload
    def __init__(
        self,
        config: SelectionCallback | None = None,
        callback: SelectionCallback | None = None,
        **kwargs: Any,
    ) -> None: ...

    def __init__(
        self,
        config: DialogConfig | SelectionCallback | None = None,
        callback: SelectionCallback | None = None,
        **kwargs: Any,
    ) -> None:
        # First positional may be the host callback (FileDialog(on_select)).
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
        self._pending_sidebar_drives: tuple[str, list[str]] | None = None
        self._awaiting_sidebar_drives = False
        self._pending_listing: list[FileEntry] | None = None
        self._pending_listing_gen: int | None = None
        self._pending_size_updates: list[tuple[str, str]] = []
        self._pending_path_input: str | None = None
        self.state = DialogState()
        JobManager.ensure_running()

        # Resolve default_path at runtime (not at import time)
        self.state.current_dir = (
            os.path.abspath(self._config.default_path) if self._config.default_path else os.getcwd()
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

        # Selectable height for table rows
        self._selec_height = self._DEFAULT_SELECTABLE_HEIGHT
        self._image_transparency = self._DEFAULT_IMAGE_TRANSPARENCY

        # Drag payload type
        self._payload_type = f"ws_{self._config.tag}"

        # Widget IDs filled in by DialogUIBuilder.
        self._filter_combo: int | str | None = None

        # Everything below allocates DPG resources (preview textures, icon
        # textures, widget tree); a failure anywhere must roll back what was
        # already created so a failed constructor doesn't leak DPG items.
        try:
            self._preview = PreviewPanel(
                config=self._config,
                preview_width=self._config.preview_width,
                show=self._config.show_preview,
            )

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
        except Exception:
            self._rollback_partial_init()
            raise
        FileDialog._instance_count += 1
        FileDialog._ensure_ui_pump()

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

    def _safe_refresh_ui(self, entries: list[FileEntry], generation: int | None = None) -> None:
        """Queue a listing for the DearPyGui thread (never rebuild from a worker).

        *generation* is the ``index_generation`` the listing was produced under;
        a stale worker therefore stamps its own old value and is rejected in
        ``_apply_pending_listing`` even if it runs after a fresh navigation.
        """
        if self._destroyed:
            return
        with FileDialog._ui_lock:
            self._pending_listing = list(entries)
            if generation is None:
                state = getattr(self, "state", None)
                generation = getattr(state, "index_generation", None)
            self._pending_listing_gen = generation
        self._schedule_ui_poll()

    def _safe_update_path_input(self, path: str) -> None:
        if self._destroyed or not hasattr(self, "_path_input"):
            return
        with FileDialog._ui_lock:
            self._pending_path_input = path
        self._schedule_ui_poll()

    def _safe_update_size_cell(self, path: str, txt: str) -> None:
        if self._destroyed:
            return
        with FileDialog._ui_lock:
            updates = getattr(self, "_pending_size_updates", None)
            if updates is None:
                self._pending_size_updates = [(path, txt)]
            else:
                updates.append((path, txt))
        self._schedule_ui_poll()

    # ── Public API ──────────────────────────────────────────────

    def show(self) -> None:
        """Show the window, navigate to the default directory, apply pending drives."""
        self.logic.navigate_to(self.state.current_dir)
        dpg.show_item(self._config.tag)
        self._apply_pending_listing()
        self._apply_pending_sidebar_drives()
        self._apply_pending_size_cells()
        self._apply_pending_path_input()
        FileDialog._ensure_ui_pump()

    def hide(self) -> None:
        """Hide the file dialog window."""
        dpg.hide_item(self._config.tag)

    def _schedule_ui_poll(self) -> None:
        """Register this dialog for the next DPG-thread drain. Workers never call DPG."""
        with FileDialog._ui_lock:
            if self._destroyed:
                return
            if self not in FileDialog._sidebar_poll_targets:
                FileDialog._sidebar_poll_targets.append(self)

    def _arm_sidebar_drive_poll(self) -> None:
        """Schedule a main-thread poll so drive widgets are not built on a worker."""
        self._awaiting_sidebar_drives = True
        self._schedule_ui_poll()
        FileDialog._ensure_ui_pump()

    def _apply_pending_sidebar_drives(self) -> None:
        """Apply a worker-computed drive list. Must run on the DPG thread."""
        if self._destroyed:
            return
        with FileDialog._ui_lock:
            pending = self._pending_sidebar_drives
            if pending is None:
                return
            self._pending_sidebar_drives = None
            self._awaiting_sidebar_drives = False
        sidebar_tag, drives = pending
        if dpg.does_item_exist(sidebar_tag):
            self._sidebar.update_drives(drives)

    def _apply_pending_listing(self) -> None:
        """Apply a worker-queued directory listing. Must run on the DPG thread."""
        if self._destroyed:
            return
        with FileDialog._ui_lock:
            pending = getattr(self, "_pending_listing", None)
            pending_gen = getattr(self, "_pending_listing_gen", None)
            self._pending_listing = None
            self._pending_listing_gen = None
        if pending is None:
            return
        if pending_gen is not None and pending_gen != self.state.index_generation:
            return
        if not hasattr(self, "ui"):
            return
        with dpg.mutex():
            if self._destroyed or not hasattr(self, "ui"):
                return
            self.ui._render_entries_list(pending)
        if (
            getattr(self, "_config", None) is not None
            and self._config.show_dir_size
            and not self.state.search_query
            and hasattr(self, "logic")
        ):
            self.logic.start_size_computation(list(self.state.pending_size_cells.keys()))

    def _apply_pending_size_cells(self) -> None:
        """Apply queued directory-size labels. Must run on the DPG thread."""
        if self._destroyed:
            return
        with FileDialog._ui_lock:
            updates = list(getattr(self, "_pending_size_updates", []))
            self._pending_size_updates = []
        if not updates:
            return
        with dpg.mutex():
            if self._destroyed:
                return
            for path, txt in updates:
                cell = self.state.pending_size_cells.get(path)
                if cell is not None and dpg.does_item_exist(cell):
                    dpg.configure_item(cell, label=txt)

    def _apply_pending_path_input(self) -> None:
        """Apply a queued path-input value. Must run on the DPG thread."""
        if self._destroyed or not hasattr(self, "_path_input"):
            return
        with FileDialog._ui_lock:
            path = getattr(self, "_pending_path_input", None)
            self._pending_path_input = None
        if path is None:
            return
        with dpg.mutex():
            if self._destroyed or not dpg.does_item_exist(self._path_input):
                return
            dpg.configure_item(self._path_input, default_value=path)

    def _has_pending_ui(self) -> bool:
        return bool(
            self._awaiting_sidebar_drives
            or getattr(self, "_pending_listing", None) is not None
            or getattr(self, "_pending_sidebar_drives", None) is not None
            or getattr(self, "_pending_size_updates", None)
            or getattr(self, "_pending_path_input", None) is not None
        )

    @classmethod
    def _ensure_ui_pump(cls) -> None:
        """Arm the frame callback from the DearPyGui thread only."""
        if cls._sidebar_poll_armed:
            return
        if cls._instance_count <= 0 and not cls._sidebar_poll_targets:
            return
        cls._sidebar_poll_armed = True
        try:
            dpg.set_frame_callback(int(dpg.get_frame_count()) + 1, cls._poll_sidebar_drives)
        except Exception:
            cls._sidebar_poll_armed = False

    @classmethod
    def _schedule_sidebar_poll(cls) -> None:
        cls._ensure_ui_pump()

    @classmethod
    def _poll_sidebar_drives(cls) -> None:
        """Drain pending UI updates between frames (DPG thread)."""
        cls._sidebar_poll_armed = False
        with cls._ui_lock:
            targets = list(cls._sidebar_poll_targets)
        remaining: list[FileDialog] = []
        for dialog in targets:
            if dialog._destroyed:
                continue
            try:
                dialog._apply_pending_listing()
                dialog._apply_pending_sidebar_drives()
                dialog._apply_pending_size_cells()
                dialog._apply_pending_path_input()
            except Exception:
                _log.exception("FileDialog UI poll failed for %s", getattr(dialog._config, "tag", "?"))
            if not dialog._destroyed and dialog._has_pending_ui():
                remaining.append(dialog)
        with cls._ui_lock:
            extras = [
                dialog for dialog in cls._sidebar_poll_targets if dialog not in remaining and not dialog._destroyed
            ]
            cls._sidebar_poll_targets = remaining + extras
            keep_pumping = bool(cls._sidebar_poll_targets) or cls._instance_count > 0
        if keep_pumping:
            cls._ensure_ui_pump()

    def _rollback_partial_init(self) -> None:
        """Delete DPG items created by a failed constructor."""
        tag = getattr(getattr(self, "_config", None), "tag", None)
        handler = getattr(self, "_key_handler", None)
        try:
            if handler is not None and dpg.does_item_exist(handler):
                dpg.delete_item(handler)
        except Exception:
            _log.debug("Partial init handler cleanup failed", exc_info=True)
        try:
            if tag and dpg.does_item_exist(tag):
                dpg.delete_item(tag)
        except Exception:
            _log.debug("Partial init window cleanup failed", exc_info=True)
        preview = getattr(self, "_preview", None)
        if preview is not None:
            try:
                preview.destroy()
            except Exception:
                _log.debug("Partial init preview cleanup failed", exc_info=True)
        icons = getattr(self, "_icons", None)
        if icons is not None:
            try:
                icons.destroy()
            except Exception:
                _log.debug("Partial init icon cleanup failed", exc_info=True)

    def destroy(self) -> None:
        """Release this dialog's DPG resources.

        When the last ``FileDialog`` in the process is destroyed, also shuts
        down ``JobManager``, the extraction temp dir, and the shared Chrome
        renderer.
        """
        if self._destroyed:
            return
        self._destroyed = True
        with FileDialog._ui_lock:
            self._awaiting_sidebar_drives = False
            self._pending_sidebar_drives = None
            self._pending_listing = None
            self._pending_size_updates = []
            self._pending_path_input = None
            try:
                FileDialog._sidebar_poll_targets.remove(self)
            except ValueError:
                pass
        try:
            if hasattr(self, "logic"):
                self.logic.cancel_background_tasks()
        except Exception:
            _log.debug("Background cancel during destroy failed", exc_info=True)
        try:
            if hasattr(self, "_preview"):
                self._preview.destroy()
        except Exception:
            _log.debug("Preview destroy failed", exc_info=True)
        try:
            if hasattr(self, "_icons"):
                self._icons.destroy()
        except Exception:
            _log.debug("Icon destroy failed", exc_info=True)
        try:
            with dpg.mutex():
                if hasattr(self, "_key_handler") and dpg.does_item_exist(self._key_handler):
                    dpg.delete_item(self._key_handler)
                if hasattr(self, "_config") and dpg.does_item_exist(self._config.tag):
                    dpg.delete_item(self._config.tag)
        except Exception:
            _log.debug("DPG teardown during destroy failed", exc_info=True)
        finally:
            FileDialog._instance_count = max(0, FileDialog._instance_count - 1)
            if FileDialog._instance_count <= 0:
                JobManager.shutdown(wait=True, timeout=2.0)
                DirectoryLister.cleanup_temp_files()
                try:
                    from ._html import HTMLRenderer

                    HTMLRenderer.shutdown_shared()
                except Exception:
                    _log.debug("HTMLRenderer shutdown failed", exc_info=True)
                for attr in ("_shared_selec_theme", "_shared_size_theme", "_shared_preview_active_theme"):
                    try:
                        theme_id = getattr(FileDialog, attr)
                        if theme_id is not None and dpg.does_item_exist(theme_id):
                            dpg.delete_item(theme_id)
                    except Exception:
                        _log.debug("Shared theme teardown failed", exc_info=True)
                    setattr(FileDialog, attr, None)
                FileDialog._instance_count = 0
                FileDialog._sidebar_poll_armed = False

    def change_callback(self, callback: SelectionCallback) -> None:
        """Change the callback function. Does NOT modify the OK button directly."""
        self._callback = callback

    def __enter__(self) -> FileDialog:
        """Enter context manager; returns the FileDialog instance."""
        return self

    def __exit__(self, *args: object) -> None:
        """Exit context manager; calls destroy() to release DPG resources."""
        self.destroy()

    # ── Navigation ──────────────────────────────────────────────

    def _on_path_enter(self, sender: Any, app_data: Any, user_data: Any) -> None:
        """Handle Enter key in the path input field."""
        path = dpg.get_value(sender)
        if path:
            self.logic.navigate_to(path)

    def _on_back(self, sender: Any, app_data: Any, user_data: Any) -> None:
        """Handle click on the '..' row (double-click navigates to parent)."""
        if _platform.is_mod_key_down():
            dpg.set_value(sender, False)
            return

        dpg.set_value(sender, False)
        if self._is_double_click(sender):
            self.logic.go_up()

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

    def _on_sort(self, sender: Any, sort_specs: Any, user_data: Any) -> None:
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

        def sort_key(row_id: Any) -> tuple[Any, ...]:
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
            deep_rows = data_rows[sep_idx + 1 :]
            local_rows.sort(key=sort_key, reverse=reverse)
            deep_rows.sort(key=sort_key, reverse=reverse)
            ordered = [back_row] + local_rows + [sep] + deep_rows
        else:
            data_rows.sort(key=sort_key, reverse=reverse)
            ordered = [back_row] + data_rows

        dpg.reorder_items(sender, 1, ordered)

    # ── Click handling ──────────────────────────────────────────

    def _on_entry_click(self, sender: Any, app_data: Any, user_data: Any) -> None:
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
        if self.state.last_clicked_element is not None and dpg.does_item_exist(self.state.last_clicked_element):
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
            self.state.selected_files,
            typed_name,
            self.state.current_dir,
        )

        needs_extract = any(is_archive_virtual_path(path) for path in selection)
        original_title = None
        if needs_extract and dpg.does_item_exist(self._config.tag):
            original_title = dpg.get_item_label(self._config.tag)
            dpg.set_item_label(
                self._config.tag,
                f"{original_title} - Extracting...",
            )
        try:
            resolved, failed_name = resolve_archive_selection(
                selection,
                max_size=self._MAX_ARCHIVE_EXTRACT_SIZE,
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

    def _on_ok(self, sender: Any, app_data: Any, user_data: Any) -> None:
        """Handle OK button click — returns current selection."""
        self._return_selection()

    def _on_cancel(self, sender: Any, app_data: Any, user_data: Any) -> None:
        """Handle Cancel button click — hides dialog without callback."""
        self.hide()

    # ── Search & filter ─────────────────────────────────────────

    def _on_search(self, sender: Any, app_data: Any, user_data: Any) -> None:
        """Handle search field input — debounced to avoid per-keystroke rescans.

        Listing via the VFS (``os.scandir`` locally, zip/7z members in
        archives) on every keystroke freezes the UI on large folders. Both
        the shallow listing and the recursive subfolder search wait until
        the user pauses typing.
        """
        self.logic.trigger_search(dpg.get_value(sender))

    def _on_subfolder_toggle(self, sender: Any, app_data: Any, user_data: Any) -> None:
        """Handle subfolder search checkbox toggle."""
        self.logic.set_search_subfolders(bool(dpg.get_value(sender)))

    def _on_filter_change(self, sender: Any, app_data: Any, user_data: Any) -> None:
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

    def _on_new_folder_confirm(self, sender: Any, app_data: Any, user_data: Any) -> None:
        """Handle new folder input confirmation."""
        name = dpg.get_value(self._new_folder_input)
        dpg.hide_item(self._new_folder_group)
        if name:
            self.logic._create_new_folder(name)
