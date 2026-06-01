"""Filesystem operations for the dpg_navigator package.

Contains DirectoryLister, which handles directory enumeration, filtering,
sorting, and display formatting. Pure logic with no DearPyGui dependency.

DirectoryIndex provides a background-built in-memory index for fast
recursive file search across directory trees.
"""
# MIT licensed

import datetime
import fnmatch
import hashlib
import logging
import os
import shutil
import tempfile
import threading
import time
import zipfile
from collections.abc import Callable, Collection

_log = logging.getLogger(__name__)

try:
    import py7zr as _py7zr
except ImportError:
    _py7zr = None

from ._types import FileEntry
from . import _platform

MAX_SCAN_DEPTH = 3
INDEX_SCAN_DEPTH = 8
"""Maximum recursion depth for the background directory index."""

INDEX_TTL: float = 60.0
"""Seconds before the directory index is considered stale."""

INDEX_MAX_RESULTS = 500
"""Maximum number of results returned from an index search."""


class DirectoryLister:
    """Lists directory contents with filtering, sorting, and error handling.

    Pure logic (no DearPyGui dependency).  Supports both real directories
    (via ``os.scandir``) and virtual archive paths (ZIP/7z) using the
    ``archive_path|/internal/path`` convention.  Also provides temporary
    file extraction for archive preview with ZipSlip protection.
    """

    _session_temp_dir: str | None = None
    """Root directory for temporary files extracted during this session."""

    @staticmethod
    def _get_session_temp_dir() -> str:
        """Create and return a session-unique temporary directory."""
        if DirectoryLister._session_temp_dir is None:
            base_temp = tempfile.gettempdir()
            # Use PID and time to ensure uniqueness
            session_id = hashlib.md5(f"{os.getpid()}_{time.time()}".encode()).hexdigest()[:8]
            temp_path = os.path.join(base_temp, f"dpg_navigator_extracted_{session_id}")
            os.makedirs(temp_path, exist_ok=True)
            DirectoryLister._session_temp_dir = temp_path
        return DirectoryLister._session_temp_dir

    @staticmethod
    def cleanup_temp_files() -> None:
        """Remove all temporary files extracted during this session."""
        if DirectoryLister._session_temp_dir and os.path.exists(DirectoryLister._session_temp_dir):
            try:
                shutil.rmtree(DirectoryLister._session_temp_dir, ignore_errors=True)
                DirectoryLister._session_temp_dir = None
            except Exception:
                pass

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

        Uses os.scandir() for efficient single-syscall-per-entry enumeration.
        Directories come first, then files, both sorted alphabetically.
        Individual file errors do NOT interrupt the listing.
        """
        if "|" in path:
            return DirectoryLister._list_archive(
                path, show_hidden, dirs_only, file_filter, search_query, show_dir_size
            )
            
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

                    size = DirectoryLister._get_size(item.path, is_dir, show_dir_size)
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

        # Directories first, then files, both alphabetically
        entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))
        return entries

    @staticmethod
    def _get_size(path: str, is_dir: bool, show_dir_size: bool) -> int | None:
        """Get file/directory size in bytes."""
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

    @staticmethod
    def format_size(size_bytes: int | None) -> str:
        """Format file size for display."""
        if size_bytes is None:
            return "-"
        for unit, limit, fmt in [("TB", 2**40, ".1f"), ("GB", 2**30, ".1f"), ("MB", 2**20, ".0f"), ("KB", 2**10, ".0f"), ("B", 1, ".0f")]:
            if size_bytes >= limit:
                return f"{size_bytes / limit:{fmt}} {unit}"
        return "0 B"

    @staticmethod
    def format_time(timestamp: float) -> str:
        """Format modification time for display."""
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(timestamp))

    @staticmethod
    def _list_archive(
        path: str,
        show_hidden: bool,
        dirs_only: bool,
        file_filter: str,
        search_query: str,
        show_dir_size: bool,
    ) -> list[FileEntry]:
        """List contents of a virtual directory inside an archive (ZIP/7Z)."""
        entries: list[FileEntry] = []
        
        parts = path.split("|", 1)
        if len(parts) != 2:
            return entries
            
        archive_path = parts[0]
        internal_dir = parts[1].replace("\\", "/").strip("/")
        
        if not os.path.isfile(archive_path):
            return entries
            
        ext = os.path.splitext(archive_path)[1].lower()
        
        is_zip = ext in {".zip", ".whl", ".egg", ".jar", ".apk"}
        is_7z = ext == ".7z"
        
        if not is_zip and not is_7z:
            return entries

        # We need to collect immediate children of `internal_dir`.
        seen_names = set()
        
        def _add_entry(item_name: str, is_d: bool, size: int | None, mtime: float):
            if item_name in seen_names:
                return
                
            if not is_d and dirs_only:
                return
                
            if search_query and search_query.lower() not in item_name.lower():
                return
                
            archive_exts = {".zip", ".whl", ".egg", ".jar", ".apk", ".7z"}
            bypass_filter = file_filter.lower() in archive_exts

            if not is_d and file_filter != ".*" and not bypass_filter:
                if not fnmatch.fnmatch(item_name.lower(), f"*{file_filter.lower()}"):
                    return

            seen_names.add(item_name)
            item_internal_path = f"{internal_dir}/{item_name}" if internal_dir else item_name
            
            entries.append(FileEntry(
                name=item_name,
                full_path=f"{archive_path}|/{item_internal_path}",
                is_dir=is_d,
                size_bytes=size,
                modified_time=mtime,
                is_hidden=False,
            ))

        try:
            if is_zip:
                with zipfile.ZipFile(archive_path, 'r') as zf:
                    for info in zf.infolist():
                        p = info.filename.strip("/")
                        if internal_dir and not p.startswith(internal_dir + "/"):
                            continue
                        rel_p = p[len(internal_dir) + 1:] if internal_dir else p
                        if not rel_p:
                            continue 
                        if "/" in rel_p:
                            child_dir_name = rel_p.split("/")[0]
                            _add_entry(child_dir_name, True, None, 0.0)
                        else:
                            is_d = info.is_dir()
                            dt = info.date_time
                            try:
                                ts = datetime.datetime(*dt).timestamp()
                            except Exception:
                                ts = 0.0
                            _add_entry(rel_p, is_d, info.file_size, ts)
                            
            elif is_7z:
                if _py7zr is None:
                    _log.warning("py7zr is not installed, cannot list .7z archive")
                    return entries
                with _py7zr.SevenZipFile(archive_path, 'r') as z:
                    for info in z.list():
                        p = info.filename.replace("\\", "/").strip("/")
                        if internal_dir and not p.startswith(internal_dir + "/"):
                            continue
                        rel_p = p[len(internal_dir) + 1:] if internal_dir else p
                        if not rel_p:
                            continue
                        if "/" in rel_p:
                            child_dir_name = rel_p.split("/")[0]
                            _add_entry(child_dir_name, True, None, 0.0)
                        else:
                            is_d = info.is_directory
                            ts = info.creationtime.timestamp() if info.creationtime else 0.0
                            _add_entry(rel_p, is_d, info.uncompressed, ts)
                            
        except Exception as e:
            _log.error("Failed to list archive %s: %s", archive_path, e)

        entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))
        return entries

    @staticmethod
    def extract_from_archive(
        virtual_path: str,
        *,
        max_size: int | None = None,
        allow_large_extensions: Collection[str] = (),
    ) -> str | None:
        """Extract a single file from an archive virtual path to a temp file.

        If *max_size* is set, oversized members are rejected before extraction
        unless their extension is listed in *allow_large_extensions*.
        """
        if "|" not in virtual_path:
            return None
            
        try:
            parts = virtual_path.split("|", 1)
            archive_path = parts[0]
            internal_path = parts[1].replace("\\", "/").strip("/")
            
            if not os.path.isfile(archive_path):
                return None
                
            ext = os.path.splitext(archive_path)[1].lower()
            is_zip = ext in {".zip", ".whl", ".egg", ".jar", ".apk"}
            is_7z = ext == ".7z"

            if not is_zip and not is_7z:
                return None

            allowed_large_exts = {item.lower() for item in allow_large_extensions}

            def _is_oversized(size: int | None) -> bool:
                member_ext = os.path.splitext(internal_path)[1].lower()
                return (
                    max_size is not None
                    and size is not None
                    and size > max_size
                    and member_ext not in allowed_large_exts
                )
            
            archive_hash = hashlib.md5(archive_path.encode()).hexdigest()[:8]
            archive_temp_root = os.path.join(DirectoryLister._get_session_temp_dir(), archive_hash)
            os.makedirs(archive_temp_root, exist_ok=True)
            
            extracted_path = ""
            
            real_root = os.path.realpath(archive_temp_root)

            if is_zip:
                with zipfile.ZipFile(archive_path, 'r') as zf:
                    info = zf.getinfo(internal_path)
                    if info.flag_bits & 0x1:
                        _log.warning("Encrypted ZIP not supported for preview: %s", archive_path)
                        return None
                    if info.is_dir():
                        return None
                    if _is_oversized(info.file_size):
                        _log.warning("Archive member exceeds preview size limit: %s", internal_path)
                        return None
                    # ZipSlip protection: reject entries that escape the extraction root
                    target = os.path.realpath(os.path.join(archive_temp_root, info.filename))
                    if not target.startswith(real_root + os.sep) and target != real_root:
                        _log.warning("ZipSlip attempt blocked: %s", info.filename)
                        return None
                    extracted_path = zf.extract(info, path=archive_temp_root)
            elif is_7z:
                if _py7zr is None:
                    _log.warning("py7zr is not installed, cannot extract from .7z")
                    return None
                with _py7zr.SevenZipFile(archive_path, 'r') as z:
                    if z.password:
                        _log.warning("Encrypted 7z not supported for preview: %s", archive_path)
                        return None
                    target_info = next(
                        (info for info in z.list() if info.filename == internal_path),
                        None,
                    )
                    if target_info is None:
                        return None
                    if _is_oversized(target_info.uncompressed):
                        _log.warning("Archive member exceeds preview size limit: %s", internal_path)
                        return None
                    # ZipSlip protection for 7z
                    target = os.path.realpath(os.path.join(archive_temp_root, internal_path))
                    if not target.startswith(real_root + os.sep) and target != real_root:
                        _log.warning("ZipSlip attempt blocked: %s", internal_path)
                        return None
                    z.extract(targets=[internal_path], path=archive_temp_root)
                    extracted_path = os.path.join(archive_temp_root, internal_path)

            if extracted_path and os.path.exists(extracted_path) and not os.path.isdir(extracted_path):
                return os.path.abspath(extracted_path)
        except Exception as e:
            _log.error("Failed to extract from archive %s: %s", virtual_path, e)
            
        return None


def validate_folder_name(name: str, current_dir: str) -> str | None:
    """Validate a folder name against path traversal attacks.

    Returns an error message string if the name is invalid, or None if valid.
    Rejects names containing '..', path separators, or names that resolve
    outside the current directory via symlinks.
    """
    if (".." in name
            or os.sep in name
            or (os.altsep and os.altsep in name)):
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
    Returns a new list (does not mutate the input).
    """
    if not selected_files:
        typed_name = typed_name.strip()
        if typed_name:
            return [os.path.join(current_dir, typed_name)]
    return list(selected_files)


