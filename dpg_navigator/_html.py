"""HTML rendering support for the preview panel.

Uses html2image (Chrome Headless) + numpy + Pillow for rendering
HTML files into a scrollable DPG raw_texture with background rendering,
auto-trim, overflow detection, and responsive scaling.
"""

from __future__ import annotations
# MIT licensed

import ctypes
import os
import tempfile
import threading
import time
import uuid
from typing import Any, cast

import dearpygui.dearpygui as dpg  # type: ignore[import-untyped]

try:
    from html2image import Html2Image as _Html2Image  # type: ignore[import-untyped]
except Exception:  # optional backend absent or incompatible (e.g. old Python)
    _Html2Image = cast(Any, None)

try:
    import numpy as _np
except Exception:  # optional backend absent or incompatible (e.g. old Python)
    _np = cast(Any, None)

try:
    from PIL import Image as _PILImage
except Exception:  # optional backend absent or incompatible (e.g. old Python)
    _PILImage = cast(Any, None)


def html_available() -> bool:
    """Return True if all HTML preview dependencies are installed."""
    return _Html2Image is not None and _np is not None and _PILImage is not None


_chrome_available_cache: bool | None = None


def chrome_available() -> bool:
    """Return True if a Chrome/Chromium binary is resolvable for rendering.

    ``html_available()`` only checks the Python packages; html2image still
    needs a browser binary on the system. The lookup touches the filesystem,
    so the result is resolved once and cached.
    """
    global _chrome_available_cache
    if _chrome_available_cache is not None:
        return _chrome_available_cache
    if not html_available():
        _chrome_available_cache = False
        return False
    try:
        hti = HTMLRenderer._get_hti()
        _chrome_available_cache = bool(hti.browser.executable)
    except Exception:
        _chrome_available_cache = False
    return _chrome_available_cache


# ── Module-level constants ─────────────────────────────────────

_RENDER_H: int = 8000
_SCROLL_SPEED: int = 50
_MARGIN: int = 10
_BG_COLOR_RGBA = (26, 26, 26, 255)
_TRIM_TOLERANCE: int = 5
_RESIZE_DEBOUNCE: float = 0.4
_OVERSCAN: int = 20
_MAX_RENDER_W: int = 4000
_CHROME_TIMEOUT: float = 30.0
"""Seconds before a hung Chrome screenshot subprocess is killed."""

_CSS_RESET = (
    "<style>"
    "html,body{margin:0!important;padding:0!important;}"
    "html::-webkit-scrollbar{width:0!important;height:0!important;}"
    "</style>"
)

_OVERFLOW_MARKER = (
    '<script>window.addEventListener("load",function(){'
    'var m=document.createElement("div");'
    'm.style.cssText="position:fixed;top:0;left:0;width:10px;height:10px;'
    'z-index:999999;pointer-events:none;";'
    'var sw=Math.max(document.documentElement.scrollWidth,'
    'document.body.scrollWidth,document.documentElement.offsetWidth,'
    'document.body.offsetWidth);'
    'var v=Math.min(sw,65535);'
    'm.style.backgroundColor="rgb("+(v>>8)+","+(v&255)+",255)";'
    'document.body.appendChild(m);'
    '});</script>'
)

# Lazily computed float32 background color
_bg_f32_cache: Any = None
_LANCZOS = getattr(getattr(_PILImage, "Resampling", _PILImage), "LANCZOS", 1)


def _get_bg_f32() -> "_np.ndarray":
    """Return the background color as a float32 RGBA array (cached)."""
    global _bg_f32_cache
    if _bg_f32_cache is None:
        _bg_f32_cache = (
            _np.array(_BG_COLOR_RGBA, dtype=_np.float32) / _np.float32(255)
        )
    return _bg_f32_cache


# ── Pure helper functions ──────────────────────────────────────

def _inject_helpers(html: str) -> str:
    """Inject CSS reset and JS overflow marker into raw HTML."""
    if "</head>" in html:
        html = html.replace("</head>", _CSS_RESET + "</head>", 1)
    else:
        html = _CSS_RESET + html
    if "</body>" in html:
        html = html.replace("</body>", _OVERFLOW_MARKER + "</body>", 1)
    else:
        html += _OVERFLOW_MARKER
    return html


