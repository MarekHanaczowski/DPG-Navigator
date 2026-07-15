"""State management for the file dialog."""
from __future__ import annotations  # PEP 604/585 annotations need this on py3.8/3.9

from dataclasses import dataclass, field
import threading
from typing import Any
from .._types import FileEntry

@dataclass
class DialogState:
    """Holds the current state of the file dialog."""
    # Navigation & Selection
    current_dir: str = ""
    history: list[str] = field(default_factory=list)
    history_index: int = -1
    is_navigating_history: bool = False
    
    selected_files: list[str] = field(default_factory=list)
    selected_elements: list[int] = field(default_factory=list)
    last_click_time: float = 0.0
    last_clicked_element: int | None = None
    focused_row_index: int = -1
    
    # Files listing
    row_entries: dict[int, FileEntry] = field(default_factory=dict)
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
    pending_size_cells: dict[str, int] = field(default_factory=dict)
    bg_generation: int = 0
    
    def navigate(self, path: str) -> None:
        """Update history stack and set current_dir.

        History is a simple stack of previous directories. ``go_back`` pops
        entries; forward history is not retained (browser-style back only).
        """
        if (
            self.current_dir
            and not self.is_navigating_history
            and self.current_dir != path
        ):
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
