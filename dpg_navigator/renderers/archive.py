"""Archive preview renderer.

Reading the archive index runs in the job returned by
:meth:`ArchiveRenderer.prepare`; extracting a clicked member runs through
``PreviewContext.run_in_background``. Both keep the DearPyGui thread free
while a large or solid archive is decompressed.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable

from .._filesystem import DirectoryLister
from .._preview_archive import (
    ArchivePreviewError,
    ArchiveTable,
    EncryptedArchiveError,
    load_7z_table,
    load_zip_table,
)
from .._preview_limits import ARCHIVE_PREVIEW_MEMBER_MAX_BYTES
from .._preview_registry import PDF_EXTS, ZIP_EXTS
from .._types import FileEntry
from ._base import BackgroundRenderer, PreviewContext, PreviewFinish, PreviewJob, TableRenderMixin, run_preview_job

_log = logging.getLogger(__name__)


class ArchiveRenderer(TableRenderMixin, BackgroundRenderer):
    """Render ZIP and 7z archive listings and selected members."""

    _TABLE_MAX_ROWS: int = 200
    _TEXT_PREVIEW_MAX_SIZE: int = ARCHIVE_PREVIEW_MEMBER_MAX_BYTES
    _PDF_EXTS: frozenset[str] = PDF_EXTS

    def __init__(self, request_update_cb: Callable[[FileEntry], None]) -> None:
        self._request_update = request_update_cb
        self._current_entry: FileEntry | None = None
        self._ctx: PreviewContext | None = None

    def render(self, entry: FileEntry, ctx: PreviewContext) -> None:
        """Render an archive listing in the supplied preview context."""
        run_preview_job(self.prepare(entry, ctx))

    def prepare(self, entry: FileEntry, ctx: PreviewContext) -> PreviewJob:
        """Return the worker job that reads the archive's member list."""
        ext = entry.ext
        if ext in ZIP_EXTS:
            return lambda: self._load_listing(entry, ctx, load_zip_table, "Encrypted ZIP archive (Password required)")
        if ext in (".7z", ".cb7"):
            return lambda: self._load_listing(entry, ctx, load_7z_table, "Encrypted 7z archive (Password required)")
        return lambda: lambda: ctx.show_error("Unsupported archive", f"{ext} is not supported")

    def clear(self) -> None:
        """Release the current archive preview context."""
        self._current_entry = None
        self._ctx = None

    def _load_listing(
        self,
        entry: FileEntry,
        ctx: PreviewContext,
        loader: Callable[[str, int], ArchiveTable],
        encrypted_status: str,
    ) -> PreviewFinish:
        """Worker: read the member table (no DearPyGui calls)."""
        try:
            table = loader(entry.full_path, self._TABLE_MAX_ROWS)
        except EncryptedArchiveError:
            return lambda: self._show_listing(entry, ctx, None, encrypted_status)
        except ArchivePreviewError:
            return self.clear
        return lambda: self._show_listing(entry, ctx, table, "")

    def _show_listing(self, entry: FileEntry, ctx: PreviewContext, table: ArchiveTable | None, status: str) -> None:
        """Finish: build the member table. Clicking a row previews that member."""
        self._ctx = ctx
        self._current_entry = entry
        if ctx.panel_id is None:
            return
        if table is None:
            self._render_table_widget(entry.name, [], [], status)
            return
        self._render_table_widget(
            entry.name,
            table.headers,
            table.rows,
            table.status,
            row_click_callback=lambda s, a, u: self._preview_archive_member(entry.full_path, table.rows[u][0]),
        )

    def _on_zip_item_clicked(self, archive_path: str, internal_path: str) -> None:
        """Extract a single file from a ZIP archive and preview it."""
        self._preview_archive_member(archive_path, internal_path)

    def _on_7z_item_clicked(self, archive_path: str, internal_path: str) -> None:
        """Extract a single file from a 7z archive and preview it."""
        self._preview_archive_member(archive_path, internal_path)

    def _preview_archive_member(self, archive_path: str, internal_path: str) -> None:
        """Extract an archive member and route it through the normal preview flow."""
        ctx = self._ctx

        def job() -> PreviewFinish:
            return self._extract_member(ctx, archive_path, internal_path)

        if ctx is None:
            run_preview_job(job)
            return
        ctx.run_in_background(os.path.basename(internal_path), job)

    def _extract_member(self, ctx: PreviewContext | None, archive_path: str, internal_path: str) -> PreviewFinish:
        """Worker: extract the member to the temp dir and describe it as an entry."""

        def error(message: str, detail: str) -> PreviewFinish:
            def finish() -> None:
                if ctx is not None:
                    ctx.show_error(message, detail)

            return finish

        try:
            virtual_path = f"{archive_path}|/{internal_path}"
            extracted_path = DirectoryLister.extract_from_archive(
                virtual_path,
                max_size=self._TEXT_PREVIEW_MAX_SIZE,
                allow_large_extensions=self._PDF_EXTS,
            )
            if not extracted_path:
                _log.warning(
                    "Could not extract archive member %s from %s",
                    internal_path,
                    archive_path,
                )
                return error("Preview unavailable", f"Could not extract {internal_path!r}")
            stat = os.stat(extracted_path)
            virtual_entry = FileEntry(
                name=f"[{os.path.basename(archive_path)}] {os.path.basename(internal_path)}",
                full_path=extracted_path,
                is_dir=False,
                size_bytes=stat.st_size,
                modified_time=stat.st_mtime,
                is_hidden=False,
            )
        except Exception:
            _log.exception(
                "Failed to preview archive member %s in %s",
                internal_path,
                archive_path,
            )
            return error("Preview failed", f"Could not preview {internal_path!r}")
        return lambda: self._request_update(virtual_entry)
