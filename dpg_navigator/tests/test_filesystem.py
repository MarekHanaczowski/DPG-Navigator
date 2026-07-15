"""Tests for dpg_navigator._filesystem — DirectoryLister (pure logic, no DPG)."""

from __future__ import annotations

import os
import time
import zipfile
from unittest.mock import patch, MagicMock

import pytest

from dpg_navigator._filesystem import DirectoryLister, DirectoryIndex, MAX_SCAN_DEPTH, INDEX_SCAN_DEPTH
from dpg_navigator._types import FileEntry


# ── format_size ─────────────────────────────────────────────────


class TestFormatSize:
    def test_none_returns_dash(self):
        assert DirectoryLister.format_size(None) == "-"

    def test_zero(self):
        assert DirectoryLister.format_size(0) == "0 B"

    def test_bytes(self):
        assert DirectoryLister.format_size(500) == "500 B"

    def test_one_byte(self):
        assert DirectoryLister.format_size(1) == "1 B"

    def test_exactly_1kb(self):
        assert DirectoryLister.format_size(1024) == "1 KB"

    def test_kilobytes(self):
        assert DirectoryLister.format_size(2048) == "2 KB"

    def test_exactly_1mb(self):
        assert DirectoryLister.format_size(2**20) == "1 MB"

    def test_megabytes(self):
        result = DirectoryLister.format_size(5 * 2**20)
        assert result == "5 MB"

    def test_exactly_1gb(self):
        assert DirectoryLister.format_size(2**30) == "1.0 GB"

    def test_gigabytes(self):
        result = DirectoryLister.format_size(3 * 2**30)
        assert result == "3.0 GB"

    def test_exactly_1tb(self):
        assert DirectoryLister.format_size(2**40) == "1.0 TB"

    def test_terabytes(self):
        result = DirectoryLister.format_size(5 * 2**40)
        assert result == "5.0 TB"

    def test_boundary_just_below_kb(self):
        result = DirectoryLister.format_size(1023)
        assert result == "1023 B"

    def test_boundary_just_below_mb(self):
        result = DirectoryLister.format_size(2**20 - 1)
        assert "KB" in result

    def test_large_tb_value(self):
        result = DirectoryLister.format_size(10 * 2**40)
        assert result == "10.0 TB"


# ── format_time ─────────────────────────────────────────────────


class TestFormatTime:
    def test_returns_string(self):
        result = DirectoryLister.format_time(1700000000.0)
        assert isinstance(result, str)

    def test_non_empty(self):
        result = DirectoryLister.format_time(1700000000.0)
        assert len(result) > 0

    def test_epoch_zero(self):
        result = DirectoryLister.format_time(0.0)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_matches_strftime_format(self):
        ts = 1700000000.0
        expected = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
        assert DirectoryLister.format_time(ts) == expected

    def test_recent_timestamp(self):
        ts = time.time()
        result = DirectoryLister.format_time(ts)
        assert isinstance(result, str)

from dpg_navigator.vfs import VFSRegistry

# ── get_size ───────────────────────────────────────────────────


class TestGetSize:
    def test_file_size(self, tmp_tree):
        path = str(tmp_tree / "file_a.txt")
        result = VFSRegistry.get_provider(path).get_size(path, is_dir=False, show_dir_size=False)
        assert result == 10

    def test_directory_no_show_dir_size(self, tmp_tree):
        path = str(tmp_tree / "dir_alpha")
        result = VFSRegistry.get_provider(path).get_size(path, is_dir=True, show_dir_size=False)
        assert result is None

    def test_directory_with_show_dir_size(self, tmp_tree):
        path = str(tmp_tree / "dir_alpha")
        result = VFSRegistry.get_provider(path).get_size(path, is_dir=True, show_dir_size=True)
        assert isinstance(result, int)
        assert result >= 7  # nested.txt = 7 bytes

    def test_empty_directory_size(self, empty_dir):
        result = VFSRegistry.get_provider(str(empty_dir)).get_size(str(empty_dir), is_dir=True, show_dir_size=True)
        assert result == 0

    def test_nonexistent_file(self, tmp_path):
        path = str(tmp_path / "nonexistent.txt")
        result = VFSRegistry.get_provider(path).get_size(path, is_dir=False, show_dir_size=False)
        assert result is None

    def test_file_size_matches_content(self, tmp_tree):
        path = str(tmp_tree / "file_b.py")
        result = VFSRegistry.get_provider(path).get_size(path, is_dir=False, show_dir_size=False)
        assert result == 20