def _auto_trim(img: "_PILImage.Image") -> "_PILImage.Image":
    """Trim empty background rows from top and bottom of the render.

    Uses vectorized numpy — computes per-row mean deviation from
    the background color across all pixels simultaneously.
    """
    w, h = img.size
    pixels = _np.array(img)
    bg_i16 = _np.array(_BG_COLOR_RGBA, dtype=_np.int16)
    row_diff = _np.abs(
        pixels.astype(_np.int16) - bg_i16,
    ).mean(axis=(1, 2))
    non_bg = _np.where(row_diff > _TRIM_TOLERANCE)[0]
    if len(non_bg) == 0:
        return img.crop((0, 0, w, 1))
    pad = 2
    y0 = max(int(non_bg[0]) - pad, 0)
    y1 = min(int(non_bg[-1]) + pad, h)
    return img.crop((0, y0, w, y1))


def _read_overflow_marker(pixels: "_np.ndarray") -> tuple[bool, int]:
    """Read the JS overflow marker encoded in pixel (3,3).

    The marker encodes DOM scrollWidth as RGB: R = width >> 8,
    G = width & 255, B > 200 indicates a valid marker.
    """
    if pixels.shape[0] < 5 or pixels.shape[1] < 5:
        return False, 0
    b = int(pixels[3, 3, 2])
    if b > 200:
        r, g = int(pixels[3, 3, 0]), int(pixels[3, 3, 1])
        sw = r * 256 + g
        return (sw > 0), sw
    return False, 0


def _clear_marker(arr: "_np.ndarray") -> None:
    """Paint over the marker area with neighboring pixels."""
    s = min(30, arr.shape[0], arr.shape[1])
    h, w = arr.shape[:2]
    if w > s:
        arr[:s, :s] = arr[:s, s:s + 1]
    elif h > s:
        arr[:s, :s] = arr[s:s + 1, :s]


def _get_scaled_doc(
    full_arr: "_np.ndarray",
    current_w: int,
    target_w: int,
    current_h: int,
) -> tuple["_np.ndarray", int, int]:
    """Scale the full render to target width using Lanczos resampling.

    Returns (scaled_array, new_width, new_height).
    """
    if target_w <= 0 or current_w == target_w:
        return full_arr, current_w, current_h
    scale = target_w / current_w
    target_h = max(1, int(current_h * scale))
    img = _PILImage.fromarray(full_arr)
    img_scaled = img.resize((target_w, target_h), _LANCZOS)
    return _np.array(img_scaled, dtype=_np.uint8), target_w, target_h


# ── HTMLRenderer class ─────────────────────────────────────────

