"""Tests for Excel metadata loading used by the preview panel."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from dpg_navigator._preview_spreadsheet import (
    ExcelPreviewError,
    load_excel_table,
)


class _Sheet:
    def __init__(self, title, rows):
        self.title = title
        self._rows = rows

    def iter_rows(self, *, values_only, max_row=None):
        assert values_only is True
        rows = self._rows if max_row is None else self._rows[:max_row]
        self.yielded = 0
        for row in rows:
            self.yielded += 1
            yield row


class _Workbook:
    def __init__(self, sheets, active=None):
        self._sheets = {sheet.title: sheet for sheet in sheets}
        self.sheetnames = list(self._sheets)
        self.active = active
        self.closed = False

    def __getitem__(self, sheet_name):
        return self._sheets[sheet_name]

    def close(self):
        self.closed = True


class TestLoadExcelTable:
    def test_loads_selected_sheet_with_bounds(self):
        summary = _Sheet("Summary", [("unused",)])
        data = _Sheet(
            "Data",
            [
                ("a", "b", "c"),
                (1, 2, 3),
                (4, 5, 6),
                (7, 8, 9),
            ],
        )
        workbook = _Workbook([summary, data], active=summary)

        table = load_excel_table(
            "book.xlsx",
            sheet_name="Data",
            max_rows=2,
            max_cols=2,
            workbook_loader=lambda *args, **kwargs: workbook,
        )

        assert table.headers == ["a", "b"]
        assert table.rows == [["1", "2"], ["4", "5"]]
        assert table.status == "Sheet: Data | 2+ rows \u00d7 3 cols | (showing first 2 rows, first 2 cols)"
        assert table.sheetnames == ["Summary", "Data"]
        assert table.sheet_name == "Data"
        assert workbook.closed is True
        assert data.yielded == 4

    def test_does_not_scan_past_row_bound(self):
        many = [("h1", "h2")] + [(i, i) for i in range(1000)]
        data = _Sheet("Data", many)
        workbook = _Workbook([data], active=data)

        table = load_excel_table(
            "big.xlsx",
            sheet_name="Data",
            max_rows=5,
            max_cols=2,
            workbook_loader=lambda *args, **kwargs: workbook,
        )

        assert data.yielded == 7
        assert table.rows == [["0", "0"], ["1", "1"], ["2", "2"], ["3", "3"], ["4", "4"]]
        assert table.status == "Sheet: Data | 5+ rows \u00d7 2 cols | (showing first 5 rows)"
        assert workbook.closed is True

    def test_exact_count_when_sheet_fits_bound(self):
        data = _Sheet(
            "Data",
            [
                ("a", "b"),
                (1, 2),
                (3, 4),
            ],
        )
        workbook = _Workbook([data], active=data)

        table = load_excel_table(
            "small.xlsx",
            sheet_name="Data",
            max_rows=10,
            max_cols=10,
            workbook_loader=lambda *args, **kwargs: workbook,
        )

        assert data.yielded == 3
        assert table.rows == [["1", "2"], ["3", "4"]]
        assert table.status == "Sheet: Data | 2 rows \u00d7 2 cols"
        assert workbook.closed is True

    def test_empty_workbook_returns_empty_status(self):
        workbook = _Workbook([])

        table = load_excel_table(
            "empty.xlsx",
            sheet_name=None,
            max_rows=10,
            max_cols=10,
            workbook_loader=lambda *args, **kwargs: workbook,
        )

        assert table.headers == []
        assert table.rows == []
        assert table.status == "No sheets found"
        assert workbook.closed is True

    def test_missing_backend_raises_preview_error(self):
        with pytest.raises(ExcelPreviewError):
            load_excel_table(
                "book.xlsx",
                sheet_name=None,
                max_rows=10,
                max_cols=10,
                workbook_loader=None,
            )

    def test_rejects_oversized_file(self):
        with patch("dpg_navigator._preview_spreadsheet.ooxml_exceeds_preview_limit", return_value=True), pytest.raises(
            ExcelPreviewError, match="too large"
        ):
            load_excel_table(
                "huge.xlsx",
                sheet_name=None,
                max_rows=10,
                max_cols=10,
                workbook_loader=lambda *args, **kwargs: None,
            )
