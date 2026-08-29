"""GUI-free file-dialog business logic.

Navigation, listing, debounced search, background index build, and
directory-size jobs. Never imports DearPyGui; talks to the UI through
injected callbacks (``refresh_ui_cb``, ``show_error_cb``, …).
"""

from __future__ import annotations

import os
import time
from typing import Callable

from .._filesystem import DirectoryIndex, DirectoryLister, is_archive_virtual_path, validate_folder_name
from .._job_manager import JobManager
from .._types import DialogConfig, DialogMode, FileEntry
from ._state import DialogState

_SEARCH_DEBOUNCE = 0.3


class DialogLogic:
    """GUI-free navigation, listing, search, and background-task logic."""

    def __init__(
        self,
        state: DialogState,
        config: DialogConfig,
        refresh_ui_cb: Callable[[list[FileEntry]], None],
        show_error_cb: Callable[[str, str], None],
        update_path_input_cb: Callable[[str], None],
        update_size_cell_cb: Callable[[str, str], None],
    ) -> None:
        self.state = state
        self.config = config
        self.refresh_ui = refresh_ui_cb
        self.show_error = show_error_cb
        self.update_path_input = update_path_input_cb
        self.update_size_cell = update_size_cell_cb

        self._dir_index = DirectoryIndex()
        self._local_entries: list[FileEntry] = []

    def go_back(self) -> None:
        """Pop the previous directory from the history stack."""
        while self.state.history:
            prev = self.state.history.pop()
            self.state.history_index = len(self.state.history) - 1
            if prev == self.state.current_dir:
                continue
            self.state.is_navigating_history = True
            try:
                self.navigate_to(prev)
            finally:
                self.state.is_navigating_history = False
            return

    def go_up(self) -> None:
        """Navigate to the parent directory or archive member directory."""
        if is_archive_virtual_path(self.state.current_dir):
            parts = self.state.current_dir.split("|", 1)
            archive_path = parts[0]
            virtual_path = parts[1].strip("/")
            if not virtual_path:
                self.navigate_to(os.path.dirname(archive_path))
            else:
                parent_virtual = os.path.dirname(virtual_path).replace("\\", "/")
                if parent_virtual in (".", "/"):
                    parent_virtual = ""
                self.navigate_to(f"{archive_path}|/{parent_virtual}")
        else:
            parent = os.path.dirname(self.state.current_dir)
            if parent != self.state.current_dir:
                self.navigate_to(parent)

    def navigate_to(self, path: str) -> None:
        """Validate a path, update navigation state, and refresh the listing."""
        if is_archive_virtual_path(path):
            parts = path.split("|", 1)
            archive_path = parts[0]
            virtual_inner = parts[1].replace("\\", "/").strip("/")
            if os.path.isabs(archive_path):
                resolved_archive = os.path.normpath(archive_path)
            else:
                base = (
                    self.state.current_dir.split("|", 1)[0]
                    if is_archive_virtual_path(self.state.current_dir)
                    else self.state.current_dir
                )
                resolved_archive = os.path.normpath(os.path.join(base, archive_path))
            if not os.path.isfile(resolved_archive):
                self.show_error(
                    "Path not found",
                    f"The archive '{resolved_archive}' does not exist or is not a file.",
                )
                self.update_path_input(self.state.current_dir)
                return
            resolved = f"{resolved_archive}|/{virtual_inner}" if virtual_inner else f"{resolved_archive}|/"
            self.state.navigate(resolved)
            self.refresh_listing()
            return

        resolved = (
            os.path.normpath(path)
            if os.path.isabs(path)
            else os.path.normpath(os.path.join(self.state.current_dir, path))
        )
        if not os.path.isdir(resolved):
            self.show_error(
                "Path not found",
                f"The path '{resolved}' does not exist or is not a directory.",
            )
            self.update_path_input(self.state.current_dir)
            return

        try:
            with os.scandir(resolved):
                pass
        except PermissionError as e:
            self.show_error(
                "Permission denied",
                f"Cannot open the folder because access is denied.\n\n{e}",
            )
            self.update_path_input(self.state.current_dir)
            return
        except OSError as e:
            self.show_error("Error", f"Cannot access the folder.\n\n{e}")
            self.update_path_input(self.state.current_dir)
            return

        self.state.navigate(resolved)
        self.refresh_listing()
        if self.config.search_subfolders:
            self.start_index_build()

    def _create_new_folder(self, name: str) -> None:
        """Create a validated folder in the current local directory."""
        name = name.strip()
        if not name:
            self.show_error("Invalid name", "Folder name cannot be empty.")
            return

        if is_archive_virtual_path(self.state.current_dir):
            self.show_error("Not supported", "Cannot create folders inside an archive.")
            return

        error = validate_folder_name(name, self.state.current_dir)
        if error:
            self.show_error("Invalid folder name", error)
            return

        new_path = os.path.join(self.state.current_dir, name)

        try:
            os.makedirs(new_path, exist_ok=False)
            self.refresh_listing()
        except FileExistsError:
            self.show_error("Folder exists", f"A folder named '{name}' already exists.")
        except OSError as e:
            self.show_error("Error", f"Could not create folder.\n\n{e}")

    def refresh_listing(self, search_query: str = "") -> None:
        """Refresh the current directory listing and optional size jobs."""
        self.cancel_background_tasks()
        self.state.search_query = search_query

        entries = DirectoryLister.list_directory(
            self.state.current_dir,
            show_hidden=self.config.show_hidden,
            dirs_only=(self.config.mode == DialogMode.OPEN_DIRS),
            file_filter=self.state.current_filter,
            search_query=search_query,
            show_dir_size=False,
        )
        self._local_entries = entries
        self.refresh_ui(entries)

        if self.config.show_dir_size:
            self.start_size_computation()

    def cancel_background_tasks(self) -> None:
        """Invalidate pending searches, index builds, and size computations."""
        self.state.bg_generation += 1
        self.state.index_generation += 1
        self._dir_index.invalidate()
        if self.state.search_debounce_timer:
            JobManager.cancel_timer(self.state.search_debounce_timer)
            self.state.search_debounce_timer = None

    def trigger_search(self, query: str) -> None:
        """Debounce shallow search and optionally append deep-search results."""
        self.state.search_query = query
        if self.state.search_debounce_timer:
            JobManager.cancel_timer(self.state.search_debounce_timer)
        gen = self.state.index_generation
        self.state.search_debounce_timer = JobManager.schedule_timer(
            _SEARCH_DEBOUNCE,
            self._run_search,
            args=(query, gen),
        )

    def _run_search(self, query: str, gen: int) -> None:
        if gen != self.state.index_generation:
            return
        entries = DirectoryLister.list_directory(
            self.state.current_dir,
            show_hidden=self.config.show_hidden,
            dirs_only=(self.config.mode == DialogMode.OPEN_DIRS),
            file_filter=self.state.current_filter,
            search_query=query,
            show_dir_size=False,
        )
        if gen != self.state.index_generation:
            return
        self._local_entries = entries
        self.refresh_ui(entries)

        if query and self.config.search_subfolders:
            self._perform_deep_search(query, gen)

        if self.config.show_dir_size and not query:
            self.start_size_computation()

    def _perform_deep_search(self, query: str, gen: int) -> None:
        if (
            gen != self.state.index_generation
            or not self._dir_index.ready
            or self._dir_index.root != self.state.current_dir
        ):
            return
        deep_results = self._dir_index.search(
            query,
            file_filter=self.state.current_filter,
            dirs_only=(self.config.mode == DialogMode.OPEN_DIRS),
            show_hidden=self.config.show_hidden,
        )
        if gen != self.state.index_generation:
            return

        local_paths = {entry.full_path for entry in self._local_entries}
        extra = [entry for entry in deep_results if entry.full_path not in local_paths]
        if not extra:
            return

        separator = FileEntry(
            name="\0deep_sep",
            full_path="",
            is_dir=False,
            size_bytes=None,
            modified_time=0.0,
            is_hidden=False,
        )
        self.refresh_ui(list(self._local_entries) + [separator] + extra)

    def start_index_build(self) -> None:
        """Build the recursive search index in a cancellable background task."""
        gen = self.state.index_generation
        root = self.state.current_dir
        if is_archive_virtual_path(root):
            return

        def _build() -> None:
            if gen != self.state.index_generation:
                return
            self._dir_index.build(
                root,
                generation=gen,
                get_generation=lambda: self.state.index_generation,
                show_hidden=self.config.show_hidden,
            )

        JobManager.submit(_build)

    def start_size_computation(self) -> None:
        """Compute visible directory sizes asynchronously and cache the results."""
        gen = self.state.bg_generation
        paths = list(self.state.pending_size_cells.keys())

        def _compute() -> None:
            for path in paths:
                if gen != self.state.bg_generation:
                    break
                size = DirectoryLister.compute_dir_size(path)
                self.state.size_cache[path] = (size, time.time())
                self.update_size_cell(path, DirectoryLister.format_size(size))

        JobManager.submit(_compute)

    def set_search_subfolders(self, enabled: bool) -> None:
        """Enable or disable recursive subfolder search.

        When turning the option off, the background index is invalidated and
        the current listing is refreshed immediately so deep-search rows
        disappear. When turning it on, a cancellable index build is started
        if one is not already ready.
        """
        self.config.search_subfolders = enabled
        if enabled:
            if not self._dir_index.ready:
                self.start_index_build()
            if self.state.search_query:
                self.trigger_search(self.state.search_query)
            return

        self.state.index_generation += 1
        self._dir_index.invalidate()
        if self.state.search_debounce_timer:
            JobManager.cancel_timer(self.state.search_debounce_timer)
            self.state.search_debounce_timer = None
        self.refresh_listing(self.state.search_query)
