"""PDF rendering support for the preview panel.

Uses pypdfium2 (Apache/BSD licensed) + numpy for high-performance
page rendering with LRU caching, raw_texture/mvBuffer transfer,
and background prefetch of neighboring pages.
"""
# MIT licensed

import ctypes
import threading
from collections import OrderedDict

import dearpygui.dearpygui as dpg

try:
    import pypdfium2 as _pdfium
except ImportError:
    _pdfium = None

try:
    import numpy as _np
except ImportError:
    _np = None

try:
    from PIL import Image as _PILImage
except ImportError:
    _PILImage = None


def pdf_available() -> bool:
    """Return True if all PDF preview dependencies are installed."""
    return _pdfium is not None and _np is not None and _PILImage is not None


class PDFRenderer:
    """Renders PDF pages into a DPG raw_texture with LRU caching.

    The rendering pipeline is:
    pypdfium2.render(scale) -> PIL RGBA -> numpy float32 / 255
    -> center on white canvas -> ctypes.memmove into mvBuffer
    -> raw_texture auto-updates on GPU.
    """

    _CACHE_SIZE: int = 10

    def __init__(self, config_tag: str):
        self._config_tag = config_tag
        self._doc = None
        self._total_pages: int = 0
        self._current_page: int = 0
        self._current_path: str = ""

        # LRU page cache: page_num -> np.ndarray (float32 RGBA)
        self._page_cache: OrderedDict[int, "_np.ndarray"] = OrderedDict()

        # raw_texture + mvBuffer state (integer IDs, no string aliases)
        self._tex_w: int = 0
        self._tex_h: int = 0
        self._tex_buffer = None
        self._buf_ptr: int | None = None
        self._tex_id: int | None = None
        self._tex_exists: bool = False

        # Thread safety
        self._doc_lock = threading.Lock()
        self._prefetch_generation: int = 0

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
            self._doc = _pdfium.PdfDocument(path)
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

    def close(self) -> None:
        """Close the PDF document and release all resources."""
        self._prefetch_generation += 1
        self._page_cache.clear()

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
                    pass
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

        # Initialize to white using memmove from numpy
        white = _np.ones(buf_size, dtype=_np.float32)
        self._buf_ptr = ctypes.addressof(
            ctypes.c_float.from_buffer(self._tex_buffer)
        )
        ctypes.memmove(self._buf_ptr, white.ctypes.data, white.nbytes)

        with dpg.texture_registry():
            self._tex_id = dpg.add_raw_texture(
                self._tex_w, self._tex_h, self._tex_buffer,
                format=dpg.mvFormat_Float_rgba,
            )
        self._tex_exists = True
        self._page_cache.clear()
        self._prefetch_generation += 1

    # ── Rendering pipeline ────────────────────────────────────

    def _render_to_array(self, page_num: int, w: int, h: int) -> "_np.ndarray":
        """Render a single page to a numpy float32 RGBA array sized w x h."""
        with self._doc_lock:
            page = self._doc[page_num]
            pw, ph = page.get_size()
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
        arr = _np.frombuffer(
            pil_img.tobytes(), dtype=_np.uint8,
        ).astype(_np.float32) / 255.0

        if iw != w or ih != h:
            canvas = _np.ones(w * h * 4, dtype=_np.float32)
            ox = (w - iw) // 2
            oy = (h - ih) // 2
            for row in range(ih):
                src_s = row * iw * 4
                dst_s = ((oy + row) * w + ox) * 4
                canvas[dst_s : dst_s + iw * 4] = arr[src_s : src_s + iw * 4]
            return _np.ascontiguousarray(canvas)
        return _np.ascontiguousarray(arr)

    # ── LRU cache ─────────────────────────────────────────────

    def _get_page(self, page_num: int) -> "_np.ndarray":
        """Get a rendered page from cache or render it fresh."""
        if page_num in self._page_cache:
            self._page_cache.move_to_end(page_num)
            return self._page_cache[page_num]
        data = self._render_to_array(page_num, self._tex_w, self._tex_h)
        self._page_cache[page_num] = data
        if len(self._page_cache) > self._CACHE_SIZE:
            self._page_cache.popitem(last=False)
        return data

    # ── Page display ──────────────────────────────────────────

    def show_page(self, page_num: int) -> tuple[int, int]:
        """Render and display a page. Returns (current_page, total_pages)."""
        if self._doc is None or self._tex_w == 0 or self._tex_h == 0:
            return (0, 0)

        page_num = max(0, min(page_num, self._total_pages - 1))
        self._current_page = page_num

        arr = self._get_page(page_num)
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
        gen = self._prefetch_generation
        thread = threading.Thread(
            target=self._prefetch_worker,
            args=(page_num, gen),
            daemon=True,
        )
        thread.start()

    def _prefetch_worker(self, page_num: int, gen: int) -> None:
        """Background thread: render and cache neighboring pages."""
        for n in [page_num + 1, page_num - 1]:
            if self._prefetch_generation != gen:
                return
            if 0 <= n < self._total_pages and n not in self._page_cache:
                try:
                    data = self._render_to_array(n, self._tex_w, self._tex_h)
                    if self._prefetch_generation != gen:
                        return
                    self._page_cache[n] = data
                    if len(self._page_cache) > self._CACHE_SIZE:
                        self._page_cache.popitem(last=False)
                except Exception:
                    pass
