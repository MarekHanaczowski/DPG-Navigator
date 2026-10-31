"""Real-DearPyGui checks for the user-facing 1.0.0b7 fixes.

Each test drives a genuine ``FileDialog`` (real widgets, real ``JobManager``,
real frame-callback UI pump) through one flow that the mocked unit tests only
cover piecewise: picking a member out of a 7z archive, rejecting a typed file
name, showing a lower-bound directory size, and replaying a subfolder search
typed while the index was still building.

Opt-in (``DPG_INTEGRATION=1``); see ``conftest.py``.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable

import dearpygui.dearpygui as dpg
import pytest

from dpg_navigator._filesystem import MAX_SCAN_DEPTH, DirectoryIndex, DirectoryLister
from dpg_navigator._types import FileEntry

from .dpg_harness import entry_named, make_dialog, pump, wait_until

pytestmark = pytest.mark.integration

_SELECTABLE = "mvAppItemType::mvSelectable"


def _row_selectable(dialog, entry: FileEntry) -> int:
    """Return a clickable cell of *entry*'s row (the one users click)."""
    for row_id, row_entry in dialog.state.row_entries.items():
        if row_entry is entry:
            for child in dpg.get_item_children(row_id, 1) or []:
                if dpg.get_item_type(child) == _SELECTABLE:
                    return child
    raise AssertionError(f"no selectable cell for {entry.name!r}")


def _run_as_dpg_callback(fn: Callable[[], None], timeout: float = 15.0) -> None:
    """Run *fn* off the render thread while frames keep rendering.

    DearPyGui dispatches item callbacks on its own callback thread, so code
    such as ``dpg.split_frame()`` inside a callback relies on the render loop
    advancing in parallel. This mirrors that instead of calling the handler
    on the thread that pumps frames (which would wait forever).
    """
    errors: list[BaseException] = []

    def target() -> None:
        try:
            fn()
        except BaseException as exc:  # re-raised on the test thread below
            errors.append(exc)

    worker = threading.Thread(target=target, name="dpg_test_callback", daemon=True)
    worker.start()
    assert wait_until(lambda: not worker.is_alive(), timeout=timeout), "callback did not finish"
    if errors:
        raise errors[0]


def _windows_labelled(label: str) -> list[int]:
    return [window for window in dpg.get_windows() if dpg.get_item_label(window) == label]


class TestSevenZipMemberSelection:
    """K1: a 7z member chosen in the dialog is extracted and returned."""

    def test_double_click_on_7z_member_returns_extracted_file(self, dpg_viewport, tmp_path):
        py7zr = pytest.importorskip("py7zr")
        payload = b"seven zip payload\n" * 64
        archive = tmp_path / "bundle.7z"
        with py7zr.SevenZipFile(archive, "w") as seven:
            seven.writestr(payload, "docs/readme.txt")
            seven.writestr(b"other", "docs/other.txt")

        chosen: list[list[str]] = []
        dialog = make_dialog(tmp_path, callback=lambda paths: chosen.append(list(paths)))
        try:
            dialog.show()
            pump()
            dialog.logic.navigate_to(f"{archive}|/docs")
            assert wait_until(lambda: any(e.name == "readme.txt" for e in dialog.state.row_entries.values()))

            entry = entry_named(dialog, "readme.txt")
            cell = _row_selectable(dialog, entry)
            # Two quick clicks on the same row = double click = "open".
            dialog._on_entry_click(cell, None, entry)
            dialog._on_entry_click(cell, None, entry)
            pump()

            assert len(chosen) == 1, f"callback calls: {chosen}"
            assert len(chosen[0]) == 1
            extracted = chosen[0][0]
            assert os.path.isfile(extracted)
            assert "|" not in extracted
            with open(extracted, "rb") as handle:
                assert handle.read() == payload
            assert not dpg.is_item_shown(dialog._config.tag)
        finally:
            dialog.destroy()
            pump()
            DirectoryLister.cleanup_temp_files()


