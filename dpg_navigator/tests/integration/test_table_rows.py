"""Real-DearPyGui checks for the explorer table.

The table draws only the rows in view (``clipper=True``) and a large listing
is built over several frames. Both depend on behaviour of the real widgets
that a mocked ``dpg`` cannot show: the clipper places rows by the height of
the first one, and the remaining rows arrive through the frame-callback pump.

Opt-in (``DPG_INTEGRATION=1``); see ``conftest.py``.
"""

from __future__ import annotations

import dearpygui.dearpygui as dpg
import pytest

from dpg_navigator.dialog._ui import FIRST_ROWS

from .dpg_harness import make_dialog, pump, wait_until

pytestmark = pytest.mark.integration


def _fill(folder, count: int) -> None:
    for i in range(count):
        (folder / f"f{i:04d}.txt").write_text("x")


def _name_cell(row: int) -> int:
    """The selectable in a row's first cell (it sits in a horizontal group)."""
    group = dpg.get_item_children(row, 1)[0]
    return dpg.get_item_children(group, 1)[-1]


def _listing_complete(dialog, count: int) -> bool:
    return len(dialog.state.row_entries) == count and dialog.state.row_backlog is None


class TestClippedTable:
    def test_rows_are_equally_tall_and_the_last_one_can_be_scrolled_to(self, dpg_viewport, tmp_path):
        """A shorter ".." row made the clipper underestimate the table's
        height, which left the end of a long listing out of reach."""
        count = FIRST_ROWS + 200
        _fill(tmp_path, count)
        dialog = make_dialog(tmp_path, show_preview=False)
        try:
            dialog.show()
            assert wait_until(lambda: _listing_complete(dialog, count))
            pump(5)
            table = dialog._explorer_table
            rows = dpg.get_item_children(table, 1)
            assert len(rows) == count + 1  # the ".." row comes first

            tops = [dpg.get_item_pos(_name_cell(row))[1] for row in rows[:4]]
            pitches = {tops[i + 1] - tops[i] for i in range(3)}
            assert len(pitches) == 1, f"row tops {tops}: the '..' row differs from file rows"

            dpg.set_y_scroll(table, dpg.get_y_scroll_max(table))
            pump(5)
            assert dpg.is_item_visible(_name_cell(rows[-1]))
        finally:
            dialog.destroy()
            pump()


class TestListingBuiltInSlices:
    def test_first_rows_come_with_the_listing_and_the_rest_through_the_pump(self, dpg_viewport, tmp_path):
        count = FIRST_ROWS + 400
        _fill(tmp_path, count)
        dialog = make_dialog(tmp_path, show_preview=False)
        try:
            dialog.show()  # applies the listing itself, before any frame

            assert len(dialog.state.row_entries) == FIRST_ROWS
            assert dialog.state.row_backlog is not None

            assert wait_until(lambda: _listing_complete(dialog, count))
            names = [entry.name for entry in dialog.state.row_entries.values()]
            assert names == sorted(names)
        finally:
            dialog.destroy()
            pump()

    def test_sorting_an_unfinished_listing_sorts_all_of_it(self, dpg_viewport, tmp_path):
        count = FIRST_ROWS + 300
        _fill(tmp_path, count)
        dialog = make_dialog(tmp_path, show_preview=False)
        try:
            dialog.show()
            assert dialog.state.row_backlog is not None
            table = dialog._explorer_table
            name_column = dpg.get_item_children(table, 0)[0]

            dialog._on_sort(table, [[name_column, -1]], None)  # Name, descending

            assert dialog.state.row_backlog is None
            rows = dpg.get_item_children(table, 1)
            assert len(rows) == count + 1
            names = [dialog.state.row_entries[row].name for row in rows[1:]]
            assert names == sorted(names, reverse=True)
        finally:
            dialog.destroy()
            pump()

    def test_a_new_listing_replaces_the_one_still_being_built(self, dpg_viewport, tmp_path):
        big = tmp_path / "big"
        big.mkdir()
        _fill(big, FIRST_ROWS + 400)
        small = tmp_path / "small"
        small.mkdir()
        (small / "only.txt").write_text("x")
        dialog = make_dialog(big, show_preview=False)
        try:
            dialog.show()
            assert dialog.state.row_backlog is not None

            dialog.logic.navigate_to(str(small))

            assert wait_until(lambda: _listing_complete(dialog, 1))
            pump(5)
            assert [entry.name for entry in dialog.state.row_entries.values()] == ["only.txt"]
            assert len(dpg.get_item_children(dialog._explorer_table, 1)) == 2
        finally:
            dialog.destroy()
            pump()