class DirectoryIndex:
    """Background-built in-memory index for fast recursive file search.

    After ``build()`` is called (typically from a background thread),
    the index holds a flat list of ``FileEntry`` objects for all files
    and directories found recursively under the root path.

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
            return (time.time() - self._built_at) > ttl

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
                if (not entry.is_dir
                        and file_filter != ".*"
                        and not fnmatch.fnmatch(entry.name.lower(), f"*{file_filter.lower()}")):
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
    ) -> None:
        """Recursively scan *root* and populate the in-memory index.

        Checks ``get_generation()`` against *generation* periodically to
        allow early cancellation when the user navigates away.
        """
        entries: list[FileEntry] = []

        try:
            self._walk(root, root, entries, 0, max_depth, generation, get_generation)
        except _Cancelled:
            return

        with self._lock:
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

                        out.append(FileEntry(
                            name=item.name,
                            full_path=item.path,
                            is_dir=is_dir,
                            size_bytes=size,
                            modified_time=mtime,
                            is_hidden=hidden,
                        ))

                    if is_dir and not hidden:
                        subdirs.append(item.path)
                except (OSError, PermissionError):
                    continue

        for subdir in subdirs:
            self._walk(root, subdir, out, depth + 1, max_depth, generation, get_generation)


class _Cancelled(Exception):
    """Raised internally to abort a DirectoryIndex.build() early."""
