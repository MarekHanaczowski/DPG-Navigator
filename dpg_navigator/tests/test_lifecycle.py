"""Lifecycle and concurrency tests exercising real background machinery.

These drive DirectoryIndex build and FileDialog background-index threads
against a real temp filesystem (generation cancellation, thread settle),
with DearPyGui mocked only at the call boundary.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

from dpg_navigator._dialog import FileDialog
from dpg_navigator._filesystem import DirectoryIndex
from dpg_navigator._types import DialogConfig
from dpg_navigator.dialog._logic import DialogLogic
from dpg_navigator.dialog._state import DialogState


class TestDirectoryIndexCancellation:
    """The generation counter must abort an in-flight build."""

    def test_build_cancels_when_generation_changes(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "f.txt").write_text("x")

        idx = DirectoryIndex()
        # get_generation() != generation → _walk aborts immediately.
        idx.build(str(tmp_path), generation=0, get_generation=lambda: 1)

        assert not idx.ready
        assert idx.search("f") == []

    def test_build_completes_when_generation_matches(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "needle.txt").write_text("x")

        idx = DirectoryIndex()
        idx.build(str(tmp_path), generation=3, get_generation=lambda: 3)

        assert idx.ready
        assert [e.name for e in idx.search("needle")] == ["needle.txt"]


def _make_logic(root: str, *, search_subfolders: bool = True):
    state = DialogState()
    state.current_dir = root
    config = DialogConfig(
        search_subfolders=search_subfolders,
        show_dir_size=False,
    )
    listings: list[list] = []
    logic = DialogLogic(
        state=state,
        config=config,
        refresh_ui_cb=lambda entries: listings.append(list(entries)),
        show_error_cb=lambda *_args: None,
        update_path_input_cb=lambda *_args: None,
        update_size_cell_cb=lambda *_args: None,
    )
    return logic, listings


class TestSearchSubfoldersToggle:
    def test_disable_stops_deep_search_results(self, tmp_path):
        nested = tmp_path / "sub"
        nested.mkdir()
        (nested / "needle.txt").write_text("x")
        (tmp_path / "other.txt").write_text("y")

        logic, listings = _make_logic(str(tmp_path))
        logic._dir_index.build(
            str(tmp_path),
            generation=logic.state.index_generation,
            get_generation=lambda: logic.state.index_generation,
        )
        logic._run_search("needle", logic.state.index_generation)
        assert any(e.name == "needle.txt" for e in listings[-1])

        logic.set_search_subfolders(False)
        assert logic.config.search_subfolders is False
        assert not any(e.name == "needle.txt" for e in listings[-1])

    def test_enable_sets_flag(self, tmp_path):
        logic, _listings = _make_logic(str(tmp_path), search_subfolders=False)
        logic.set_search_subfolders(True)
        assert logic.config.search_subfolders is True


class TestSafeUiCallbacks:
    def test_size_cell_skipped_when_destroyed(self):
        dialog = FileDialog.__new__(FileDialog)
        dialog._destroyed = True
        dialog.state = DialogState()
        dialog.state.pending_size_cells["/x"] = 99
        with patch("dpg_navigator._dialog.dpg") as mock_dpg:
            dialog._safe_update_size_cell("/x", "1 KB")
        mock_dpg.configure_item.assert_not_called()

    def test_refresh_skipped_when_destroyed(self):
        dialog = FileDialog.__new__(FileDialog)
        dialog._destroyed = True
        dialog.ui = MagicMock()
        with patch("dpg_navigator._dialog.dpg") as mock_dpg:
            dialog._safe_refresh_ui([])
        dialog.ui._render_entries_list.assert_not_called()
        mock_dpg.mutex.assert_not_called()

    def test_refresh_renders_when_alive(self):
        dialog = FileDialog.__new__(FileDialog)
        dialog._destroyed = False
        dialog.ui = MagicMock()
        with patch("dpg_navigator._dialog.dpg") as mock_dpg:
            dialog._safe_refresh_ui([])
        mock_dpg.mutex.assert_called()
        dialog.ui._render_entries_list.assert_called_once_with([])

    def test_path_input_skipped_when_destroyed(self):
        dialog = FileDialog.__new__(FileDialog)
        dialog._destroyed = True
        dialog._path_input = 1
        with patch("dpg_navigator._dialog.dpg") as mock_dpg:
            dialog._safe_update_path_input("/tmp")
        mock_dpg.configure_item.assert_not_called()


class TestGoUpShortcuts:
    """Alt+Up and the '..' row must use DialogLogic.go_up (archive-aware)."""

    def _dialog(self):
        dialog = FileDialog.__new__(FileDialog)
        dialog._config = DialogConfig(tag="nav_test")
        dialog.logic = MagicMock()
        dialog.state = DialogState()
        dialog._explorer_table = 1
        return dialog

    def test_alt_up_calls_logic_go_up(self):
        dialog = self._dialog()
        with patch("dpg_navigator._keyboard.dpg") as mock_dpg:
            mock_dpg.does_item_exist.return_value = True
            mock_dpg.is_item_shown.return_value = True
            mock_dpg.mvKey_LAlt = "LAlt"
            mock_dpg.mvKey_RAlt = "RAlt"
            mock_dpg.is_key_down.side_effect = lambda key: key == "LAlt"
            dialog._on_key_up(None, None, None)
        dialog.logic.go_up.assert_called_once()

    def test_plain_up_does_not_go_up(self):
        dialog = self._dialog()
        dialog.state.focused_row_index = 0
        with patch("dpg_navigator._keyboard.dpg") as mock_dpg:
            mock_dpg.does_item_exist.return_value = True
            mock_dpg.is_item_shown.return_value = True
            mock_dpg.is_key_down.return_value = False
            mock_dpg.get_item_children.return_value = []
            dialog._on_key_up(None, None, None)
        dialog.logic.go_up.assert_not_called()

    def test_activate_dotdot_row_calls_go_up(self):
        dialog = self._dialog()
        dialog.state.focused_row_index = 0
        dialog.state.row_entries = {}
        with patch("dpg_navigator._keyboard.dpg") as mock_dpg:
            mock_dpg.get_item_children.return_value = [99]
            dialog._activate_focused_row()
        dialog.logic.go_up.assert_called_once()

    def test_back_double_click_calls_go_up(self):
        dialog = self._dialog()
        sender = 7
        dialog.state.last_click_time = time.time()
        dialog.state.last_clicked_element = sender
        with patch("dpg_navigator._dialog.dpg") as mock_dpg, patch("dpg_navigator._dialog._platform") as plat:
            plat.is_mod_key_down.return_value = False
            dialog._on_back(sender, None, None)
        dialog.logic.go_up.assert_called_once()
        mock_dpg.set_value.assert_called()
