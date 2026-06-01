"""Archive metadata loading for the preview panel.

Parses ZIP and 7z members into table-ready rows without depending on DearPyGui.
"""
# MIT licensed

import zipfile
from dataclasses import dataclass

try:
    import py7zr as _py7zr
except ImportError:
    _py7zr = None

from ._filesystem import DirectoryLister


class ArchivePreviewError(Exception):
    """Archive metadata could not be loaded."""


class EncryptedArchiveError(ArchivePreviewError):
    """Archive requires a password."""


@dataclass(frozen=True, slots=True)
class ArchiveTable:
    """Table-ready archive metadata."""

    headers: list[str]
    rows: list[list[str]]
    status: str


def seven_zip_available() -> bool:
    """Return True when 7z metadata loading is available."""
    return _py7zr is not None


def _status(total_files: int, total_uncompressed: int, max_rows: int) -> str:
    parts = [f"{total_files} files"]
    if total_files > max_rows:
        parts.append(f"(showing largest {max_rows})")
    parts.append(f"| Extracted: {DirectoryLister.format_size(total_uncompressed)}")
    return " ".join(parts)


def _ratio(uncompressed: int, compressed: int) -> str:
    if uncompressed <= 0:
        return "0.0%"
    ratio = ((uncompressed - compressed) / uncompressed) * 100.0
    return f"{ratio:.1f}%"


def load_zip_table(path: str, max_rows: int) -> ArchiveTable:
    """Load ZIP members sorted by uncompressed size descending."""
    rows: list[list[str]] = []
    total_uncompressed = 0

    try:
        with zipfile.ZipFile(path, "r") as zf:
            info_list = zf.infolist()
            info_list.sort(key=lambda info: info.file_size, reverse=True)

            for info in info_list:
                total_uncompressed += info.file_size
                if len(rows) < max_rows:
                    rows.append([
                        info.filename,
                        DirectoryLister.format_size(info.file_size),
                        DirectoryLister.format_size(info.compress_size),
                        _ratio(info.file_size, info.compress_size),
                        f"{info.date_time[0]}-{info.date_time[1]:02d}-{info.date_time[2]:02d}",
                    ])
    except (OSError, PermissionError, zipfile.BadZipFile) as exc:
        raise ArchivePreviewError from exc
    except RuntimeError as exc:
        if "password" in str(exc).lower():
            raise EncryptedArchiveError from exc
        raise ArchivePreviewError from exc

    if not rows:
        return ArchiveTable([], [], "Empty archive")
    return ArchiveTable(
        ["Filename", "Size", "Packed", "Ratio", "Date"],
        rows,
        _status(len(info_list), total_uncompressed, max_rows),
    )


def load_7z_table(path: str, max_rows: int) -> ArchiveTable:
    """Load 7z members sorted by uncompressed size descending."""
    if _py7zr is None:
        raise ArchivePreviewError("py7zr is not installed")

    rows: list[list[str]] = []
    total_uncompressed = 0

    try:
        with _py7zr.SevenZipFile(path, mode="r") as archive:
            info_list = archive.list()
            info_list.sort(
                key=lambda info: info.uncompressed if info.uncompressed else 0,
                reverse=True,
            )

            for info in info_list:
                uncompressed = info.uncompressed if info.uncompressed else 0
                compressed = info.compressed if info.compressed else 0
                total_uncompressed += uncompressed
                if len(rows) < max_rows:
                    date = info.creationtime.strftime("%Y-%m-%d") if info.creationtime else ""
                    rows.append([
                        info.filename,
                        DirectoryLister.format_size(uncompressed),
                        DirectoryLister.format_size(compressed),
                        _ratio(uncompressed, compressed),
                        date,
                    ])
    except (OSError, PermissionError) as exc:
        raise ArchivePreviewError from exc
    except Exception as exc:
        message = str(exc).lower()
        if "password" in message or "encrypted" in message:
            raise EncryptedArchiveError from exc
        raise ArchivePreviewError from exc

    if not rows:
        return ArchiveTable([], [], "Empty 7z archive")
    return ArchiveTable(
        ["Filename", "Size", "Packed", "Ratio", "Date"],
        rows,
        _status(len(info_list), total_uncompressed, max_rows),
    )