# ── list_directory ──────────────────────────────────────────────


class TestListDirectory:
    def test_returns_list(self, tmp_tree):
        result = DirectoryLister.list_directory(str(tmp_tree), show_hidden=True)
        assert isinstance(result, list)

    def test_all_entries_are_file_entry(self, tmp_tree):
        result = DirectoryLister.list_directory(str(tmp_tree), show_hidden=True)
        for entry in result:
            assert isinstance(entry, FileEntry)

    def test_empty_directory(self, empty_dir):
        result = DirectoryLister.list_directory(str(empty_dir))
        assert result == []

    def test_nonexistent_directory(self, tmp_path):
        result = DirectoryLister.list_directory(str(tmp_path / "nonexistent"))
        assert result == []

    def test_contains_files_and_dirs(self, tmp_tree):
        result = DirectoryLister.list_directory(str(tmp_tree), show_hidden=True)
        has_file = any(not e.is_dir for e in result)
        has_dir = any(e.is_dir for e in result)
        assert has_file
        assert has_dir

    def test_dirs_sorted_before_files(self, tmp_tree):
        result = DirectoryLister.list_directory(str(tmp_tree), show_hidden=True)
        saw_file = False
        for entry in result:
            if not entry.is_dir:
                saw_file = True
            elif saw_file:
                pytest.fail(f"Directory {entry.name!r} appears after a file")

    def test_alphabetical_within_group(self, tmp_tree):
        result = DirectoryLister.list_directory(str(tmp_tree), show_hidden=True)
        dirs = [e.name.lower() for e in result if e.is_dir]
        files = [e.name.lower() for e in result if not e.is_dir]
        assert dirs == sorted(dirs)
        assert files == sorted(files)

    def test_hidden_files_excluded_by_default(self, tmp_tree):
        result = DirectoryLister.list_directory(str(tmp_tree), show_hidden=False)
        names = [e.name for e in result]
        assert ".hidden_file" not in names
        assert ".hidden_dir" not in names

    def test_hidden_files_included_when_requested(self, tmp_tree):
        result = DirectoryLister.list_directory(str(tmp_tree), show_hidden=True)
        names = [e.name for e in result]
        assert ".hidden_file" in names
        assert ".hidden_dir" in names

    def test_dirs_only(self, tmp_tree):
        result = DirectoryLister.list_directory(str(tmp_tree), dirs_only=True, show_hidden=True)
        for entry in result:
            assert entry.is_dir, f"Non-directory {entry.name!r} in dirs_only listing"

    def test_file_filter_py(self, tmp_tree):
        result = DirectoryLister.list_directory(str(tmp_tree), file_filter=".py", show_hidden=True)
        files = [e for e in result if not e.is_dir]
        for f in files:
            assert f.name.lower().endswith(".py"), f"{f.name} doesn't match .py filter"

    def test_file_filter_txt(self, tmp_tree):
        result = DirectoryLister.list_directory(str(tmp_tree), file_filter=".txt", show_hidden=True)
        files = [e for e in result if not e.is_dir]
        assert any(f.name == "file_a.txt" for f in files)

    def test_file_filter_wildcard_shows_all(self, tmp_tree):
        result_all = DirectoryLister.list_directory(str(tmp_tree), file_filter=".*", show_hidden=True)
        result_wild = DirectoryLister.list_directory(str(tmp_tree), show_hidden=True)
        assert len(result_all) == len(result_wild)

    def test_file_filter_does_not_affect_dirs(self, tmp_tree):
        result = DirectoryLister.list_directory(str(tmp_tree), file_filter=".py", show_hidden=True)
        dirs = [e for e in result if e.is_dir]
        assert len(dirs) > 0, "Dirs should still appear with file filter"

    def test_search_query_filters_by_name(self, tmp_tree):
        result = DirectoryLister.list_directory(str(tmp_tree), search_query="file_a", show_hidden=True)
        assert len(result) == 1
        assert result[0].name == "file_a.txt"

    def test_search_query_case_insensitive(self, tmp_tree):
        result_lower = DirectoryLister.list_directory(str(tmp_tree), search_query="file_a", show_hidden=True)
        result_upper = DirectoryLister.list_directory(str(tmp_tree), search_query="FILE_A", show_hidden=True)
        assert len(result_lower) == len(result_upper)

    def test_search_query_partial_match(self, tmp_tree):
        result = DirectoryLister.list_directory(str(tmp_tree), search_query="alpha", show_hidden=True)
        assert any(e.name == "dir_alpha" for e in result)

    def test_search_query_no_match(self, tmp_tree):
        result = DirectoryLister.list_directory(str(tmp_tree), search_query="zzz_nonexistent", show_hidden=True)
        assert result == []

    def test_entry_has_full_path(self, tmp_tree):
        result = DirectoryLister.list_directory(str(tmp_tree), show_hidden=True)
        for entry in result:
            assert os.path.isabs(entry.full_path)
            assert entry.name in entry.full_path

    def test_entry_has_modified_time(self, tmp_tree):
        result = DirectoryLister.list_directory(str(tmp_tree), show_hidden=True)
        for entry in result:
            assert isinstance(entry.modified_time, float)
            assert entry.modified_time > 0

    def test_entry_size_for_files(self, tmp_tree):
        result = DirectoryLister.list_directory(str(tmp_tree), show_hidden=True)
        for entry in result:
            if not entry.is_dir:
                assert isinstance(entry.size_bytes, int)
                assert entry.size_bytes >= 0

    def test_entry_size_none_for_dirs(self, tmp_tree):
        result = DirectoryLister.list_directory(str(tmp_tree), show_hidden=True)
        for entry in result:
            if entry.is_dir:
                assert entry.size_bytes is None

    def test_permission_error_returns_empty(self, tmp_path):
        """Directory with no read permissions should return empty list."""
        restricted = tmp_path / "restricted"
        restricted.mkdir()
        # On Windows, permission simulation is limited; skip gracefully
        if os.name != "nt":
            restricted.chmod(0o000)
            try:
                result = DirectoryLister.list_directory(str(restricted))
                assert result == []
            finally:
                restricted.chmod(0o755)

    def test_individual_entry_error_skipped_gracefully(self, tmp_path):
        """If one entry raises OSError during stat, it is skipped and the
        rest of the listing proceeds normally."""
        (tmp_path / "good.txt").write_text("ok")
        (tmp_path / "also_good.txt").write_text("ok")

        original_scandir = os.scandir

        class PatchedScanner:
            """Wraps a real scandir iterator to inject a broken entry."""

            def __init__(self, path):
                self._real = original_scandir(path)
                self._path = path
                self._injected = False

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self._real.close()

            def __iter__(self):
                for entry in self._real:
                    if not self._injected and entry.name == "good.txt":
                        self._injected = True
                        broken = MagicMock()
                        broken.name = "broken_entry"
                        broken.path = os.path.join(self._path, "broken_entry")
                        broken.is_dir.side_effect = OSError("simulated stat failure")
                        yield broken
                    yield entry

        with patch("dpg_navigator._filesystem.os.scandir", side_effect=PatchedScanner):
            result = DirectoryLister.list_directory(str(tmp_path))

        names = [e.name for e in result]
        assert "good.txt" in names
        assert "also_good.txt" in names
        assert "broken_entry" not in names

    def test_combined_filters(self, tmp_tree):
        """show_hidden=False + file_filter + search_query together."""
        result = DirectoryLister.list_directory(
            str(tmp_tree),
            show_hidden=False,
            file_filter=".txt",
            search_query="file",
        )
        for entry in result:
            if not entry.is_dir:
                assert entry.name.endswith(".txt")
                assert "file" in entry.name.lower()
            assert not entry.name.startswith(".")

    def test_dir_z_sorted_before_file_a(self, tmp_path):
        """Directory 'zebra' must appear before file 'apple.txt'."""
        (tmp_path / "apple.txt").write_text("a")
        (tmp_path / "zebra").mkdir()
        result = DirectoryLister.list_directory(str(tmp_path))
        assert result[0].name == "zebra"
        assert result[0].is_dir
        assert result[1].name == "apple.txt"
        assert not result[1].is_dir

    def test_case_insensitive_sort(self, tmp_path):
        """Filenames differing only in case should sort case-insensitively."""
        (tmp_path / "Banana.txt").write_text("b")
        (tmp_path / "apple.txt").write_text("a")
        (tmp_path / "Cherry.txt").write_text("c")
        result = DirectoryLister.list_directory(str(tmp_path))
        names = [e.name.lower() for e in result]
        assert names == sorted(names)

    def test_zero_byte_file(self, tmp_path):
        """A 0-byte file should have size_bytes == 0."""
        (tmp_path / "empty.txt").write_text("")
        result = DirectoryLister.list_directory(str(tmp_path))
        assert result[0].size_bytes == 0

    def test_filter_conflict_search_and_extension(self, tmp_path):
        """Search matches name but filter excludes extension -> empty."""
        (tmp_path / "report.txt").write_text("data")
        (tmp_path / "report.py").write_text("code")
        result = DirectoryLister.list_directory(
            str(tmp_path), file_filter=".py", search_query="report",
        )
        files = [e for e in result if not e.is_dir]
        assert len(files) == 1
        assert files[0].name == "report.py"

    def test_search_hidden_file_excluded(self, tmp_path):
        """Search matches hidden file but show_hidden=False -> excluded."""
        (tmp_path / ".secret.txt").write_text("hidden")
        result = DirectoryLister.list_directory(
            str(tmp_path), show_hidden=False, search_query="secret",
        )
        assert result == []

    @pytest.mark.skipif(os.name == "nt", reason="Symlinks require elevated privileges on Windows")
    def test_symlink_to_file_followed(self, tmp_path):
        """Symlink to a file should appear as a file entry."""
        target = tmp_path / "real.txt"
        target.write_text("data")
        link = tmp_path / "link.txt"
        link.symlink_to(target)
        result = DirectoryLister.list_directory(str(tmp_path))
        names = {e.name for e in result}
        assert "link.txt" in names
        link_entry = next(e for e in result if e.name == "link.txt")
        assert not link_entry.is_dir

    @pytest.mark.skipif(os.name == "nt", reason="Symlinks require elevated privileges on Windows")
    def test_symlink_to_dir_followed(self, tmp_path):
        """Symlink to a directory should appear as a directory entry."""
        target = tmp_path / "real_dir"
        target.mkdir()
        link = tmp_path / "link_dir"
        link.symlink_to(target)
        result = DirectoryLister.list_directory(str(tmp_path))
        link_entry = next(e for e in result if e.name == "link_dir")
        assert link_entry.is_dir

    @pytest.mark.skipif(os.name == "nt", reason="Symlinks require elevated privileges on Windows")
    def test_broken_symlink_skipped(self, tmp_path):
        """Broken symlink (target deleted) should be silently skipped."""
        target = tmp_path / "gone.txt"
        target.write_text("temp")
        link = tmp_path / "broken_link"
        link.symlink_to(target)
        target.unlink()  # break the symlink
        result = DirectoryLister.list_directory(str(tmp_path))
        names = {e.name for e in result}
        assert "broken_link" not in names

    def test_deeply_nested_dir_size(self, tmp_path):
        """show_dir_size on 3-level deep structure returns correct total."""
        d1 = tmp_path / "level1"
        d2 = d1 / "level2"
        d3 = d2 / "level3"
        d3.mkdir(parents=True)
        (d1 / "a.txt").write_text("12345")       # 5 bytes
        (d2 / "b.txt").write_text("123456789")    # 9 bytes
        (d3 / "c.txt").write_text("12")           # 2 bytes
        size = VFSRegistry.get_provider(str(d1)).get_size(str(d1), is_dir=True, show_dir_size=True)
        assert size == 16

    def test_depth_limited_dir_size(self, tmp_path):
        """os.walk stops at MAX_SCAN_DEPTH to prevent runaway scanning."""
        root = tmp_path / "root"
        current = root
        for i in range(MAX_SCAN_DEPTH + 2):
            current = current / f"level{i}"
        current.mkdir(parents=True)
        (current / "deep.txt").write_text("data")  # 4 bytes, beyond limit

        (root / "shallow.txt").write_text("12345")  # 5 bytes, within limit

        size = VFSRegistry.get_provider(str(root)).get_size(str(root), is_dir=True, show_dir_size=True)
        assert size == 5  # only shallow.txt counted

    def test_show_dir_size_integration(self, tmp_path):
        """list_directory with show_dir_size=True should give dirs non-None size."""
        sub = tmp_path / "subdir"
        sub.mkdir()
        (sub / "data.txt").write_text("12345678")  # 8 bytes
        (tmp_path / "root_file.txt").write_text("abc")

        result = DirectoryLister.list_directory(
            str(tmp_path), show_dir_size=True,
        )
        dir_entry = next(e for e in result if e.is_dir)
        assert dir_entry.name == "subdir"
        assert dir_entry.size_bytes is not None
        assert dir_entry.size_bytes == 8

        file_entry = next(e for e in result if not e.is_dir)
        assert file_entry.size_bytes == 3


