"""SQLite metadata loading for the preview panel.

Reads databases in read-only mode and returns table-ready rows without
depending on DearPyGui.
"""
# MIT licensed

import sqlite3
from dataclasses import dataclass
from pathlib import Path


class SQLitePreviewError(Exception):
    """SQLite database data could not be loaded."""


@dataclass(frozen=True, slots=True)
class SQLiteTable:
    """Table-ready SQLite data."""

    headers: list[str]
    rows: list[list[str]]
    status: str
    tables: list[str]
    table_name: str


def _quote_identifier(identifier: str) -> str:
    """Escape an SQLite identifier for use between double quotes."""
    return identifier.replace('"', '""')


def load_sqlite_table(
    path: str,
    *,
    table_name: str | None,
    max_rows: int,
    max_cols: int,
) -> SQLiteTable:
    """Load one SQLite table into bounded table-ready data."""
    uri = f"{Path(path).resolve().as_uri()}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=5)
    except sqlite3.Error as exc:
        raise SQLitePreviewError(str(exc)) from exc

    try:
        cursor = connection.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor.fetchall()]
        if not tables:
            return SQLiteTable([], [], "No tables found", [], "")

        selected_table = tables[0]
        if table_name is not None and table_name in tables:
            selected_table = table_name
        safe_table_name = _quote_identifier(selected_table)

        cursor.execute(f'PRAGMA table_info("{safe_table_name}");')
        all_headers = [info[1] for info in cursor.fetchall()]
        headers = all_headers[:max_cols]

        cursor.execute(f'SELECT * FROM "{safe_table_name}" LIMIT {max_rows};')
        rows = [
            [str(cell) for cell in row[:max_cols]]
            for row in cursor.fetchall()
        ]

        cursor.execute(f'SELECT COUNT(*) FROM "{safe_table_name}";')
        total_rows = cursor.fetchone()[0]
    except sqlite3.Error as exc:
        raise SQLitePreviewError(str(exc)) from exc
    finally:
        connection.close()

    status = f"Table: {selected_table} | {total_rows} total rows"
    truncated = []
    if total_rows > max_rows:
        truncated.append(f"first {max_rows} rows")
    if len(all_headers) > max_cols:
        truncated.append(f"first {max_cols} cols")
    if truncated:
        status += f" (showing {', '.join(truncated)})"

    return SQLiteTable(headers, rows, status, tables, selected_table)
