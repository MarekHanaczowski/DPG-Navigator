"""SQLite metadata loading for the preview panel.

Reads databases in read-only mode and returns table-ready rows without
depending on DearPyGui.
"""

from __future__ import annotations

# MIT licensed
import sqlite3
from dataclasses import dataclass
from pathlib import Path

MAX_COUNT_SCAN = 100_000
"""Row-count scan cap.

An exact ``COUNT(*)`` scans the whole table, which is slow for huge tables the
preview only shows a slice of. The count is bounded to this many rows; past it
the total is reported as ``N+``."""


class SQLitePreviewError(Exception):
    """SQLite database data could not be loaded."""


@dataclass(frozen=True)
class SQLiteTable:
    """Table-ready SQLite data."""

    headers: list[str]
    rows: list[list[str]]
    status: str
    tables: list[str]
    table_name: str


MAX_CELL_CHARS = 500
"""Longest cell text shown in the preview; longer values end with ``...``."""


def _format_cell(value: object) -> str:
    """Render one SQLite value as bounded preview text.

    BLOBs are summarized by length instead of dumping ``bytes`` reprs, and
    long text is cut to :data:`MAX_CELL_CHARS` so one huge value cannot
    bloat the table widget.
    """
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<BLOB {len(value)} bytes>"
    text = str(value)
    if len(text) > MAX_CELL_CHARS:
        return text[:MAX_CELL_CHARS] + "..."
    return text


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
        # Untrusted database: do not let schema objects (views, triggers,
        # defaults) call application-defined or side-effecting SQL functions.
        # Older SQLite builds (< 3.31) do not know the pragma; ignore that.
        connection.execute("PRAGMA trusted_schema=OFF;")
    except sqlite3.Error:
        pass

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

        # Table name originates from sqlite_master and is quoted above; it cannot
        # be a parameter in SQLite, so B608 is a false positive here.
        cursor.execute(
            f'SELECT * FROM "{safe_table_name}" LIMIT ?;',  # nosec B608
            (max_rows,),
        )
        rows = [[_format_cell(cell) for cell in row[:max_cols]] for row in cursor.fetchall()]

        # Bounded count: scan at most MAX_COUNT_SCAN+1 rows instead of the whole
        # table, so a huge table cannot stall the preview on COUNT(*).
        cursor.execute(
            f'SELECT COUNT(*) FROM (SELECT 1 FROM "{safe_table_name}" LIMIT ?);',  # nosec B608
            (MAX_COUNT_SCAN + 1,),
        )
        counted = cursor.fetchone()[0]
        count_capped = counted > MAX_COUNT_SCAN
        total_rows = MAX_COUNT_SCAN if count_capped else counted
    except sqlite3.Error as exc:
        raise SQLitePreviewError(str(exc)) from exc
    finally:
        connection.close()

    total_label = f"{total_rows}+" if count_capped else str(total_rows)
    status = f"Table: {selected_table} | {total_label} total rows"
    truncated = []
    if total_rows > max_rows:
        truncated.append(f"first {max_rows} rows")
    if len(all_headers) > max_cols:
        truncated.append(f"first {max_cols} cols")
    if truncated:
        status += f" (showing {', '.join(truncated)})"

    return SQLiteTable(headers, rows, status, tables, selected_table)
