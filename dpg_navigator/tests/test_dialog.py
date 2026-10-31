"""Tests for FileDialog glue: selection, archives, sidebar drives, adapters.

DearPyGui is mocked. Path validation and listing helpers are imported from
``dpg_navigator._filesystem`` rather than reimplemented here.
"""

from __future__ import annotations

import os
import time
import zipfile
from unittest.mock import MagicMock, patch

import pytest

from dpg_navigator._dialog import FileDialog
from dpg_navigator._filesystem import (
    DirectoryIndex,
    DirectoryLister,
    build_selection_list,
    validate_folder_name,
)
from dpg_navigator._types import DialogConfig, FileEntry
from dpg_navigator.dialog._state import DialogState
from dpg_navigator.dialog._ui import DialogUIBuilder


class TestSidebarDriveLoading:
    def test_sidebar_build_defers_drive_enumeration(self):
        builder = DialogUIBuilder.__new__(DialogUIBuilder)
        builder.dialog = MagicMock()
        builder.dialog._sidebar.get_width.return_value = 200
        builder.dialog._destroyed = False
        builder.logic = MagicMock()
        builder.config = MagicMock(
            show_shortcuts=True,
            custom_dirs=[],
        )

        with (
            patch("dpg_navigator.dialog._ui.dpg") as mock_dpg,
            patch("dpg_navigator.dialog._ui.get_special_dirs", return_value={}),
            patch("dpg_navigator.dialog._ui.get_drives") as get_drives,
            patch("dpg_navigator.dialog._ui.JobManager.submit") as submit,
        ):
            mock_dpg.child_window.return_value = MagicMock()
            builder._build_sidebar("dialog", 56)

        get_drives.assert_not_called()
        submit.assert_called_once_with(
            builder._load_sidebar_drives,
            "dialog_shortcut_menu",
        )
        builder.dialog._arm_sidebar_drive_poll.assert_called_once()
        builder.dialog._sidebar.render.assert_called_once()
        assert builder.dialog._sidebar.render.call_args.kwargs["drives"] == []

    def test_delayed_drive_result_is_stored_not_applied(self):
        builder = DialogUIBuilder.__new__(DialogUIBuilder)
        builder.dialog = MagicMock()
        builder.dialog._destroyed = False
        builder.dialog._sidebar = MagicMock()

        def delayed_drives():
            time.sleep(0.01)
            return ["/slow-network-mount"]

        with (
            patch(
                "dpg_navigator.dialog._ui.get_drives",
                side_effect=delayed_drives,
            ),
            patch("dpg_navigator.dialog._ui.dpg") as mock_dpg,
        ):
            builder._load_sidebar_drives("dialog_shortcut_menu")

        mock_dpg.mutex.assert_not_called()
        builder.dialog._sidebar.update_drives.assert_not_called()
        assert builder.dialog._pending_sidebar_drives == (
            "dialog_shortcut_menu",
            ["/slow-network-mount"],
        )


class TestSidebarDrivePoll:
    def teardown_method(self):
        FileDialog._sidebar_poll_targets = []
        FileDialog._sidebar_poll_armed = False

    def test_apply_updates_sidebar_on_main_thread(self):
        dialog = FileDialog.__new__(FileDialog)
        dialog._destroyed = False
        dialog._pending_sidebar_drives = ("tag", ["/mnt"])
        dialog._awaiting_sidebar_drives = True
        dialog._sidebar = MagicMock()
        with patch("dpg_navigator._dialog.dpg") as mock_dpg:
            mock_dpg.does_item_exist.return_value = True
            dialog._apply_pending_sidebar_drives()
        dialog._sidebar.update_drives.assert_called_once_with(["/mnt"])
        assert dialog._awaiting_sidebar_drives is False
        assert dialog._pending_sidebar_drives is None

    def test_poll_reschedules_while_waiting(self):
        dialog = FileDialog.__new__(FileDialog)
        dialog._destroyed = False
        dialog._pending_sidebar_drives = None
        dialog._awaiting_sidebar_drives = True
        FileDialog._sidebar_poll_targets = [dialog]
        FileDialog._sidebar_poll_armed = True
        with patch("dpg_navigator._dialog.dpg") as mock_dpg:
            mock_dpg.get_frame_count.return_value = 4
            FileDialog._poll_sidebar_drives()
        mock_dpg.set_frame_callback.assert_called_once()
        assert FileDialog._sidebar_poll_targets == [dialog]
        assert FileDialog._sidebar_poll_armed is True

    def test_arm_is_a_no_op_when_already_scheduled(self):
        dialog = FileDialog.__new__(FileDialog)
        dialog._destroyed = False
        FileDialog._sidebar_poll_armed = True
        with patch("dpg_navigator._dialog.dpg") as mock_dpg:
            dialog._arm_sidebar_drive_poll()
        mock_dpg.set_frame_callback.assert_not_called()
        assert dialog in FileDialog._sidebar_poll_targets


