"""Filesystem operations for the dpg_navigator package.

``DirectoryLister`` is a static facade: it does not scan the disk itself.
It asks ``VFSRegistry.get_provider(path)`` and delegates to
``LocalVFSProvider`` or ``ArchiveVFSProvider``. Archive virtual paths use
``archive_path|/internal/path``.

``DirectoryIndex`` is a background-built in-memory index for recursive
search, capped at ``INDEX_MAX_ENTRIES``.
"""

from __future__ import annotations

# MIT licensed
import fnmatch
import hashlib
import logging
import os
import shutil
import tempfile
import threading
import time
from collections.abc import Callable, Collection

_log = logging.getLogger(__name__)

from . import _platform
from ._preview_registry import SEVEN_Z_EXTS, ZIP_EXTS
from ._types import FileEntry
from .vfs import VFSRegistry
from .vfs._local import MAX_SCAN_DEPTH as MAX_SCAN_DEPTH

INDEX_SCAN_DEPTH = 8
"""Maximum recursion depth for the background directory index."""

INDEX_TTL: float = 60.0
"""Seconds before the directory index is considered stale."""

INDEX_MAX_RESULTS = 500
"""Maximum number of results returned from an index search."""

INDEX_MAX_ENTRIES = 50_000
"""Hard cap on indexed entries so a huge tree cannot exhaust memory.

The recursive index has a depth limit but a wide tree can still produce
millions of entries; past this cap the build stops and the partial index is
kept (search results are already limited to :data:`INDEX_MAX_RESULTS`)."""


def _short_md5(data: bytes) -> str:
    """Return an 8-char MD5 hex digest for non-cryptographic naming."""
    return hashlib.md5(data, usedforsecurity=False).hexdigest()[:8]


class DirectoryLister:
    """Lists directory contents with filtering, sorting, and error handling.

    Pure logic (no DearPyGui dependency). Delegates to ``VFSRegistry``:
    physical paths go through ``LocalVFSProvider``, virtual archive paths
    (``archive_path|/internal/path``) through ``ArchiveVFSProvider``.
    Also extracts archive members to a session temp dir with ZipSlip checks.
    """

    _session_temp_dir: str | None = None
    """Root directory for temporary files extracted during this session."""

    @staticmethod
    def _get_session_temp_dir() -> str:
        """Create and return a session-unique temporary directory."""
        if DirectoryLister._session_temp_dir is None:
            DirectoryLister._session_temp_dir = tempfile.mkdtemp(prefix="dpg_navigator_extracted_")
        return DirectoryLister._session_temp_dir

    @staticmethod
    def cleanup_temp_files() -> None:
        """Remove all temporary files extracted during this session."""
        path = DirectoryLister._session_temp_dir
        DirectoryLister._session_temp_dir = None
        if not path or not os.path.exists(path):
            return
        for attempt in range(3):
            try:
                shutil.rmtree(path)
                return
            except OSError:
                time.sleep(0.05 * (attempt + 1))
        shutil.rmtree(path, ignore_errors=True)
        _log.warning("Session extract directory cleanup was incomplete: %s", path)

    @staticmethod
    def list_directory(
        path: str,
        show_hidden: bool = False,
        dirs_only: bool = False,
        file_filter: str = ".*",
        search_query: str = "",
        show_dir_size: bool = False,
    ) -> list[FileEntry]:
        """Return a sorted list of FileEntry for the given directory.

        Delegates to the appropriate VFS Provider.
        """
        provider = VFSRegistry.get_provider(path)
        return provider.list_dir(
            path,
            show_hidden=show_hidden,
            dirs_only=dirs_only,
            file_filter=file_filter,
            search_query=search_query,
            show_dir_size=show_dir_size,
        )

    @staticmethod
    def compute_dir_size(path: str) -> int:
        """Return the bounded total size (bytes) of a directory tree.

        Public entry point for background size computation. Always returns an ``int`` (0 on error).
        """
        provider = VFSRegistry.get_provider(path)
        size = provider.get_size(path, is_dir=True, show_dir_size=True)
        return size if size is not None else 0

    @staticmethod
    def format_size(size_bytes: int | None) -> str:
        """Format file size for display."""
        if size_bytes is None:
            return "-"
        for unit, limit, fmt in [
            ("TB", 2**40, ".1f"),
            ("GB", 2**30, ".1f"),
            ("MB", 2**20, ".0f"),
            ("KB", 2**10, ".0f"),
            ("B", 1, ".0f"),
        ]:
            if size_bytes >= limit:
                return f"{size_bytes / limit:{fmt}} {unit}"
        return "0 B"

    @staticmethod
    def format_time(timestamp: float) -> str:
        """Format modification time for display."""
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(timestamp))

    @staticmethod
    def extract_from_archive(
        virtual_path: str,
        *,
        max_size: int | None = None,
        allow_large_extensions: Collection[str] = (),
    ) -> str | None:
        """Extract a single file from an archive virtual path to a temp file.

        If *max_size* is set, oversized members are rejected before extraction.
        Extensions listed in *allow_large_extensions* get the bounded
        large-preview budget instead (the allowlist raises a small cap, it
        never removes the limit entirely).
        """
        provider = VFSRegistry.get_provider(virtual_path)
        temp_root = DirectoryLister._get_session_temp_dir()
        return provider.extract_file(
            virtual_path,
            temp_root=temp_root,
            max_size=max_size,
            allow_large_extensions=allow_large_extensions,
        )


