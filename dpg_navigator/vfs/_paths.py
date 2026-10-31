"""Archive virtual-path parsing shared by the VFS, the facade, and dialog logic.

Convention: ``C:\\path\\to\\file.zip|/inner/dir``. POSIX file names may
contain ``|`` themselves, so the split happens on the **first** ``|`` whose
left side ends with a zip/7z extension rather than on the first ``|``.
"""

from __future__ import annotations

import os

from .._preview_registry import SEVEN_Z_EXTS, ZIP_EXTS

ARCHIVE_EXTS: frozenset[str] = ZIP_EXTS | SEVEN_Z_EXTS
"""Extensions whose files can be browsed as ``archive|inner`` virtual paths."""


def split_archive_path(path: str) -> tuple[str, str] | None:
    """Split *path* into ``(archive_path, inner_path)`` or return ``None``.

    The separator is the first ``|`` whose left side has an extension in
    :data:`ARCHIVE_EXTS`. *inner_path* is returned verbatim (callers
    normalize slashes). ``None`` means *path* is not an archive virtual path.
    """
    start = 0
    while True:
        index = path.find("|", start)
        if index < 0:
            return None
        left = path[:index]
        if os.path.splitext(left)[1].lower() in ARCHIVE_EXTS:
            return left, path[index + 1 :]
        start = index + 1


def is_within_directory(path: str, directory: str) -> bool:
    """True when *path* equals *directory* or lies below it.

    Both arguments should already be resolved (``os.path.realpath``).
    ``os.path.commonpath`` compares whole path components, so a sibling
    such as ``/data/dir-evil`` is not mistaken for a child of ``/data/dir``
    and a drive root (``C:\\``) works without a doubled separator. Paths on
    different Windows drives (or mixing absolute and relative) raise
    ``ValueError``; they are never inside.
    """
    try:
        target = os.path.normcase(os.path.abspath(path))
        base = os.path.normcase(os.path.abspath(directory))
        return os.path.commonpath([target, base]) == base
    except ValueError:
        return False
