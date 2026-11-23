"""Modular preview panel for the file dialog.

Routes a ``FileEntry`` through ``resolve_preview_kind()`` to a
``BaseRenderer``. Text decoding (BOM / UTF-16 / binary) lives here so
tests can cover it without a live renderer.

Loading runs off the DearPyGui thread once :meth:`PreviewPanel.set_notifier`
has been called (``FileDialog`` does this): a renderer's ``prepare()``
returns a job, one worker runs the newest job, and the dialog's frame pump
calls :meth:`PreviewPanel.apply_pending` to build the widgets. The previous
preview stays on screen until the new one is ready; a "Loading" line
replaces it only when loading takes longer than ``LOADING_PLACEHOLDER_DELAY``.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import dearpygui.dearpygui as dpg  # type: ignore[import-untyped]

from ._job_manager import JobManager
from ._preview_limits import PREVIEW_TEXT_CHUNK_BYTES
from ._preview_registry import (
    PILLOW_EXTRA_EXTS,
    STB_IMAGE_EXTS,
    PreviewCapabilities,
    PreviewKind,
    resolve_preview_kind,
)
from ._types import DialogConfig, FileEntry
from .renderers._base import BaseRenderer, PreviewContext, PreviewFinish, PreviewJob
from .renderers.archive import ArchiveRenderer
from .renderers.data import DataRenderer
from .renderers.document import DocumentRenderer
from .renderers.font import FontRenderer
from .renderers.image import ImageRenderer
from .renderers.text import TextRenderer

_log = logging.getLogger(__name__)

LOADING_PLACEHOLDER_DELAY = 0.1
"""Seconds a load may take before the old preview is replaced by a Loading line."""

_UTF16_LE_BOM = b"\xff\xfe"
_UTF16_BE_BOM = b"\xfe\xff"
_NUL = b"\x00"


def _strip_bom(text: str) -> str:
    """Drop a leading U+FEFF left behind by UTF-32 codecs."""
    return text[1:] if text.startswith("\ufeff") else text


def decode_preview_bytes(
    raw_bytes: bytes,
    *,
    known_encoding: str | None = None,
) -> tuple[str | None, bool, str | None]:
    """Decode a file fragment for the text preview.

    Returns ``(text, is_binary, encoding)``. Binary fragments return
    ``(None, True, None)``. Empty input returns ``("", False, None)``.
    """
    if not raw_bytes:
        return "", False, None

    if known_encoding:
        return (
            raw_bytes.decode(known_encoding, errors="replace"),
            False,
            known_encoding,
        )

    try:
        return raw_bytes.decode("utf-8-sig"), False, "utf-8-sig"
    except UnicodeDecodeError:
        pass

    if raw_bytes.startswith(b"\x00\x00\xfe\xff"):
        try:
            return _strip_bom(raw_bytes.decode("utf-32-be")), False, "utf-32-be"
        except UnicodeDecodeError:
            pass
    if raw_bytes.startswith(b"\xff\xfe\x00\x00"):
        try:
            return _strip_bom(raw_bytes.decode("utf-32-le")), False, "utf-32-le"
        except UnicodeDecodeError:
            pass
    if raw_bytes.startswith((_UTF16_LE_BOM, _UTF16_BE_BOM)):
        try:
            return raw_bytes.decode("utf-16"), False, "utf-16"
        except UnicodeDecodeError:
            pass

    check_size = min(len(raw_bytes), 8192)
    if _NUL in raw_bytes[:check_size]:
        return None, True, None

    try:
        return raw_bytes.decode("cp1250"), False, "cp1250"
    except UnicodeDecodeError:
        return raw_bytes.decode("cp1250", errors="replace"), False, "cp1250"


@dataclass
class _PendingLoad:
    """The load the panel is waiting for (DearPyGui-thread bookkeeping)."""

    generation: int
    label: str
    started: float
    replaces_preview: bool
    placeholder_shown: bool = False


class PreviewPanel:
    """Route selected files to the appropriate DearPyGui preview renderer.

    Source code previews as monospace text through ``TextRenderer``.
    Mouse wheel and left-button drag are forwarded to the active renderer
    when the pane is hovered (image zoom/pan, PDF paging, HTML scroll).
    """

    _TEXT_PREVIEW_MAX_SIZE = PREVIEW_TEXT_CHUNK_BYTES

    @staticmethod
    def preview_image_exts() -> frozenset[str]:
        """Return image extensions supported by the image preview path."""
        return STB_IMAGE_EXTS | PILLOW_EXTRA_EXTS

    def __init__(self, config: DialogConfig, preview_width: int, show: bool) -> None:
        self._config = config
        self._config_tag = config.tag
        self._saved_width = preview_width
        self._show = show

        self._panel_id: int | None = None
        self._table_wrapper: int | None = None
        self._current_entry: FileEntry | None = None

        # (path, encoding) detected on the first page; later pages reuse it.
        # Written by worker jobs as one tuple so readers never see a mix.
        self._text_encoding: tuple[str, str] | None = None

        self.ctx = PreviewContext(
            panel_id=0,
            table_wrapper=0,
            config_tag=self._config_tag,
            capabilities=self._preview_capabilities(),
            trusted_html_preview=config.trusted_html_preview,
        )
        self.ctx.on_clear = self.clear
        self.ctx.on_show_error = self._show_preview_error
        self.ctx.run_in_background = self._run_in_background

        # Background loading. ``_load_generation`` is bumped on the DPG thread
        # by every new request; a worker publishes a result only while its
        # generation is still current. One worker drains ``_queued`` so a burst
        # of selections (arrow keys held down) runs only the newest job.
        self._notify: Callable[[], None] | None = None
        self._load_lock = threading.Lock()
        self._load_generation = 0
        self._queued: tuple[int, Callable[[], PreviewFinish]] | None = None
        self._worker_busy = False
        self._ready: tuple[int, PreviewFinish] | None = None
        self._pending: _PendingLoad | None = None

        self._renderers: dict[PreviewKind, BaseRenderer] = {
            PreviewKind.IMAGE: ImageRenderer(),
            PreviewKind.FONT: FontRenderer(),
            PreviewKind.TEXT: TextRenderer(self._load_text_content, self.update),
            PreviewKind.CSV: DataRenderer(self._load_text_content),
            PreviewKind.EXCEL: DataRenderer(self._load_text_content),
            PreviewKind.SQLITE: DataRenderer(self._load_text_content),
            PreviewKind.XML: DataRenderer(self._load_text_content),
            PreviewKind.ZIP: ArchiveRenderer(self.update),
            PreviewKind.SEVEN_Z: ArchiveRenderer(self.update),
            PreviewKind.HTML: DocumentRenderer(self._load_text_content),
            PreviewKind.MARKDOWN: DocumentRenderer(self._load_text_content),
            PreviewKind.PDF: DocumentRenderer(self._load_text_content),
            PreviewKind.WORD: DocumentRenderer(self._load_text_content),
            PreviewKind.PPTX: DocumentRenderer(self._load_text_content),
        }

        self._active_renderer: BaseRenderer | None = None

    def _preview_capabilities(self) -> PreviewCapabilities:
        """Probe optional preview backends available in the current environment."""
        from ._availability import (
            excel_available,
            mammoth_available,
            markdown_available,
            pptx_available,
        )
        from ._pdf import pdf_available
        from ._preview_archive import seven_zip_available
        from ._preview_word import word_available

        # PreviewCapabilities fields (see _preview_registry): pdf, word, mammoth,
        # pptx, markdown, excel, seven_z. It has no html/chrome fields
        # — HTML routing is unconditional on extension, so html_available()/
        # chrome_available() are not part of the capability set.
        return PreviewCapabilities(
            pdf=pdf_available(),
            word=word_available(),
            mammoth=mammoth_available(),
            pptx=pptx_available(),
            markdown=markdown_available(),
            excel=excel_available(),
            seven_z=seven_zip_available(),
        )

    def attach(self, table_wrapper: int, panel_id: int | None) -> None:
        """Attach the preview panel and explorer wrapper item IDs."""
        self._table_wrapper = table_wrapper
        self._panel_id = panel_id
        if self._panel_id:
            self.ctx.panel_id = self._panel_id
        if self._table_wrapper:
            self.ctx.table_wrapper = self._table_wrapper

    def toggle(self, explorer_table: int) -> None:
        """Show or hide the preview child window."""
        if not self._panel_id:
            return
        self._show = not self._show
        dpg.configure_item(self._panel_id, show=self._show)
        self.layout()

    def layout(self) -> None:
        """Ask the active renderer to re-layout its content after a resize."""
        if not self._panel_id or not self._show:
            return
        handler = getattr(self._active_renderer, "on_resize", None)
        if callable(handler):
            handler(None, None, None)

    def on_resize(self, sender: Any, app_data: Any, user_data: Any) -> None:
        """Forward a DearPyGui resize event to the active renderer."""
        if not self._panel_id or not self._show:
            return
        handler = getattr(self._active_renderer, "on_resize", None)
        if callable(handler):
            handler(sender, app_data, user_data)

    def _preview_hovered(self) -> bool:
        """True when the preview pane is shown and the cursor is over it."""
        if self._panel_id is None or not self._show:
            return False
        return bool(dpg.does_item_exist(self._panel_id) and dpg.is_item_hovered(self._panel_id))

    def on_mouse_down(self, sender: Any, app_data: Any, user_data: Any) -> None:
        """Start a renderer drag (image pan) when the pane is hovered."""
        if not self._preview_hovered():
            return
        handler = getattr(self._active_renderer, "on_mouse_down", None)
        if callable(handler):
            handler(sender, app_data, user_data)

    def on_mouse_drag(self, sender: Any, app_data: Any, user_data: Any) -> None:
        """Continue a renderer-specific drag started on the preview pane."""
        handler = getattr(self._active_renderer, "on_mouse_drag", None)
        if callable(handler):
            handler(sender, app_data, user_data)

    def on_mouse_up(self, sender: Any, app_data: Any, user_data: Any) -> None:
        """End a renderer-specific drag."""
        handler = getattr(self._active_renderer, "on_mouse_up", None)
        if callable(handler):
            handler(sender, app_data, user_data)

    def clear(self) -> None:
        """Clear the panel and release the active renderer's state."""
        if self._panel_id:
            dpg.delete_item(self._panel_id, children_only=True)
        if self._active_renderer:
            self._active_renderer.clear()
            self._active_renderer = None
        for tag in self.ctx.pptx_texture_tags:
            if dpg.does_item_exist(tag):
                dpg.delete_item(tag)
        self.ctx.pptx_texture_tags.clear()

    def _show_preview_error(self, message: str, detail: str) -> None:
        self.clear()
        if self._panel_id:
            dpg.add_text(message, color=[255, 100, 100], parent=self._panel_id)
            dpg.add_text(detail, color=[200, 200, 200], parent=self._panel_id)

    def update(self, entry: FileEntry | None) -> None:
        """Route a selected file to its preview renderer.

        With a notifier set, a renderer that has ``prepare()`` loads on a
        worker and the widgets appear on a later frame (see
        :meth:`apply_pending`). Without one, everything runs here.
        """
        if not self._panel_id or not self._show:
            return

        if entry is None or entry.is_dir:
            self._cancel_pending_load()
            self._current_entry = None
            self.clear()
            return

        kind = resolve_preview_kind(
            entry.name,
            capabilities=self.ctx.capabilities,
            image_extensions=self.preview_image_exts(),
        )
        renderer = self._renderers.get(kind)
        if renderer is None:
            self._cancel_pending_load()
            self._commit(entry, None, lambda: None)
            dpg.add_text(f"Unsupported preview: {kind.name}", color=[150, 150, 150], parent=self._panel_id)
            return

        prepare = getattr(renderer, "prepare", None)
        if not callable(prepare):
            self._cancel_pending_load()
            self._commit(entry, renderer, lambda: renderer.render(entry, self.ctx))
            return

        try:
            job: PreviewJob = prepare(entry, self.ctx)
        except Exception as exc:
            _log.exception("Preparing preview of %s failed", entry.full_path)
            prepare_error = str(exc)
            self._cancel_pending_load()
            self._commit(entry, renderer, lambda: self.ctx.show_error("Preview failed", prepare_error))
            return

        def load() -> PreviewFinish:
            try:
                finish = job()
            except Exception as exc:
                _log.exception("Loading preview of %s failed", entry.full_path)
                load_error = str(exc)

                def finish() -> None:
                    self.ctx.show_error("Preview failed", load_error)

            return lambda: self._commit(entry, renderer, finish)

        self._start_load(entry.name, load, replaces_preview=True)

    def _commit(self, entry: FileEntry, renderer: BaseRenderer | None, finish: PreviewFinish) -> None:
        """Replace the shown preview with *entry* and run *finish* (DPG thread).

        The same file in the same renderer only loses its widgets: the
        renderer is not cleared, so state it carries over in ``prepare()``
        (the text page) survives. Anything else is a full clear. Excel and
        SQLite previews reopen on the first sheet or table either way.
        """
        if not self._panel_id:
            return
        same_path = (
            self._current_entry is not None
            and entry.full_path == self._current_entry.full_path
            and self._active_renderer is renderer
            and renderer is not None
        )
        if same_path:
            dpg.delete_item(self._panel_id, children_only=True)
        else:
            self.clear()
        self._current_entry = entry
        self._active_renderer = renderer
        finish()

    # ── Background loading ─────────────────────────────────────

    def set_notifier(self, notify: Callable[[], None] | None) -> None:
        """Enable background loading.

        *notify* is called, from a worker too, when a result is ready. It must
        not call DearPyGui: ``FileDialog`` passes ``_schedule_ui_poll``, and its
        frame pump then calls :meth:`apply_pending`.
        """
        self._notify = notify

    def _run_in_background(self, label: str, job: PreviewJob) -> None:
        """``PreviewContext.run_in_background``: a follow-up load in the shown preview.

        Ignored while a newly selected file is loading: the shown preview is
        about to be replaced, and queueing the follow-up would supersede the
        new file's load, leaving the old preview on screen for good.
        """
        with self._load_lock:
            pending = self._pending
        if pending is not None and pending.replaces_preview:
            return
        self._start_load(label, job, replaces_preview=False)

    def _start_load(self, label: str, job: Callable[[], PreviewFinish], *, replaces_preview: bool) -> None:
        """Queue *job* as the newest load; superseded loads are dropped (DPG thread)."""
        notify = self._notify
        if notify is None:
            self._cancel_pending_load()
            job()()
            return
        self._load_generation += 1
        generation = self._load_generation
        with self._load_lock:
            self._ready = None
            self._queued = (generation, job)
            self._pending = _PendingLoad(generation, label, time.monotonic(), replaces_preview)
            start_worker = not self._worker_busy
            self._worker_busy = True
        # Keeps the dialog in the frame pump so the Loading line can appear.
        notify()
        if not start_worker:
            return
        try:
            future = JobManager.submit(self._drain_loads)
        except Exception:
            _log.exception("Could not start the preview worker")
            self._abandon_queue("Could not start the preview worker")
            return
        future.add_done_callback(self._on_worker_finished)

    def _on_worker_finished(self, future: Any) -> None:
        """A worker cancelled before it ran (pool shutdown) or one that crashed
        leaves no one draining the queue."""
        if future.cancelled():
            self._abandon_queue("Preview loading was cancelled")
        elif future.exception() is not None:
            self._abandon_queue(f"Preview worker failed: {future.exception()}")

    def _abandon_queue(self, reason: str) -> None:
        """No worker will drain the queue: fail the waiting load instead of
        leaving it pending (and its Loading line on screen) for good.

        May run on any thread; it only stores state and notifies.
        """
        with self._load_lock:
            self._worker_busy = False
            self._queued = None
            pending = self._pending
            if pending is None or pending.generation != self._load_generation or self._ready is not None:
                return
            self._ready = (pending.generation, self._error_finish(reason))
        notify = self._notify
        if notify is not None:
            notify()

    def _drain_loads(self) -> None:
        """Worker: run queued jobs, newest only, until the queue is empty."""
        while True:
            with self._load_lock:
                item = self._queued
                self._queued = None
                if item is None:
                    self._worker_busy = False
                    return
            generation, job = item
            if generation != self._load_generation:
                continue
            try:
                finish = job()
            except Exception as exc:
                _log.exception("Preview job failed")
                finish = self._error_finish(str(exc))
            with self._load_lock:
                if generation != self._load_generation:
                    continue
                self._ready = (generation, finish)
            notify = self._notify
            if notify is not None:
                notify()

    def _error_finish(self, detail: str) -> PreviewFinish:
        def finish() -> None:
            self._show_preview_error("Preview failed", detail)

        return finish

    def _cancel_pending_load(self) -> None:
        """Forget any queued or finished load (DPG thread)."""
        self._load_generation += 1
        with self._load_lock:
            self._queued = None
            self._ready = None
            self._pending = None

    def has_pending(self) -> bool:
        """True while a background load is queued, running, or waiting to apply."""
        return self._pending is not None or self._ready is not None

    def apply_pending(self) -> None:
        """Build a finished load, or show the Loading line (DPG thread, every frame)."""
        with self._load_lock:
            ready = self._ready
            self._ready = None
            pending = self._pending
            if ready is not None and ready[0] == self._load_generation:
                self._pending = None
        if ready is not None:
            generation, finish = ready
            if generation != self._load_generation:
                return
            try:
                finish()
            except Exception as exc:
                _log.exception("Applying preview failed")
                self._show_preview_error("Preview failed", str(exc))
            return
        if pending is None or pending.placeholder_shown:
            return
        if time.monotonic() - pending.started < LOADING_PLACEHOLDER_DELAY:
            return
        pending.placeholder_shown = True
        self._show_loading(pending)

    def _show_loading(self, pending: _PendingLoad) -> None:
        """Replace the old preview with a Loading line while a slow load runs."""
        if not self._panel_id or not dpg.does_item_exist(self._panel_id):
            return
        if pending.replaces_preview:
            # The new file's commit would clear it anyway; drop the old
            # renderer now so it stops its own background work (Chrome render).
            self.clear()
        else:
            dpg.delete_item(self._panel_id, children_only=True)
        dpg.add_text(f"Loading {pending.label}...", color=[150, 150, 150], parent=self._panel_id)

    def _load_text_content(self, path: str, seek_offset: int = 0) -> tuple[str | None, bool]:
        """Read a file fragment as text with encoding detection and binary check."""
        try:
            with open(path, "rb") as f:
                if seek_offset > 0:
                    f.seek(seek_offset)
                raw_bytes = f.read(self._TEXT_PREVIEW_MAX_SIZE)

            known = None
            stored = self._text_encoding
            if seek_offset > 0 and stored is not None and stored[0] == path:
                known = stored[1]
            text, is_bin, encoding = decode_preview_bytes(
                raw_bytes,
                known_encoding=known,
            )
            if encoding is not None:
                self._text_encoding = (path, encoding)
            return text, is_bin
        except OSError:
            return None, False

    def build_handlers(self, dialog_tag: str, is_active_fn: Callable[[], bool]) -> None:
        """Keep the compatibility hook; global handlers live on KeyboardMixin."""

    def shutdown(self) -> None:
        """Clear the active renderer and release preview-owned resources."""
        self._notify = None
        self._cancel_pending_load()
        self.clear()

    def destroy(self) -> None:
        """Release preview resources during :meth:`FileDialog.destroy`."""
        self.shutdown()

    @property
    def visible(self) -> bool:
        """Whether the preview panel is currently shown (tracked by toggle)."""
        return self._show

    def on_mouse_wheel(self, sender: Any, app_data: Any, user_data: Any) -> None:
        """Route the mouse wheel to the active renderer when the pane is hovered.

        Image preview zooms toward the cursor; PDF changes page; HTML
        scrolls its viewport. Renderers without ``on_mouse_wheel`` ignore it.
        """
        if self._panel_id is None or not self._show:
            return
        if not dpg.does_item_exist(self._panel_id) or not dpg.is_item_hovered(self._panel_id):
            return
        handler = getattr(self._active_renderer, "on_mouse_wheel", None)
        if callable(handler):
            handler(sender, app_data, user_data)
