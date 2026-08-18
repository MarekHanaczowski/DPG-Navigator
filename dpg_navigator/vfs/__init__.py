"""Virtual File System (VFS) abstraction for dpg_navigator."""

from __future__ import annotations

from ._base import VFSProvider
from ._registry import VFSRegistry

__all__ = ["VFSProvider", "VFSRegistry"]
