"""Archive filesystem provider for ZIP and 7z."""

from __future__ import annotations

import datetime
import fnmatch
import hashlib
import logging
import os
import zipfile
from collections.abc import Collection
from typing import Any

from .._preview_limits import PDF_PREVIEW_MAX_BYTES
from .._preview_registry import SEVEN_Z_EXTS, ZIP_EXTS
from .._types import FileEntry
from ._base import VFSProvider

_log = logging.getLogger(__name__)

_py7zr: Any
try:
    import py7zr as _py7zr
except Exception:
    _py7zr = None


def _short_md5(data: bytes) -> str:
    """Return an 8-char MD5 hex digest for non-cryptographic naming."""
    return hashlib.md5(data, usedforsecurity=False).hexdigest()[:8]


class ArchiveVFSProvider(VFSProvider):
    """Virtual paths inside ZIP and 7z: ``archive_path|/inner/dir``."""

    def is_valid_path(self, path: str) -> bool:
        if "|" not in path:
            return False
        parts = path.split("|", 1)
        if len(parts) != 2:
            return False
        ext = os.path.splitext(parts[0])[1].lower()
        return ext in ZIP_EXTS or ext in SEVEN_Z_EXTS

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

        parts = path.split("|", 1)
        if len(parts) != 2:
            return entries

        archive_path = parts[0]
        internal_dir = parts[1].replace("\\", "/").strip("/")

        if not os.path.isfile(archive_path):
            return entries

        ext = os.path.splitext(archive_path)[1].lower()
        is_zip = ext in ZIP_EXTS
        is_7z = ext in SEVEN_Z_EXTS

        if not is_zip and not is_7z:
            return entries

        seen_names = set()

        def _add_entry(item_name: str, is_d: bool, size: int | None, mtime: float) -> None:
            if item_name in seen_names:
                return
            hidden = item_name.startswith(".")
            if hidden and not show_hidden:
                return
            if not is_d and dirs_only:
                return
            if search_query and search_query.lower() not in item_name.lower():
                return

            bypass_filter = file_filter.lower() in (ZIP_EXTS | SEVEN_Z_EXTS)
            if (
                not is_d
                and file_filter != ".*"
                and not bypass_filter
                and not fnmatch.fnmatch(item_name.lower(), f"*{file_filter.lower()}")
            ):
                return

            seen_names.add(item_name)
            item_internal_path = f"{internal_dir}/{item_name}" if internal_dir else item_name

            entries.append(
                FileEntry(
                    name=item_name,
                    full_path=f"{archive_path}|/{item_internal_path}",
                    is_dir=is_d,
                    size_bytes=size,
                    modified_time=mtime,
                    is_hidden=hidden,
                )
            )

        try:
            if is_zip:
                with zipfile.ZipFile(archive_path, "r") as zf:
                    for info in zf.infolist():
                        # Normalize like the 7z branch so members stored with
                        # backslash separators list (and later extract) as
                        # nested paths instead of flat unextractable names.
                        p = info.filename.replace("\\", "/").strip("/")
                        if _has_dotdot_segment(p):
                            continue
                        if internal_dir and not p.startswith(internal_dir + "/"):
                            continue
                        rel_p = p[len(internal_dir) + 1 :] if internal_dir else p
                        if not rel_p:
                            continue
                        if "/" in rel_p:
                            child_dir_name = rel_p.split("/")[0]
                            dt = info.date_time
                            try:
                                ts = datetime.datetime(*dt).timestamp()
                            except Exception:
                                ts = 0.0
                            _add_entry(child_dir_name, True, None, ts)
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
                with _py7zr.SevenZipFile(archive_path, "r") as z:
                    for info in z.list():
                        p = info.filename.replace("\\", "/").strip("/")
                        if _has_dotdot_segment(p):
                            continue
                        if internal_dir and not p.startswith(internal_dir + "/"):
                            continue
                        rel_p = p[len(internal_dir) + 1 :] if internal_dir else p
                        if not rel_p:
                            continue
                        if "/" in rel_p:
                            child_dir_name = rel_p.split("/")[0]
                            ts = info.creationtime.timestamp() if info.creationtime else 0.0
                            _add_entry(child_dir_name, True, None, ts)
                        else:
                            is_d = info.is_directory
                            ts = info.creationtime.timestamp() if info.creationtime else 0.0
                            _add_entry(rel_p, is_d, info.uncompressed, ts)

        except Exception as e:
            _log.error("Failed to list archive %s: %s", archive_path, e)

        entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))
        return entries

    def get_size(self, path: str, is_dir: bool, show_dir_size: bool) -> int | None:
        """Return ``None`` because archive directory sizes are not computed."""
        return None

    def extract_file(
        self,
        virtual_path: str,
        temp_root: str,
        max_size: int | None = None,
        allow_large_extensions: Collection[str] = (),
    ) -> str | None:
        if "|" not in virtual_path:
            return None

        try:
            parts = virtual_path.split("|", 1)
            archive_path = parts[0]
            internal_path = parts[1].replace("\\", "/").strip("/")
            if _has_dotdot_segment(internal_path):
                _log.warning("Refusing archive member with '..' segment: %s", internal_path)
                return None

            if not os.path.isfile(archive_path):
                return None

            ext = os.path.splitext(archive_path)[1].lower()
            is_zip = ext in ZIP_EXTS
            is_7z = ext in SEVEN_Z_EXTS

            if not is_zip and not is_7z:
                return None

            allowed_large_exts = {item.lower() for item in allow_large_extensions}
            budget = _extract_budget(internal_path, max_size, allowed_large_exts)

            def _is_oversized(size: int | None) -> bool:
                return budget is not None and size is not None and size > budget

            archive_hash = _short_md5(archive_path.encode())
            archive_temp_root = os.path.join(temp_root, archive_hash)
            os.makedirs(archive_temp_root, exist_ok=True)

            extracted_path = ""
            real_root = os.path.realpath(archive_temp_root)

            if is_zip:
                with zipfile.ZipFile(archive_path, "r") as zf:
                    info = _zip_member_info(zf, internal_path)
                    if info is None:
                        return None
                    if info.flag_bits & 0x1:
                        _log.warning("Encrypted ZIP not supported for preview: %s", archive_path)
                        return None
                    if info.is_dir():
                        return None
                    if _is_oversized(info.file_size):
                        _log.warning("Archive member exceeds preview size limit: %s", internal_path)
                        return None
                    target = os.path.realpath(os.path.join(archive_temp_root, info.filename))
                    if not target.startswith(real_root + os.sep) and target != real_root:
                        _log.warning("ZipSlip attempt blocked: %s", info.filename)
                        return None
                    extracted_path = _extract_zip_member(zf, info, archive_temp_root, budget)
            elif is_7z:
                if _py7zr is None:
                    _log.warning("py7zr is not installed, cannot extract from .7z")
                    return None
                with _py7zr.SevenZipFile(archive_path, "r") as z:
                    needs_password = getattr(z, "needs_password", None)
                    encrypted = False
                    if callable(needs_password):
                        try:
                            encrypted = bool(needs_password())
                        except Exception:
                            encrypted = False
                    if encrypted:
                        _log.warning("Encrypted 7z not supported for preview: %s", archive_path)
                        return None
                    target_info = next(
                        (info for info in z.list() if info.filename.replace("\\", "/").strip("/") == internal_path),
                        None,
                    )
                    if target_info is None:
                        return None
                    if _is_oversized(target_info.uncompressed):
                        _log.warning("Archive member exceeds preview size limit: %s", internal_path)
                        return None
                    target = os.path.realpath(os.path.join(archive_temp_root, internal_path))
                    if not target.startswith(real_root + os.sep) and target != real_root:
                        _log.warning("ZipSlip attempt blocked: %s", internal_path)
                        return None
                    extracted_path = _extract_7z_member(
                        z,
                        target_info.filename,
                        internal_path,
                        archive_temp_root,
                        budget,
                    )

            return _finalize_extracted_member(
                extracted_path,
                real_root,
                internal_path,
                budget,
            )
        except Exception as e:
            _log.error("Failed to extract from archive %s: %s", virtual_path, e)

        return None


