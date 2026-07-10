"""Tests for pure table parsing helpers."""

from __future__ import annotations

from dpg_navigator._preview_table import parse_csv_table


class TestParseCsvTable:
    def test_detects_semicolon_delimiter(self):
        table = parse_csv_table(
            "name;value\nalpha;1\n",
            "data.csv",
            max_rows=10,
            max_cols=10,
        )

        assert table.headers == ["name", "value"]
        assert table.rows == [["alpha", "1"]]
        assert table.status == "1 rows \u00d7 2 cols"

    def test_uses_tab_delimiter_for_tsv(self):
        table = parse_csv_table(
            "name\tvalue\nalpha\t1\n",
            "data.tsv",
            max_rows=10,
            max_cols=10,
        )

        assert table.headers == ["name", "value"]
        assert table.rows == [["alpha", "1"]]

    def test_falls_back_to_comma_for_single_column(self):
        table = parse_csv_table(
            "value\n1\n2\n",
            "data.csv",
            max_rows=10,
            max_cols=10,
        )

        assert table.headers == ["value"]
        assert table.rows == [["1"], ["2"]]

    def test_caps_rows_and_columns(self):
        table = parse_csv_table(
            "a,b,c\n1,2,3\n4,5,6\n7,8,9\n",
            "data.csv",
            max_rows=2,
            max_cols=2,
        )

        assert table.headers == ["a", "b"]
        assert table.rows == [["1", "2"], ["4", "5"]]
        assert table.status == "3 rows \u00d7 3 cols | (showing first 2 rows, first 2 cols)"

    def test_empty_text_returns_empty_table(self):
        table = parse_csv_table("", "data.csv", max_rows=10, max_cols=10)

        assert table.headers == []
        assert table.rows == []
        assert table.status == "Empty file"
