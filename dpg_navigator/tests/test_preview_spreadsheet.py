"""Tests for Excel metadata loading used by the preview panel."""

import pytest

from dpg_navigator._preview_spreadsheet import (
    ExcelPreviewError,
    load_excel_table,
)


class _Sheet:
    def __init__(self, title, rows):
        self.title = title
        self._rows = rows

    def iter_rows(self, *, values_only):
        assert values_only is True
        return iter(self._rows)


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
        assert table.status == "Sheet: Data | 3 rows \u00d7 3 cols | (showing first 2 rows, first 2 cols)"
        assert table.sheetnames == ["Summary", "Data"]
        assert table.sheet_name == "Data"
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