def _extract_budget(internal_path: str, max_size: int | None, allowed_large_exts: set[str]) -> int | None:
    """Return the write budget for a member; large-allowlist still has a hard cap.

    An allowlisted extension raises a small *max_size* to the bounded
    large-preview cap (``PDF_PREVIEW_MAX_BYTES``) — it never removes the
    budget entirely, so a crafted member cannot bypass the cap (audit A4-10).
    """
    ext = os.path.splitext(internal_path)[1].lower()
    if ext in allowed_large_exts:
        if max_size is None:
            return PDF_PREVIEW_MAX_BYTES
        return max(max_size, PDF_PREVIEW_MAX_BYTES)
    return max_size


def _has_dotdot_segment(normalized_path: str) -> bool:
    """True when a normalized (forward-slash) member path contains a ``..`` segment."""
    return any(segment == ".." for segment in normalized_path.split("/"))


def _zip_member_info(zf: zipfile.ZipFile, internal_path: str) -> zipfile.ZipInfo | None:
    """Look up a ZIP member by its normalized (forward-slash) name.

    Listing normalizes ``\\`` to ``/``, so a member stored with backslash
    separators must be found by comparing normalized names — a plain
    ``getinfo`` would raise ``KeyError`` for it.
    """
    try:
        return zf.getinfo(internal_path)
    except KeyError:
        pass
    for info in zf.infolist():
        if info.filename.replace("\\", "/").strip("/") == internal_path:
            return info
    return None


