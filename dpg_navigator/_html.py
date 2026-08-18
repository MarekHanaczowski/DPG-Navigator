"""HTML rendering support for the preview panel.

Uses html2image (Chrome Headless) + numpy + Pillow for rendering
HTML files into a scrollable DPG raw_texture with background rendering,
auto-trim, overflow detection, and responsive scaling.
"""

from __future__ import annotations

# MIT licensed
import ctypes
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from concurrent.futures import Future
from typing import Any, Callable

import dearpygui.dearpygui as dpg  # type: ignore[import-untyped]

from ._job_manager import JobManager, TimerTask
from ._optional import OptionalModule, as_optional, require_optional

_log = logging.getLogger(__name__)

_Html2Image: OptionalModule | None
try:
    from html2image import Html2Image as _Html2Image_cls  # type: ignore[import-untyped]

    _Html2Image = as_optional(_Html2Image_cls)
except Exception:  # optional backend absent or incompatible (e.g. old Python)
    _Html2Image = None

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

try:
    import psutil as _psutil  # type: ignore[import-untyped]
except Exception:  # required dep; still degrade to Popen.kill()
    _psutil = None


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
_MAX_HTML_BYTES: int = 2 * 1024 * 1024
"""Reject HTML/Markdown sources larger than this before spawning Chrome."""
_CHROME_TIMEOUT: float = 30.0
"""Seconds before a hung Chrome screenshot subprocess is killed."""

_chrome_owner = threading.local()
_chromium_run_patched = False


class _ChromeCancelled(Exception):
    """Raised when a screenshot is aborted because the preview closed."""


