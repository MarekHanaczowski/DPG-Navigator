"""Measure heavy pure-data preview paths without starting DearPyGui.

Run from the repository root:

    python benchmarks/benchmark_heavy_paths.py
    python benchmarks/benchmark_heavy_paths.py --profile quick --json
"""
# MIT licensed

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import tempfile
import time
import zipfile
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from dpg_navigator._filesystem import DirectoryIndex
from dpg_navigator._preview_archive import load_zip_table
from dpg_navigator._preview_spreadsheet import excel_available, load_excel_table
from dpg_navigator._preview_sqlite import load_sqlite_table
from dpg_navigator._preview_table import parse_csv_table


@dataclass(frozen=True, slots=True)
class Workload:
    """Input sizes used by a benchmark profile."""

    csv_rows: int
    excel_rows: int
    sqlite_rows: int
    zip_members: int
    directory_count: int
    files_per_directory: int


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    """Timing summary for one benchmark."""

    name: str
    median_ms: float
    minimum_ms: float
    iterations: int
    details: str


PROFILES = {
    "quick": Workload(
        csv_rows=1_000,
        excel_rows=500,
        sqlite_rows=1_000,
        zip_members=200,
        directory_count=10,
        files_per_directory=20,
    ),
    "default": Workload(
        csv_rows=50_000,
        excel_rows=10_000,
        sqlite_rows=50_000,
        zip_members=5_000,
        directory_count=100,
        files_per_directory=100,
    ),
}


def _measure(
    name: str,
    action: Callable[[], object],
    *,
    iterations: int,
    details: str,
) -> BenchmarkResult:
    durations = []
    for _ in range(iterations):
        started = time.perf_counter()
        action()
        durations.append((time.perf_counter() - started) * 1_000)
    return BenchmarkResult(
        name=name,
        median_ms=round(statistics.median(durations), 3),
        minimum_ms=round(min(durations), 3),
        iterations=iterations,
        details=details,
    )


def _make_csv(rows: int) -> str:
    lines = ["id,name,value,category"]
    lines.extend(f"{index},item-{index},{index * 3},group-{index % 10}" for index in range(rows))
    return "\n".join(lines)


def _make_excel(path: Path, rows: int) -> bool:
    if not excel_available():
        return False
    from openpyxl import Workbook  # type: ignore[import-untyped]

    workbook = Workbook(write_only=True)
    worksheet = workbook.create_sheet()
    worksheet.title = "Data"
    worksheet.append(["id", "name", "value", "category"])
    for index in range(rows):
        worksheet.append([index, f"item-{index}", index * 3, f"group-{index % 10}"])
    workbook.save(path)
    return True


def _make_sqlite(path: Path, rows: int) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            'CREATE TABLE "data" ("id", "name", "value", "category")',
        )
        connection.executemany(
            'INSERT INTO "data" VALUES (?, ?, ?, ?)',
            ((index, f"item-{index}", index * 3, f"group-{index % 10}") for index in range(rows)),
        )
        connection.commit()


def _make_zip(path: Path, members: int) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for index in range(members):
            archive.writestr(f"group-{index % 10}/item-{index}.txt", "x" * 128)


def _make_tree(path: Path, directory_count: int, files_per_directory: int) -> None:
    for directory_index in range(directory_count):
        directory = path / f"group-{directory_index:04d}"
        directory.mkdir()
        for file_index in range(files_per_directory):
            (directory / f"item-{file_index:04d}.txt").write_text("x", encoding="utf-8")


def run_benchmarks(profile: str, iterations: int) -> list[BenchmarkResult]:
    """Build fixtures and return timing results for the selected profile."""
    workload = PROFILES[profile]
    csv_text = _make_csv(workload.csv_rows)
    results = [
        _measure(
            "csv_parse",
            lambda: parse_csv_table(csv_text, "data.csv", max_rows=200, max_cols=50),
            iterations=iterations,
            details=f"{workload.csv_rows} data rows",
        ),
    ]

    with tempfile.TemporaryDirectory(prefix="dpg_navigator_benchmark_") as temp_dir:
        root = Path(temp_dir)

        excel_path = root / "data.xlsx"
        if _make_excel(excel_path, workload.excel_rows):
            results.append(
                _measure(
                    "excel_load",
                    lambda: load_excel_table(
                        str(excel_path),
                        sheet_name=None,
                        max_rows=200,
                        max_cols=50,
                    ),
                    iterations=iterations,
                    details=f"{workload.excel_rows} data rows",
                )
            )

        sqlite_path = root / "data.sqlite"
        _make_sqlite(sqlite_path, workload.sqlite_rows)
        results.append(
            _measure(
                "sqlite_load",
                lambda: load_sqlite_table(
                    str(sqlite_path),
                    table_name="data",
                    max_rows=200,
                    max_cols=50,
                ),
                iterations=iterations,
                details=f"{workload.sqlite_rows} data rows",
            )
        )

        zip_path = root / "data.zip"
        _make_zip(zip_path, workload.zip_members)
        results.append(
            _measure(
                "zip_load",
                lambda: load_zip_table(str(zip_path), max_rows=200),
                iterations=iterations,
                details=f"{workload.zip_members} members",
            )
        )

        tree_path = root / "tree"
        tree_path.mkdir()
        _make_tree(
            tree_path,
            workload.directory_count,
            workload.files_per_directory,
        )

        def build_and_search_index() -> None:
            index = DirectoryIndex()
            index.build(str(tree_path), 0, lambda: 0)
            index.search("item")

        total_files = workload.directory_count * workload.files_per_directory
        results.append(
            _measure(
                "directory_index",
                build_and_search_index,
                iterations=iterations,
                details=f"{workload.directory_count} dirs, {total_files} files",
            )
        )

    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=PROFILES, default="default")
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    if args.iterations < 1:
        parser.error("--iterations must be positive")

    results = run_benchmarks(args.profile, args.iterations)
    if args.as_json:
        print(json.dumps([asdict(result) for result in results], indent=2))
        return

    print(f"Profile: {args.profile}; iterations: {args.iterations}")
    print(f"{'benchmark':<20} {'median ms':>12} {'minimum ms':>12}  details")
    for result in results:
        print(
            f"{result.name:<20} {result.median_ms:>12.3f} {result.minimum_ms:>12.3f}  {result.details}",
        )


if __name__ == "__main__":
    main()