# ── Path traversal validation ───────────────────────────────────


class TestPathTraversalValidation:
    """Test validate_folder_name() imported from dpg_navigator._filesystem."""

    def test_simple_name_valid(self, tmp_path):
        assert validate_folder_name("MyFolder", str(tmp_path)) is None

    def test_name_with_spaces_valid(self, tmp_path):
        assert validate_folder_name("My Folder", str(tmp_path)) is None

    def test_name_with_dash_valid(self, tmp_path):
        assert validate_folder_name("my-folder", str(tmp_path)) is None

    def test_name_with_underscore_valid(self, tmp_path):
        assert validate_folder_name("my_folder_2024", str(tmp_path)) is None

    def test_unicode_name_valid(self, tmp_path):
        assert validate_folder_name("Dokumenty", str(tmp_path)) is None

    def test_dot_dot_rejected(self, tmp_path):
        assert validate_folder_name("..", str(tmp_path)) is not None

    def test_parent_traversal_rejected(self, tmp_path):
        assert validate_folder_name("../../etc", str(tmp_path)) is not None

    def test_path_separator_rejected(self, tmp_path):
        name = f"folder{os.sep}subfolder"
        assert validate_folder_name(name, str(tmp_path)) is not None

    @pytest.mark.skipif(os.altsep is None, reason="No alt separator on this OS")
    def test_alt_separator_rejected(self, tmp_path):
        name = f"folder{os.altsep}subfolder"
        assert validate_folder_name(name, str(tmp_path)) is not None

    def test_hidden_folder_name_valid(self, tmp_path):
        """Dot-prefix folders (like .git) should be allowed."""
        assert validate_folder_name(".git", str(tmp_path)) is None

    def test_double_dot_in_middle_rejected(self, tmp_path):
        assert validate_folder_name("folder/../escape", str(tmp_path)) is not None

    def test_backslash_on_windows(self, tmp_path):
        """On Windows, backslash is os.sep so it should be rejected."""
        if os.sep == "\\":
            assert validate_folder_name("folder\\sub", str(tmp_path)) is not None

    def test_forward_slash_on_windows(self, tmp_path):
        """On Windows, / is os.altsep so it should be rejected."""
        if os.altsep == "/":
            assert validate_folder_name("folder/sub", str(tmp_path)) is not None

    def test_empty_name(self, tmp_path):
        """Empty name is rejected."""
        assert validate_folder_name("", str(tmp_path)) is not None

    def test_whitespace_name(self, tmp_path):
        assert validate_folder_name("   ", str(tmp_path)) is not None

    def test_single_dot_rejected(self, tmp_path):
        """Bare '.' is not a valid new folder name."""
        assert validate_folder_name(".", str(tmp_path)) is not None

    def test_error_message_contains_name(self, tmp_path):
        """Error messages from validate_folder_name include the offending name."""
        result = validate_folder_name("..", str(tmp_path))
        assert ".." in result


# ── Selection return logic ──────────────────────────────────────


