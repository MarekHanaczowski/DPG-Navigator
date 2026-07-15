"""Local physical filesystem provider."""

from __future__ import annotations

import fnmatch
import logging
import os
from typing import Collection

from ._base import VFSProvider
from .._types import FileEntry
from .. import _platform

_log = logging.getLogger(__name__)

MAX_SCAN_DEPTH = 3


class LocalVFSProvider(VFSProvider):
    """Provides access to physical files via os.scandir."""

    def is_valid_path(self, path: str) -> bool:
        """Local handles paths without virtual dividers."""
        return "|" not in path

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

                    if not is_dir and file_filter != ".*" and not fnmatch.fnmatch(item.name.lower(), f"*{file_filter.lower()}"):
                        continue

                    size = self.get_size(item.path, is_dir, show_dir_size)
                    mtime = item.stat(follow_symlinks=True).st_mtime

                    entries.append(FileEntry(
                        name=item.name,
                        full_path=item.path,
                        is_dir=is_dir,
                        size_bytes=size,
                        modified_time=mtime,
                        is_hidden=hidden,
                    ))
                except (OSError, PermissionError):
                    continue

        entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))
        return entries

    def get_size(self, path: str, is_dir: bool, show_dir_size: bool) -> int | None:
        if is_dir:
            if not show_dir_size:
                return None
            total = 0
            try:
                for root, dirs, files in os.walk(path):
                    depth = root.replace(path, "", 1).count(os.sep)
                    if depth >= MAX_SCAN_DEPTH:
                        dirs.clear()
                        continue
                    for f in files:
                        try:
                            total += os.path.getsize(os.path.join(root, f))
                        except OSError:
                            pass
            except OSError:
                pass
            return total
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
