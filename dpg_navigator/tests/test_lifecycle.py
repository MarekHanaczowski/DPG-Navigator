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
from dpg_navigator._types import DialogConfig, FileEntry
from dpg_navigator.dialog._logic import DialogLogic
from dpg_navigator.dialog._state import DialogState
from dpg_navigator.dialog._ui import DialogUIBuilder


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

    def test_build_does_not_publish_after_walk_if_generation_changed(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "f.txt").write_text("x")

        idx = DirectoryIndex()
        seen = {"n": 0}

        def get_generation() -> int:
            seen["n"] += 1
            return 1 if seen["n"] < 3 else 99

        idx.build(str(tmp_path), generation=1, get_generation=get_generation)
        assert not idx.ready
        assert idx.search("f") == []


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
        refresh_ui_cb=lambda entries, gen=None: listings.append(list(entries)),
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

    def test_refresh_listing_restarts_index(self, tmp_path):
        logic, _listings = _make_logic(str(tmp_path), search_subfolders=True)
        with patch.object(logic, "start_index_build") as start:
            logic.refresh_listing()
        start.assert_called_once()

    def test_deep_search_ignores_index_from_other_root(self, tmp_path):
        other = tmp_path / "other"
        here = tmp_path / "here"
        other.mkdir()
        here.mkdir()
        (other / "needle.txt").write_text("x")
        (here / "local.txt").write_text("y")

        logic, listings = _make_logic(str(here))
        logic._dir_index.build(
            str(other),
            generation=logic.state.index_generation,
            get_generation=lambda: logic.state.index_generation,
        )
        logic._run_search("needle", logic.state.index_generation)
        assert not any(e.name == "needle.txt" for entries in listings for e in entries)


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

    def test_refresh_queues_listing_without_render(self):
        dialog = FileDialog.__new__(FileDialog)
        dialog._destroyed = False
        dialog.ui = MagicMock()
        dialog._awaiting_sidebar_drives = False
        with patch.object(FileDialog, "_schedule_ui_poll") as sched:
            dialog._safe_refresh_ui([])
        assert dialog._pending_listing == []
        dialog.ui._render_entries_list.assert_not_called()
        sched.assert_called_once()

    def test_apply_pending_listing_renders_on_dpg_thread(self):
        dialog = FileDialog.__new__(FileDialog)
        dialog._destroyed = False
        dialog.ui = MagicMock()
        dialog._pending_listing = []
        with patch("dpg_navigator._dialog.dpg") as mock_dpg:
            dialog._apply_pending_listing()
        mock_dpg.mutex.assert_called()
        dialog.ui._render_entries_list.assert_called_once_with([])
        assert dialog._pending_listing is None

    def test_stale_generation_listing_is_dropped(self):
        """A worker stamps the generation its listing was built under, so a
        listing produced before a navigation bump never overwrites the fresh
        one — even if the worker's callback runs after the bump."""
        dialog = FileDialog.__new__(FileDialog)
        dialog._destroyed = False
        dialog.ui = MagicMock()
        dialog.state = DialogState()
        dialog.state.index_generation = 7
        with patch.object(FileDialog, "_schedule_ui_poll"):
            dialog._safe_refresh_ui([], generation=6)
        assert dialog._pending_listing_gen == 6
        with patch("dpg_navigator._dialog.dpg"):
            dialog._apply_pending_listing()
        dialog.ui._render_entries_list.assert_not_called()
        assert dialog._pending_listing is None

    def test_matching_generation_listing_is_applied(self):
        dialog = FileDialog.__new__(FileDialog)
        dialog._destroyed = False
        dialog.ui = MagicMock()
        dialog.state = DialogState()
        dialog.state.index_generation = 7
        with patch.object(FileDialog, "_schedule_ui_poll"):
            dialog._safe_refresh_ui([], generation=7)
        with patch("dpg_navigator._dialog.dpg"):
            dialog._apply_pending_listing()
        dialog.ui._render_entries_list.assert_called_once_with([])

    def test_schedule_ui_poll_ignores_destroyed_dialog(self):
        dialog = FileDialog.__new__(FileDialog)
        dialog._destroyed = True
        before = list(FileDialog._sidebar_poll_targets)
        dialog._schedule_ui_poll()
        assert FileDialog._sidebar_poll_targets == before

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
            mock_dpg.get_active_window.return_value = "nav_test"
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
            mock_dpg.get_active_window.return_value = "nav_test"
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