# ── Polish / Unicode characters ────────────────────────────────


class TestExtractFromArchive:
    def test_extract_zip_member(self, tmp_path):
        archive_path = tmp_path / "sample.zip"
        with zipfile.ZipFile(archive_path, "w") as zf:
            zf.writestr("docs/readme.txt", "hello")

        try:
            extracted = DirectoryLister.extract_from_archive(
                f"{archive_path}|/docs/readme.txt",
            )
            assert extracted is not None
            assert os.path.isfile(extracted)
            with open(extracted, "r", encoding="utf-8") as handle:
                assert handle.read() == "hello"
        finally:
            DirectoryLister.cleanup_temp_files()

    def test_rejects_oversized_member_when_limit_exceeded(self, tmp_path):
        archive_path = tmp_path / "large.zip"
        with zipfile.ZipFile(archive_path, "w") as zf:
            zf.writestr("large.txt", "x" * 32)

        try:
            extracted = DirectoryLister.extract_from_archive(
                f"{archive_path}|/large.txt",
                max_size=8,
            )
            assert extracted is None
        finally:
            DirectoryLister.cleanup_temp_files()

    def test_allows_oversized_member_for_whitelisted_extension(self, tmp_path):
        archive_path = tmp_path / "report.zip"
        with zipfile.ZipFile(archive_path, "w") as zf:
            zf.writestr("report.pdf", "x" * 32)

        try:
            extracted = DirectoryLister.extract_from_archive(
                f"{archive_path}|/report.pdf",
                max_size=8,
                allow_large_extensions={".pdf"},
            )
            assert extracted is not None
            assert os.path.isfile(extracted)
        finally:
            DirectoryLister.cleanup_temp_files()


