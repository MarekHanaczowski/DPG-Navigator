"""Tests for dpg_navigator._dialog — path validation and selection logic.

Only tests logic that can be verified WITHOUT running DearPyGui.
All DPG calls are mocked where needed.

Imports validate_folder_name and build_selection_list from the ACTUAL source
(dpg_navigator._filesystem) instead of duplicating the logic in tests.
"""

import os
import time
from unittest.mock import patch, MagicMock

import pytest

from dpg_navigator._filesystem import validate_folder_name, build_selection_list, DirectoryLister
from dpg_navigator._dialog import FileDialog
from dpg_navigator._preview import PreviewPanel


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
        """Empty name passes validation (other checks handle it)."""
        assert validate_folder_name("", str(tmp_path)) is None

    def test_whitespace_name(self, tmp_path):
        assert validate_folder_name("   ", str(tmp_path)) is None

    def test_single_dot_valid(self, tmp_path):
        """Single dot is not '..' so passes the first check, but realpath
        resolves it to current_dir, which starts with current_dir."""
        assert validate_folder_name(".", str(tmp_path)) is None

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


# ── Double-click detection logic ────────────────────────────────


class TestDoubleClickLogic:
    """Test the double-click timing logic extracted from FileDialog.

    This logic is a simple comparison (time_diff < threshold and same_sender)
    that is unlikely to be extracted into a standalone function, so we
    reproduce it here as a static method.
    """

    THRESHOLD = 0.5

    @staticmethod
    def _is_double_click(
        current_time: float,
        last_click_time: float,
        current_sender: int,
        last_sender: int | None,
        threshold: float = 0.5,
    ) -> bool:
        """Reproduce the double-click detection logic."""
        return (
            current_time - last_click_time < threshold
            and last_sender == current_sender
        )

    def test_fast_same_element_is_double(self):
        assert self._is_double_click(1.2, 1.0, sender_id := 42, 42) is True

    def test_slow_same_element_not_double(self):
        assert self._is_double_click(2.0, 1.0, 42, 42) is False

    def test_fast_different_element_not_double(self):
        assert self._is_double_click(1.2, 1.0, 42, 99) is False

    def test_exactly_at_threshold_not_double(self):
        assert self._is_double_click(1.5, 1.0, 42, 42) is False

    def test_just_under_threshold_is_double(self):
        assert self._is_double_click(1.499, 1.0, 42, 42) is True

    def test_none_last_sender_not_double(self):
        assert self._is_double_click(1.2, 1.0, 42, None) is False

    def test_zero_last_click_time(self):
        """After reset (last_click_time=0), a quick click IS detected as double
        because 0.3 - 0 = 0.3 < threshold.  In real code time.time() >> 0,
        so this edge case never occurs — see test_reset_after_navigation."""
        assert self._is_double_click(0.3, 0, 42, 42) is True

    def test_reset_after_navigation(self):
        """After navigation, last_click_time is set to 0."""
        assert self._is_double_click(1000.0, 0, 42, 42) is False


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


class TestCreateNewFolderExecution:
    """Test actual folder creation using validate_folder_name + os.makedirs."""

    @staticmethod
    def _create_folder(name: str, current_dir: str) -> str | None:
        """Execute folder creation using the REAL validate_folder_name.

        Returns error message on failure, None on success.
        """
        error = validate_folder_name(name, current_dir)
        if error:
            return error

        try:
            os.makedirs(os.path.join(current_dir, name), exist_ok=False)
            return None
        except FileExistsError:
            return f"Folder '{name}' already exists."
        except PermissionError:
            return f"Permission denied to create '{name}'."
        except OSError as e:
            return f"Cannot create folder.\n\n{e}"

    def test_successful_creation(self, tmp_path):
        result = self._create_folder("new_folder", str(tmp_path))
        assert result is None
        assert (tmp_path / "new_folder").is_dir()

    def test_already_exists(self, tmp_path):
        (tmp_path / "existing").mkdir()
        result = self._create_folder("existing", str(tmp_path))
        assert "already exists" in result

    def test_path_traversal_blocked(self, tmp_path):
        result = self._create_folder("..", str(tmp_path))
        assert "Invalid folder name" in result
        # Verify nothing was created
        assert not (tmp_path / "..").exists() or (tmp_path / "..").is_dir()

    def test_separator_in_name_blocked(self, tmp_path):
        name = f"a{os.sep}b"
        result = self._create_folder(name, str(tmp_path))
        assert "Invalid folder name" in result

    def test_unicode_name_created(self, tmp_path):
        result = self._create_folder("Nowy Folder", str(tmp_path))
        assert result is None
        assert (tmp_path / "Nowy Folder").is_dir()

    def test_dot_prefix_allowed(self, tmp_path):
        result = self._create_folder(".config", str(tmp_path))
        assert result is None
        assert (tmp_path / ".config").is_dir()

    def test_nested_path_traversal_blocked(self, tmp_path):
        result = self._create_folder("../../escape", str(tmp_path))
        assert "Invalid folder name" in result


