"""Virtual filesystem: physical paths and zip/7z members.

Archive convention: ``C:\\path\\file.zip|/inner/dir`` — ``|`` separates the
archive file from the path inside it. ``DirectoryLister`` delegates here.
"""

from __future__ import annotations

from ._base import VFSProvider
from ._registry import VFSRegistry

__all__ = ["VFSProvider", "VFSRegistry"]