class HTMLRenderer:
    """Renders HTML into a scrollable DPG raw_texture via Chrome Headless.

    Accepts HTML from a file path (``open``) or a raw string
    (``open_string``, used by mammoth Word preview).

    The rendering pipeline is:
    1. Read/receive HTML, inject CSS reset and JS overflow marker
    2. Chrome Headless screenshot (with overscan for scrollbar compensation)
    3. Read JS overflow marker — re-render wider if content overflowed
    4. Auto-trim empty background rows from top/bottom (vectorized numpy)
    5. Scale to fit viewport width if document is wider
    6. Copy visible scroll region into raw_texture via ctypes.memmove

    Uses the same generation-counter pattern as PDFRenderer and
    DirectoryIndex to safely cancel stale background renders.
    """

    # Shared Html2Image instance (lazy-initialized, one Chrome config for all)
    _hti: Any = None
    _hti_lock: threading.Lock = threading.Lock()

    def __init__(self, config_tag: str):
        self._config_tag = config_tag
        self._current_path: str = ""
        self._html_content: str = ""

        # Full render from Chrome (after trim, before scaling)
        self._full_array: Any = None
        self._full_w: int = 0
        self._full_h: int = 0

        # Display document (possibly scaled down from full_array)
        self._doc_array: Any = None
        self._doc_w: int = 0
        self._doc_h: int = 0
        self._scroll_y: float = 0

        # DPG raw_texture state (integer IDs, no string aliases)
        self._tex_w: int = 0
        self._tex_h: int = 0
        self._tex_buffer: Any = None
        self._buf_ptr: int | None = None
        self._tex_id: int | None = None
        self._tex_exists: bool = False
        self._viewport_buf: Any = None

        # Render state
        self._render_generation: int = 0
        self._is_rendering: bool = False
        self._min_unclipped_w: int = 0
        self._last_chrome_w: int = 0
        self._last_render_time: float = 0
        self._status_text: str = ""

        # Resize debounce
        self._resize_timer: threading.Timer | None = None

        # Callbacks (invoked inside dpg.mutex)
        self._on_complete: Any = None
        self._on_resize_complete: Any = None

    # ── Properties ────────────────────────────────────────────

    @property
    def is_open(self) -> bool:
        return self._html_content != ""

    @property
    def tex_id(self) -> int | None:
        """DPG integer ID of the raw_texture, or None if not created."""
        return self._tex_id

    @property
    def status_text(self) -> str:
        return self._status_text

    @property
    def is_rendering(self) -> bool:
        return self._is_rendering

    # ── Html2Image singleton ──────────────────────────────────

    @classmethod
    def _get_hti(cls) -> "_Html2Image":
        """Lazily initialize the shared Html2Image instance."""
        if cls._hti is None:
            with cls._hti_lock:
                if cls._hti is None:
                    cls._hti = _Html2Image(
                        output_path=tempfile.gettempdir(),
                        custom_flags=[
                            '--hide-scrollbars',
                            '--force-device-scale-factor=1',
                            '--disable-gpu',
                            '--log-level=3',
                        ],
                        disable_logging=True,
                    )
                    # html2image runs Chrome via subprocess.run() with no
                    # timeout, so a hung browser would block the render thread
                    # forever. Inject a timeout: subprocess.run then kills the
                    # process and raises TimeoutExpired, which _hti_screenshot
                    # turns into a clean render failure.
                    try:
                        cls._hti.browser._subprocess_run_kwargs["timeout"] = _CHROME_TIMEOUT
                    except (AttributeError, TypeError):  # pragma: no cover
                        pass
        return cls._hti

    # ── Open / close ──────────────────────────────────────────

    def open(
        self, path: str, w: int, h: int,
        on_complete=None, on_resize_complete=None,
    ) -> bool:
        """Open an HTML file and start background rendering.

        Args:
            path: Path to the HTML file.
            w: Texture width (full panel width).
            h: Texture height (panel height minus status bar).
            on_complete: Optional callback invoked inside dpg.mutex()
                when the background render finishes.
            on_resize_complete: Optional callback invoked inside dpg.mutex()
                when a debounced resize recreates the texture (caller must
                rebuild image widget with new tex_id).

        Returns True if the file was read and rendering started.
        """
        self.close()

        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                raw_html = f.read()
        except (OSError, PermissionError):
            return False

        self._current_path = path
        self._html_content = _inject_helpers(raw_html)
        self._on_complete = on_complete
        self._on_resize_complete = on_resize_complete
        self._status_text = "Rendering..."

        self._recreate_texture(w, h)
        content_w = max(100, w - 2 * _MARGIN)
        self._start_render(content_w)
        return True

    def open_string(
        self, html_content: str, w: int, h: int,
        on_complete=None, on_resize_complete=None,
    ) -> bool:
        """Open raw HTML content and start background rendering.

        Same as ``open()`` but accepts an HTML string directly instead
        of reading from a file.  Used by mammoth Word preview.

        Returns True if rendering started.
        """
        self.close()

        self._current_path = ""
        self._html_content = _inject_helpers(html_content)
        self._on_complete = on_complete
        self._on_resize_complete = on_resize_complete
        self._status_text = "Rendering..."

        self._recreate_texture(w, h)
        content_w = max(100, w - 2 * _MARGIN)
        self._start_render(content_w)
        return True

    def close(self) -> None:
        """Cancel any background render and release DPG resources."""
        self._render_generation += 1

        if self._resize_timer is not None:
            self._resize_timer.cancel()
            self._resize_timer = None

        if self._tex_exists:
            if self._tex_id is not None and dpg.does_item_exist(self._tex_id):
                dpg.delete_item(self._tex_id)
            self._tex_exists = False
        self._tex_id = None
        self._tex_buffer = None
        self._buf_ptr = None
        self._viewport_buf = None

        self._full_array = None
        self._full_w = 0
        self._full_h = 0
        self._doc_array = None
        self._doc_w = 0
        self._doc_h = 0
        self._scroll_y = 0
        self._min_unclipped_w = 0
        self._last_chrome_w = 0
        self._is_rendering = False
        self._html_content = ""
        self._current_path = ""
        self._on_complete = None
        self._on_resize_complete = None
        self._status_text = ""

    # ── Texture management ────────────────────────────────────

    def _recreate_texture(self, w: int, h: int) -> None:
        """Create or recreate the raw_texture and pre-allocated viewport buffer."""
        if self._tex_exists:
            if self._tex_id is not None and dpg.does_item_exist(self._tex_id):
                dpg.delete_item(self._tex_id)
            self._tex_exists = False

        self._tex_w = max(1, w)
        self._tex_h = max(1, h)

        buf_size = self._tex_w * self._tex_h * 4
        self._tex_buffer = dpg.mvBuffer(buf_size)
        if self._tex_buffer is None:
            raise RuntimeError("Failed to allocate HTML texture buffer")

        bg = _get_bg_f32()
        self._viewport_buf = _np.empty(
            (self._tex_h, self._tex_w, 4), dtype=_np.float32,
        )
        self._viewport_buf[:] = bg

        self._buf_ptr = ctypes.addressof(
            ctypes.c_float.from_buffer(self._tex_buffer),
        )
        ctypes.memmove(
            self._buf_ptr, self._viewport_buf.ctypes.data,
            self._viewport_buf.nbytes,
        )

        with dpg.texture_registry():
            self._tex_id = dpg.add_raw_texture(
                self._tex_w, self._tex_h, self._tex_buffer,
                format=dpg.mvFormat_Float_rgba,
            )
        self._tex_exists = True

    # ── Chrome screenshot ─────────────────────────────────────

    def _hti_screenshot(
        self, width: int, height: int,
    ) -> "_PILImage.Image | None":
        """Take a Chrome Headless screenshot with overscan compensation.

        Renders +20px wider to mask the Windows OS scrollbar reservation
        artifact, then crops the extra width.
        """
        hti = self._get_hti()
        temp_name = f"dpg_html_{uuid.uuid4().hex[:12]}.png"
        target_path = os.path.join(tempfile.gettempdir(), temp_name)
        try:
            hti.screenshot(
                html_str=self._html_content,
                save_as=temp_name,
                size=(width + _OVERSCAN, height),
            )
        except Exception:
            return None
        if not os.path.exists(target_path):
            return None
        img_full = _PILImage.open(target_path)
        img_full.load()
        try:
            os.remove(target_path)
        except OSError:
            pass
        img = img_full.crop((0, 0, width, height))
        img_full.close()
        return img

    # ── Background rendering ──────────────────────────────────

    def _start_render(self, content_w: int) -> None:
        """Start a background Chrome render with a new generation counter."""
        self._render_generation += 1
        self._is_rendering = True
        self._status_text = "Rendering..."
        gen = self._render_generation
        threading.Thread(
            target=self._render_worker,
            args=(content_w, gen),
            daemon=True,
        ).start()

    def _render_worker(self, content_w: int, gen: int) -> None:
        """Background render thread.

        1. Chrome screenshot at content_w (with overscan)
        2. Read JS overflow marker — re-render wider if content overflowed
        3. Clear marker, auto-trim
        4. Scale to viewport width (outside mutex for performance)
        5. Update shared state and texture inside dpg.mutex()
        """
        t0 = time.perf_counter()
        chrome_w = max(content_w, 100)

        img = self._hti_screenshot(chrome_w, _RENDER_H)
        if img is None:
            self._is_rendering = False
            self._status_text = "Render failed"
            with dpg.mutex():
                if self._on_complete and self._render_generation == gen:
                    self._on_complete()
            return
        if self._render_generation != gen:
            img.close()
            self._is_rendering = False
            return

        img_rgba = img.convert("RGBA")
        img.close()
        pixels = _np.array(img_rgba)
        _, scroll_w = _read_overflow_marker(pixels)

        # Re-render if content overflowed the viewport
        if scroll_w > chrome_w + 5:
            img_rgba.close()
            if self._render_generation != gen:
                self._is_rendering = False
                return
            render_w = min(scroll_w + 10, _MAX_RENDER_W)
            img2 = self._hti_screenshot(render_w, _RENDER_H)
            if img2 is None:
                self._is_rendering = False
                self._status_text = "Render failed"
                with dpg.mutex():
                    if self._on_complete and self._render_generation == gen:
                        self._on_complete()
                return
            if self._render_generation != gen:
                img2.close()
                self._is_rendering = False
                return
            img_rgba = img2.convert("RGBA")
            img2.close()
            pixels = _np.array(img_rgba)
            cached_min_w = scroll_w
            chrome_w = render_w
        else:
            cached_min_w = 0

        _clear_marker(pixels)
        img_clean = _PILImage.fromarray(pixels)
        img_rgba.close()
        img_trimmed = _auto_trim(img_clean)
        img_clean.close()

        arr = _np.array(img_trimmed, dtype=_np.uint8)
        raw_w, raw_h = img_trimmed.size
        img_trimmed.close()

        # Heavy scaling done OUTSIDE dpg.mutex() — critical for 60fps
        new_doc_array, new_doc_w, new_doc_h = _get_scaled_doc(
            arr, raw_w, content_w, raw_h,
        )

        elapsed = (time.perf_counter() - t0) * 1000

        with dpg.mutex():
            if self._render_generation != gen:
                self._is_rendering = False
                return
            self._full_array = arr
            self._full_w = raw_w
            self._full_h = raw_h
            self._min_unclipped_w = cached_min_w
            self._last_chrome_w = chrome_w
            self._doc_array = new_doc_array
            self._doc_w = new_doc_w
            self._doc_h = new_doc_h
            self._scroll_y = 0
            self._last_render_time = elapsed
            self._is_rendering = False
            self._update_texture()
            if self._on_complete is not None:
                self._on_complete()

    # ── Texture update ────────────────────────────────────────

    def _update_texture(self) -> None:
        """Copy the visible scroll region from doc_array into the texture buffer.

        Applies horizontal margins and centers the document if narrower
        than the viewport.  Uses pre-allocated viewport_buf to avoid
        per-frame numpy allocations.
        """
        if (self._doc_array is None or self._buf_ptr is None
                or self._viewport_buf is None):
            return

        bg = _get_bg_f32()
        content_w = self._tex_w - 2 * _MARGIN

        max_sy = max(0, self._doc_h - self._tex_h)
        sy = max(0, min(int(self._scroll_y), max_sy))

        copy_h = min(self._tex_h, self._doc_h - sy)
        copy_w = min(content_w, self._doc_w)
        if copy_h <= 0 or copy_w <= 0:
            return

        region = self._doc_array[sy:sy + copy_h, :copy_w]

        self._viewport_buf[:] = bg

        if self._doc_w < content_w:
            pad_x = _MARGIN + (content_w - self._doc_w) // 2
        else:
            pad_x = _MARGIN

        self._viewport_buf[:copy_h, pad_x:pad_x + copy_w] = (
            region.astype(_np.float32) / _np.float32(255)
        )

        ctypes.memmove(
            self._buf_ptr, self._viewport_buf.ctypes.data,
            self._viewport_buf.nbytes,
        )

        # Build status text
        parts = []
        if self._is_rendering:
            parts.append("[Rendering]")
        if self._last_chrome_w > content_w > 0:
            zoom = content_w / self._last_chrome_w
            parts.append(f"Scale: {zoom:.0%}")
        if max_sy > 0:
            parts.append(f"Scroll: {sy}/{max_sy}")
        if self._last_render_time > 0:
            parts.append(f"{self._last_render_time:.0f}ms")
        self._status_text = " | ".join(parts) if parts else "Ready"

    # ── Scroll ────────────────────────────────────────────────

    def on_scroll(self, wheel_delta: float) -> None:
        """Handle mouse wheel scroll.  Positive delta = scroll up."""
        if self._doc_array is None:
            return
        self._scroll_y -= wheel_delta * _SCROLL_SPEED
        max_sy = max(0, self._doc_h - self._tex_h)
        self._scroll_y = max(0.0, min(self._scroll_y, float(max_sy)))
        self._update_texture()

    # ── Resize ────────────────────────────────────────────────

    def on_resize(self, w: int, h: int) -> None:
        """Handle panel resize with fully debounced texture recreation.

        All expensive work (texture recreation, PIL scaling, Chrome re-render)
        is deferred until 0.4s after the last resize event.  During continuous
        drag the old texture stays visible, avoiding main-thread freezes.

        The ``_on_resize_complete`` callback (set in ``open()``) is invoked
        inside ``dpg.mutex()`` when the debounce fires, so the caller can
        rebuild image widgets with the new ``tex_id``.
        """
        if not self.is_open:
            return
        if w == self._tex_w and h == self._tex_h and self._tex_exists:
            return

        if self._resize_timer is not None:
            self._resize_timer.cancel()

        # Capture target dimensions for the closure
        target_w, target_h = w, h

        def _debounced():
            if not self.is_open:
                return
            # Cancel any in-progress render
            self._render_generation += 1
            self._is_rendering = False

            content_w = max(1, target_w - 2 * _MARGIN)

            # Heavy PIL scaling OUTSIDE dpg.mutex() to avoid blocking render
            new_doc = None
            if self._full_array is not None:
                new_doc = _get_scaled_doc(
                    self._full_array, self._full_w, content_w, self._full_h,
                )

            with dpg.mutex():
                if not self.is_open:
                    return
                self._recreate_texture(target_w, target_h)
                if new_doc is not None:
                    self._doc_array, self._doc_w, self._doc_h = new_doc
                    self._scroll_y = 0
                    self._update_texture()
                if self._on_resize_complete is not None:
                    self._on_resize_complete()

            # Chrome re-render if layout is responsive
            if not (self._min_unclipped_w > 0
                    and content_w < self._min_unclipped_w
                    and self._full_array is not None):
                self._start_render(content_w)

        self._resize_timer = threading.Timer(_RESIZE_DEBOUNCE, _debounced)
        self._resize_timer.daemon = True
        self._resize_timer.start()