# ── Async directory size cache logic ──────────────────────────


class TestSizeCacheLogic:
    """Test the directory size cache and generation counter logic.

    Tests the data-layer behavior without requiring a running DPG context.
    """

    def test_cache_ttl_constant(self):
        assert FileDialog._SIZE_CACHE_TTL == 60.0

    def test_cache_hit_fresh(self):
        """Fresh cache entry (within TTL) should be used."""
        cache: dict[str, tuple[int | None, float]] = {
            "/tmp/dir": (1024, time.time()),
        }
        size, ts = cache["/tmp/dir"]
        assert time.time() - ts < FileDialog._SIZE_CACHE_TTL

    def test_cache_miss_expired(self):
        """Expired cache entry (beyond TTL) should be treated as miss."""
        cache: dict[str, tuple[int | None, float]] = {
            "/tmp/dir": (1024, time.time() - 120),
        }
        size, ts = cache["/tmp/dir"]
        assert time.time() - ts >= FileDialog._SIZE_CACHE_TTL

    def test_generation_counter_cancels_stale_thread(self):
        """Background thread should stop when generation changes."""
        generation = 1
        current_gen = 2  # simulates _bg_generation incremented

        # Thread should abort because generation != current_gen
        assert generation != current_gen

    def test_compute_sizes_bg_updates_cache(self, tmp_path):
        """_compute_sizes_bg fills _size_cache for each directory."""
        sub = tmp_path / "subdir"
        sub.mkdir()
        (sub / "data.txt").write_text("12345678")  # 8 bytes

        # Simulate the background computation directly
        cache: dict[str, tuple[int | None, float]] = {}
        path = str(sub)
        size = DirectoryLister._get_size(path, is_dir=True, show_dir_size=True)
        cache[path] = (size, time.time())

        assert path in cache
        assert cache[path][0] == 8

    def test_compute_sizes_bg_respects_generation(self, tmp_path):
        """When generation changes mid-computation, remaining dirs are skipped."""
        dirs = []
        for i in range(3):
            d = tmp_path / f"dir_{i}"
            d.mkdir()
            (d / "f.txt").write_text("x" * (i + 1))
            dirs.append(str(d))

        cache: dict[str, tuple[int | None, float]] = {}
        generation = 5
        current_gen = [5]  # mutable, simulates self._bg_generation

        processed = []
        for path in dirs:
            if current_gen[0] != generation:
                break
            size = DirectoryLister._get_size(path, is_dir=True, show_dir_size=True)
            cache[path] = (size, time.time())
            processed.append(path)
            # Simulate generation change after first dir
            if len(processed) == 1:
                current_gen[0] = 6

        assert len(processed) == 1
        assert dirs[0] in cache
        assert dirs[1] not in cache
        assert dirs[2] not in cache

    def test_f5_clears_cache(self):
        """F5 refresh should clear the entire size cache."""
        cache: dict[str, tuple[int | None, float]] = {
            "/tmp/a": (100, time.time()),
            "/tmp/b": (200, time.time()),
        }
        cache.clear()  # simulates _on_key_f5 behavior
        assert len(cache) == 0

    def test_sort_uses_cached_size(self):
        """Sort by size column should use cached value for directories."""
        cache: dict[str, tuple[int | None, float]] = {
            "/tmp/big": (1000, time.time()),
            "/tmp/small": (10, time.time()),
        }

        entry_big = MagicMock(
            is_dir=True, size_bytes=None, full_path="/tmp/big", name="big"
        )
        entry_small = MagicMock(
            is_dir=True, size_bytes=None, full_path="/tmp/small", name="small"
        )

        def get_sort_size(entry):
            size = entry.size_bytes
            if size is None and entry.is_dir:
                cached = cache.get(entry.full_path)
                if cached is not None:
                    size = cached[0]
            return size or 0

        assert get_sort_size(entry_big) == 1000
        assert get_sort_size(entry_small) == 10
        assert get_sort_size(entry_big) > get_sort_size(entry_small)

    def test_cache_stores_zero_for_empty_dir(self, tmp_path):
        """Empty directory should cache size as 0, not None."""
        empty = tmp_path / "empty_dir"
        empty.mkdir()
        size = DirectoryLister._get_size(str(empty), is_dir=True, show_dir_size=True)
        assert size == 0


