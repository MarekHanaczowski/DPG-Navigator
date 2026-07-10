"""Tests for SQLite metadata loading used by the preview panel."""

import sqlite3
from unittest.mock import patch

import pytest

from dpg_navigator._preview_sqlite import SQLitePreviewError, load_sqlite_table


class TestLoadSQLiteTable:
    def test_loads_selected_table_with_bounds(self, tmp_path):
        database_path = tmp_path / "sample.sqlite"
        with sqlite3.connect(database_path) as connection:
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
        with sqlite3.connect(database_path) as connection:
            connection.execute('CREATE TABLE "t" ("v")')
            connection.executemany(
                'INSERT INTO "t" VALUES (?)', [(i,) for i in range(5)],
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
        with sqlite3.connect(database_path) as connection:
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
        with sqlite3.connect(database_path):
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