def is_archive_virtual_path(path: str) -> bool:
    """True when *path* uses ``archive|inner`` and the left side is a zip/7z."""
    if "|" not in path:
        return False
    archive = path.split("|", 1)[0]
    return os.path.splitext(archive)[1].lower() in ZIP_EXTS | SEVEN_Z_EXTS


def validate_folder_name(name: str, current_dir: str) -> str | None:
    """Validate a folder name against path traversal attacks.

    Returns an error message string if the name is invalid, or None if valid.
    Rejects empty/whitespace names, ``.`` / ``..``, path separators, or names
    that resolve outside the current directory via symlinks.
    """
    if not name or not name.strip():
        return "Folder name cannot be empty."
    if name in (".", ".."):
        return f"Invalid folder name: '{name}'."
    if ".." in name or os.sep in name or (os.altsep and os.altsep in name):
        return f"Invalid folder name: '{name}'."

    new_path = os.path.join(current_dir, name)
    resolved = os.path.realpath(new_path)
    real_dir = os.path.realpath(current_dir)
    if not (resolved == real_dir or resolved.startswith(real_dir + os.sep)):
        return f"Invalid folder name: '{name}'."

    return None


def build_selection_list(
    selected_files: list[str],
    typed_name: str,
    current_dir: str,
) -> list[str]:
    """Build the final file selection list.

    If no files are selected, uses the typed filename to construct a path.
    Rejects typed names that escape *current_dir* (``..``, separators that
    leave the directory). Absolute typed paths are kept as explicit intent.
    Returns a new list (does not mutate the input).
    """
    if not selected_files:
        typed_name = typed_name.strip()
        if not typed_name:
            return []
        if os.path.isabs(typed_name):
            return [typed_name]
        # Same rejection policy as validate_folder_name for relative names.
        if ".." in typed_name or os.sep in typed_name or (os.altsep and os.altsep in typed_name):
            return []
        candidate = os.path.join(current_dir, typed_name)
        real_dir = os.path.realpath(current_dir)
        real_cand = os.path.realpath(candidate)
        if not (real_cand == real_dir or real_cand.startswith(real_dir + os.sep)):
            return []
        return [candidate]
    return list(selected_files)


def resolve_archive_selection(
    paths: list[str],
    *,
    max_size: int | None = None,
) -> tuple[list[str], str | None]:
    """Extract archive virtual paths in *paths* to session temp files.

    Paths without ``|`` are kept as-is. Returns ``(resolved, failed_name)``
    where *failed_name* is the basename of the first member that could not
    be extracted (encrypted, oversized, ZipSlip, missing). On failure
    *resolved* may be partial and must be discarded by the caller.
    """
    resolved: list[str] = []
    for path in paths:
        if not is_archive_virtual_path(path):
            resolved.append(path)
            continue
        extracted = DirectoryLister.extract_from_archive(
            path,
            max_size=max_size,
        )
        if not extracted:
            inner = path.rsplit("|", 1)[-1].replace("\\", "/").strip("/")
            name = inner.rsplit("/", 1)[-1] if inner else path
            return resolved, name
        resolved.append(extracted)
    return resolved, None