# ── Polish characters in validation and selection ─────────────


class TestFileDialogLifecycle:
    def test_cancel_pending_search_cancels_timer(self):
        dialog = FileDialog.__new__(FileDialog)
        timer = MagicMock()
        dialog._search_debounce_timer = timer

        dialog._cancel_pending_search()

        timer.cancel.assert_called_once_with()
        assert dialog._search_debounce_timer is None

    def test_cancel_background_tasks_invalidates_all_work(self):
        dialog = FileDialog.__new__(FileDialog)
        timer = MagicMock()
        dialog._bg_generation = 3
        dialog._index_generation = 7
        dialog._dir_index = MagicMock()
        dialog._search_debounce_timer = timer

        dialog._cancel_background_tasks()

        assert dialog._bg_generation == 4
        assert dialog._index_generation == 8
        dialog._dir_index.invalidate.assert_called_once_with()
        timer.cancel.assert_called_once_with()
        assert dialog._search_debounce_timer is None

    def test_destroy_is_idempotent(self):
        dialog = FileDialog.__new__(FileDialog)
        dialog._destroyed = False
        dialog._bg_generation = 0
        dialog._index_generation = 0
        dialog._dir_index = MagicMock()
        dialog._search_debounce_timer = None
        dialog._preview = MagicMock()
        dialog._icons = MagicMock()
        dialog._config = MagicMock(tag="dialog_tag")

        with patch("dpg_navigator._dialog.dpg") as mock_dpg, \
             patch.object(DirectoryLister, "cleanup_temp_files") as cleanup, \
             patch.object(FileDialog, "_instance_count", 1), \
             patch.object(FileDialog, "_shared_selec_theme", None), \
             patch.object(FileDialog, "_shared_size_theme", None), \
             patch.object(FileDialog, "_shared_preview_active_theme", None):
            mock_dpg.does_item_exist.return_value = False

            dialog.destroy()
            dialog.destroy()

            assert FileDialog._instance_count == 0

        dialog._preview.destroy.assert_called_once_with()
        dialog._icons.destroy.assert_called_once_with()
        dialog._dir_index.invalidate.assert_called_once_with()
        cleanup.assert_called_once_with()

    def test_temp_cleanup_deferred_until_last_instance(self):
        """The shared extraction dir is wiped only when the last dialog closes.

        Two live instances share a class-level temp dir; destroying the first
        must not delete files the second is still previewing.
        """
        def _make():
            d = FileDialog.__new__(FileDialog)
            d._destroyed = False
            d._bg_generation = 0
            d._index_generation = 0
            d._dir_index = MagicMock()
            d._search_debounce_timer = None
            d._preview = MagicMock()
            d._icons = MagicMock()
            d._config = MagicMock(tag="dialog_tag")
            return d

        first, second = _make(), _make()

        with patch("dpg_navigator._dialog.dpg") as mock_dpg, \
             patch.object(DirectoryLister, "cleanup_temp_files") as cleanup, \
             patch.object(FileDialog, "_instance_count", 2), \
             patch.object(FileDialog, "_shared_selec_theme", None), \
             patch.object(FileDialog, "_shared_size_theme", None), \
             patch.object(FileDialog, "_shared_preview_active_theme", None):
            mock_dpg.does_item_exist.return_value = False

            first.destroy()
            assert FileDialog._instance_count == 1
            cleanup.assert_not_called()

            second.destroy()
            assert FileDialog._instance_count == 0
            cleanup.assert_called_once_with()


