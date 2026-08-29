"""PDF rendering support for the preview panel.

Uses pypdfium2 (Apache/BSD licensed) + numpy for high-performance
page rendering with LRU caching, raw_texture/mvBuffer transfer,
and background prefetch of neighboring pages.
"""

from __future__ import annotations

# MIT licensed
import ctypes
import logging
import os
import threading
from collections import OrderedDict
from concurrent.futures import Future
from typing import Any

_log = logging.getLogger(__name__)

import dearpygui.dearpygui as dpg  # type: ignore[import-untyped]

from ._job_manager import JobManager
from ._optional import OptionalModule, as_optional, require_optional
from ._preview_limits import PDF_PREVIEW_MAX_BYTES

_pdfium: OptionalModule | None
try:
    import pypdfium2 as _pdfium_mod  # type: ignore[import-untyped]

    _pdfium = as_optional(_pdfium_mod)
except Exception:  # optional backend absent or incompatible (e.g. old Python)
    _pdfium = None

_np: OptionalModule | None
try:
    import numpy as _numpy_mod

    _np = as_optional(_numpy_mod)
except Exception:  # optional backend absent or incompatible (e.g. old Python)
    _np = None

_PILImage: OptionalModule | None
try:
    from PIL import Image as _PILImage_mod

    _PILImage = as_optional(_PILImage_mod)
except Exception:  # optional backend absent or incompatible (e.g. old Python)
    _PILImage = None


def pdf_available() -> bool:
    """Return True if all PDF preview dependencies are installed."""
    return _pdfium is not None and _np is not None and _PILImage is not None


_MAX_PDF_BYTES = PDF_PREVIEW_MAX_BYTES
"""Reject PDF files larger than this before opening them in pypdfium2."""


