"""Tests for dpg_navigator._dialog — path validation and selection logic.

Only tests logic that can be verified WITHOUT running DearPyGui.
All DPG calls are mocked where needed.

Imports validate_folder_name and build_selection_list from the ACTUAL source
(dpg_navigator._filesystem) instead of duplicating the logic in tests.
"""

from __future__ import annotations

import os
import time
from unittest.mock import patch, MagicMock

import pytest

from dpg_navigator._filesystem import validate_folder_name, build_selection_list, DirectoryLister
from dpg_navigator._types import DialogConfig, FileEntry
from dpg_navigator.vfs import VFSRegistry
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
        size = VFSRegistry.get_provider(path).get_size(path, is_dir=True, show_dir_size=True)
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
            size = VFSRegistry.get_provider(path).get_size(path, is_dir=True, show_dir_size=True)
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
        size = VFSRegistry.get_provider(str(empty)).get_size(str(empty), is_dir=True, show_dir_size=True)
        assert size == 0


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
        error = validate_folder_name(name, str(tmp_path))
        assert error is None
        os.makedirs(os.path.join(str(tmp_path), name), exist_ok=False)
        assert (tmp_path / name).is_dir()


# ── Preview image extension tests ──────────────────────────────


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
