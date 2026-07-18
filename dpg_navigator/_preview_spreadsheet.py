"""Excel metadata loading for the preview panel.

Parses workbook sheets into table-ready rows without depending on DearPyGui.
"""

from __future__ import annotations
# MIT licensed

from dataclasses import dataclass
from typing import Any, Callable, cast

try:
    from openpyxl import load_workbook as _load_workbook  # type: ignore[import-untyped]
except Exception:  # optional backend absent or incompatible (e.g. old Python)
    _load_workbook = cast(Any, None)


class ExcelPreviewError(Exception):
    """Excel workbook data could not be loaded."""


@dataclass(frozen=True)
class SpreadsheetTable:
    """Table-ready worksheet data."""

    headers: list[str]
    rows: list[list[str]]
    status: str
    sheetnames: list[str]
    sheet_name: str


def excel_available() -> bool:
    """Return True when Excel workbook loading is available."""
    return _load_workbook is not None


def load_excel_table(
    path: str,
    *,
    sheet_name: str | None,
    max_rows: int,
    max_cols: int,
    workbook_loader: Callable[..., Any] | None = _load_workbook,
) -> SpreadsheetTable:
    """Load one worksheet into bounded table-ready data."""
    if workbook_loader is None:
        raise ExcelPreviewError("openpyxl is not installed")

    try:
        workbook = workbook_loader(path, read_only=True, data_only=True)
    except Exception as exc:
        raise ExcelPreviewError(str(exc)) from exc

    try:
        sheetnames = list(workbook.sheetnames)
        worksheet = None
        if sheet_name and sheet_name in sheetnames:
            worksheet = workbook[sheet_name]
        elif sheetnames:
            worksheet = workbook.active if workbook.active is not None else workbook[sheetnames[0]]

        if worksheet is None:
            return SpreadsheetTable([], [], "No sheets found", sheetnames, "")

        selected_sheet = worksheet.title
        all_rows: list[list[str]] = []
        total_rows = 0
        widest_row = 0

        for row in worksheet.iter_rows(values_only=True):
            total_rows += 1
            if len(all_rows) < max_rows + 1:
                all_rows.append([
                    str(cell) if cell is not None else ""
                    for cell in row[:max_cols]
                ])
            widest_row = max(widest_row, len(row))
    except Exception as exc:
        raise ExcelPreviewError(str(exc)) from exc
    finally:
        workbook.close()

    if not all_rows:
        return SpreadsheetTable(
            [],
            [],
            f"Sheet: {selected_sheet} | Empty sheet",
            sheetnames,
            selected_sheet,
        )

    headers = all_rows[0]
    rows = all_rows[1:]
    total_data_rows = total_rows - 1
    display_cols = min(widest_row, max_cols)

    while len(headers) < display_cols:
        headers.append(f"Col{len(headers) + 1}")

    parts = [
        f"Sheet: {selected_sheet}",
        f"{total_data_rows} rows \u00d7 {widest_row} cols",
    ]
    truncated = []
    if len(rows) < total_data_rows:
        truncated.append(f"first {len(rows)} rows")
    if display_cols < widest_row:
        truncated.append(f"first {display_cols} cols")
    if truncated:
        parts.append(f"(showing {', '.join(truncated)})")

    return SpreadsheetTable(headers, rows, " | ".join(parts), sheetnames, selected_sheet)