class _ChromiumSubprocessProxy:
    """Replace html2image's ``chromium.subprocess`` without touching stdlib."""

    def run(self, *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        return _chrome_popen_run(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(subprocess, name)


def _ensure_chromium_run_hook() -> None:
    """Route html2image Chrome launches through ``_chrome_popen_run``."""
    global _chromium_run_patched
    if _chromium_run_patched:
        return
    try:
        import html2image.browsers.chromium as chromium_mod  # type: ignore[import-untyped]
    except Exception:
        return
    chromium_mod.subprocess = _ChromiumSubprocessProxy()
    _chromium_run_patched = True


def _kill_process_tree(proc: Any) -> None:
    """Kill *proc* and its children (headless Chrome is multi-process)."""
    poll = getattr(proc, "poll", None)
    if callable(poll) and poll() is not None:
        return
    pid = getattr(proc, "pid", None)
    if _psutil is not None and pid is not None:
        try:
            parent = _psutil.Process(pid)
            victims = parent.children(recursive=True)
            victims.append(parent)
            for victim in victims:
                try:
                    victim.kill()
                except Exception:
                    pass
            _psutil.wait_procs(victims, timeout=1.0)
        except Exception:
            _log.debug("psutil Chrome process-tree kill failed", exc_info=True)
    try:
        if not callable(poll) or proc.poll() is None:
            proc.kill()
    except OSError:
        pass
    try:
        proc.wait(timeout=1.0)
    except Exception:
        pass


def _chrome_popen_run(
    command: Any,
    *args: Any,
    **kwargs: Any,
) -> subprocess.CompletedProcess[Any]:
    """``subprocess.run`` stand-in that records Popen so close() can kill it."""
    if args:
        raise TypeError("chrome run hook does not take extra positional args")
    timeout = kwargs.pop("timeout", _CHROME_TIMEOUT)
    kwargs.pop("check", None)
    owner = getattr(_chrome_owner, "renderer", None)
    gen = getattr(_chrome_owner, "generation", None)
    if owner is not None and owner._render_generation != gen:
        raise _ChromeCancelled()
    proc = subprocess.Popen(command, **kwargs)
    if owner is not None:
        HTMLRenderer._register_chrome(proc, owner)
    try:
        if owner is not None and owner._render_generation != gen:
            _kill_process_tree(proc)
            raise _ChromeCancelled()
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_process_tree(proc)
            stdout, stderr = proc.communicate()
            raise
        return subprocess.CompletedProcess(command, proc.returncode, stdout, stderr)
    finally:
        HTMLRenderer._unregister_chrome(proc)


_CSS_RESET = (
    "<style>"
    "html,body{margin:0!important;padding:0!important;}"
    "html::-webkit-scrollbar{width:0!important;height:0!important;}"
    "</style>"
)

# Encodes DOM scrollWidth into pixel (3,3). Inert while Chrome is launched
# with --disable-javascript (production flags). Kept so a wider re-render
# can still run if that flag is ever dropped.
_OVERFLOW_MARKER = (
    '<script>window.addEventListener("load",function(){'
    'var m=document.createElement("div");'
    'm.style.cssText="position:fixed;top:0;left:0;width:10px;height:10px;'
    'z-index:999999;pointer-events:none;";'
    "var sw=Math.max(document.documentElement.scrollWidth,"
    "document.body.scrollWidth,document.documentElement.offsetWidth,"
    "document.body.offsetWidth);"
    "var v=Math.min(sw,65535);"
    'm.style.backgroundColor="rgb("+(v>>8)+","+(v&255)+",255)";'
    "document.body.appendChild(m);"
    "});</script>"
)

_FILE_ATTR_RE = re.compile(
    r"""(?ix)
    (\s(?:src|href|poster|data)\s*=\s*)
    (["'])file:.*?\2
    """
)
_FILE_CSS_RE = re.compile(r"""(?i)url\(\s*(["']?)file:[^)]*\)""")


def _strip_file_urls(html: str) -> str:
    """Drop file: URLs so Chrome cannot be pointed at local paths."""
    html = _FILE_ATTR_RE.sub(r"\1\2\2", html)
    return _FILE_CSS_RE.sub("url()", html)


# Lazily computed float32 background color
_bg_f32_cache: Any = None
_LANCZOS: Any = 1
if _PILImage is not None:
    _LANCZOS = getattr(getattr(_PILImage, "Resampling", _PILImage), "LANCZOS", 1)


def _get_bg_f32() -> Any:
    """Return the background color as a float32 RGBA array (cached)."""
    global _bg_f32_cache
    np = require_optional(_np, "numpy")
    if _bg_f32_cache is None:
        _bg_f32_cache = np.array(_BG_COLOR_RGBA, dtype=np.float32) / np.float32(255)
    return _bg_f32_cache


# ── Pure helper functions ──────────────────────────────────────


def _inject_helpers(html: str) -> str:
    """Inject CSS reset and JS overflow marker into raw HTML.

    The marker does not run under the default ``--disable-javascript`` flag.
    Local ``file:`` URLs are stripped before Chrome sees the document.
    """
    html = _strip_file_urls(html)
    if "</head>" in html:
        html = html.replace("</head>", _CSS_RESET + "</head>", 1)
    else:
        html = _CSS_RESET + html
    if "</body>" in html:
        html = html.replace("</body>", _OVERFLOW_MARKER + "</body>", 1)
    else:
        html += _OVERFLOW_MARKER
    return html


def _auto_trim(img: Any) -> Any:
    """Trim empty background rows from top and bottom of the render.

    Uses vectorized numpy — computes per-row mean deviation from
    the background color across all pixels simultaneously.
    """
    np = require_optional(_np, "numpy")
    w, h = img.size
    pixels = np.array(img)
    bg_i16 = np.array(_BG_COLOR_RGBA, dtype=np.int16)
    row_diff = np.abs(
        pixels.astype(np.int16) - bg_i16,
    ).mean(axis=(1, 2))
    non_bg = np.where(row_diff > _TRIM_TOLERANCE)[0]
    if len(non_bg) == 0:
        return img.crop((0, 0, w, 1))
    pad = 2
    y0 = max(int(non_bg[0]) - pad, 0)
    y1 = min(int(non_bg[-1]) + pad, h)
    return img.crop((0, y0, w, y1))


def _read_overflow_marker(pixels: Any) -> tuple[bool, int]:
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


def _clear_marker(arr: Any) -> None:
    """Paint over the marker area with neighboring pixels."""
    s = min(30, arr.shape[0], arr.shape[1])
    h, w = arr.shape[:2]
    if w > s:
        arr[:s, :s] = arr[:s, s : s + 1]
    elif h > s:
        arr[:s, :s] = arr[s : s + 1, :s]


def _get_scaled_doc(
    full_arr: Any,
    current_w: int,
    target_w: int,
    current_h: int,
) -> tuple[Any, int, int]:
    """Scale the full render to target width using Lanczos resampling.

    Returns (scaled_array, new_width, new_height).
    """
    if target_w <= 0 or current_w == target_w:
        return full_arr, current_w, current_h
    np = require_optional(_np, "numpy")
    pil = require_optional(_PILImage, "Pillow")
    scale = target_w / current_w
    target_h = max(1, int(current_h * scale))
    img = pil.fromarray(full_arr)
    img_scaled = img.resize((target_w, target_h), _LANCZOS)
    return np.array(img_scaled, dtype=np.uint8), target_w, target_h


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
    _chrome_profile_dir: str | None = None
    _chrome_proc_lock: threading.Lock = threading.Lock()
    _chrome_procs: list[tuple[Any, Any]] = []

    def __init__(self, config_tag: str) -> None:
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
        self._render_future: Future[Any] | None = None
        self._is_rendering: bool = False
        self._min_unclipped_w: int = 0
        self._last_chrome_w: int = 0
        self._last_render_time: float = 0
        self._status_text: str = ""

        # Resize debounce (JobManager.schedule_timer returns a TimerTask)
        self._resize_timer: TimerTask | None = None

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
    def _register_chrome(cls, proc: Any, owner: Any) -> None:
        with cls._chrome_proc_lock:
            cls._chrome_procs.append((proc, owner))

    @classmethod
    def _unregister_chrome(cls, proc: Any) -> None:
        with cls._chrome_proc_lock:
            cls._chrome_procs = [item for item in cls._chrome_procs if item[0] is not proc]

    @classmethod
    def _kill_owned_chrome(cls, owner: Any | None) -> None:
        """Kill tracked Chrome processes. ``owner=None`` kills all."""
        with cls._chrome_proc_lock:
            if owner is None:
                victims = [proc for proc, _owner in cls._chrome_procs]
            else:
                victims = [proc for proc, item_owner in cls._chrome_procs if item_owner is owner]
        for proc in victims:
            _kill_process_tree(proc)

    @classmethod
    def _get_hti(cls) -> Any:
        """Lazily initialize the shared Html2Image instance."""
        html2image = require_optional(_Html2Image, "html2image")
        _ensure_chromium_run_hook()
        if cls._hti is None:
            with cls._hti_lock:
                if cls._hti is None:
                    profile_dir = tempfile.mkdtemp(prefix="dpg_nav_chrome_")
                    cls._chrome_profile_dir = profile_dir
                    cls._hti = html2image(
                        output_path=profile_dir,
                        custom_flags=[
                            "--hide-scrollbars",
                            "--force-device-scale-factor=1",
                            "--disable-gpu",
                            "--log-level=3",
                            # JS off: untrusted HTML must not run. The injected
                            # overflow marker is therefore a no-op (see A06).
                            "--disable-javascript",
                            '--proxy-server="http://127.0.0.1:0"',
                            "--block-new-web-contents",
                            f"--user-data-dir={profile_dir}",
                        ],
                        disable_logging=True,
                    )
                    # html2image has no timeout; our Popen hook honors this
                    # value and close()/shutdown_shared() can kill earlier.
                    try:
                        cls._hti.browser._subprocess_run_kwargs["timeout"] = _CHROME_TIMEOUT
                    except (AttributeError, TypeError):  # pragma: no cover
                        pass
        return cls._hti

    # ── Open / close ──────────────────────────────────────────

    def open(
        self,
        path: str,
        w: int,
        h: int,
        on_complete: Callable[..., Any] | None = None,
        on_resize_complete: Callable[..., Any] | None = None,
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
            with open(path, "rb") as f:
                raw_bytes = f.read(_MAX_HTML_BYTES + 1)
        except (OSError, PermissionError):
            return False
        if len(raw_bytes) > _MAX_HTML_BYTES:
            self._status_text = "File too large for preview"
            return False
        raw_html = raw_bytes.decode("utf-8", errors="replace")

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
        self,
        html_content: str,
        w: int,
        h: int,
        on_complete: Callable[..., Any] | None = None,
        on_resize_complete: Callable[..., Any] | None = None,
    ) -> bool:
        """Open raw HTML content and start background rendering.

        Same as ``open()`` but accepts an HTML string directly instead
        of reading from a file.  Used by mammoth Word preview.

        Returns True if rendering started.
        """
        self.close()

        if len(html_content.encode("utf-8", errors="replace")) > _MAX_HTML_BYTES:
            self._status_text = "Content too large for preview"
            return False

        self._current_path = ""
        self._html_content = _inject_helpers(html_content)
        self._on_complete = on_complete
        self._on_resize_complete = on_resize_complete
        self._status_text = "Rendering..."

        self._recreate_texture(w, h)
        content_w = max(100, w - 2 * _MARGIN)
        self._start_render(content_w)
        return True

    def _cancel_render_future(self) -> None:
        """Drop a queued Chrome render so a worker never starts it."""
        fut = self._render_future
        self._render_future = None
        if fut is not None:
            fut.cancel()

    def close(self) -> None:
        """Cancel any background render, kill this preview's Chrome, release DPG."""
        self._render_generation += 1
        self._cancel_render_future()
        type(self)._kill_owned_chrome(self)

        if self._resize_timer is not None:
            JobManager.cancel_timer(self._resize_timer)
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

    @classmethod
    def shutdown_shared(cls) -> None:
        """Drop the shared Html2Image singleton after the last dialog closes.

        Kills any in-flight Chrome child processes first so the session
        profile directory can be removed without racing a live browser.
        """
        cls._kill_owned_chrome(None)
        with cls._chrome_proc_lock:
            cls._chrome_procs.clear()
        with cls._hti_lock:
            cls._hti = None
            profile_dir = cls._chrome_profile_dir
            cls._chrome_profile_dir = None
        if profile_dir:
            shutil.rmtree(profile_dir, ignore_errors=True)
        global _chrome_available_cache
        _chrome_available_cache = None

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

        np = require_optional(_np, "numpy")
        bg = _get_bg_f32()
        self._viewport_buf = np.empty(
            (self._tex_h, self._tex_w, 4),
            dtype=np.float32,
        )
        self._viewport_buf[:] = bg

        self._buf_ptr = ctypes.addressof(
            ctypes.c_float.from_buffer(self._tex_buffer),
        )
        ctypes.memmove(
            self._buf_ptr,
            self._viewport_buf.ctypes.data,
            self._viewport_buf.nbytes,
        )

        with dpg.texture_registry():
            self._tex_id = dpg.add_raw_texture(
                self._tex_w,
                self._tex_h,
                self._tex_buffer,
                format=dpg.mvFormat_Float_rgba,
            )
        self._tex_exists = True

    # ── Chrome screenshot ─────────────────────────────────────

    def _hti_screenshot(
        self,
        width: int,
        height: int,
    ) -> Any | None:
        """Take a Chrome Headless screenshot with overscan compensation.

        Renders +20px wider to mask the Windows OS scrollbar reservation
        artifact, then crops the extra width.
        """
        hti = self._get_hti()
        temp_name = f"dpg_html_{uuid.uuid4().hex[:12]}.png"
        out_dir = getattr(hti, "output_path", None) or type(self)._chrome_profile_dir or tempfile.gettempdir()
        target_path = os.path.join(str(out_dir), temp_name)
        _chrome_owner.renderer = self
        _chrome_owner.generation = self._render_generation
        try:
            hti.screenshot(
                html_str=self._html_content,
                save_as=temp_name,
                size=(width + _OVERSCAN, height),
            )
        except Exception:
            return None
        finally:
            _chrome_owner.renderer = None
            _chrome_owner.generation = None
        if not os.path.exists(target_path):
            return None
        pil = require_optional(_PILImage, "Pillow")
        img_full = pil.open(target_path)
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
        self._cancel_render_future()
        self._render_generation += 1
        type(self)._kill_owned_chrome(self)
        self._is_rendering = True
        self._status_text = "Rendering..."
        gen = self._render_generation
        self._render_future = JobManager.submit(self._render_worker, content_w, gen)

    def _render_worker(self, content_w: int, gen: int) -> None:
        """Background render thread.

        1. Chrome screenshot at content_w (with overscan)
        2. Read JS overflow marker — re-render wider if content overflowed
        3. Clear marker, auto-trim
        4. Scale to viewport width (outside mutex for performance)
        5. Update shared state and texture inside dpg.mutex()
        """
        np = require_optional(_np, "numpy")
        pil = require_optional(_PILImage, "Pillow")
        t0 = time.perf_counter()
        chrome_w = max(content_w, 100)

        if self._render_generation != gen:
            self._is_rendering = False
            return

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
        pixels = np.array(img_rgba)
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
            pixels = np.array(img_rgba)
            cached_min_w = scroll_w
            chrome_w = render_w
        else:
            cached_min_w = 0

        _clear_marker(pixels)
        img_clean = pil.fromarray(pixels)
        img_rgba.close()
        img_trimmed = _auto_trim(img_clean)
        img_clean.close()

        arr = np.array(img_trimmed, dtype=np.uint8)
        raw_w, raw_h = img_trimmed.size
        img_trimmed.close()

        # Heavy scaling done OUTSIDE dpg.mutex() — critical for 60fps
        new_doc_array, new_doc_w, new_doc_h = _get_scaled_doc(
            arr,
            raw_w,
            content_w,
            raw_h,
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
        if self._doc_array is None or self._buf_ptr is None or self._viewport_buf is None:
            return

        np = require_optional(_np, "numpy")
        bg = _get_bg_f32()
        content_w = self._tex_w - 2 * _MARGIN

        max_sy = max(0, self._doc_h - self._tex_h)
        sy = max(0, min(int(self._scroll_y), max_sy))

        copy_h = min(self._tex_h, self._doc_h - sy)
        copy_w = min(content_w, self._doc_w)
        if copy_h <= 0 or copy_w <= 0:
            return

        region = self._doc_array[sy : sy + copy_h, :copy_w]

        self._viewport_buf[:] = bg

        if self._doc_w < content_w:
            pad_x = _MARGIN + (content_w - self._doc_w) // 2
        else:
            pad_x = _MARGIN

        self._viewport_buf[:copy_h, pad_x : pad_x + copy_w] = region.astype(np.float32) / np.float32(255)

        ctypes.memmove(
            self._buf_ptr,
            self._viewport_buf.ctypes.data,
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
            JobManager.cancel_timer(self._resize_timer)

        # Capture target dimensions for the closure
        target_w, target_h = w, h

        def _debounced() -> None:
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
                    self._full_array,
                    self._full_w,
                    content_w,
                    self._full_h,
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
            if not (self._min_unclipped_w > 0 and content_w < self._min_unclipped_w and self._full_array is not None):
                self._start_render(content_w)

        self._resize_timer = JobManager.schedule_timer(_RESIZE_DEBOUNCE, _debounced)
