"""Mutable FileDialog state (navigation, selection, search, generations).

``DialogState`` is a plain dataclass. The only method is ``navigate()``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .._types import FileEntry


@dataclass
class RowBacklog:
    """Rows of a listing that the frame poll has not built yet.

    A large listing is turned into table rows over several frames. ``query``
    and ``base_dir`` are the search query and folder the listing was produced
    for: later slices label their rows against these, not against whatever
    the user has typed or opened since.
    """

    entries: list[FileEntry]
    query: str
    base_dir: str
    pos: int = 0  # index of the next entry to build


@dataclass
class DialogState:
    """Mutable dialog state (navigation, selection, search, generations).

    No behavior beyond ``navigate()``. ``bg_generation`` / ``index_generation``
    cancel stale background listing and index builds.
    """

    # Navigation & Selection
    current_dir: str = ""
    history: list[str] = field(default_factory=list)
    history_index: int = -1
    is_navigating_history: bool = False

    selected_files: list[str] = field(default_factory=list)
    selected_elements: list[int] = field(default_factory=list)
    last_click_time: float = 0.0  # time.monotonic() of the previous click
    last_clicked_element: int | None = None
    focused_row_index: int = -1

    # Files listing
    row_entries: dict[int, FileEntry] = field(default_factory=dict)
    row_backlog: RowBacklog | None = None
    """Rows still to be built for the current listing; ``None`` when complete."""
    current_filter: str = ""
    current_sort: tuple[str, int] = ("Name", 1)  # (column, direction)

    # Search
    search_query: str = ""
    index_generation: int = 0
    search_debounce_timer: Any = None  # JobManager.TimerTask | None
    deep_separator_row: int | None = None

    # Preview & UI
    is_preview_open: bool = False

    # Async Loading
    size_cache: dict[str, tuple[int | None, float]] = field(default_factory=dict)
    """Directory path -> ``(size, time.monotonic() when it was computed)``."""
    size_truncated: set[str] = field(default_factory=set)
    """Paths whose cached size is a lower bound (scan hit the depth cap)."""
    pending_size_cells: dict[str, int] = field(default_factory=dict)
    bg_generation: int = 0

    def navigate(self, path: str) -> None:
        """Update history stack and set current_dir.

        History is a simple stack of previous directories. ``go_back`` pops
        entries; forward history is not retained (browser-style back only).
        """
        if self.current_dir and not self.is_navigating_history and self.current_dir != path:
            if not self.history or self.history[-1] != self.current_dir:
                self.history.append(self.current_dir)
            self.history_index = len(self.history) - 1

        self.current_dir = path
        self.selected_files.clear()
        self.selected_elements.clear()
        self.last_clicked_element = None
        self.focused_row_index = -1
        self.search_query = ""
        self.pending_size_cells.clear()
        # is_navigating_history is cleared by go_back's finally block