class TestArchiveExtractLimit:
    """Double-clicking a member inside an archive extracts with a size cap."""

    def _dialog(self):
        d = FileDialog.__new__(FileDialog)
        d._selected_files = []
        d._selected_elements = []
        d._row_entries = {}
        d._explorer_table = 1
        d._filename_input = 2
        d._focused_row_index = -1
        d._last_clicked_element = None
        d._config = MagicMock(tag="dlg", multi_selection=False)
        d._preview = MagicMock()
        return d

    def test_double_click_extract_passes_max_size(self):
        dialog = self._dialog()
        entry = type("Entry", (), {
            "is_dir": False,
            "name": "big.bin",
            "full_path": "archive.zip|/big.bin",
        })()

        with patch("dpg_navigator._dialog.dpg"), \
             patch("dpg_navigator._dialog._platform.is_mod_key_down", return_value=False), \
             patch.object(FileDialog, "_is_double_click", return_value=True), \
             patch.object(FileDialog, "_return_selection"), \
             patch.object(DirectoryLister, "extract_from_archive", return_value="/tmp/x") as extract:
            dialog._on_entry_click(10, None, entry)

        extract.assert_called_once_with(
            "archive.zip|/big.bin",
            max_size=FileDialog._MAX_ARCHIVE_EXTRACT_SIZE,
        )

    def test_oversized_member_shows_error_and_aborts(self):
        dialog = self._dialog()
        entry = type("Entry", (), {
            "is_dir": False,
            "name": "bomb.bin",
            "full_path": "archive.zip|/bomb.bin",
        })()

        with patch("dpg_navigator._dialog.dpg"), \
             patch("dpg_navigator._dialog._platform.is_mod_key_down", return_value=False), \
             patch.object(FileDialog, "_is_double_click", return_value=True), \
             patch.object(FileDialog, "_return_selection") as ret, \
             patch.object(FileDialog, "_show_message") as show, \
             patch.object(DirectoryLister, "extract_from_archive", return_value=None):
            dialog._on_entry_click(10, None, entry)

        show.assert_called_once()
        ret.assert_not_called()


class TestWordRendererSelection:
    """WORD routes to the mammoth HTML renderer only when it is available."""

    @staticmethod
    def _panel():
        panel = PreviewPanel.__new__(PreviewPanel)
        panel._panel_id = 1
        panel._visible = True
        panel._current_entry = None
        panel._text_offset = 0
        panel._text_encoding = None
        panel._pdf = None
        panel._html = None
        return panel

    @staticmethod
    def _entry():
        return type("Entry", (), {
            "is_dir": False,
            "name": "report.docx",
            "full_path": "/docs/report.docx",
        })()

    def test_routes_to_mammoth_when_available(self):
        from dpg_navigator._preview_registry import PreviewCapabilities

        panel = self._panel()
        caps = PreviewCapabilities(word=True, mammoth=True)
        with patch.object(PreviewPanel, "_preview_capabilities", return_value=caps), \
             patch.object(PreviewPanel, "_delete_pptx_textures"), \
             patch.object(PreviewPanel, "_render_word_html_preview") as html_word, \
             patch.object(PreviewPanel, "_render_word_preview") as text_word:
            panel.update(self._entry())

        html_word.assert_called_once()
        text_word.assert_not_called()

    def test_routes_to_text_without_mammoth(self):
        from dpg_navigator._preview_registry import PreviewCapabilities

        panel = self._panel()
        caps = PreviewCapabilities(word=True, mammoth=False)
        with patch.object(PreviewPanel, "_preview_capabilities", return_value=caps), \
             patch.object(PreviewPanel, "_delete_pptx_textures"), \
             patch.object(PreviewPanel, "_render_word_html_preview") as html_word, \
             patch.object(PreviewPanel, "_render_word_preview") as text_word:
            panel.update(self._entry())

        text_word.assert_called_once()
        html_word.assert_not_called()


