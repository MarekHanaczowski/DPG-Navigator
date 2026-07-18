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
    search_debounce_timer: threading.Timer | None = None
    deep_separator_row: int | None = None
    
    # Preview & UI
    is_preview_open: bool = False
    
    # Async Loading
    size_cache: dict[str, tuple[int | None, float]] = field(default_factory=dict)
    pending_size_cells: dict[str, int] = field(default_factory=dict)
    bg_generation: int = 0
    
    def navigate(self, path: str) -> None:
        """Update history and set current_dir."""
        if self.current_dir and not self.is_navigating_history:
            # Truncate forward history if we navigated back and then went somewhere new
            self.history = self.history[: self.history_index + 1]
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
        self.is_navigating_history = False