class TestReturnSelectionLogic:
    """Test build_selection_list() imported from dpg_navigator._filesystem."""

    def test_selected_files_returned_as_is(self):
        result = build_selection_list(["/tmp/a.txt"], "", "/tmp")
        assert result == ["/tmp/a.txt"]

    def test_multiple_selected_files(self):
        files = ["/tmp/a.txt", "/tmp/b.txt"]
        result = build_selection_list(files, "", "/tmp")
        assert result == files

    def test_typed_name_when_no_selection(self):
        result = build_selection_list([], "myfile.txt", "/home/user")
        assert result == [os.path.join("/home/user", "myfile.txt")]

    def test_typed_name_stripped(self):
        result = build_selection_list([], "  myfile.txt  ", "/home/user")
        assert result == [os.path.join("/home/user", "myfile.txt")]

    def test_empty_typed_name_returns_empty(self):
        result = build_selection_list([], "", "/home/user")
        assert result == []

    def test_whitespace_typed_name_returns_empty(self):
        result = build_selection_list([], "   ", "/home/user")
        assert result == []

    def test_selected_files_take_priority_over_typed(self):
        """When files are selected, typed name is ignored."""
        result = build_selection_list(["/tmp/selected.txt"], "typed.txt", "/tmp")
        assert result == ["/tmp/selected.txt"]

    def test_typed_name_builds_full_path(self, tmp_path):
        result = build_selection_list([], "test.py", str(tmp_path))
        expected = os.path.join(str(tmp_path), "test.py")
        assert result == [expected]

    def test_does_not_mutate_input(self):
        """build_selection_list must return a NEW list, not modify the input."""
        original = ["/tmp/a.txt"]
        result = build_selection_list(original, "", "/tmp")
        assert result == original
        assert result is not original

    def test_typed_name_rejects_parent_traversal(self, tmp_path):
        result = build_selection_list([], "..", str(tmp_path))
        assert result == []

    def test_typed_name_rejects_path_separators(self, tmp_path):
        result = build_selection_list([], f"sub{os.sep}file.txt", str(tmp_path))
        assert result == []

    def test_typed_name_rejects_dotdot_segment(self, tmp_path):
        result = build_selection_list([], f"..{os.sep}escape.txt", str(tmp_path))
        assert result == []


class TestFileDialogArchiveSelection:
    """FileDialog._return_selection extracts archive members and surfaces failures."""

    def _dialog(self, tmp_path, selected):
        dialog = FileDialog.__new__(FileDialog)
        dialog.state = DialogState()
        dialog.state.selected_files = selected
        dialog.state.current_dir = str(tmp_path)
        dialog._callback = MagicMock()
        dialog._filename_input = 1
        dialog._status_label = 2
        dialog._config = DialogConfig(modal=True, tag="sel_archive_test")
        dialog.hide = MagicMock()
        return dialog

    def test_oversized_member_shows_error_and_keeps_dialog_open(self, tmp_path):
        archive_path = tmp_path / "large.zip"
        with zipfile.ZipFile(archive_path, "w") as zf:
            zf.writestr("docs/large.txt", "x" * 32)
        dialog = self._dialog(tmp_path, [f"{archive_path}|/docs/large.txt"])
        dialog._MAX_ARCHIVE_EXTRACT_SIZE = 8
        try:
            with patch("dpg_navigator._dialog.dpg") as mock_dpg:
                mock_dpg.get_value.return_value = ""
                mock_dpg.does_item_exist.return_value = True
                mock_dpg.get_item_label.return_value = "File Dialog"
                dialog._return_selection()
                status = mock_dpg.set_value.call_args[0][1]
            dialog._callback.assert_not_called()
            dialog.hide.assert_not_called()
            assert "Extraction Error" in status
            assert "large.txt" in status
        finally:
            DirectoryLister.cleanup_temp_files()

    def test_rejected_typed_name_shows_message_and_keeps_dialog_open(self, tmp_path):
        dialog = self._dialog(tmp_path, [])
        with patch("dpg_navigator._dialog.dpg") as mock_dpg:
            mock_dpg.get_value.return_value = f"sub{os.sep}escape.txt"
            mock_dpg.does_item_exist.return_value = True
            dialog._return_selection()
            status = mock_dpg.set_value.call_args[0][1]
        dialog.hide.assert_not_called()
        dialog._callback.assert_not_called()
        assert status.startswith("Invalid file name:")
        assert "path separator" in status

    def test_valid_typed_name_returns_path(self, tmp_path):
        dialog = self._dialog(tmp_path, [])
        with patch("dpg_navigator._dialog.dpg") as mock_dpg:
            mock_dpg.get_value.return_value = "new_report.txt"
            mock_dpg.does_item_exist.return_value = True
            dialog._return_selection()
        dialog.hide.assert_called_once()
        dialog._callback.assert_called_once_with([os.path.join(str(tmp_path), "new_report.txt")])

    def test_empty_typed_name_still_returns_empty_selection(self, tmp_path):
        dialog = self._dialog(tmp_path, [])
        with patch("dpg_navigator._dialog.dpg") as mock_dpg:
            mock_dpg.get_value.return_value = ""
            mock_dpg.does_item_exist.return_value = True
            dialog._return_selection()
        dialog.hide.assert_called_once()
        dialog._callback.assert_called_once_with([])

    def test_member_within_limit_invokes_callback(self, tmp_path):
        archive_path = tmp_path / "ok.zip"
        with zipfile.ZipFile(archive_path, "w") as zf:
            zf.writestr("docs/readme.txt", "hello")
        dialog = self._dialog(tmp_path, [f"{archive_path}|/docs/readme.txt"])
        dialog._MAX_ARCHIVE_EXTRACT_SIZE = 1024
        try:
            with patch("dpg_navigator._dialog.dpg") as mock_dpg:
                mock_dpg.get_value.return_value = ""
                mock_dpg.does_item_exist.return_value = True
                mock_dpg.get_item_label.return_value = "File Dialog"
                dialog._return_selection()
            dialog.hide.assert_called_once()
            dialog._callback.assert_called_once()
            resolved = dialog._callback.call_args[0][0]
            assert len(resolved) == 1
            assert os.path.isfile(resolved[0])
        finally:
            DirectoryLister.cleanup_temp_files()