class TestInstanceCount:
    def setup_method(self):
        self._saved = FileDialog._instance_count
        self._themes = (
            FileDialog._shared_selec_theme,
            FileDialog._shared_size_theme,
            FileDialog._shared_preview_active_theme,
        )

    def teardown_method(self):
        FileDialog._instance_count = self._saved
        (
            FileDialog._shared_selec_theme,
            FileDialog._shared_size_theme,
            FileDialog._shared_preview_active_theme,
        ) = self._themes

    def _bare_dialog(self) -> FileDialog:
        dialog = FileDialog.__new__(FileDialog)
        dialog._destroyed = False
        dialog._awaiting_sidebar_drives = False
        dialog._pending_sidebar_drives = None
        dialog._pending_listing = None
        dialog.logic = MagicMock()
        dialog._preview = MagicMock()
        dialog._icons = MagicMock()
        dialog._config = DialogConfig(tag="count_test")
        dialog._key_handler = 1
        return dialog

    def test_first_of_two_destroy_skips_shared_teardown(self):
        FileDialog._instance_count = 2
        dialog = self._bare_dialog()
        with (
            patch("dpg_navigator._dialog.dpg") as mock_dpg,
            patch("dpg_navigator._dialog.JobManager") as jobs,
            patch("dpg_navigator._dialog.DirectoryLister.cleanup_temp_files") as cleanup,
            patch("dpg_navigator._html.HTMLRenderer.shutdown_shared"),
        ):
            mock_dpg.does_item_exist.return_value = False
            dialog.destroy()
        assert FileDialog._instance_count == 1
        jobs.shutdown.assert_not_called()
        cleanup.assert_not_called()

    def test_last_destroy_runs_shared_teardown(self):
        FileDialog._instance_count = 1
        dialog = self._bare_dialog()
        with (
            patch("dpg_navigator._dialog.dpg") as mock_dpg,
            patch("dpg_navigator._dialog.JobManager") as jobs,
            patch("dpg_navigator._dialog.DirectoryLister.cleanup_temp_files") as cleanup,
            patch("dpg_navigator._html.HTMLRenderer.shutdown_shared"),
        ):
            mock_dpg.does_item_exist.return_value = False
            dialog.destroy()
        assert FileDialog._instance_count == 0
        jobs.shutdown.assert_called_once()
        cleanup.assert_called_once()

    def test_destroy_decrements_when_preview_raises(self):
        FileDialog._instance_count = 1
        dialog = self._bare_dialog()
        dialog._preview.destroy.side_effect = RuntimeError("preview boom")
        with (
            patch("dpg_navigator._dialog.dpg") as mock_dpg,
            patch("dpg_navigator._dialog.JobManager") as jobs,
            patch("dpg_navigator._dialog.DirectoryLister.cleanup_temp_files") as cleanup,
            patch("dpg_navigator._html.HTMLRenderer.shutdown_shared"),
        ):
            mock_dpg.does_item_exist.return_value = False
            dialog.destroy()
        assert FileDialog._instance_count == 0
        jobs.shutdown.assert_called_once()
        cleanup.assert_called_once()


class TestKeyboardFocusAndSelectAll:
    def _dialog(self, **config: object) -> FileDialog:
        dialog = FileDialog.__new__(FileDialog)
        dialog._config = DialogConfig(tag="nav_test", **config)  # type: ignore[arg-type]
        dialog.logic = MagicMock()
        dialog.state = DialogState()
        dialog.hide = MagicMock()  # type: ignore[method-assign]
        dialog._explorer_table = 1
        dialog._path_input = None  # type: ignore[assignment]
        dialog._filename_input = None  # type: ignore[assignment]
        dialog._new_folder_input = None  # type: ignore[assignment]
        dialog._search_input = None  # type: ignore[assignment]
        dialog._selected_files = []
        dialog._selected_elements = []
        return dialog

    def test_escape_ignored_when_shown_but_unfocused(self):
        dialog = self._dialog()
        with patch("dpg_navigator._keyboard.dpg") as mock_dpg:
            mock_dpg.does_item_exist.return_value = True
            mock_dpg.is_item_shown.return_value = True
            mock_dpg.get_active_window.return_value = "other"
            mock_dpg.is_item_focused.return_value = False
            mock_dpg.is_item_active.return_value = False
            dialog._on_key_escape(None, None, None)
        dialog.hide.assert_not_called()

    def test_escape_hides_when_window_active(self):
        dialog = self._dialog()
        with patch("dpg_navigator._keyboard.dpg") as mock_dpg:
            mock_dpg.does_item_exist.return_value = True
            mock_dpg.is_item_shown.return_value = True
            mock_dpg.get_active_window.return_value = "nav_test"
            dialog._on_key_escape(None, None, None)
        dialog.hide.assert_called_once()

    def test_ctrl_a_ignored_when_search_input_active(self):
        dialog = self._dialog()
        dialog._search_input = 42
        with patch("dpg_navigator._keyboard.dpg") as mock_dpg, patch("dpg_navigator._keyboard._platform") as plat:
            mock_dpg.does_item_exist.return_value = True
            mock_dpg.is_item_shown.return_value = True
            mock_dpg.get_active_window.return_value = "nav_test"
            mock_dpg.is_item_active.side_effect = lambda item: item == 42
            plat.is_mod_key_down.return_value = True
            dialog._on_key_a(None, None, None)
        mock_dpg.get_item_children.assert_not_called()

    def test_ctrl_a_ignored_when_multi_selection_off(self):
        dialog = self._dialog(multi_selection=False)
        with patch("dpg_navigator._keyboard.dpg") as mock_dpg, patch("dpg_navigator._keyboard._platform") as plat:
            mock_dpg.does_item_exist.return_value = True
            mock_dpg.is_item_shown.return_value = True
            mock_dpg.get_active_window.return_value = "nav_test"
            plat.is_mod_key_down.return_value = True
            dialog._on_key_a(None, None, None)
        mock_dpg.get_item_children.assert_not_called()


class TestRowEntriesReset:
    def test_render_clears_stale_row_ids(self):
        state = DialogState()
        stale = FileEntry("old.txt", "/old.txt", is_dir=False, size_bytes=1, modified_time=0.0, is_hidden=False)
        state.row_entries[99] = stale
        dialog = MagicMock()
        dialog._status_label = None
        dialog._path_input = 1
        dialog._explorer_table = 2
        dialog._selec_height = 20
        builder = DialogUIBuilder(dialog, state, MagicMock(), DialogConfig())
        with patch("dpg_navigator.dialog._ui.dpg") as mock_dpg:
            mock_dpg.get_item_children.return_value = []
            builder._render_entries_list([])
        assert state.row_entries == {}
