"""Local physical filesystem provider."""

from __future__ import annotations

import fnmatch
import logging
import os
from collections.abc import Collection

from .. import _platform
from .._types import FileEntry
from ._base import VFSProvider
from ._paths import split_archive_path

_log = logging.getLogger(__name__)

MAX_SCAN_DEPTH = 3


def _walk_depth(root: str, top: str) -> int:
    """Return how many directory levels *root* lies below *top*.

    ``os.path.relpath`` handles trailing separators and drive roots, which
    a plain string ``replace`` of the prefix got wrong (``C:\\`` as *top*).
    """
    try:
        rel = os.path.relpath(root, top)
    except ValueError:
        return 0
    if rel == os.curdir:
        return 0
    return rel.count(os.sep) + 1


def compute_dir_size_info(path: str) -> tuple[int, bool]:
    """Return ``(total_bytes, truncated)`` for the directory tree at *path*.

    Files at most ``MAX_SCAN_DEPTH - 1`` levels below *path* are summed.
    *truncated* is True when the scan skipped content (deeper levels or an
    unreadable subdirectory), so *total_bytes* is only a lower bound.
    """
    total = 0
    truncated = False

    def _on_error(err: OSError) -> None:
        nonlocal truncated
        if getattr(err, "filename", None) != path:
            truncated = True

    try:
        for root, dirs, files in os.walk(path, onerror=_on_error):
            if _walk_depth(root, path) >= MAX_SCAN_DEPTH:
                if dirs or files:
                    truncated = True
                dirs.clear()
                continue
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass  # broken symlink or vanished file: nothing to count
    except OSError:
        truncated = True
    return total, truncated


class LocalVFSProvider(VFSProvider):
    """Provides access to physical files via os.scandir."""

    def is_valid_path(self, path: str) -> bool:
        """Local handles every path that is not an ``archive|inner`` path."""
        return split_archive_path(path) is None

    def list_dir(
        self,
        path: str,
        show_hidden: bool = False,
        dirs_only: bool = False,
        file_filter: str = ".*",
        search_query: str = "",
        show_dir_size: bool = False,
    ) -> list[FileEntry]:
        entries: list[FileEntry] = []
        try:
            scanner = os.scandir(path)
        except (PermissionError, OSError) as e:
            _log.debug("Failed to list directory %s: %s", path, e)
            return entries

        with scanner:
            for item in scanner:
                try:
                    is_dir = item.is_dir(follow_symlinks=True)
                    is_file = item.is_file(follow_symlinks=True)
                    if not is_dir and not is_file:
                        continue

                    hidden = _platform.is_hidden(item.path)
                    if hidden and not show_hidden:
                        continue

                    if not is_dir and dirs_only:
                        continue

                    if search_query and search_query.lower() not in item.name.lower():
                        continue

                    if (
                        not is_dir
                        and file_filter != ".*"
                        and not fnmatch.fnmatch(item.name.lower(), f"*{file_filter.lower()}")
                    ):
                        continue

                    size = self.get_size(item.path, is_dir, show_dir_size)
                    mtime = item.stat(follow_symlinks=True).st_mtime

                    entries.append(
                        FileEntry(
                            name=item.name,
                            full_path=item.path,
                            is_dir=is_dir,
                            size_bytes=size,
                            modified_time=mtime,
                            is_hidden=hidden,
                        )
                    )
                except (OSError, PermissionError):
                    continue

        entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))
        return entries

    def get_size(self, path: str, is_dir: bool, show_dir_size: bool) -> int | None:
        if is_dir:
            if not show_dir_size:
                return None
            return compute_dir_size_info(path)[0]
        try:
            return os.path.getsize(path)
        except OSError:
            return None

    def extract_file(
        self,
        virtual_path: str,
        temp_root: str,
        max_size: int | None = None,
        allow_large_extensions: Collection[str] = (),
    ) -> str | None:
        # Local files don't need extraction, return the path itself if valid
        if os.path.isfile(virtual_path):
            return virtual_path
        return None
