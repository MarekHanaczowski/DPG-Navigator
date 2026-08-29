"""Virtual File System abstract base classes."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Collection

from .._types import FileEntry


class VFSProvider(ABC):
    """Abstract provider for a virtual or physical filesystem."""

    @abstractmethod
    def is_valid_path(self, path: str) -> bool:
        """Check if this provider can handle the given path format."""
        pass

    @abstractmethod
    def list_dir(
        self,
        path: str,
        show_hidden: bool = False,
        dirs_only: bool = False,
        file_filter: str = ".*",
        search_query: str = "",
        show_dir_size: bool = False,
    ) -> list[FileEntry]:
        """Return a list of FileEntry for the given path."""
        pass

    @abstractmethod
    def get_size(self, path: str, is_dir: bool, show_dir_size: bool) -> int | None:
        """Get file or directory size in bytes."""
        pass

    @abstractmethod
    def extract_file(
        self,
        virtual_path: str,
        temp_root: str,
        max_size: int | None = None,
        allow_large_extensions: Collection[str] = (),
    ) -> str | None:
        """Extract a single file (if applicable) and return physical path.

        For LocalVFSProvider, this should just return the path if it's already physical.
        """
        pass