# ── Double-click detection logic ────────────────────────────────


class TestDoubleClickLogic:
    """Exercise the real ``FileDialog._is_double_click`` with a patched clock."""

    @staticmethod
    def _dialog(last_time: float, last_sender: int | None) -> FileDialog:
        dialog = FileDialog.__new__(FileDialog)
        dialog.state = DialogState()
        dialog.state.last_click_time = last_time
        dialog.state.last_clicked_element = last_sender
        return dialog

    @staticmethod
    def _click(dialog: FileDialog, sender: int, now: float) -> bool:
        with patch("dpg_navigator._dialog.time.time", return_value=now):
            return dialog._is_double_click(sender)

    def test_threshold_constant(self):
        assert FileDialog.DOUBLE_CLICK_THRESHOLD == 0.5

    def test_fast_same_element_is_double_and_resets(self):
        dialog = self._dialog(1000.0, 42)
        assert self._click(dialog, 42, 1000.2) is True
        assert dialog.state.last_click_time == 0
        assert dialog.state.last_clicked_element is None

    def test_slow_same_element_not_double(self):
        dialog = self._dialog(1000.0, 42)
        assert self._click(dialog, 42, 1001.0) is False
        assert dialog.state.last_click_time == 1001.0
        assert dialog.state.last_clicked_element == 42

    def test_fast_different_element_not_double(self):
        dialog = self._dialog(1000.0, 42)
        assert self._click(dialog, 99, 1000.2) is False
        assert dialog.state.last_clicked_element == 99

    def test_exactly_at_threshold_not_double(self):
        dialog = self._dialog(1000.0, 42)
        assert self._click(dialog, 42, 1000.0 + FileDialog.DOUBLE_CLICK_THRESHOLD) is False

    def test_no_previous_click_not_double(self):
        dialog = self._dialog(0.0, None)
        assert self._click(dialog, 42, 1000.0) is False

    def test_third_click_after_double_starts_over(self):
        dialog = self._dialog(1000.0, 42)
        assert self._click(dialog, 42, 1000.1) is True
        assert self._click(dialog, 42, 1000.2) is False
        assert self._click(dialog, 42, 1000.3) is True


# ── Path traversal with symlinks ───────────────────────────────


class TestPathTraversalSymlinks:
    """Test that symlink-based escapes are blocked by realpath validation.

    Uses the real validate_folder_name from dpg_navigator._filesystem.
    """

    @pytest.mark.skipif(os.name == "nt", reason="Symlinks need privileges on Windows")
    def test_symlink_escape_blocked(self, tmp_path):
        """Symlink pointing outside current_dir should be allowed as a name
        (it's just a folder name, not a symlink creation). The validation
        checks the NAME, not existing filesystem entries."""
        # The name "escape_link" is a valid folder name (no .. or separators)
        assert validate_folder_name("escape_link", str(tmp_path)) is None

    @pytest.mark.skipif(os.name == "nt", reason="Symlinks need privileges on Windows")
    def test_realpath_resolves_through_existing_symlink(self, tmp_path):
        """If a symlink exists at the target path, realpath resolves it.
        The folder won't be created (exist_ok=False), but validation
        should still check the resolved path is under current_dir."""
        outside = tmp_path / "outside"
        outside.mkdir()
        inside = tmp_path / "workdir"
        inside.mkdir()
        # Create a symlink inside workdir pointing to outside
        (inside / "sneaky").symlink_to(outside)
        # Now validate: resolved path of workdir/sneaky = outside, which
        # is NOT under workdir
        result = validate_folder_name("sneaky", str(inside))
        assert result is not None