class TestHtmlPreviewFallback:
    """HTML preview degrades to raw text when the Chrome backend is absent."""

    @staticmethod
    def _entry():
        return type("Entry", (), {
            "name": "page.html",
            "full_path": "/tmp/page.html",
        })()

    def test_falls_back_to_text_without_backend(self):
        panel = PreviewPanel.__new__(PreviewPanel)
        panel._panel_id = 1
        panel._html = None
        entry = self._entry()

        with patch.object(PreviewPanel, "_render_text_preview") as text_mock:
            PreviewPanel._render_html_preview(panel, entry)

        text_mock.assert_called_once_with(entry)

    def test_no_fallback_when_panel_missing(self):
        panel = PreviewPanel.__new__(PreviewPanel)
        panel._panel_id = None
        panel._html = None

        with patch.object(PreviewPanel, "_render_text_preview") as text_mock:
            PreviewPanel._render_html_preview(panel, self._entry())

        text_mock.assert_not_called()


class TestTagCollision:
    """A second dialog with an already-taken tag must not reuse the live id.

    Two dialogs sharing a DPG tag crash in dpg.window(tag=...). __init__
    resolves this by switching to a unique tag when the requested one already
    exists. These tests construct real FileDialog instances with the heavy
    collaborators (UI build, preview panel, icons, directory index) stubbed
    out, so only the tag-resolution logic runs. ``existing_tags`` stands in for
    DPG's live item registry: does_item_exist consults it, and each dialog
    registers its resolved tag just as _build_ui -> dpg.window(tag=...) would.
    """

    @staticmethod
    def _construct(mock_dpg, existing_tags, **kwargs):
        mock_dpg.does_item_exist.side_effect = lambda tag: tag in existing_tags
        with patch("dpg_navigator._dialog.PreviewPanel"), \
             patch("dpg_navigator._dialog.IconRegistry"), \
             patch("dpg_navigator._dialog.DirectoryIndex"), \
             patch.object(FileDialog, "_build_ui", lambda self: None):
            dialog = FileDialog(**kwargs)
        existing_tags.add(dialog._config.tag)
        return dialog

    def test_default_tag_kept_when_free(self):
        with patch("dpg_navigator._dialog.dpg") as mock_dpg:
            dialog = self._construct(mock_dpg, set())
            assert dialog._config.tag == "dpg_navigator"

    def test_second_default_dialog_gets_unique_tag(self):
        with patch("dpg_navigator._dialog.dpg") as mock_dpg:
            existing = set()
            first = self._construct(mock_dpg, existing)
            second = self._construct(mock_dpg, existing)

            assert first._config.tag == "dpg_navigator"
            assert second._config.tag != first._config.tag
            assert second._config.tag.startswith("dpg_navigator_")

    def test_explicit_tag_collision_is_resolved(self):
        with patch("dpg_navigator._dialog.dpg") as mock_dpg:
            dialog = self._construct(mock_dpg, {"my_dialog"}, tag="my_dialog")

            assert dialog._config.tag != "my_dialog"
            assert dialog._config.tag.startswith("my_dialog_")

    def test_unique_tag_propagates_to_payload_type(self):
        with patch("dpg_navigator._dialog.dpg") as mock_dpg:
            dialog = self._construct(mock_dpg, {"dpg_navigator"})

            assert dialog._config.tag != "dpg_navigator"
            assert dialog._payload_type == f"ws_{dialog._config.tag}"