class PDFRenderer:
    """Renders PDF pages into a DPG raw_texture with LRU caching.

    The rendering pipeline is:
    pypdfium2.render(scale) -> PIL RGBA -> numpy float32 / 255
    -> center on white canvas -> ctypes.memmove into mvBuffer
    -> raw_texture auto-updates on GPU.
    """

    _CACHE_SIZE: int = 10

    def __init__(self, config_tag: str) -> None:
        self._config_tag = config_tag
        self._doc: Any = None
        self._total_pages: int = 0
        self._current_page: int = 0
        self._current_path: str = ""

        # LRU page cache: page_num -> np.ndarray (float32 RGBA)
        self._page_cache: OrderedDict[int, Any] = OrderedDict()

        # raw_texture + mvBuffer state (integer IDs, no string aliases)
        self._tex_w: int = 0
        self._tex_h: int = 0
        self._tex_buffer: Any = None
        self._buf_ptr: int | None = None
        self._tex_id: int | None = None
        self._tex_exists: bool = False

        # Thread safety
        self._doc_lock = threading.Lock()
        self._cache_lock = threading.Lock()
        self._prefetch_generation: int = 0
        self._prefetch_future: Future[Any] | None = None

    # ── Properties ────────────────────────────────────────────

    @property
    def is_open(self) -> bool:
        return self._doc is not None

    @property
    def current_page(self) -> int:
        return self._current_page

    @property
    def total_pages(self) -> int:
        return self._total_pages

    @property
    def tex_id(self) -> int | None:
        """DPG integer ID of the raw_texture, or None if not created."""
        return self._tex_id

    # ── Open / close ──────────────────────────────────────────

    def open(self, path: str, w: int, h: int) -> bool:
        """Open a PDF file and prepare for rendering.

        Returns True on success, False on failure.
        """
        self.close()

        try:
            if os.path.getsize(path) > _MAX_PDF_BYTES:
                return False
        except OSError:
            return False

        try:
            pdfium = require_optional(_pdfium, "pypdfium2")
            self._doc = pdfium.PdfDocument(path)
            self._total_pages = len(self._doc)
            self._current_path = path
            self._current_page = 0
        except Exception:
            self._doc = None
            return False

        if self._total_pages == 0:
            self._doc.close()
            self._doc = None
            return False

        self._recreate_texture(w, h)
        return True

    def _cancel_prefetch_future(self) -> None:
        """Drop a queued prefetch so a worker never starts it."""
        fut = self._prefetch_future
        self._prefetch_future = None
        if fut is not None:
            fut.cancel()

    def close(self) -> None:
        """Close the PDF document and release all resources."""
        # Bump the generation and clear atomically, so a prefetch worker cannot
        # observe the old generation yet insert after the clear.
        with self._cache_lock:
            self._prefetch_generation += 1
            self._page_cache.clear()
        self._cancel_prefetch_future()

        if self._tex_exists:
            if self._tex_id is not None and dpg.does_item_exist(self._tex_id):
                dpg.delete_item(self._tex_id)
            self._tex_exists = False
        self._tex_id = None
        self._tex_buffer = None
        self._buf_ptr = None

        with self._doc_lock:
            if self._doc is not None:
                try:
                    self._doc.close()
                except Exception:
                    _log.debug("Failed to close PDF document", exc_info=True)
                self._doc = None
        self._total_pages = 0
        self._current_page = 0
        self._current_path = ""

    # ── Texture management ────────────────────────────────────

    def _recreate_texture(self, w: int, h: int) -> None:
        """Create or recreate the raw_texture and mvBuffer at the given size.

        Only manages the texture resource — the image widget that displays
        it is the caller's responsibility (``close()`` deletes it,
        ``_render_pdf_preview`` / ``on_resize`` in PreviewPanel recreate it).
        """
        if self._tex_exists:
            if self._tex_id is not None and dpg.does_item_exist(self._tex_id):
                dpg.delete_item(self._tex_id)
            self._tex_exists = False

        self._tex_w = max(1, w)
        self._tex_h = max(1, h)

        buf_size = self._tex_w * self._tex_h * 4
        self._tex_buffer = dpg.mvBuffer(buf_size)
        if self._tex_buffer is None:
            raise RuntimeError("Failed to allocate PDF texture buffer")

        # Initialize to white using memmove from numpy
        np = require_optional(_np, "numpy")
        white = np.ones(buf_size, dtype=np.float32)
        self._buf_ptr = ctypes.addressof(ctypes.c_float.from_buffer(self._tex_buffer))
        ctypes.memmove(self._buf_ptr, white.ctypes.data, white.nbytes)

        with dpg.texture_registry():
            self._tex_id = dpg.add_raw_texture(
                self._tex_w,
                self._tex_h,
                self._tex_buffer,
                format=dpg.mvFormat_Float_rgba,
            )
        self._tex_exists = True
        with self._cache_lock:
            self._prefetch_generation += 1
            self._page_cache.clear()
        self._cancel_prefetch_future()

    # ── Rendering pipeline ────────────────────────────────────

    def _render_to_array(self, page_num: int, w: int, h: int) -> Any:
        """Render a single page to a numpy float32 RGBA array sized w x h."""
        if self._doc is None:
            raise RuntimeError("PDF document is not open")

        np = require_optional(_np, "numpy")
        with self._doc_lock:
            page = self._doc[page_num]
            pw, ph = page.get_size()
            if pw <= 0 or ph <= 0:
                raise ValueError("PDF page has invalid dimensions")
            scale = min(w / pw, h / ph)
            bitmap = page.render(scale=scale)
            pil_img = bitmap.to_pil().convert("RGBA")
            del bitmap

        iw, ih = pil_img.size
        # Clamp to target — float rounding in pypdfium2 can overshoot by 1px
        if iw > w:
            pil_img = pil_img.crop((0, 0, w, ih))
            iw = w
        if ih > h:
            pil_img = pil_img.crop((0, 0, iw, h))
            ih = h
        arr = (
            np.frombuffer(
                pil_img.tobytes(),
                dtype=np.uint8,
            ).astype(np.float32)
            / 255.0
        )

        if iw != w or ih != h:
            canvas = np.ones(w * h * 4, dtype=np.float32)
            ox = (w - iw) // 2
            oy = (h - ih) // 2
            # Vectorized centering on a 2D view of the flat canvas — bit-identical
            # to the former per-row loop, but without Python-level iteration.
            canvas.reshape(h, w, 4)[oy : oy + ih, ox : ox + iw] = arr.reshape(ih, iw, 4)
            return np.ascontiguousarray(canvas)
        return np.ascontiguousarray(arr)

    # ── LRU cache ─────────────────────────────────────────────

    def _get_page(self, page_num: int) -> Any:
        """Get a rendered page from cache or render it fresh."""
        with self._cache_lock:
            if page_num in self._page_cache:
                self._page_cache.move_to_end(page_num)
                return self._page_cache[page_num]
        data = self._render_to_array(page_num, self._tex_w, self._tex_h)
        with self._cache_lock:
            self._page_cache[page_num] = data
            if len(self._page_cache) > self._CACHE_SIZE:
                self._page_cache.popitem(last=False)
        return data

    # ── Page display ──────────────────────────────────────────

    def show_page(self, page_num: int) -> tuple[int, int]:
        """Render and display a page. Returns (current_page, total_pages)."""
        if self._doc is None or self._tex_w == 0 or self._tex_h == 0:
            return (0, 0)
        if self._buf_ptr is None:
            return (0, 0)

        page_num = max(0, min(page_num, self._total_pages - 1))
        self._current_page = page_num

        arr = self._get_page(page_num)
        # Guard against a cached array whose size no longer matches the
        # texture buffer (e.g. a stale render surviving a resize): copying it
        # via memmove would overflow/underflow the buffer.
        if arr.size != self._tex_w * self._tex_h * 4:
            return (self._current_page, self._total_pages)
        ctypes.memmove(self._buf_ptr, arr.ctypes.data, arr.nbytes)

        self._start_prefetch(page_num)
        return (self._current_page, self._total_pages)

    def next_page(self) -> tuple[int, int]:
        """Navigate to the next page. Returns (current_page, total_pages)."""
        if self._current_page < self._total_pages - 1:
            return self.show_page(self._current_page + 1)
        return (self._current_page, self._total_pages)

    def prev_page(self) -> tuple[int, int]:
        """Navigate to the previous page. Returns (current_page, total_pages)."""
        if self._current_page > 0:
            return self.show_page(self._current_page - 1)
        return (self._current_page, self._total_pages)

    # ── Resize ────────────────────────────────────────────────

    def on_resize(self, w: int, h: int) -> tuple[int, int] | None:
        """Handle panel resize: recreate texture and re-render current page.

        Returns ``(current_page, total_pages)`` when the texture was
        recreated, or ``None`` when no change was needed (caller should
        skip rebuilding the image widget).
        """
        if self._doc is None:
            return None
        if w == self._tex_w and h == self._tex_h and self._tex_exists:
            return None
        self._recreate_texture(w, h)
        return self.show_page(self._current_page)

    # ── Prefetch ──────────────────────────────────────────────

    def _start_prefetch(self, page_num: int) -> None:
        """Prefetch neighboring pages in a background thread."""
        self._cancel_prefetch_future()
        gen = self._prefetch_generation
        self._prefetch_future = JobManager.submit(self._prefetch_worker, page_num, gen)

    def _prefetch_worker(self, page_num: int, gen: int) -> None:
        """Background thread: render and cache neighboring pages."""
        for n in [page_num + 1, page_num - 1]:
            if self._prefetch_generation != gen:
                return
            if not (0 <= n < self._total_pages):
                continue
            with self._cache_lock:
                if n in self._page_cache:
                    continue
            try:
                data = self._render_to_array(n, self._tex_w, self._tex_h)
                with self._cache_lock:
                    # Re-check under the lock: close()/_recreate_texture() bump
                    # the generation and clear the cache atomically, so a stale
                    # worker must not insert a page from the previous document.
                    if self._prefetch_generation != gen:
                        return
                    self._page_cache[n] = data
                    if len(self._page_cache) > self._CACHE_SIZE:
                        self._page_cache.popitem(last=False)
            except Exception:
                _log.debug("PDF prefetch failed for page %s", n, exc_info=True)