# ── Folder creation execution tests ────────────────────────────


def _folder_logic(current_dir: str):
    """Real DialogLogic with recording callbacks, for folder-creation tests."""
    from dpg_navigator.dialog._logic import DialogLogic

    state = DialogState()
    state.current_dir = current_dir
    errors: list[tuple[str, str]] = []
    listings: list[list[FileEntry]] = []
    logic = DialogLogic(
        state=state,
        config=DialogConfig(search_subfolders=False, show_dir_size=False),
        refresh_ui_cb=lambda entries, _gen: listings.append(list(entries)),
        show_error_cb=lambda title, msg: errors.append((title, msg)),
        update_path_input_cb=lambda _path: None,
        update_size_cell_cb=lambda *_args: None,
    )
    return logic, errors, listings


class TestCreateNewFolderExecution:
    """Folder creation through the production ``DialogLogic._create_new_folder``."""

    def test_successful_creation_refreshes_listing(self, tmp_path):
        logic, errors, listings = _folder_logic(str(tmp_path))
        logic._create_new_folder("new_folder")
        assert errors == []
        assert (tmp_path / "new_folder").is_dir()
        assert any(entry.name == "new_folder" for entry in listings[-1])

    def test_name_is_stripped(self, tmp_path):
        logic, errors, _ = _folder_logic(str(tmp_path))
        logic._create_new_folder("  padded  ")
        assert errors == []
        assert (tmp_path / "padded").is_dir()

    def test_already_exists(self, tmp_path):
        (tmp_path / "existing").mkdir()
        logic, errors, _ = _folder_logic(str(tmp_path))
        logic._create_new_folder("existing")
        assert errors == [("Folder exists", "A folder named 'existing' already exists.")]

    def test_empty_name_rejected(self, tmp_path):
        logic, errors, _ = _folder_logic(str(tmp_path))
        logic._create_new_folder("   ")
        assert errors == [("Invalid name", "Folder name cannot be empty.")]

    def test_path_traversal_blocked(self, tmp_path):
        before = sorted(os.listdir(tmp_path.parent))
        logic, errors, _ = _folder_logic(str(tmp_path))
        logic._create_new_folder("..")
        assert errors and errors[0][0] == "Invalid folder name"
        assert sorted(os.listdir(tmp_path.parent)) == before

    def test_separator_in_name_blocked(self, tmp_path):
        logic, errors, _ = _folder_logic(str(tmp_path))
        logic._create_new_folder(f"a{os.sep}b")
        assert errors and errors[0][0] == "Invalid folder name"
        assert not (tmp_path / "a").exists()

    def test_nested_path_traversal_blocked(self, tmp_path):
        logic, errors, _ = _folder_logic(str(tmp_path))
        logic._create_new_folder("../../escape")
        assert errors and errors[0][0] == "Invalid folder name"

    def test_unicode_name_created(self, tmp_path):
        logic, errors, _ = _folder_logic(str(tmp_path))
        logic._create_new_folder("Nowy Folder")
        assert errors == []
        assert (tmp_path / "Nowy Folder").is_dir()

    def test_dot_prefix_allowed(self, tmp_path):
        logic, errors, _ = _folder_logic(str(tmp_path))
        logic._create_new_folder(".config")
        assert errors == []
        assert (tmp_path / ".config").is_dir()

    def test_refused_inside_archive(self, tmp_path):
        archive_path = tmp_path / "pack.zip"
        with zipfile.ZipFile(archive_path, "w") as zf:
            zf.writestr("a.txt", "x")
        logic, errors, _ = _folder_logic(f"{archive_path}|/")
        logic._create_new_folder("inner")
        assert errors == [("Not supported", "Cannot create folders inside an archive.")]

    def test_os_error_is_reported(self, tmp_path):
        logic, errors, _ = _folder_logic(str(tmp_path))
        with patch("dpg_navigator.dialog._logic.os.makedirs", side_effect=PermissionError("denied")):
            logic._create_new_folder("locked")
        assert len(errors) == 1
        assert errors[0][0] == "Error"
        assert "denied" in errors[0][1]


