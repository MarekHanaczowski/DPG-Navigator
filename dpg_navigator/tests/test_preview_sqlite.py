"""Tests for SQLite metadata loading used by the preview panel."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from unittest.mock import patch

import pytest

from dpg_navigator._preview_sqlite import MAX_CELL_CHARS, SQLitePreviewError, load_sqlite_table


class TestLoadSQLiteTable:
    def test_loads_selected_table_with_bounds(self, tmp_path):
        database_path = tmp_path / "sample.sqlite"
        with closing(sqlite3.connect(database_path)) as connection, connection:
            connection.execute('CREATE TABLE "data" ("a", "b", "c")')
            connection.executemany(
                'INSERT INTO "data" VALUES (?, ?, ?)',
                [(1, 2, 3), (4, 5, 6), (7, 8, 9)],
            )

        table = load_sqlite_table(
            str(database_path),
            table_name="data",
            max_rows=2,
            max_cols=2,
        )

        assert table.headers == ["a", "b"]
        assert table.rows == [["1", "2"], ["4", "5"]]
        assert table.status == "Table: data | 3 total rows (showing first 2 rows, first 2 cols)"
        assert table.tables == ["data"]
        assert table.table_name == "data"

    def test_row_count_is_bounded(self, tmp_path):
        """A table larger than the scan cap reports its total as ``N+``."""
        database_path = tmp_path / "big.sqlite"
        with closing(sqlite3.connect(database_path)) as connection, connection:
            connection.execute('CREATE TABLE "t" ("v")')
            connection.executemany(
                'INSERT INTO "t" VALUES (?)',
                [(i,) for i in range(5)],
            )

        with patch("dpg_navigator._preview_sqlite.MAX_COUNT_SCAN", 3):
            table = load_sqlite_table(
                str(database_path),
                table_name="t",
                max_rows=2,
                max_cols=5,
            )

        assert "3+ total rows" in table.status

    def test_quoted_table_name_is_escaped(self, tmp_path):
        database_path = tmp_path / "quoted.sqlite"
        with closing(sqlite3.connect(database_path)) as connection, connection:
            connection.execute('CREATE TABLE "odd""name" ("value")')
            connection.execute('INSERT INTO "odd""name" VALUES ("safe")')

        table = load_sqlite_table(
            str(database_path),
            table_name='odd"name',
            max_rows=10,
            max_cols=10,
        )

        assert table.headers == ["value"]
        assert table.rows == [["safe"]]
        assert table.table_name == 'odd"name'

    def test_empty_database_returns_empty_status(self, tmp_path):
        database_path = tmp_path / "empty.sqlite"
        with closing(sqlite3.connect(database_path)):
            pass

        table = load_sqlite_table(
            str(database_path),
            table_name=None,
            max_rows=10,
            max_cols=10,
        )

        assert table.headers == []
        assert table.rows == []
        assert table.status == "No tables found"

    def test_missing_database_raises_preview_error(self, tmp_path):
        with pytest.raises(SQLitePreviewError):
            load_sqlite_table(
                str(tmp_path / "missing.sqlite"),
                table_name=None,
                max_rows=10,
                max_cols=10,
            )


def _single_value_db(tmp_path, value) -> str:
    database_path = tmp_path / "cells.sqlite"
    with closing(sqlite3.connect(database_path)) as connection, connection:
        connection.execute('CREATE TABLE "t" ("v")')
        connection.execute('INSERT INTO "t" VALUES (?)', (value,))
    return str(database_path)


class TestSQLiteCellFormatting:
    def test_long_text_is_truncated_with_ellipsis(self, tmp_path):
        path = _single_value_db(tmp_path, "x" * (MAX_CELL_CHARS + 250))

        table = load_sqlite_table(path, table_name="t", max_rows=5, max_cols=5)

        cell = table.rows[0][0]
        assert cell == "x" * MAX_CELL_CHARS + "..."

    def test_text_at_limit_is_kept(self, tmp_path):
        path = _single_value_db(tmp_path, "y" * MAX_CELL_CHARS)

        table = load_sqlite_table(path, table_name="t", max_rows=5, max_cols=5)

        assert table.rows[0][0] == "y" * MAX_CELL_CHARS

    def test_blob_is_summarized_by_length(self, tmp_path):
        path = _single_value_db(tmp_path, sqlite3.Binary(b"\x00\x01" * 2048))

        table = load_sqlite_table(path, table_name="t", max_rows=5, max_cols=5)

        assert table.rows[0][0] == "<BLOB 4096 bytes>"

    def test_null_and_numbers_still_render(self, tmp_path):
        database_path = tmp_path / "mixed.sqlite"
        with closing(sqlite3.connect(database_path)) as connection, connection:
            connection.execute('CREATE TABLE "t" ("a", "b", "c")')
            connection.execute('INSERT INTO "t" VALUES (NULL, 3, 1.5)')

        table = load_sqlite_table(str(database_path), table_name="t", max_rows=5, max_cols=5)

        assert table.rows == [["None", "3", "1.5"]]


class _RecordingConnection(sqlite3.Connection):
    executed: list[str] = []
    fail_pragma = False

    def execute(self, sql, *args):  # type: ignore[override]
        type(self).executed.append(sql)
        if self.fail_pragma and sql.upper().startswith("PRAGMA TRUSTED_SCHEMA"):
            raise sqlite3.OperationalError("unknown pragma")
        return super().execute(sql, *args)


class TestSQLiteTrustedSchema:
    def _load_with_recording(self, tmp_path, *, fail_pragma: bool):
        path = _single_value_db(tmp_path, "v")
        real_connect = sqlite3.connect
        _RecordingConnection.executed = []
        _RecordingConnection.fail_pragma = fail_pragma

        def connect(*args, **kwargs):
            return real_connect(*args, factory=_RecordingConnection, **kwargs)

        with patch("dpg_navigator._preview_sqlite.sqlite3.connect", side_effect=connect):
            return load_sqlite_table(path, table_name="t", max_rows=5, max_cols=5)

    def test_trusted_schema_is_disabled_after_connect(self, tmp_path):
        table = self._load_with_recording(tmp_path, fail_pragma=False)

        assert table.rows == [["v"]]
        normalized = [sql.replace(" ", "").rstrip(";").upper() for sql in _RecordingConnection.executed]
        assert normalized[0] == "PRAGMATRUSTED_SCHEMA=OFF"

    def test_pragma_failure_is_ignored(self, tmp_path):
        table = self._load_with_recording(tmp_path, fail_pragma=True)

        assert table.rows == [["v"]]
