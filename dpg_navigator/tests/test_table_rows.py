"""Tests for building the explorer table in slices.

A large listing is not turned into rows in one blocking call: the first
``FIRST_ROWS`` rows are built with the listing and the rest by the frame
poll. DearPyGui is mocked at the call boundary; every ``table_row`` gets its
own id so ``row_entries`` can be counted.
"""

from __future__ import annotations

import itertools
import os
from unittest.mock import MagicMock, patch

import pytest

from dpg_navigator._dialog import FileDialog
from dpg_navigator._types import DialogConfig, FileEntry
from dpg_navigator.dialog._state import DialogState, RowBacklog
from dpg_navigator.dialog._ui import FIRST_ROWS, ROW_BUDGET, DialogUIBuilder

_ROOT = os.path.abspath(os.sep + "root")


def _file(name: str, folder: str = _ROOT) -> FileEntry:
    return FileEntry(name, os.path.join(folder, name), is_dir=False, size_bytes=1, modified_time=0.0, is_hidden=False)


def _files(count: int) -> list[FileEntry]:
    return [_file(f"f{i:05d}.txt") for i in range(count)]


_SEPARATOR = FileEntry("\0deep_sep", "", is_dir=False, size_bytes=None, modified_time=0.0, is_hidden=False)


@pytest.fixture
def ui_dpg():
    """Mocked ``dpg`` of the UI builder; each table row gets a fresh id."""
    with patch("dpg_navigator.dialog._ui.dpg") as mock_dpg:
        mock_dpg.table_row.return_value.__enter__.side_effect = itertools.count(1000)
        yield mock_dpg


def _builder(state: DialogState | None = None) -> DialogUIBuilder:
    state = state or DialogState()
    state.current_dir = state.current_dir or _ROOT
    dialog = MagicMock()
    dialog._status_label = None
    dialog._selec_height = 16
    return DialogUIBuilder(dialog, state, MagicMock(), DialogConfig())


def _labels(mock_dpg: MagicMock) -> list[str]:
    return [call.kwargs["label"] for call in mock_dpg.add_selectable.call_args_list]


class TestFirstSlice:
    def test_small_listing_is_built_at_once(self, ui_dpg):
        builder = _builder()

        builder._render_entries_list(_files(5))

        assert len(builder.state.row_entries) == 5
        assert builder.state.row_backlog is None

    def test_large_listing_builds_only_the_first_rows(self, ui_dpg):
        builder = _builder()

        builder._render_entries_list(_files(FIRST_ROWS + 300))

        assert len(builder.state.row_entries) == FIRST_ROWS
        backlog = builder.state.row_backlog
        assert backlog is not None
        assert backlog.pos == FIRST_ROWS
        assert len(backlog.entries) == FIRST_ROWS + 300

    def test_old_rows_are_deleted_in_one_call(self, ui_dpg):
        builder = _builder()
        builder.dialog._explorer_table = 77

        builder._render_entries_list(_files(3))

        ui_dpg.delete_item.assert_called_once_with(77, children_only=True, slot=1)

    def test_new_listing_replaces_an_unfinished_one(self, ui_dpg):
        builder = _builder()
        builder._render_entries_list(_files(FIRST_ROWS + 300))

        builder._render_entries_list([_file("only.txt")])

        assert [entry.name for entry in builder.state.row_entries.values()] == ["only.txt"]
        assert builder.state.row_backlog is None


