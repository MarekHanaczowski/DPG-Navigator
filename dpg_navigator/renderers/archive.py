"""Archive preview renderer."""

from __future__ import annotations  # PEP 604/585 in signatures need this on py3.8/3.9

import logging
import os
from typing import Callable

from .._filesystem import DirectoryLister
from .._preview_archive import (
    ArchivePreviewError,
    EncryptedArchiveError,
    load_7z_table,
    load_zip_table,
)
from .._preview_registry import PDF_EXTS
from .._types import FileEntry
from ._base import BaseRenderer, PreviewContext, TableRenderMixin

_log = logging.getLogger(__name__)


class ArchiveRenderer(TableRenderMixin, BaseRenderer):
    """Render ZIP and 7z archive listings and selected members."""

    _TABLE_MAX_ROWS: int = 200
    _TEXT_PREVIEW_MAX_SIZE: int = 256 * 1024
    _PDF_EXTS: frozenset[str] = PDF_EXTS

    def __init__(self, request_update_cb: Callable[[FileEntry], None]) -> None:
        self._request_update = request_update_cb
        self._current_entry: FileEntry | None = None
        self._ctx: PreviewContext | None = None

    def render(self, entry: FileEntry, ctx: PreviewContext) -> None:
        """Render an archive listing in the supplied preview context."""
        self._ctx = ctx
        self._current_entry = entry
        ext = entry.ext
        if ext == ".zip":
            self._render_zip_preview(entry)
        elif ext in (".7z", ".cb7"):
            self._render_7z_preview(entry)
        else:
            ctx.show_error("Unsupported archive", f"{ext} is not supported")

    def clear(self) -> None:
        """Release the current archive preview context."""
        self._current_entry = None
        self._ctx = None

    def _render_zip_preview(self, entry: FileEntry) -> None:
        """Parse a ZIP archive and display its contents as a native DPG table."""
        if self._ctx is None or self._ctx.panel_id is None:
            return

        try:
            table = load_zip_table(entry.full_path, self._TABLE_MAX_ROWS)
        except EncryptedArchiveError:
            self._render_table_widget(entry.name, [], [], "Encrypted ZIP archive (Password required)")
            return
        except ArchivePreviewError:
            self.clear()
            return

        self._render_table_widget(
            entry.name,
            table.headers,
            table.rows,
            table.status,
            row_click_callback=lambda s, a, u: self._on_zip_item_clicked(entry.full_path, table.rows[u][0]),
        )

    def _on_zip_item_clicked(self, archive_path: str, internal_path: str) -> None:
        """Extract a single file from a ZIP archive and preview it."""
        self._preview_archive_member(archive_path, internal_path)

    def _preview_archive_member(self, archive_path: str, internal_path: str) -> None:
        """Extract an archive member and route it through the normal preview flow."""
        try:
            virtual_path = f"{archive_path}|/{internal_path}"
            extracted_path = DirectoryLister.extract_from_archive(
                virtual_path,
                max_size=self._TEXT_PREVIEW_MAX_SIZE,
                allow_large_extensions=self._PDF_EXTS,
            )
            if extracted_path:
                stat = os.stat(extracted_path)
                virtual_entry = FileEntry(
                    name=f"[{os.path.basename(archive_path)}] {os.path.basename(internal_path)}",
                    full_path=extracted_path,
                    is_dir=False,
                    size_bytes=stat.st_size,
                    modified_time=stat.st_mtime,
                    is_hidden=False,
                )
                self._request_update(virtual_entry)
            else:
                _log.warning(
                    "Could not extract archive member %s from %s",
                    internal_path,
                    archive_path,
                )
                if self._ctx is not None:
                    self._ctx.show_error(
                        "Preview unavailable",
                        f"Could not extract {internal_path!r}",
                    )
        except Exception:
            _log.exception(
                "Failed to preview archive member %s in %s",
                internal_path,
                archive_path,
            )
            if self._ctx is not None:
                self._ctx.show_error(
                    "Preview failed",
                    f"Could not preview {internal_path!r}",
                )

    def _render_7z_preview(self, entry: FileEntry) -> None:
        """Parse a 7z archive and display its contents as a native DPG table."""
        if self._ctx is None or self._ctx.panel_id is None:
            return

        try:
            table = load_7z_table(entry.full_path, self._TABLE_MAX_ROWS)
        except EncryptedArchiveError:
            self._render_table_widget(entry.name, [], [], "Encrypted 7z archive (Password required)")
            return
        except ArchivePreviewError:
            self.clear()
            return

        self._render_table_widget(
            entry.name,
            table.headers,
            table.rows,
            table.status,
            row_click_callback=lambda s, a, u: self._on_7z_item_clicked(entry.full_path, table.rows[u][0]),
        )

    def _on_7z_item_clicked(self, archive_path: str, internal_path: str) -> None:
        """Extract a single file from a 7z archive and preview it."""
        self._preview_archive_member(archive_path, internal_path)
