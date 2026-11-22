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


def compute_dir_size_info(path: str) -> tuple[int, bool]:
    """Return ``(total_bytes, truncated)`` for the directory tree at *path*.

    Files at most ``MAX_SCAN_DEPTH - 1`` levels below *path* are summed.
    *truncated* is True when the scan skipped content (deeper levels or an
    unreadable subdirectory), so *total_bytes* is only a lower bound. An
    unreadable or missing *path* itself reports ``(0, False)``.

    Sizes come from each ``os.scandir`` entry's cached stat rather than a
    second ``stat`` per file. Symlinked files count their target; symlinked
    directories are not entered.
    """
    total = 0
    truncated = False
    pending: list[tuple[str, int]] = [(path, 0)]

    while pending:
        current, depth = pending.pop()
        try:
            scanner = os.scandir(current)
        except OSError:
            if depth > 0:
                truncated = True
            continue
        with scanner:
            try:
                if depth >= MAX_SCAN_DEPTH:
                    # Past the cap nothing is summed; only note whether
                    # anything was left uncounted.
                    if next(scanner, None) is not None:
                        truncated = True
                    continue
                for item in scanner:
                    try:
                        if item.is_dir():
                            if not item.is_symlink():
                                pending.append((item.path, depth + 1))
                        else:
                            total += item.stat().st_size
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

                    hidden = _platform.is_hidden_entry(item)
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

                    # One stat serves size and time. ``DirEntry`` caches it,
                    # and on Windows it is the directory's own copy from the
                    # scan (as Explorer shows it), so a file still being
                    # written can lag until its handle is closed.
                    st = item.stat(follow_symlinks=True)
                    size = self.get_size(item.path, True, show_dir_size) if is_dir else st.st_size
                    mtime = st.st_mtime

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