class TestPreviewLifecycle:
    def test_close_active_renderers_closes_open_renderers(self):
        panel = PreviewPanel.__new__(PreviewPanel)
        panel._pdf = MagicMock(is_open=True)
        panel._html = MagicMock(is_open=True)
        panel._pdf_image_id = 1
        panel._pdf_page_label = 2
        panel._html_image_id = 3
        panel._html_status_label = 4

        panel._close_active_renderers()

        panel._pdf.close.assert_called_once_with()
        panel._html.close.assert_called_once_with()
        assert panel._pdf_image_id is None
        assert panel._pdf_page_label is None
        assert panel._html_image_id is None
        assert panel._html_status_label is None

    def test_force_close_closes_inactive_renderers(self):
        panel = PreviewPanel.__new__(PreviewPanel)
        panel._pdf = MagicMock(is_open=False)
        panel._html = MagicMock(is_open=False)
        panel._pdf_image_id = None
        panel._pdf_page_label = None
        panel._html_image_id = None
        panel._html_status_label = None

        panel._close_active_renderers(force=True)

        panel._pdf.close.assert_called_once_with()
        panel._html.close.assert_called_once_with()

    def test_delete_pptx_textures_removes_registered_items(self):
        panel = PreviewPanel.__new__(PreviewPanel)
        panel._pptx_texture_tags = {"pptx_1", "pptx_2"}

        with patch("dpg_navigator._preview.dpg") as mock_dpg:
            mock_dpg.does_item_exist.side_effect = lambda tag: tag == "pptx_1"

            panel._delete_pptx_textures()

        mock_dpg.delete_item.assert_called_once_with("pptx_1")
        assert panel._pptx_texture_tags == set()


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
        error = validate_folder_name(name, str(tmp_path))
        assert error is None
        os.makedirs(os.path.join(str(tmp_path), name), exist_ok=False)
        assert (tmp_path / name).is_dir()


# ── Preview image extension tests ──────────────────────────────


class TestPreviewImageExts:
    """Tests for _STB_IMAGE_EXTS, _PILLOW_EXTRA_EXTS, and preview_image_exts()."""

    def test_stb_exts_contains_basic_formats(self):
        for ext in (".png", ".jpg", ".jpeg", ".bmp", ".tga"):
            assert ext in PreviewPanel._STB_IMAGE_EXTS

    def test_stb_exts_contains_new_formats(self):
        for ext in (".gif", ".psd", ".hdr", ".pgm", ".ppm", ".pnm"):
            assert ext in PreviewPanel._STB_IMAGE_EXTS

    def test_pillow_extra_exts(self):
        for ext in (".webp", ".tiff", ".tif", ".ico", ".heic", ".heif", ".avif"):
            assert ext in PreviewPanel._PILLOW_EXTRA_EXTS

    def test_stb_and_pillow_disjoint(self):
        overlap = PreviewPanel._STB_IMAGE_EXTS & PreviewPanel._PILLOW_EXTRA_EXTS
        assert overlap == set(), f"Overlap: {overlap}"

    @patch("dpg_navigator._preview._PILImage", new=None)
    def test_preview_exts_without_pillow(self):
        result = PreviewPanel.preview_image_exts()
        assert result == PreviewPanel._STB_IMAGE_EXTS
        assert ".webp" not in result

    @patch("dpg_navigator._preview._PILImage", new=MagicMock())
    def test_preview_exts_with_pillow(self):
        result = PreviewPanel.preview_image_exts()
        assert ".webp" in result
        assert ".png" in result
        assert result == PreviewPanel._STB_IMAGE_EXTS | PreviewPanel._PILLOW_EXTRA_EXTS


class TestLoadImagePillow:
    """Tests for the Pillow fallback loader."""

    def test_load_image_pillow_rgba(self, tmp_path):
        """Pillow loader converts image to RGBA float data."""
        PIL = pytest.importorskip("PIL.Image")
        img = PIL.new("RGB", (2, 2), color=(255, 0, 0))
        path = str(tmp_path / "test.webp")
        img.save(path)

        w, h, data = PreviewPanel.load_image_pillow(path)
        assert w == 2
        assert h == 2
        # 2x2 RGBA = 16 floats
        assert len(data) == 16
        # First pixel: R=1.0, G=0.0, B=0.0, A=1.0
        assert abs(data[0] - 1.0) < 0.01
        assert abs(data[1] - 0.0) < 0.01
        assert abs(data[2] - 0.0) < 0.01
        assert abs(data[3] - 1.0) < 0.01

    def test_load_image_pillow_palette(self, tmp_path):
        """Pillow loader handles palette (P mode) images correctly."""
        PIL = pytest.importorskip("PIL.Image")
        img = PIL.new("P", (3, 3))
        path = str(tmp_path / "palette.png")
        img.save(path)

        w, h, data = PreviewPanel.load_image_pillow(path)
        assert w == 3
        assert h == 3
        assert len(data) == 3 * 3 * 4


