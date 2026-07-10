"""Tests for archive metadata loading used by the preview panel."""

from __future__ import annotations

import zipfile
from unittest.mock import patch

import pytest

from dpg_navigator._preview_archive import (
    ArchivePreviewError,
    load_7z_table,
    load_zip_table,
)


class TestLoadZipTable:
    def test_loads_rows_sorted_by_largest_member(self, tmp_path):
        archive_path = tmp_path / "sample.zip"
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("small.txt", "a")
            archive.writestr("large.txt", "b" * 20)

        table = load_zip_table(str(archive_path), max_rows=10)

        assert table.headers == ["Filename", "Size", "Packed", "Ratio", "Date"]
        assert [row[0] for row in table.rows] == ["large.txt", "small.txt"]
        assert table.status == "2 files | Extracted: 21 B"

    def test_caps_rows_and_reports_truncation(self, tmp_path):
        archive_path = tmp_path / "many.zip"
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("a.txt", "a")
            archive.writestr("b.txt", "bb")
            archive.writestr("c.txt", "ccc")

        table = load_zip_table(str(archive_path), max_rows=2)

        assert [row[0] for row in table.rows] == ["c.txt", "b.txt"]
        assert table.status == "3 files (showing largest 2) | Extracted: 6 B"

    def test_empty_archive_has_empty_status(self, tmp_path):
        archive_path = tmp_path / "empty.zip"
        with zipfile.ZipFile(archive_path, "w"):
            pass

        table = load_zip_table(str(archive_path), max_rows=10)

        assert table.headers == []
        assert table.rows == []
        assert table.status == "Empty archive"

    def test_invalid_zip_raises_preview_error(self, tmp_path):
        archive_path = tmp_path / "broken.zip"
        archive_path.write_text("not a zip")

        with pytest.raises(ArchivePreviewError):
            load_zip_table(str(archive_path), max_rows=10)


class TestLoad7zTable:
    def test_missing_backend_raises_preview_error(self):
        with patch("dpg_navigator._preview_archive._py7zr", None):
            with pytest.raises(ArchivePreviewError):
                load_7z_table("archive.7z", max_rows=10)