class TestPolishCharacters:
    """Verify that files and directories with Polish diacritics
    (ą, ć, ę, ł, ń, ó, ś, ź, ż) are handled correctly."""

    def test_polish_file_listed(self, tmp_path):
        """File with Polish characters appears in listing."""
        (tmp_path / "zdjęcie.png").write_bytes(b"\x89PNG\x00")
        result = DirectoryLister.list_directory(str(tmp_path))
        names = [e.name for e in result]
        assert "zdjęcie.png" in names

    def test_polish_dir_listed(self, tmp_path):
        """Directory with Polish characters appears in listing."""
        (tmp_path / "Dokumenty źródłowe").mkdir()
        result = DirectoryLister.list_directory(str(tmp_path))
        names = [e.name for e in result]
        assert "Dokumenty źródłowe" in names

    def test_polish_file_entry_properties(self, tmp_path):
        """FileEntry preserves Polish characters in name and full_path."""
        (tmp_path / "łąka.txt").write_text("trawa")
        result = DirectoryLister.list_directory(str(tmp_path))
        entry = result[0]
        assert entry.name == "łąka.txt"
        assert entry.full_path == os.path.join(str(tmp_path), "łąka.txt")
        assert not entry.is_dir
        assert entry.size_bytes == len("trawa".encode())

    def test_polish_dir_entry_properties(self, tmp_path):
        """Directory entry preserves Polish characters."""
        (tmp_path / "żółć").mkdir()
        result = DirectoryLister.list_directory(str(tmp_path))
        entry = result[0]
        assert entry.name == "żółć"
        assert entry.is_dir
        assert entry.full_path.endswith("żółć")

    def test_multiple_polish_names_sorted(self, tmp_path):
        """Polish-named entries are sorted correctly."""
        (tmp_path / "ćma.txt").write_text("c")
        (tmp_path / "ąkacja.txt").write_text("a")
        (tmp_path / "źrebak.txt").write_text("z")
        result = DirectoryLister.list_directory(str(tmp_path))
        names = [e.name.lower() for e in result]
        assert names == sorted(names)

    def test_search_query_polish(self, tmp_path):
        """Search query with Polish characters finds matching entries."""
        (tmp_path / "zdjęcie_wakacje.jpg").write_bytes(b"\xff\xd8")
        (tmp_path / "notatka.txt").write_text("abc")
        result = DirectoryLister.list_directory(
            str(tmp_path), search_query="zdjęcie",
        )
        assert len(result) == 1
        assert result[0].name == "zdjęcie_wakacje.jpg"

    def test_search_query_polish_case_insensitive(self, tmp_path):
        """Search with Polish chars is case-insensitive."""
        (tmp_path / "Łódź.txt").write_text("city")
        result = DirectoryLister.list_directory(
            str(tmp_path), search_query="łódź",
        )
        assert len(result) == 1
        assert result[0].name == "Łódź.txt"

    def test_polish_dir_with_files_inside(self, tmp_path):
        """Directory with Polish name containing files is listed correctly."""
        d = tmp_path / "Zdjęcia"
        d.mkdir()
        (d / "plaża.jpg").write_bytes(b"\xff\xd8")
        result = DirectoryLister.list_directory(str(tmp_path))
        entry = next(e for e in result if e.is_dir)
        assert entry.name == "Zdjęcia"

    def test_polish_dir_size(self, tmp_path):
        """show_dir_size works for directories with Polish names."""
        d = tmp_path / "ścieżka"
        d.mkdir()
        (d / "dane.txt").write_text("12345")  # 5 bytes
        size = VFSRegistry.get_provider(str(d)).get_size(str(d), is_dir=True, show_dir_size=True)
        assert size == 5

    def test_mixed_ascii_and_polish(self, tmp_path):
        """Mixed ASCII and Polish names coexist in listing."""
        (tmp_path / "readme.txt").write_text("hello")
        (tmp_path / "opis_główny.txt").write_text("cześć", encoding="utf-8")
        (tmp_path / "Katalog").mkdir()
        (tmp_path / "Różne").mkdir()
        result = DirectoryLister.list_directory(str(tmp_path))
        names = {e.name for e in result}
        assert names == {"Katalog", "Różne", "opis_główny.txt", "readme.txt"}

    def test_all_polish_diacritics_in_filename(self, tmp_path):
        """Filename containing all Polish diacritics is handled."""
        name = "ąćęłńóśźż_ĄĆĘŁŃÓŚŹŻ.txt"
        (tmp_path / name).write_text("test")
        result = DirectoryLister.list_directory(str(tmp_path))
        assert result[0].name == name

    def test_filter_with_polish_filename(self, tmp_path):
        """File filter works correctly with Polish-named files."""
        (tmp_path / "pióro.py").write_text("code")
        (tmp_path / "książka.txt").write_text("text")
        result = DirectoryLister.list_directory(
            str(tmp_path), file_filter=".py",
        )
        files = [e for e in result if not e.is_dir]
        assert len(files) == 1
        assert files[0].name == "pióro.py"