def _unlink_quiet(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def _extract_zip_member(zf: zipfile.ZipFile, info: zipfile.ZipInfo, dest_root: str, budget: int | None) -> str:
    """Stream a ZIP member to disk and abort if the write budget is exceeded."""
    dest = os.path.join(dest_root, info.filename)
    parent = os.path.dirname(dest)
    if parent:
        os.makedirs(parent, exist_ok=True)
    if os.path.islink(dest) or os.path.isdir(dest):
        raise OSError("Refusing to extract over a non-regular path")
    written = 0
    try:
        with zf.open(info, "r") as src, open(dest, "wb") as out:
            while True:
                chunk = src.read(64 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if budget is not None and written > budget:
                    raise OSError("Archive member exceeds extract budget")
                out.write(chunk)
    except BaseException:
        # Covers the budget abort *and* stream failures (bad CRC, truncated
        # data, disk errors): never leave a partial write behind. The ``with``
        # has already closed both handles, so the unlink works on Windows.
        _unlink_quiet(dest)
        raise
    return dest


def _extract_7z_member(
    archive: Any,
    archive_name: str,
    internal_path: str,
    dest_root: str,
    budget: int | None,
) -> str:
    """Extract one 7z member, aborting if the write budget is exceeded."""
    dest = os.path.join(dest_root, internal_path.replace("/", os.sep))
    parent = os.path.dirname(dest)
    if parent:
        os.makedirs(parent, exist_ok=True)

    class _BudgetWriter:
        def __init__(self) -> None:
            self._fp = open(dest, "wb")  # noqa: SIM115 — py7zr owns the writer lifetime
            self._written = 0

        def write(self, data: bytes) -> int:
            self._written += len(data)
            if budget is not None and self._written > budget:
                self._fp.close()
                _unlink_quiet(dest)
                raise OSError("Archive member exceeds extract budget")
            return self._fp.write(data)

        def close(self) -> None:
            self._fp.close()

        def __enter__(self) -> _BudgetWriter:
            return self

        def __exit__(self, *args: object) -> None:
            self.close()

    factory = getattr(archive, "extract", None)
    writer_factory = None
    try:
        from py7zr.io import WriterFactory as _WriterFactory

        class _Factory(_WriterFactory):  # type: ignore[misc]
            def create(self, filename: str) -> Any:  # noqa: ANN401
                return _BudgetWriter()

        writer_factory = _Factory()
    except Exception:
        writer_factory = None

    if writer_factory is not None and callable(factory):
        try:
            archive.extract(targets=[archive_name], path=dest_root, factory=writer_factory)
            return dest
        except TypeError:
            pass

    archive.extract(targets=[archive_name], path=dest_root)
    if not os.path.exists(dest):
        # py7zr writes under the member's *raw* stored name; a name that
        # normalizes differently (e.g. a literal backslash on POSIX) lands
        # elsewhere under dest_root. Move it to the computed dest so the
        # budget check below and the finalize checks always see the payload.
        raw_dest = os.path.join(dest_root, archive_name)
        if os.path.lexists(raw_dest):
            os.replace(raw_dest, dest)
    if budget is not None and os.path.isfile(dest) and os.path.getsize(dest) > budget:
        _unlink_quiet(dest)
        raise OSError("Archive member exceeds extract budget")
    return dest


def _finalize_extracted_member(
    extracted_path: str,
    real_root: str,
    internal_path: str,
    max_size: int | None,
) -> str | None:
    """Reject symlinks, escaped paths, and members larger than *max_size*."""
    if not extracted_path:
        return None
    if os.path.islink(extracted_path):
        _log.warning("Archive member is a symlink: %s", internal_path)
        _unlink_quiet(extracted_path)
        return None
    if not os.path.exists(extracted_path) or os.path.isdir(extracted_path):
        return None
    final = os.path.realpath(extracted_path)
    if not final.startswith(real_root + os.sep) and final != real_root:
        _log.warning("Extracted path escaped archive temp root: %s", internal_path)
        _unlink_quiet(extracted_path)
        return None
    if max_size is not None:
        try:
            actual = os.path.getsize(final)
        except OSError:
            return None
        if actual > max_size:
            _log.warning("Archive member exceeds preview size limit after extract: %s", internal_path)
            _unlink_quiet(final)
            return None
    return os.path.abspath(final)
