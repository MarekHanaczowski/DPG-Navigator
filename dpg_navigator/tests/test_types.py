"""Tests for dpg_navigator._types — enums, dataclasses, constants."""

from __future__ import annotations

import pytest

from dpg_navigator._types import (
    DEFAULT_FILTER_LIST,
    DialogConfig,
    DialogMode,
    FileEntry,
    StyleVariant,
)

# ── DialogMode ──────────────────────────────────────────────────


class TestDialogMode:
    def test_has_open_files(self):
        assert hasattr(DialogMode, "OPEN_FILES")

    def test_has_open_dirs(self):
        assert hasattr(DialogMode, "OPEN_DIRS")

    def test_members_are_distinct(self):
        assert DialogMode.OPEN_FILES != DialogMode.OPEN_DIRS

    def test_member_count(self):
        assert len(DialogMode) == 2


# ── StyleVariant ────────────────────────────────────────────────


class TestStyleVariant:
    def test_has_labeled(self):
        assert hasattr(StyleVariant, "LABELED")

    def test_has_compact(self):
        assert hasattr(StyleVariant, "COMPACT")

    def test_members_are_distinct(self):
        assert StyleVariant.LABELED != StyleVariant.COMPACT

    def test_member_count(self):
        assert len(StyleVariant) == 2


# ── FileEntry ───────────────────────────────────────────────────


class TestFileEntry:
    def test_create_file_entry(self):
        entry = FileEntry(
            name="test.py",
            full_path="/tmp/test.py",
            is_dir=False,
            size_bytes=1024,
            modified_time=1700000000.0,
            is_hidden=False,
        )
        assert entry.name == "test.py"
        assert entry.full_path == "/tmp/test.py"
        assert entry.is_dir is False
        assert entry.size_bytes == 1024
        assert entry.modified_time == 1700000000.0
        assert entry.is_hidden is False

    def test_create_directory_entry(self):
        entry = FileEntry(
            name="mydir",
            full_path="/tmp/mydir",
            is_dir=True,
            size_bytes=None,
            modified_time=1700000000.0,
            is_hidden=False,
        )
        assert entry.is_dir is True
        assert entry.size_bytes is None

    def test_create_hidden_entry(self):
        entry = FileEntry(
            name=".bashrc",
            full_path="/home/.bashrc",
            is_dir=False,
            size_bytes=256,
            modified_time=1700000000.0,
            is_hidden=True,
        )
        assert entry.is_hidden is True

    def test_size_none_for_directory(self):
        entry = FileEntry("d", "/d", True, None, 0.0, False)
        assert entry.size_bytes is None

    def test_equality(self):
        a = FileEntry("f", "/f", False, 10, 1.0, False)
        b = FileEntry("f", "/f", False, 10, 1.0, False)
        assert a == b

    def test_inequality_different_name(self):
        a = FileEntry("f1", "/f1", False, 10, 1.0, False)
        b = FileEntry("f2", "/f2", False, 10, 1.0, False)
        assert a != b

    def test_rejects_empty_name(self):
        with pytest.raises(ValueError, match="name"):
            FileEntry("", "/x", False, 0, 0.0, False)

    def test_rejects_negative_size(self):
        with pytest.raises(ValueError, match="size_bytes"):
            FileEntry("f", "/f", False, -1, 0.0, False)


# ── DialogConfig ────────────────────────────────────────────────