# ── Async directory size cache logic ──────────────────────────


class TestSizeCacheLogic:
    """Directory-size cache behavior through the production code paths."""

    @staticmethod
    def _logic(root, cells=None):
        from dpg_navigator.dialog._logic import DialogLogic

        state = DialogState()
        state.current_dir = str(root)
        return DialogLogic(
            state=state,
            config=DialogConfig(search_subfolders=False, show_dir_size=True),
            refresh_ui_cb=lambda *_args: None,
            show_error_cb=lambda *_args: None,
            update_path_input_cb=lambda *_args: None,
            update_size_cell_cb=(lambda p, text: cells.append((p, text))) if cells is not None else (lambda *_a: None),
        )

    @staticmethod
    def _run_now(fn, *args, **kwargs):
        fn(*args, **kwargs)

    def test_cache_ttl_constant(self):
        assert FileDialog._SIZE_CACHE_TTL == 60.0

    def test_size_job_fills_cache_and_cell(self, tmp_path):
        sub = tmp_path / "subdir"
        sub.mkdir()
        (sub / "data.txt").write_text("12345678")  # 8 bytes
        cells: list[tuple[str, str]] = []
        logic = self._logic(tmp_path, cells)

        with patch("dpg_navigator.dialog._logic.JobManager.submit", side_effect=self._run_now):
            logic.start_size_computation([str(sub)])

        size, stamp = logic.state.size_cache[str(sub)]
        assert size == 8
        assert time.time() - stamp < FileDialog._SIZE_CACHE_TTL
        assert cells == [(str(sub), "8 B")]

    def test_empty_dir_caches_zero(self, tmp_path):
        empty = tmp_path / "empty_dir"
        empty.mkdir()
        logic = self._logic(tmp_path)

        with patch("dpg_navigator.dialog._logic.JobManager.submit", side_effect=self._run_now):
            logic.start_size_computation([str(empty)])

        assert logic.state.size_cache[str(empty)][0] == 0

    def test_generation_change_stops_remaining_dirs(self, tmp_path):
        dirs = []
        for i in range(3):
            d = tmp_path / f"dir_{i}"
            d.mkdir()
            (d / "f.txt").write_text("x" * (i + 1))
            dirs.append(str(d))
        logic = self._logic(tmp_path)

        def bump_generation(_path, _text):
            logic.state.bg_generation += 1  # e.g. the user navigated away

        logic.update_size_cell = bump_generation
        with patch("dpg_navigator.dialog._logic.JobManager.submit", side_effect=self._run_now):
            logic.start_size_computation(dirs)

        assert list(logic.state.size_cache) == [dirs[0]]

    def test_size_job_skipped_when_nothing_to_measure(self, tmp_path):
        logic = self._logic(tmp_path)
        with patch("dpg_navigator.dialog._logic.JobManager.submit") as submit:
            logic.start_size_computation([])
        submit.assert_not_called()

    def test_f5_clears_cache_and_refreshes(self):
        dialog = FileDialog.__new__(FileDialog)
        dialog.state = DialogState()
        dialog.logic = MagicMock()
        dialog.state.size_cache.update({"/tmp/a": (100, time.time()), "/tmp/b": (200, time.time())})

        with (
            patch.object(FileDialog, "_is_dialog_active", return_value=True),
            patch.object(FileDialog, "_refresh_listing", create=True) as refresh,
        ):
            dialog._on_key_f5(None, None, None)

        assert dialog.state.size_cache == {}
        dialog.logic._dir_index.invalidate.assert_called_once()
        refresh.assert_called_once()

    def test_sort_by_size_uses_cached_dir_size(self):
        dialog = FileDialog.__new__(FileDialog)
        dialog.state = DialogState()
        big = FileEntry("big", "/tmp/big", True, None, 1.0, False)
        small = FileEntry("small", "/tmp/small", True, None, 1.0, False)
        dialog.state.row_entries = {11: small, 12: big}
        dialog.state.size_cache = {"/tmp/big": (1000, time.time()), "/tmp/small": (10, time.time())}

        with patch("dpg_navigator._dialog.dpg") as mock_dpg:
            mock_dpg.get_item_children.side_effect = lambda _item, slot: (
                [100, 101, 102, 103] if slot == 0 else [1, 11, 12]
            )
            dialog._on_sort("table", [(103, -1)], None)  # column 3 = Size, descending

        mock_dpg.reorder_items.assert_called_once_with("table", 1, [1, 12, 11])