class TestRenderPendingRows:
    def test_without_limits_builds_everything(self, ui_dpg):
        builder = _builder()
        builder._render_entries_list(_files(FIRST_ROWS + 300))

        assert builder.render_pending_rows() is True

        assert len(builder.state.row_entries) == FIRST_ROWS + 300
        assert builder.state.row_backlog is None

    def test_rows_keep_the_order_of_the_listing(self, ui_dpg):
        builder = _builder()
        entries = _files(FIRST_ROWS + 50)
        builder._render_entries_list(entries)
        builder.render_pending_rows()

        assert list(builder.state.row_entries.values()) == entries

    def test_max_rows_stops_early(self, ui_dpg):
        builder = _builder()
        builder._render_entries_list(_files(FIRST_ROWS + 300))

        assert builder.render_pending_rows(max_rows=100) is False

        assert len(builder.state.row_entries) == FIRST_ROWS + 100

    def test_spent_budget_still_builds_one_row(self, ui_dpg):
        """Progress is guaranteed even when a single row overruns the budget."""
        builder = _builder()
        builder._render_entries_list(_files(FIRST_ROWS + 3))
        clock = itertools.count(0.0, 1.0)  # every reading is a second later

        with patch("dpg_navigator.dialog._ui.time.perf_counter", side_effect=lambda: next(clock)):
            assert builder.render_pending_rows(budget=ROW_BUDGET) is False
            assert len(builder.state.row_entries) == FIRST_ROWS + 1
            assert builder.render_pending_rows(budget=ROW_BUDGET) is False
            assert builder.render_pending_rows(budget=ROW_BUDGET) is True

        assert len(builder.state.row_entries) == FIRST_ROWS + 3
        assert builder.state.row_backlog is None

    def test_nothing_pending_is_done(self, ui_dpg):
        assert _builder().render_pending_rows() is True

    def test_later_rows_are_labelled_for_the_listing_they_belong_to(self, ui_dpg):
        """A query typed, or a folder opened, while rows are still being built
        must not change how the rest of the old listing is labelled."""
        state = DialogState()
        state.current_dir = _ROOT
        state.search_query = "f"
        builder = _builder(state)
        sub = os.path.join(_ROOT, "sub")
        builder._render_entries_list([*_files(FIRST_ROWS), _file("deep.txt", sub)])

        state.search_query = ""
        state.current_dir = os.path.join(_ROOT, "elsewhere")
        builder.render_pending_rows()

        assert os.path.join("sub", "deep.txt") in _labels(ui_dpg)

    def test_separator_row_is_remembered_and_is_not_an_entry(self, ui_dpg):
        builder = _builder()

        builder._render_entries_list([_file("a.txt"), _SEPARATOR, _file("b.txt")])

        assert builder.state.deep_separator_row is not None
        assert builder.state.deep_separator_row not in builder.state.row_entries
        assert [entry.name for entry in builder.state.row_entries.values()] == ["a.txt", "b.txt"]
        assert "-- Subfolders --" in _labels(ui_dpg)

    def test_a_failing_entry_does_not_stop_the_rest(self, ui_dpg):
        builder = _builder()
        broken = _file("broken.txt")
        builder.dialog._icons.get_for_file.side_effect = lambda name: (
            (_ for _ in ()).throw(RuntimeError("no icon")) if name == "broken.txt" else "icon"
        )

        builder._render_entries_list([_file("a.txt"), broken, _file("b.txt")])

        assert [entry.name for entry in builder.state.row_entries.values()] == ["a.txt", "b.txt"]
        assert builder.state.row_backlog is None


class TestPlainRows:
    def test_back_row_sits_in_a_group_like_file_rows(self, ui_dpg):
        """The table clipper needs every row equally tall; the group is what
        gives a file row its height."""
        builder = _builder()

        builder._render_entries_list([])

        ui_dpg.group.assert_called_once_with(horizontal=True)
        assert _labels(ui_dpg) == [".."]


class TestDialogDrivesTheBacklog:
    def _dialog(self, *, show_dir_size: bool = False) -> FileDialog:
        dialog = FileDialog.__new__(FileDialog)
        dialog._destroyed = False
        dialog._config = DialogConfig(tag="rows_test", show_dir_size=show_dir_size)
        dialog.state = DialogState()
        dialog.ui = MagicMock()
        dialog.logic = MagicMock()
        return dialog

    def _backlog(self) -> RowBacklog:
        return RowBacklog(entries=_files(3), query="", base_dir=_ROOT)

    def test_poll_step_builds_within_the_budget_under_the_mutex(self):
        dialog = self._dialog()
        dialog.state.row_backlog = self._backlog()

        with patch("dpg_navigator._dialog.dpg") as mock_dpg:
            dialog._apply_pending_rows()

        mock_dpg.mutex.assert_called_once()
        dialog.ui.render_pending_rows.assert_called_once_with(budget=ROW_BUDGET)

    def test_poll_step_is_idle_without_a_backlog(self):
        dialog = self._dialog()

        with patch("dpg_navigator._dialog.dpg") as mock_dpg:
            dialog._apply_pending_rows()

        mock_dpg.mutex.assert_not_called()
        dialog.ui.render_pending_rows.assert_not_called()

    def test_backlog_keeps_the_poll_alive(self):
        dialog = self._dialog()
        dialog._awaiting_sidebar_drives = False
        assert dialog._has_pending_ui() is False

        dialog.state.row_backlog = self._backlog()

        assert dialog._has_pending_ui() is True

    def test_sizes_wait_for_the_last_row(self):
        dialog = self._dialog(show_dir_size=True)
        dialog.state.row_backlog = self._backlog()
        dialog.state.pending_size_cells = {"/a": 1}

        with patch("dpg_navigator._dialog.dpg"):
            dialog._apply_pending_rows()  # mocked UI leaves the backlog in place
        dialog.logic.start_size_computation.assert_not_called()

        dialog.ui.render_pending_rows.side_effect = lambda **_: setattr(dialog.state, "row_backlog", None)
        with patch("dpg_navigator._dialog.dpg"):
            dialog._apply_pending_rows()
        dialog.logic.start_size_computation.assert_called_once_with(["/a"])

    def test_finish_builds_everything_without_a_budget(self):
        dialog = self._dialog()
        dialog.state.row_backlog = self._backlog()

        with patch("dpg_navigator._dialog.dpg"):
            dialog._finish_pending_rows()

        dialog.ui.render_pending_rows.assert_called_once_with()

    def test_sort_finishes_the_listing_first(self):
        """Sorting reorders the rows that exist; rows added afterwards would
        land unsorted at the end."""
        dialog = self._dialog()
        order: list[str] = []
        dialog._finish_pending_rows = lambda: order.append("finish")  # type: ignore[method-assign]

        with patch("dpg_navigator._dialog.dpg") as mock_dpg:
            mock_dpg.get_item_children.side_effect = lambda *_: order.append("read rows") or [5]
            dialog._on_sort(1, [[5, 1]], None)

        assert order[0] == "finish"


