"""Archive filesystem provider for ZIP and 7z."""

from __future__ import annotations

import datetime
import fnmatch
import hashlib
import logging
import os
import zipfile
from typing import Any, Collection

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
    try:
        return hashlib.md5(data, usedforsecurity=False).hexdigest()[:8]
    except TypeError:
        # Python 3.8 fallback; used only for non-cryptographic temp-dir naming.
        return hashlib.md5(data).hexdigest()[:8]  # nosec B324


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
                    is_hidden=False,
                )
            )

        try:
            if is_zip:
                with zipfile.ZipFile(archive_path, "r") as zf:
                    for info in zf.infolist():
                        p = info.filename.strip("/")
                        if internal_dir and not p.startswith(internal_dir + "/"):
                            continue
                        rel_p = p[len(internal_dir) + 1 :] if internal_dir else p
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
                with _py7zr.SevenZipFile(archive_path, "r") as z:
                    for info in z.list():
                        p = info.filename.replace("\\", "/").strip("/")
                        if internal_dir and not p.startswith(internal_dir + "/"):
                            continue
                        rel_p = p[len(internal_dir) + 1 :] if internal_dir else p
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

            if not os.path.isfile(archive_path):
                return None

            ext = os.path.splitext(archive_path)[1].lower()
            is_zip = ext in ZIP_EXTS
            is_7z = ext in SEVEN_Z_EXTS

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

            archive_hash = _short_md5(archive_path.encode())
            archive_temp_root = os.path.join(temp_root, archive_hash)
            os.makedirs(archive_temp_root, exist_ok=True)

            extracted_path = ""
            real_root = os.path.realpath(archive_temp_root)

            if is_zip:
                with zipfile.ZipFile(archive_path, "r") as zf:
                    info = zf.getinfo(internal_path)
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
                    extracted_path = zf.extract(info, path=archive_temp_root)
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
                        (info for info in z.list() if info.filename == internal_path),
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
                    z.extract(targets=[internal_path], path=archive_temp_root)
                    extracted_path = os.path.join(archive_temp_root, internal_path)

            return _finalize_extracted_member(
                extracted_path,
                real_root,
                internal_path,
                max_size,
                allowed_large_exts,
            )
        except Exception as e:
            _log.error("Failed to extract from archive %s: %s", virtual_path, e)

        return None


def _finalize_extracted_member(
    extracted_path: str,
    real_root: str,
    internal_path: str,
    max_size: int | None,
    allowed_large_exts: set[str],
) -> str | None:
    """Reject symlinks, escaped paths, and members larger than *max_size*."""
    if not extracted_path or not os.path.exists(extracted_path) or os.path.isdir(extracted_path):
        return None
    if os.path.islink(extracted_path):
        _log.warning("Archive member is a symlink: %s", internal_path)
        try:
            os.unlink(extracted_path)
        except OSError:
            pass
        return None
    final = os.path.realpath(extracted_path)
    if not final.startswith(real_root + os.sep) and final != real_root:
        _log.warning("Extracted path escaped archive temp root: %s", internal_path)
        try:
            os.unlink(extracted_path)
        except OSError:
            pass
        return None
    if max_size is not None:
        member_ext = os.path.splitext(internal_path)[1].lower()
        try:
            actual = os.path.getsize(final)
        except OSError:
            return None
        if actual > max_size and member_ext not in allowed_large_exts:
            _log.warning("Archive member exceeds preview size limit after extract: %s", internal_path)
            try:
                os.unlink(final)
            except OSError:
                pass
            return None
    return os.path.abspath(final)
