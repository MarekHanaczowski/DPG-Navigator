"""Helpers for real-DearPyGui integration tests.

Imported only by ``test_*.py`` under this package, which are not collected
unless ``DPG_INTEGRATION=1``.
"""

from __future__ import annotations

import time
import uuid

import dearpygui.dearpygui as dpg

from dpg_navigator import FileDialog
from dpg_navigator._types import FileEntry


def pump(frames: int = 3) -> None:
    for _ in range(frames):
        dpg.render_dearpygui_frame()


def wait_until(predicate, timeout: float = 20.0, interval: float = 0.05) -> bool:
    """Pump DPG frames until *predicate* is true or *timeout* elapses."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        dpg.render_dearpygui_frame()
        if predicate():
            return True
        time.sleep(interval)
    return False


def make_dialog(tmp_path, **kwargs) -> FileDialog:
    defaults = {
        "default_path": str(tmp_path),
        "show_preview": True,
        "show_shortcuts": False,
        "show_dir_size": False,
        "search_subfolders": False,
        "tag": f"int_{uuid.uuid4().hex[:8]}",
        "width": 900,
        "height": 600,
    }
    defaults.update(kwargs)
    return FileDialog(**defaults)


def entry_named(dialog: FileDialog, name: str) -> FileEntry:
    for entry in dialog.state.row_entries.values():
        if entry.name == name:
            return entry
    names = sorted(e.name for e in dialog.state.row_entries.values())
    raise AssertionError(f"{name!r} not in listing: {names}")