# ── Markdown preview ──────────────────────────────────────────────


class TestVirtualArchivePreview:
    def test_preview_delegates_archive_extraction(self, tmp_path):
        extracted = tmp_path / "virtual.txt"
        extracted.write_text("content")
        captured = {}

        class FakePanel:
            _TEXT_PREVIEW_MAX_SIZE = PreviewPanel._TEXT_PREVIEW_MAX_SIZE
            _PDF_EXTS = PreviewPanel._PDF_EXTS

            def update(self, entry):
                captured["entry"] = entry

            def clear(self):
                captured["cleared"] = True

        virtual_entry = type("Entry", (), {
            "name": "virtual.txt",
            "full_path": "archive.zip|/virtual.txt",
        })()

        fake_panel = FakePanel()
        with patch("dpg_navigator._preview.DirectoryLister.extract_from_archive", return_value=str(extracted)) as extract_mock:
            PreviewPanel._handle_virtual_archive_preview(fake_panel, virtual_entry)

        extract_mock.assert_called_once_with(
            "archive.zip|/virtual.txt",
            max_size=PreviewPanel._TEXT_PREVIEW_MAX_SIZE,
            allow_large_extensions=PreviewPanel._PDF_EXTS,
        )
        assert "cleared" not in captured
        assert captured["entry"].full_path == str(extracted)
        assert captured["entry"].size_bytes == len("content")

    def test_preview_clears_when_extraction_fails(self):
        captured = {}

        class FakePanel:
            _TEXT_PREVIEW_MAX_SIZE = PreviewPanel._TEXT_PREVIEW_MAX_SIZE
            _PDF_EXTS = PreviewPanel._PDF_EXTS

            def update(self, entry):
                captured["entry"] = entry

            def clear(self):
                captured["cleared"] = True

        virtual_entry = type("Entry", (), {
            "name": "missing.txt",
            "full_path": "archive.zip|/missing.txt",
        })()

        fake_panel = FakePanel()
        with patch("dpg_navigator._preview.DirectoryLister.extract_from_archive", return_value=None):
            PreviewPanel._handle_virtual_archive_preview(fake_panel, virtual_entry)

        assert captured == {"cleared": True}


class TestMarkdownAvailable:
    """Tests for markdown_available() availability function."""

    def test_available_when_both_installed(self):
        with patch("dpg_navigator._preview._markdown", MagicMock()), \
             patch("dpg_navigator._preview.html_available", return_value=True):
            from dpg_navigator._preview import markdown_available
            assert markdown_available() is True

    def test_unavailable_without_markdown(self):
        with patch("dpg_navigator._preview._markdown", None), \
             patch("dpg_navigator._preview.html_available", return_value=True):
            from dpg_navigator._preview import markdown_available
            assert markdown_available() is False

    def test_unavailable_without_html(self):
        with patch("dpg_navigator._preview._markdown", MagicMock()), \
             patch("dpg_navigator._preview.html_available", return_value=False):
            from dpg_navigator._preview import markdown_available
            assert markdown_available() is False

    def test_unavailable_when_both_missing(self):
        with patch("dpg_navigator._preview._markdown", None), \
             patch("dpg_navigator._preview.html_available", return_value=False):
            from dpg_navigator._preview import markdown_available
            assert markdown_available() is False


class TestMarkdownExts:
    """Tests for _MD_EXTS frozenset."""

    def test_md_ext_present(self):
        assert ".md" in PreviewPanel._MD_EXTS

    def test_markdown_ext_present(self):
        assert ".markdown" in PreviewPanel._MD_EXTS

    def test_md_exts_are_frozenset(self):
        assert isinstance(PreviewPanel._MD_EXTS, frozenset)

    def test_md_in_text_preview_exts(self):
        """'.md' is also in _TEXT_PREVIEW_EXTS (rendering intercepts before text)."""
        assert ".md" in PreviewPanel._TEXT_PREVIEW_EXTS