class DirectoryIndex:
    """Background-built in-memory index for fast recursive file search.

    After ``build()`` is called (typically from a background thread),
    the index holds a flat list of ``FileEntry`` objects for files and
    directories found under the root path, up to ``INDEX_MAX_ENTRIES``
    (extra entries are dropped; the partial index is kept).

    Thread safety: ``build()`` writes ``_entries`` and ``_ready`` behind
    ``_lock``; ``search()`` reads them behind the same lock.  A
    *generation* counter lets callers cancel a stale build early.
    """

    def __init__(self) -> None:
        self._entries: list[FileEntry] = []
        self._root: str = ""
        self._ready: bool = False
        self._built_at: float = 0.0
        self._lock = threading.Lock()

    # ── public query API ───────────────────────────────────────

    @property
    def ready(self) -> bool:
        with self._lock:
            return self._ready

    @property
    def root(self) -> str:
        with self._lock:
            return self._root

    def is_stale(self, ttl: float = INDEX_TTL) -> bool:
        """Return True if the index is older than *ttl* seconds."""
        with self._lock:
            if not self._ready:
                return True
            return (time.time() - self._built_at) >= ttl

    def search(
        self,
        query: str,
        *,
        show_hidden: bool = False,
        dirs_only: bool = False,
        file_filter: str = ".*",
        max_results: int = INDEX_MAX_RESULTS,
    ) -> list[FileEntry]:
        """Search the index for entries matching *query* (substring, case-insensitive).

        Returns up to *max_results* entries.  Applies the same filtering
        rules as ``DirectoryLister.list_directory`` (hidden, dirs_only,
        file_filter) but operates on the pre-built in-memory list.
        """
        if not query:
            return []

        q = query.lower()
        results: list[FileEntry] = []

        with self._lock:
            if not self._ready:
                return []
            for entry in self._entries:
                if q not in entry.name.lower():
                    continue
                if entry.is_hidden and not show_hidden:
                    continue
                if not entry.is_dir and dirs_only:
                    continue
                if (
                    not entry.is_dir
                    and file_filter != ".*"
                    and not fnmatch.fnmatch(entry.name.lower(), f"*{file_filter.lower()}")
                ):
                    continue
                results.append(entry)
                if len(results) >= max_results:
                    break

        # dirs first, then alphabetically
        results.sort(key=lambda e: (not e.is_dir, e.name.lower()))
        return results

    # ── build (called from background thread) ──────────────────

    def build(
        self,
        root: str,
        generation: int,
        get_generation: Callable[[], int],
        max_depth: int = INDEX_SCAN_DEPTH,
        show_hidden: bool = False,
    ) -> None:
        """Recursively scan *root* and populate the in-memory index.

        Checks ``get_generation()`` against *generation* periodically to
        allow early cancellation when the user navigates away. Hidden
        directories are descended only when *show_hidden* is set, mirroring
        the shallow :meth:`DirectoryLister.list_directory` behavior.
        """
        entries: list[FileEntry] = []

        try:
            self._walk(
                root,
                root,
                entries,
                0,
                max_depth,
                generation,
                get_generation,
                show_hidden,
            )
        except _Cancelled:
            return
        except _IndexFull:
            # Keep the partial index — it is still usable for search.
            _log.warning(
                "Directory index truncated at %d entries under %s",
                INDEX_MAX_ENTRIES,
                root,
            )

        with self._lock:
            if get_generation() != generation:
                return
            self._entries = entries
            self._root = root
            self._built_at = time.time()
            self._ready = True

    def invalidate(self) -> None:
        """Mark the index as stale so the next search triggers a rebuild."""
        with self._lock:
            self._ready = False
            self._entries = []
            self._root = ""

    # ── internals ──────────────────────────────────────────────

    def _walk(
        self,
        root: str,
        path: str,
        out: list[FileEntry],
        depth: int,
        max_depth: int,
        generation: int,
        get_generation: Callable[[], int],
        show_hidden: bool,
    ) -> None:
        """Recursive os.scandir walk with depth limit and cancellation."""
        if depth > max_depth:
            return
        if get_generation() != generation:
            raise _Cancelled

        try:
            scanner = os.scandir(path)
        except (PermissionError, OSError):
            return

        subdirs: list[str] = []
        with scanner:
            for item in scanner:
                try:
                    is_dir = item.is_dir(follow_symlinks=True)
                    is_file = item.is_file(follow_symlinks=True)
                    if not is_dir and not is_file:
                        continue

                    hidden = _platform.is_hidden(item.path)

                    # Only index contents below the root (not root's own entries —
                    # those are served by the normal list_directory call)
                    if depth > 0:
                        if len(out) >= INDEX_MAX_ENTRIES:
                            raise _IndexFull
                        try:
                            mtime = item.stat(follow_symlinks=True).st_mtime
                        except OSError:
                            mtime = 0.0
                        size: int | None
                        if is_dir:
                            size = None
                        else:
                            try:
                                size = os.path.getsize(item.path)
                            except OSError:
                                size = None

                        out.append(
                            FileEntry(
                                name=item.name,
                                full_path=item.path,
                                is_dir=is_dir,
                                size_bytes=size,
                                modified_time=mtime,
                                is_hidden=hidden,
                            )
                        )

                    # Recurse into real subdirectories only. Symlinked dirs are
                    # skipped so the index cannot escape the selected tree or
                    # loop on cycles; hidden dirs are descended only when the
                    # caller opted into show_hidden.
                    if is_dir and not item.is_symlink() and (show_hidden or not hidden):
                        subdirs.append(item.path)
                except (OSError, PermissionError):
                    continue

        for subdir in subdirs:
            self._walk(
                root,
                subdir,
                out,
                depth + 1,
                max_depth,
                generation,
                get_generation,
                show_hidden,
            )


class _Cancelled(Exception):
    """Raised internally to abort a DirectoryIndex.build() early."""


class _IndexFull(Exception):
    """Raised internally when the index hits INDEX_MAX_ENTRIES."""