# ── DirectoryIndex ─────────────────────────────────────────────


@pytest.fixture
def nested_tree(tmp_path):
    """Create a directory tree for index tests.

    Structure:
        tmp_path/
        ├── root_file.txt     (5 bytes)
        ├── sub_a/
        │   ├── report.py     (4 bytes)
        │   └── deep/
        │       └── data.csv  (3 bytes)
        └── sub_b/
            └── readme.md     (6 bytes)
    """
    (tmp_path / "root_file.txt").write_text("hello")
    sa = tmp_path / "sub_a"
    sa.mkdir()
    (sa / "report.py").write_text("code")
    deep = sa / "deep"
    deep.mkdir()
    (deep / "data.csv").write_text("1,2")
    sb = tmp_path / "sub_b"
    sb.mkdir()
    (sb / "readme.md").write_text("readme")
    return tmp_path


class TestDirectoryIndex:
    def _build_sync(self, index, root, max_depth=INDEX_SCAN_DEPTH):
        """Build index synchronously for testing."""
        gen = 0
        index.build(root, gen, lambda: gen, max_depth=max_depth)

    def test_not_ready_before_build(self):
        idx = DirectoryIndex()
        assert not idx.ready

    def test_ready_after_build(self, nested_tree):
        idx = DirectoryIndex()
        self._build_sync(idx, str(nested_tree))
        assert idx.ready
        assert idx.root == str(nested_tree)

    def test_search_finds_nested_file(self, nested_tree):
        idx = DirectoryIndex()
        self._build_sync(idx, str(nested_tree))
        results = idx.search("report")
        assert len(results) == 1
        assert results[0].name == "report.py"

    def test_search_finds_deep_file(self, nested_tree):
        idx = DirectoryIndex()
        self._build_sync(idx, str(nested_tree))
        results = idx.search("data")
        assert len(results) == 1
        assert results[0].name == "data.csv"

    def test_search_case_insensitive(self, nested_tree):
        idx = DirectoryIndex()
        self._build_sync(idx, str(nested_tree))
        results = idx.search("README")
        assert len(results) == 1
        assert results[0].name == "readme.md"

    def test_search_empty_query_returns_empty(self, nested_tree):
        idx = DirectoryIndex()
        self._build_sync(idx, str(nested_tree))
        assert idx.search("") == []

    def test_search_no_match(self, nested_tree):
        idx = DirectoryIndex()
        self._build_sync(idx, str(nested_tree))
        assert idx.search("zzz_nonexistent") == []

    def test_search_not_ready_returns_empty(self, nested_tree):
        idx = DirectoryIndex()
        assert idx.search("report") == []

    def test_excludes_root_level_entries(self, nested_tree):
        """Index should NOT contain entries from root dir (depth=0)."""
        idx = DirectoryIndex()
        self._build_sync(idx, str(nested_tree))
        results = idx.search("root_file")
        assert len(results) == 0

    def test_includes_subdirectories(self, nested_tree):
        """Index should contain sub-directory entries (sub_a, sub_b, deep)."""
        idx = DirectoryIndex()
        self._build_sync(idx, str(nested_tree))
        results = idx.search("deep")
        assert len(results) == 1
        assert results[0].is_dir

    def test_file_filter(self, nested_tree):
        idx = DirectoryIndex()
        self._build_sync(idx, str(nested_tree))
        results = idx.search("re", file_filter=".py")
        files = [e for e in results if not e.is_dir]
        for f in files:
            assert f.name.endswith(".py")

    def test_dirs_only(self, nested_tree):
        idx = DirectoryIndex()
        self._build_sync(idx, str(nested_tree))
        results = idx.search("sub", dirs_only=True)
        for r in results:
            assert r.is_dir

    def test_max_results_limit(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        for i in range(20):
            (sub / f"match_{i}.txt").write_text("x")
        idx = DirectoryIndex()
        self._build_sync(idx, str(tmp_path))
        results = idx.search("match", max_results=5)
        assert len(results) == 5

    def test_invalidate(self, nested_tree):
        idx = DirectoryIndex()
        self._build_sync(idx, str(nested_tree))
        assert idx.ready
        idx.invalidate()
        assert not idx.ready
        assert idx.search("report") == []

    def test_is_stale(self, nested_tree):
        idx = DirectoryIndex()
        self._build_sync(idx, str(nested_tree))
        assert not idx.is_stale(ttl=60.0)
        assert idx.is_stale(ttl=0.0)

    def test_hidden_dir_not_descended_by_default(self, tmp_path):
        """Contents of hidden dirs are absent unless show_hidden is set."""
        secret = tmp_path / ".secret"
        secret.mkdir()
        (secret / "needle.txt").write_text("x")

        idx = DirectoryIndex()
        idx.build(str(tmp_path), 0, lambda: 0)  # show_hidden defaults to False
        assert idx.search("needle", show_hidden=False) == []
        assert idx.search("needle", show_hidden=True) == []

    def test_hidden_dir_descended_with_show_hidden(self, tmp_path):
        """With show_hidden=True the walker recurses into hidden dirs."""
        secret = tmp_path / ".secret"
        secret.mkdir()
        (secret / "needle.txt").write_text("x")

        idx = DirectoryIndex()
        idx.build(str(tmp_path), 0, lambda: 0, show_hidden=True)
        results = idx.search("needle", show_hidden=True)
        assert len(results) == 1
        assert results[0].name == "needle.txt"

    def test_symlinked_dir_not_followed(self, tmp_path):
        """A symlinked directory must not let the index escape the root."""
        target = tmp_path / "target"
        target.mkdir()
        (target / "escaped.txt").write_text("x")
        root = tmp_path / "root"
        root.mkdir()
        try:
            os.symlink(str(target), str(root / "link"), target_is_directory=True)
        except (OSError, NotImplementedError, AttributeError):
            pytest.skip("symlink creation not permitted on this platform")

        idx = DirectoryIndex()
        idx.build(str(root), 0, lambda: 0, show_hidden=True)
        # The symlink target's contents live outside `root` and must not appear.
        assert idx.search("escaped") == []

    def test_caps_entries_and_keeps_partial(self, tmp_path):
        """The index stops at INDEX_MAX_ENTRIES but keeps the partial result."""
        sub = tmp_path / "sub"
        sub.mkdir()
        for i in range(6):
            (sub / f"f{i}.txt").write_text("x")

        idx = DirectoryIndex()
        with patch("dpg_navigator._filesystem.INDEX_MAX_ENTRIES", 3):
            idx.build(str(tmp_path), 0, lambda: 0)

        assert idx.ready
        assert len(idx._entries) == 3

    def test_cancellation_via_generation(self, nested_tree):
        """Build should abort when generation changes mid-scan."""
        gen = [0]
        idx = DirectoryIndex()
        # Build with generation mismatch after start
        gen[0] = 0
        def changing_gen():
            gen[0] += 1  # increment every check — cancels immediately
            return gen[0]
        idx.build(str(nested_tree), 0, changing_gen)
        # Index should NOT be ready (cancelled)
        assert not idx.ready

    def test_rebuild_replaces_old_entries(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "old.txt").write_text("old")
        idx = DirectoryIndex()
        self._build_sync(idx, str(tmp_path))
        assert len(idx.search("old")) == 1

        # Modify filesystem and rebuild
        (sub / "old.txt").unlink()
        (sub / "new.txt").write_text("new")
        self._build_sync(idx, str(tmp_path))
        assert len(idx.search("old")) == 0
        assert len(idx.search("new")) == 1

    def test_permission_error_skipped(self, tmp_path):
        """Directories that raise PermissionError are silently skipped."""
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "ok.txt").write_text("ok")
        idx = DirectoryIndex()
        self._build_sync(idx, str(tmp_path))
        assert len(idx.search("ok")) == 1

    def test_hidden_files_excluded_by_default(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / ".secret").write_text("hidden")
        (sub / "visible.txt").write_text("visible")
        idx = DirectoryIndex()
        self._build_sync(idx, str(tmp_path))
        assert len(idx.search("secret", show_hidden=False)) == 0
        assert len(idx.search("secret", show_hidden=True)) == 1

    def test_results_sorted_dirs_first(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "match_file.txt").write_text("f")
        (sub / "match_dir").mkdir()
        idx = DirectoryIndex()
        self._build_sync(idx, str(tmp_path))
        results = idx.search("match")
        assert len(results) == 2
        assert results[0].is_dir
        assert not results[1].is_dir

    def test_depth_limit_respected(self, tmp_path):
        """Files beyond max_depth should NOT appear in the index."""
        current = tmp_path
        for i in range(5):
            current = current / f"d{i}"
        current.mkdir(parents=True)
        (current / "deep_file.txt").write_text("deep")

        # Shallow search
        idx = DirectoryIndex()
        self._build_sync(idx, str(tmp_path), max_depth=2)
        assert len(idx.search("deep_file")) == 0

        # Deep enough search
        idx2 = DirectoryIndex()
        self._build_sync(idx2, str(tmp_path), max_depth=10)
        assert len(idx2.search("deep_file")) == 1

    def test_polish_characters(self, tmp_path):
        sub = tmp_path / "katalog"
        sub.mkdir()
        (sub / "zdjęcie.png").write_bytes(b"\x89PNG")
        idx = DirectoryIndex()
        self._build_sync(idx, str(tmp_path))
        results = idx.search("zdjęcie")
        assert len(results) == 1
        assert results[0].name == "zdjęcie.png"