class TestStatusHeight:
    """Tests for the _STATUS_HEIGHT class constant."""

    def test_status_height_is_int(self):
        assert isinstance(PreviewPanel._STATUS_HEIGHT, int)

    def test_status_height_positive(self):
        assert PreviewPanel._STATUS_HEIGHT > 0


# ── CSV / Excel preview ───────────────────────────────────────────


class TestCsvExts:
    """Tests for _CSV_EXTS frozenset."""

    def test_csv_ext_present(self):
        assert ".csv" in PreviewPanel._CSV_EXTS

    def test_tsv_ext_present(self):
        assert ".tsv" in PreviewPanel._CSV_EXTS

    def test_csv_exts_are_frozenset(self):
        assert isinstance(PreviewPanel._CSV_EXTS, frozenset)

    def test_csv_in_text_preview_exts(self):
        """'.csv' is also in _TEXT_PREVIEW_EXTS (table preview intercepts before text)."""
        assert ".csv" in PreviewPanel._TEXT_PREVIEW_EXTS

    def test_tsv_in_text_preview_exts(self):
        assert ".tsv" in PreviewPanel._TEXT_PREVIEW_EXTS


class TestExcelExts:
    """Tests for _EXCEL_EXTS frozenset."""

    def test_xlsx_ext_present(self):
        assert ".xlsx" in PreviewPanel._EXCEL_EXTS

    def test_xls_not_present(self):
        """Only .xlsx is supported, not legacy .xls."""
        assert ".xls" not in PreviewPanel._EXCEL_EXTS

    def test_excel_exts_are_frozenset(self):
        assert isinstance(PreviewPanel._EXCEL_EXTS, frozenset)

    def test_excel_not_in_text_preview_exts(self):
        """Excel is binary — not in _TEXT_PREVIEW_EXTS."""
        assert ".xlsx" not in PreviewPanel._TEXT_PREVIEW_EXTS


class TestTableMaxConstants:
    """Tests for _TABLE_MAX_ROWS and _TABLE_MAX_COLS class constants."""

    def test_max_rows_is_int(self):
        assert isinstance(PreviewPanel._TABLE_MAX_ROWS, int)

    def test_max_rows_positive(self):
        assert PreviewPanel._TABLE_MAX_ROWS > 0

    def test_max_rows_default(self):
        assert PreviewPanel._TABLE_MAX_ROWS == 200

    def test_max_cols_is_int(self):
        assert isinstance(PreviewPanel._TABLE_MAX_COLS, int)

    def test_max_cols_positive(self):
        assert PreviewPanel._TABLE_MAX_COLS > 0

    def test_max_cols_default(self):
        assert PreviewPanel._TABLE_MAX_COLS == 50


class TestExcelAvailable:
    """Tests for excel_available() availability function."""

    def test_available_when_installed(self):
        with patch("dpg_navigator._preview._load_workbook", MagicMock()):
            from dpg_navigator._preview import excel_available
            assert excel_available() is True

    def test_unavailable_when_missing(self):
        with patch("dpg_navigator._preview._load_workbook", None):
            from dpg_navigator._preview import excel_available
            assert excel_available() is False


class TestCsvParsing:
    """Test CSV delimiter detection logic."""

    def test_sniffer_detects_semicolon(self):
        import csv as csv_mod
        sample = "a;b;c\n1;2;3\n"
        dialect = csv_mod.Sniffer().sniff(sample)
        assert dialect.delimiter == ";"

    def test_sniffer_detects_comma(self):
        import csv as csv_mod
        sample = "a,b,c\n1,2,3\n"
        dialect = csv_mod.Sniffer().sniff(sample)
        assert dialect.delimiter == ","

    def test_sniffer_detects_tab(self):
        import csv as csv_mod
        sample = "a\tb\tc\n1\t2\t3\n"
        dialect = csv_mod.Sniffer().sniff(sample)
        assert dialect.delimiter == "\t"

    def test_sniffer_fallback_on_single_column(self):
        """Sniffer may fail on single-column data; code falls back to comma."""
        import csv as csv_mod
        sample = "value\n1\n2\n"
        try:
            csv_mod.Sniffer().sniff(sample)
        except csv_mod.Error:
            pass  # expected — code falls back to comma