class TestDialogConfig:
    def test_default_values(self):
        cfg = DialogConfig()
        assert cfg.title == "File Dialog"
        assert cfg.tag == "dpg_navigator"
        assert cfg.width == 950
        assert cfg.height == 650
        assert cfg.min_size == (460, 320)
        assert cfg.mode == DialogMode.OPEN_FILES
        assert cfg.default_path is None
        assert cfg.filter_list is None
        assert cfg.file_filter == ".*"
        assert cfg.show_dir_size is False
        assert cfg.allow_drag is True
        assert cfg.multi_selection is True
        assert cfg.show_shortcuts is True
        assert cfg.no_resize is False
        assert cfg.modal is True
        assert cfg.show_hidden is False
        assert cfg.show_preview is False
        assert cfg.trusted_html_preview is False
        assert cfg.preview_width == 300
        assert cfg.style == StyleVariant.LABELED

    def test_custom_values(self):
        cfg = DialogConfig(
            title="Custom",
            width=800,
            height=600,
            mode=DialogMode.OPEN_DIRS,
            style=StyleVariant.COMPACT,
            show_hidden=True,
            multi_selection=False,
            trusted_html_preview=True,
        )
        assert cfg.title == "Custom"
        assert cfg.width == 800
        assert cfg.height == 600
        assert cfg.mode == DialogMode.OPEN_DIRS
        assert cfg.style == StyleVariant.COMPACT
        assert cfg.show_hidden is True
        assert cfg.multi_selection is False
        assert cfg.trusted_html_preview is True

    def test_min_size_is_tuple(self):
        cfg = DialogConfig()
        assert isinstance(cfg.min_size, tuple)
        assert len(cfg.min_size) == 2

    def test_custom_filter_list(self):
        filters = [".*", ".py", ".txt"]
        cfg = DialogConfig(filter_list=filters, file_filter=".*")
        assert cfg.filter_list == [".*", ".py", ".txt"]

    def test_custom_default_path(self):
        cfg = DialogConfig(default_path="/tmp")
        assert cfg.default_path == "/tmp"

    def test_rejects_non_positive_width(self):
        with pytest.raises(ValueError, match="width"):
            DialogConfig(width=0)

    def test_rejects_bool_as_size(self):
        with pytest.raises(ValueError, match="height"):
            DialogConfig(height=True)  # type: ignore[arg-type]

    def test_rejects_empty_title(self):
        with pytest.raises(ValueError, match="title"):
            DialogConfig(title="  ")

    def test_rejects_file_filter_missing_from_list(self):
        with pytest.raises(ValueError, match="file_filter"):
            DialogConfig(filter_list=[".py", ".txt"], file_filter=".*")

    def test_rejects_bad_extension(self):
        with pytest.raises(ValueError, match="file_filter"):
            DialogConfig(file_filter="py")

    def test_rejects_nul_in_default_path(self):
        with pytest.raises(ValueError, match="default_path"):
            DialogConfig(default_path="C:\\tmp\0secret")

    def test_rejects_bad_custom_dirs(self):
        with pytest.raises(ValueError, match="custom_dirs"):
            DialogConfig(custom_dirs=[("", "/tmp")])

    def test_accepts_custom_dirs(self):
        cfg = DialogConfig(custom_dirs=[("Projects", "D:/Projects")])
        assert cfg.custom_dirs == [("Projects", "D:/Projects")]

    def test_rejects_bad_min_size(self):
        with pytest.raises(ValueError, match="min_size"):
            DialogConfig(min_size=(0, 100))

    def test_rejects_width_below_min_size(self):
        with pytest.raises(ValueError, match="min_size"):
            DialogConfig(width=100, min_size=(200, 200))

    def test_rejects_glob_metacharacters_in_filter(self):
        with pytest.raises(ValueError, match="metacharacters"):
            DialogConfig(file_filter=".p*")

    def test_rejects_non_enum_mode(self):
        with pytest.raises(TypeError, match="DialogMode"):
            DialogConfig(mode="open")  # type: ignore[arg-type]


# ── DEFAULT_FILTER_LIST ─────────────────────────────────────────


class TestDefaultFilterList:
    def test_is_tuple(self):
        assert isinstance(DEFAULT_FILTER_LIST, tuple)

    def test_not_empty(self):
        assert len(DEFAULT_FILTER_LIST) > 0

    def test_first_is_wildcard(self):
        assert DEFAULT_FILTER_LIST[0] == ".*"

    def test_all_start_with_dot(self):
        for ext in DEFAULT_FILTER_LIST:
            assert ext.startswith("."), f"Extension {ext!r} does not start with '.'"

    def test_no_duplicates(self):
        assert len(DEFAULT_FILTER_LIST) == len(set(DEFAULT_FILTER_LIST))

    def test_is_sorted_after_wildcard(self):
        """Extensions after '.*' should be in alphabetical order."""
        rest = list(DEFAULT_FILTER_LIST[1:])
        assert rest == sorted(rest), "Filter list is not sorted alphabetically"

    @pytest.mark.parametrize(
        "ext",
        [
            ".py",
            ".txt",
            ".md",
            ".exe",
            ".zip",
            ".jpg",
            ".pdf",
            ".json",
            ".html",
            ".xlsx",
            ".pptx",
            ".epub",
            ".kt",
            ".vue",
            ".toml",
            ".vob",
            ".heic",
        ],
    )
    def test_common_extensions_present(self, ext):
        assert ext in DEFAULT_FILTER_LIST, f"{ext} missing from DEFAULT_FILTER_LIST"

    def test_all_lowercase(self):
        for ext in DEFAULT_FILTER_LIST:
            assert ext == ext.lower(), f"Extension {ext!r} is not lowercase"