class TestKeyboardWithUnfinishedListing:
    def _dialog(self, **config: object) -> FileDialog:
        dialog = FileDialog.__new__(FileDialog)
        dialog._config = DialogConfig(tag="rows_kb", **config)  # type: ignore[arg-type]
        dialog.logic = MagicMock()
        dialog.state = DialogState()
        dialog._explorer_table = 1
        dialog._preview = MagicMock()
        dialog._finish_pending_rows = MagicMock()  # type: ignore[method-assign]
        dialog._select_row_by_index = MagicMock()  # type: ignore[method-assign]
        return dialog

    def _move(self, dialog: FileDialog, delta: int, rows: int) -> None:
        with patch("dpg_navigator._keyboard.dpg") as mock_dpg:
            mock_dpg.get_item_children.return_value = list(range(rows))
            dialog._move_focus(delta)

    def test_move_inside_the_built_rows_does_not_wait(self):
        dialog = self._dialog()
        dialog.state.focused_row_index = 3

        self._move(dialog, 1, rows=50)

        dialog._finish_pending_rows.assert_not_called()
        dialog._select_row_by_index.assert_called_once_with(4)

    def test_move_onto_the_last_built_row_finishes_the_listing(self):
        dialog = self._dialog()
        dialog.state.focused_row_index = 48

        self._move(dialog, 1, rows=50)

        dialog._finish_pending_rows.assert_called_once()

    def test_up_without_focus_needs_the_real_last_row(self):
        dialog = self._dialog()
        dialog.state.focused_row_index = -1

        self._move(dialog, -1, rows=50)

        dialog._finish_pending_rows.assert_called_once()

    def test_select_all_finishes_the_listing(self):
        dialog = self._dialog(multi_selection=True)
        for name in ("_path_input", "_filename_input", "_new_folder_input", "_search_input"):
            setattr(dialog, name, None)
        with patch("dpg_navigator._keyboard.dpg") as mock_dpg, patch("dpg_navigator._keyboard._platform") as plat:
            mock_dpg.does_item_exist.return_value = True
            mock_dpg.is_item_shown.return_value = True
            mock_dpg.get_active_window.return_value = "rows_kb"
            mock_dpg.get_item_children.return_value = []
            plat.is_mod_key_down.return_value = True
            dialog._on_key_a(None, None, None)

        dialog._finish_pending_rows.assert_called_once()

    def test_back_row_selection_reaches_the_selectable_inside_the_group(self):
        dialog = FileDialog.__new__(FileDialog)
        dialog._config = DialogConfig(tag="rows_kb")
        dialog.state = DialogState()
        dialog._explorer_table = 1
        dialog._preview = MagicMock()
        children = {1: [10], 10: [20], 20: [30]}  # table -> row -> group -> selectable

        with patch("dpg_navigator._keyboard.dpg") as mock_dpg:
            mock_dpg.get_item_children.side_effect = lambda item, slot: children.get(item, [])
            mock_dpg.does_item_exist.return_value = False
            dialog._select_row_by_index(0)

        mock_dpg.set_value.assert_called_once_with(30, True)
        assert dialog.state.last_clicked_element == 30
