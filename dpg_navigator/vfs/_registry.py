"""VFS Registry for routing paths to their appropriate provider."""

from __future__ import annotations

from ._archive import ArchiveVFSProvider
from ._base import VFSProvider
from ._local import LocalVFSProvider


class VFSRegistry:
    """Registry to manage and route paths to the correct VFS provider."""

    _providers: list[VFSProvider] = []

    @classmethod
    def register_default_providers(cls) -> None:
        """Register ArchiveVFSProvider then LocalVFSProvider.

        Archive matches ``path|inner`` virtual paths; Local matches the rest.
        """
        if not cls._providers:
            cls._providers.extend(
                [
                    ArchiveVFSProvider(),
                    LocalVFSProvider(),
                ]
            )

    @classmethod
    def get_provider(cls, path: str) -> VFSProvider:
        """Return the first VFS provider that can handle the given path.

        Falls back to LocalVFSProvider if no specific match is found.
        """
        if not cls._providers:
            cls.register_default_providers()

        for provider in cls._providers:
            if provider.is_valid_path(path):
                return provider

        for provider in cls._providers:
            if isinstance(provider, LocalVFSProvider):
                return provider
        return LocalVFSProvider()