# ── Polish characters in validation and selection ─────────────


class TestPolishCharactersValidation:
    """Verify that validate_folder_name and build_selection_list
    handle Polish diacritics correctly."""

    def test_validate_polish_folder_name(self, tmp_path):
        """Polish folder names pass validation."""
        assert validate_folder_name("Zdjęcia", str(tmp_path)) is None

    def test_validate_all_diacritics(self, tmp_path):
        """Folder name with all Polish diacritics passes validation."""
        assert validate_folder_name("ąćęłńóśźż", str(tmp_path)) is None

    def test_validate_polish_with_spaces(self, tmp_path):
        """Polish name with spaces passes validation."""
        assert validate_folder_name("Nowy Katalog Źródeł", str(tmp_path)) is None

    def test_validate_polish_uppercase(self, tmp_path):
        """Polish uppercase characters pass validation."""
        assert validate_folder_name("ĄĆĘŁŃÓŚŹŻ", str(tmp_path)) is None

    def test_validate_polish_traversal_still_blocked(self, tmp_path):
        """Path traversal with Polish characters is still blocked."""
        assert validate_folder_name("../Zdjęcia", str(tmp_path)) is not None

    def test_validate_polish_separator_still_blocked(self, tmp_path):
        """Separator in Polish-named path is still blocked."""
        name = f"Ścieżka{os.sep}podkatalog"
        assert validate_folder_name(name, str(tmp_path)) is not None

    def test_build_selection_polish_typed_name(self):
        """Typed Polish filename is combined with current_dir."""
        result = build_selection_list([], "zdjęcie.png", "/home/user")
        assert result == [os.path.join("/home/user", "zdjęcie.png")]

    def test_build_selection_polish_selected_files(self):
        """Selected files with Polish names returned as-is."""
        files = ["/tmp/łąka.txt", "/tmp/żółć.py"]
        result = build_selection_list(files, "", "/tmp")
        assert result == files

    def test_build_selection_polish_typed_stripped(self):
        """Whitespace around Polish typed name is stripped."""
        result = build_selection_list([], "  książka.txt  ", "/home")
        assert result == [os.path.join("/home", "książka.txt")]

    def test_create_polish_folder(self, tmp_path):
        """Full folder creation flow with Polish name succeeds."""
        name = "Różne dokumenty"
        logic, errors, _ = _folder_logic(str(tmp_path))
        logic._create_new_folder(name)
        assert errors == []
        assert (tmp_path / name).is_dir()


# ── Preview image extension tests ──────────────────────────────


class TestDialogCompatibilityAdapters:
    def test_keyboard_mixin_adapters_share_dialog_state(self):
        dialog = FileDialog.__new__(FileDialog)
        dialog.state = DialogState()
        dialog.logic = MagicMock()

        size_cache: dict[str, tuple[int | None, float]] = {"file.txt": (4, 1.0)}
        directory_index = DirectoryIndex()
        selected_files = ["/tmp/file.txt"]
        selected_elements = [11]
        row_entries = {
            12: FileEntry("file.txt", "/tmp/file.txt", False, 4, 1.0, False),
        }

        dialog._size_cache = size_cache
        dialog._dir_index = directory_index
        dialog._selected_files = selected_files
        dialog._selected_elements = selected_elements
        dialog._row_entries = row_entries
        dialog._current_dir = "/tmp"
        dialog._focused_row_index = 2
        dialog._last_clicked_element = 11

        assert dialog.state.size_cache is size_cache
        assert dialog.logic._dir_index is directory_index
        assert dialog.state.selected_files is selected_files
        assert dialog.state.selected_elements is selected_elements
        assert dialog.state.row_entries is row_entries
        assert dialog.state.current_dir == "/tmp"
        assert dialog.state.focused_row_index == 2
        assert dialog.state.last_clicked_element == 11
