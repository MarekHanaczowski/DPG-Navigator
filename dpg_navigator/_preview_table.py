"""Pure table parsing helpers for preview renderers."""

from __future__ import annotations

# MIT licensed
import csv
import io
import os
from dataclasses import dataclass


class CsvPreviewError(Exception):
    """CSV or TSV content could not be parsed."""


@dataclass(frozen=True)
class TableData:
    """Table-ready text data."""

    headers: list[str]
    rows: list[list[str]]
    status: str


def parse_csv_table(
    text: str,
    filename: str,
    *,
    max_rows: int,
    max_cols: int,
) -> TableData:
    """Parse CSV or TSV text into bounded table-ready data."""
    ext = os.path.splitext(filename)[1].lower()
    stream = io.StringIO(text)

    try:
        if ext == ".tsv":
            delimiter = "\t"
            dialect = None
        else:
            try:
                dialect = csv.Sniffer().sniff(text[:8192])
            except csv.Error:
                dialect = None
            delimiter = dialect.delimiter if dialect else ","

        reader = csv.reader(stream, dialect) if dialect else csv.reader(stream, delimiter=delimiter)

        all_rows: list[list[str]] = []
        total_rows = 0
        widest_row = 0
        for row in reader:
            total_rows += 1
            if len(all_rows) < max_rows + 1:
                all_rows.append(row[:max_cols])
            widest_row = max(widest_row, len(row))
    except Exception as exc:
        raise CsvPreviewError from exc

    if not all_rows:
        return TableData([], [], "Empty file")

    headers = all_rows[0]
    rows = all_rows[1:]
    total_data_rows = total_rows - 1
    display_cols = min(widest_row, max_cols)

    while len(headers) < display_cols:
        headers.append(f"Col{len(headers) + 1}")

    parts = [f"{total_data_rows} rows \u00d7 {widest_row} cols"]
    truncated = []
    if len(rows) < total_data_rows:
        truncated.append(f"first {len(rows)} rows")
    if display_cols < widest_row:
        truncated.append(f"first {display_cols} cols")
    if truncated:
        parts.append(f"(showing {', '.join(truncated)})")

    return TableData(headers, rows, " | ".join(parts))