class TestTypedFileName:
    """W1/D2: a rejected typed name explains why and keeps the dialog open."""

    @pytest.mark.parametrize(
        "typed",
        [
            pytest.param(f"sub{os.sep}escape.txt", id="separator"),
            pytest.param(
                "CON",
                id="windows-reserved",
                marks=pytest.mark.skipif(os.name != "nt", reason="Windows-only name rule"),
            ),
            pytest.param(
                "a?b.txt",
                id="windows-invalid-char",
                marks=pytest.mark.skipif(os.name != "nt", reason="Windows-only name rule"),
            ),
        ],
    )
    def test_modal_dialog_shows_reason_in_status_line(self, dpg_viewport, tmp_path, typed):
        chosen: list[list[str]] = []
        dialog = make_dialog(tmp_path, modal=True, callback=lambda paths: chosen.append(list(paths)))
        try:
            dialog.show()
            pump()
            dpg.set_value(dialog._filename_input, typed)
            dialog._on_ok(None, None, None)
            pump()

            assert chosen == []
            assert dpg.is_item_shown(dialog._config.tag)
            assert dpg.is_item_shown(dialog._status_label)
            status = dpg.get_value(dialog._status_label)
            assert status.startswith("Invalid file name: ")
            assert typed in status
        finally:
            dialog.destroy()
            pump()

    def test_non_modal_dialog_opens_message_window(self, dpg_viewport, tmp_path):
        chosen: list[list[str]] = []
        dialog = make_dialog(tmp_path, modal=False, callback=lambda paths: chosen.append(list(paths)))
        title = "Invalid file name"
        before = set(_windows_labelled(title))
        try:
            dialog.show()
            pump()
            dpg.set_value(dialog._filename_input, f"sub{os.sep}escape.txt")
            _run_as_dpg_callback(lambda: dialog._on_ok(None, None, None))
            pump()

            assert chosen == []
            assert dpg.is_item_shown(dialog._config.tag)
            opened = [window for window in _windows_labelled(title) if window not in before]
            assert len(opened) == 1, "expected one message window"
        finally:
            for window in _windows_labelled(title):
                if window not in before:
                    dpg.delete_item(window)
            dialog.destroy()
            pump()

    def test_valid_typed_name_is_returned(self, dpg_viewport, tmp_path):
        chosen: list[list[str]] = []
        dialog = make_dialog(tmp_path, callback=lambda paths: chosen.append(list(paths)))
        try:
            dialog.show()
            pump()
            dpg.set_value(dialog._filename_input, "report v1..2.txt")
            dialog._on_ok(None, None, None)
            pump()

            assert chosen == [[os.path.join(dialog.state.current_dir, "report v1..2.txt")]]
            assert not dpg.is_item_shown(dialog._config.tag)
        finally:
            dialog.destroy()
            pump()


class TestDirectorySizeColumn:
    """W3: a size cut off at the scan depth is labelled as a lower bound."""

    def test_size_cells_show_exact_and_lower_bound_values(self, dpg_viewport, tmp_path):
        deep = tmp_path / "deep"
        level = deep
        for depth in range(MAX_SCAN_DEPTH + 1):
            level = level / f"l{depth}"
            level.mkdir(parents=True)
            (level / "f.bin").write_bytes(b"x" * 1024)
        small = tmp_path / "small"
        small.mkdir()
        (small / "f.bin").write_bytes(b"x" * 1024)

        dialog = make_dialog(tmp_path, show_dir_size=True)
        try:
            dialog.show()
            pump()
            deep_path = entry_named(dialog, "deep").full_path
            small_path = entry_named(dialog, "small").full_path

            def labels() -> tuple[str, str]:
                cells = dialog.state.pending_size_cells
                if deep_path not in cells or small_path not in cells:
                    return ("", "")
                return (dpg.get_item_label(cells[deep_path]), dpg.get_item_label(cells[small_path]))

            assert wait_until(lambda: "..." not in labels() and "" not in labels()), f"labels: {labels()}"
            deep_label, small_label = labels()
            # Files at depth 1 and 2 count (2 KB); depth >= MAX_SCAN_DEPTH is skipped.
            assert deep_label == ">= 2 KB"
            assert small_label == "1 KB"
            assert deep_label.isascii()
        finally:
            dialog.destroy()
            pump()


class TestSubfolderSearchReplay:
    """W2: a query typed while the index builds still gets subfolder results."""

    def test_query_typed_during_index_build_shows_subfolder_hits(self, dpg_viewport, tmp_path, monkeypatch):
        (tmp_path / "top.txt").write_text("top")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "needle.txt").write_text("found me")

        real_build = DirectoryIndex.build
        build_started = threading.Event()

        def slow_build(self, *args, **kwargs):
            # Longer than the 0.3 s search debounce, so the debounced deep
            # search runs while the index is not ready yet.
            build_started.set()
            time.sleep(1.0)
            return real_build(self, *args, **kwargs)

        monkeypatch.setattr(DirectoryIndex, "build", slow_build)

        dialog = make_dialog(tmp_path, search_subfolders=True)
        try:
            dialog.show()
            pump()
            assert build_started.wait(5.0), "index build was not started"
            dpg.set_value(dialog._search_input, "needle")
            dialog._on_search(dialog._search_input, "needle", None)

            def deep_hit() -> bool:
                names = [entry.full_path for entry in dialog.state.row_entries.values()]
                return dialog.state.deep_separator_row is not None and str(sub / "needle.txt") in names

            assert wait_until(deep_hit, timeout=15.0), (
                f"subfolder hit never appeared; rows: {sorted(e.name for e in dialog.state.row_entries.values())}"
            )
        finally:
            dialog.destroy()
            pump()
