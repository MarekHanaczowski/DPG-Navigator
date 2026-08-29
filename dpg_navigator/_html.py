"""Safe and trusted HTML rendering for the preview panel.

Safe mode sanitizes HTML structurally and adds a restrictive CSP before a
per-render Chrome session sees it. Trusted mode is an explicit opt-in for raw
``.html``/``.htm`` files and keeps browser fidelity while retaining resource
limits, the Chrome sandbox, subprocess ownership, and an isolated profile.
"""

from __future__ import annotations

# MIT licensed
import ctypes
import html
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from concurrent.futures import Future
from dataclasses import dataclass
from pathlib import Path
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

_bleach: OptionalModule | None
try:
    import bleach as _bleach_mod

    _bleach = as_optional(_bleach_mod)
except Exception:  # required dep; fail closed if unavailable or incompatible
    _bleach = None


def html_available() -> bool:
    """Return True if all HTML preview dependencies are installed."""
    return _Html2Image is not None and _np is not None and _PILImage is not None and _bleach is not None


_chrome_available_cache: bool | None = None
_chrome_executable_cache: str | None = None


def chrome_available() -> bool:
    """Return True if a Chrome/Chromium binary is resolvable for rendering.

    ``html_available()`` only checks the Python packages; html2image still
    needs a browser binary. Lookup order starts with ``DPG_CHROME_BIN``,
    ``CHROME_BIN``, and ``CHROME_PATH``, then checks platform-specific Chrome
    locations. POSIX validation uses a bounded subprocess probe and no temporary
    profile. The result is cached.
    """
    global _chrome_available_cache, _chrome_executable_cache
    if _chrome_available_cache is not None:
        return _chrome_available_cache
    if not html_available():
        _chrome_available_cache = False
        return False
    try:
        _chrome_executable_cache = _discover_chrome_executable()
    except Exception:
        _log.debug("Chrome availability probe failed", exc_info=True)
        _chrome_executable_cache = None
    _chrome_available_cache = _chrome_executable_cache is not None
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
_CHROME_PROBE_TIMEOUT: float = 5.0
"""Maximum seconds spent validating a Chrome binary on POSIX."""

_chrome_owner = threading.local()
_chromium_run_patched = False


def _resolve_chrome_executable() -> str | None:
    """Return an explicit Chrome binary from the environment, if set.

    html2image only honors ``CHROME_BIN`` when a separate toggle var is set.
    CI and hosts can pass ``DPG_CHROME_BIN`` (preferred), ``CHROME_BIN``, or
    ``CHROME_PATH`` instead.
    """
    for key in ("DPG_CHROME_BIN", "CHROME_BIN", "CHROME_PATH"):
        raw = os.environ.get(key)
        if not raw:
            continue
        path = os.path.expanduser(raw.strip())
        if os.path.isfile(path):
            return path
        located = shutil.which(path)
        if located:
            return located
    return None


def _validate_chrome_executable(candidate: str) -> str | None:
    """Return a usable Chrome path, bounding POSIX ``--version`` probes."""
    path = candidate if os.path.isfile(candidate) else shutil.which(candidate)
    if path is None:
        return None
    if os.name == "nt":
        return path
    try:
        completed = subprocess.run(
            [path, "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=_CHROME_PROBE_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = completed.stdout.decode("utf-8", errors="replace").lower()
    return path if completed.returncode == 0 and "chrom" in output else None


def _discover_chrome_executable() -> str | None:
    """Find Chrome without invoking html2image's unbounded executable search."""
    explicit = _resolve_chrome_executable()
    if explicit is not None:
        return _validate_chrome_executable(explicit)

    candidates: list[str] = []
    if os.name == "nt":
        for prefix in (
            os.environ.get("PROGRAMFILES(X86)"),
            os.environ.get("PROGRAMFILES"),
            os.environ.get("LOCALAPPDATA"),
        ):
            if prefix:
                candidates.append(os.path.join(prefix, "Google", "Chrome", "Application", "chrome.exe"))
    elif sys.platform == "darwin":
        candidates.extend(
            [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Chromium.app/Contents/MacOS/Chromium",
            ]
        )
    else:
        candidates.extend(
            [
                "chrome-headless-shell",
                "chromium",
                "chromium-browser",
                "google-chrome",
                "google-chrome-stable",
                "chrome",
            ]
        )
    for candidate in candidates:
        validated = _validate_chrome_executable(candidate)
        if validated is not None:
            return validated
    return None


def _is_headless_shell(executable: str | None) -> bool:
    """Return True if *executable* is Chrome's old-headless screenshot binary."""
    if not executable:
        return False
    return "headless-shell" in os.path.basename(executable).lower()


def _chrome_custom_flags(
    profile_dir: str,
    *,
    crash_dir: str | None = None,
    trusted: bool = False,
) -> list[str]:
    """Return Chrome flags for one isolated safe or trusted render.

    The dead proxy is ``127.0.0.1:1`` without extra quotes: a quoted value
    becomes part of argv on POSIX, and port 0 can stall connect(). Port 1
    is almost always connection-refused, so subresource loads fail fast.
    ``--proxy-bypass-list=<-loopback>`` disables Chrome's default exclusion
    of localhost, so loopback HTTP also hits that dead proxy. ``file://``
    is not an HTTP proxy hop (html2image writes a temp HTML file).

    ``DPG_CHROME_NO_SANDBOX=1`` adds container flags (``--no-sandbox``,
    ``--no-zygote``, …) for CI where the sandbox cannot start. Not the
    default — those flags weaken process isolation. ``--disable-gpu`` is
    omitted there: it hangs ``--screenshot`` on Chrome for Testing + xvfb.
    """
    flags = [
        "--hide-scrollbars",
        "--force-device-scale-factor=1",
        "--log-level=3",
        "--block-new-web-contents",
        f"--user-data-dir={profile_dir}",
        f"--crash-dumps-dir={crash_dir or profile_dir}",
    ]
    if not trusted:
        flags.extend(
            [
                "--proxy-server=http://127.0.0.1:1",
                "--proxy-bypass-list=<-loopback>",
                "--disable-background-networking",
                "--disable-component-update",
                "--disable-domain-reliability",
                "--disable-sync",
                "--dns-prefetch-disable",
                "--metrics-recording-only",
            ]
        )
    if os.environ.get("DPG_CHROME_NO_SANDBOX") == "1":
        flags.extend(
            [
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--no-zygote",
                "--no-first-run",
                "--virtual-time-budget=10000",
            ]
        )
    else:
        flags.insert(2, "--disable-gpu")
    return flags


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
            _log.warning(
                "Chrome screenshot timed out after %.0fs (%s)",
                timeout,
                command[0] if isinstance(command, list) and command else command,
            )
            _kill_process_tree(proc)
            try:
                proc.communicate(timeout=2.0)
            except Exception:
                pass
            raise
        if proc.returncode:
            raise subprocess.CalledProcessError(
                proc.returncode,
                command,
                output=stdout,
                stderr=stderr,
            )
        return subprocess.CompletedProcess(command, proc.returncode, stdout, stderr)
    finally:
        HTMLRenderer._unregister_chrome(proc)


_CSS_RESET_TEXT = (
    "html,body{margin:0!important;padding:0!important;}html::-webkit-scrollbar{width:0!important;height:0!important;}"
)
_SAFE_LAYOUT_CSS = (
    "html,body{background:#1a1a1a;color:#e0e0e0;max-width:100%;"
    "overflow-wrap:anywhere;word-break:break-word;}"
    "*,*::before,*::after{box-sizing:border-box;}"
    "img,video,canvas,svg,table,pre,blockquote{max-width:100%;}"
    "img{height:auto;}"
    "pre{white-space:pre-wrap;overflow-wrap:anywhere;}"
    "table{table-layout:fixed;}"
    ".safe-wrapper{padding:10px;}"
)
_SAFE_CSP = (
    "default-src 'none'; "
    "base-uri 'none'; "
    "connect-src 'none'; "
    "font-src 'none'; "
    "form-action 'none'; "
    "frame-src 'none'; "
    "img-src data:; "
    "media-src 'none'; "
    "object-src 'none'; "
    "script-src 'none'; "
    "style-src 'unsafe-inline'; "
    "worker-src 'none'"
)
_SAFE_HTML_TAGS = frozenset(
    {
        "abbr",
        "b",
        "blockquote",
        "br",
        "caption",
        "code",
        "col",
        "colgroup",
        "dd",
        "del",
        "details",
        "div",
        "dl",
        "dt",
        "em",
        "figcaption",
        "figure",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "i",
        "img",
        "kbd",
        "li",
        "mark",
        "ol",
        "p",
        "pre",
        "q",
        "s",
        "samp",
        "small",
        "span",
        "strong",
        "sub",
        "summary",
        "sup",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "tr",
        "u",
        "ul",
        "var",
    }
)
_SAFE_GLOBAL_ATTRIBUTES = frozenset({"class", "dir", "id", "lang", "title"})
_SAFE_TAG_ATTRIBUTES: dict[str, frozenset[str]] = {
    "col": frozenset({"span", "width"}),
    "colgroup": frozenset({"span", "width"}),
    "img": frozenset({"alt", "height", "src", "width"}),
    "ol": frozenset({"reversed", "start", "type"}),
    "td": frozenset({"colspan", "rowspan"}),
    "th": frozenset({"colspan", "rowspan", "scope"}),
}
_SAFE_DATA_IMAGE_PREFIXES = (
    "data:image/gif;base64,",
    "data:image/jpeg;base64,",
    "data:image/png;base64,",
    "data:image/webp;base64,",
)


def _is_safe_data_image(value: str) -> bool:
    """Return whether *value* is an explicitly allowed embedded raster image."""
    return value.strip().lower().startswith(_SAFE_DATA_IMAGE_PREFIXES)


def _allow_safe_attribute(tag: str, name: str, value: str) -> bool:
    """Bleach attribute callback for the safe preview allow-list."""
    if name in _SAFE_GLOBAL_ATTRIBUTES:
        return True
    if name not in _SAFE_TAG_ATTRIBUTES.get(tag, frozenset()):
        return False
    if tag == "img" and name == "src":
        return _is_safe_data_image(value)
    if name in {"height", "span", "start", "width", "colspan", "rowspan"}:
        stripped = value.strip()
        return stripped.isdigit() and int(stripped) <= 100000
    return True


def _sanitize_html_fragment(html: str) -> str:
    """Sanitize an untrusted HTML fragment using an HTML5 parser allow-list."""
    bleach = require_optional(_bleach, "bleach")
    return str(
        bleach.clean(
            html,
            tags=_SAFE_HTML_TAGS,
            attributes=_allow_safe_attribute,
            protocols=frozenset({"data"}),
            strip=True,
            strip_comments=True,
        )
    )


def _prepare_safe_document(html: str, *, css: str = "", wrapper_class: str = "safe-wrapper") -> str:
    """Build a complete safe document with policy metadata before content."""
    if not wrapper_class.replace("-", "").isalnum():
        raise ValueError("wrapper_class must contain only letters, digits, and hyphens")
    sanitized = _sanitize_html_fragment(html)
    controlled_css = _CSS_RESET_TEXT + _SAFE_LAYOUT_CSS + css
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        f'<meta http-equiv="Content-Security-Policy" content="{_SAFE_CSP}">'
        f"<style>{controlled_css}</style></head><body>"
        f'<div class="{wrapper_class}">{sanitized}</div>'
        "</body></html>"
    )


_CSS_RESET = f"<style>{_CSS_RESET_TEXT}</style>"

# Trusted mode only: encode DOM width and height plus a two-pixel signature.
# The complete marker fits in the top-left 10x10 region cleared after capture.
_OVERFLOW_MARKER = (
    '<script>window.addEventListener("load",function(){'
    "function p(x,y,v){var e=document.createElement('i');"
    "e.style.cssText='position:fixed;left:'+x+'px;top:'+y+'px;width:1px;height:1px;"
    "z-index:2147483647;pointer-events:none;background:rgb('+(v>>8)+','+(v&255)+',255)';"
    "document.body.appendChild(e);}"
    "var d=document.documentElement,b=document.body;"
    "var sw=Math.max(d.scrollWidth,b.scrollWidth,d.offsetWidth,b.offsetWidth);"
    "var sh=Math.max(d.scrollHeight,b.scrollHeight,d.offsetHeight,b.offsetHeight);"
    "p(3,3,Math.min(sw,65535));p(3,4,Math.min(sh,65535));"
    "var s=document.createElement('i');"
    "s.style.cssText='position:fixed;left:4px;top:3px;width:1px;height:1px;"
    "z-index:2147483647;pointer-events:none;background:rgb(17,34,51)';"
    "document.body.appendChild(s);"
    "});</script>"
)


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


def _inject_helpers(html_text: str, *, base_href: str | None = None) -> str:
    """Inject renderer-owned helpers into explicitly trusted raw HTML."""
    lower = html_text.lower()
    base = ""
    if base_href is not None and "<base" not in lower:
        base = f'<base href="{html.escape(base_href, quote=True)}">'
    head_end = lower.find("</head>")
    if head_end >= 0:
        html_text = html_text[:head_end] + base + _CSS_RESET + html_text[head_end:]
    else:
        html_text = base + _CSS_RESET + html_text
    lower = html_text.lower()
    body_end = lower.find("</body>")
    if body_end >= 0:
        html_text = html_text[:body_end] + _OVERFLOW_MARKER + html_text[body_end:]
    else:
        html_text += _OVERFLOW_MARKER
    return html_text


def _auto_trim(img: Any) -> Any:
    """Trim empty background rows from top and bottom of the render.

    A row remains content when even a sparse pixel differs from the background.
    A second exact-difference pass preserves low-contrast dark content while
    still reducing a genuinely blank render to one pixel.
    """
    np = require_optional(_np, "numpy")
    w, h = img.size
    pixels = np.array(img)
    bg_i16 = np.array(_BG_COLOR_RGBA, dtype=np.int16)
    row_diff = np.abs(pixels.astype(np.int16) - bg_i16).max(axis=(1, 2))
    non_bg = np.where(row_diff > _TRIM_TOLERANCE)[0]
    if len(non_bg) == 0:
        non_bg = np.where(row_diff > 0)[0]
    if len(non_bg) == 0:
        return img.crop((0, 0, w, 1))
    pad = 2
    y0 = max(int(non_bg[0]) - pad, 0)
    y1 = min(int(non_bg[-1]) + pad + 1, h)
    return img.crop((0, y0, w, y1))


def _read_overflow_marker(pixels: Any) -> tuple[bool, int, int]:
    """Read the trusted-mode marker encoded in a signed 2x2 pixel pattern.

    Pixel (3,3) stores DOM width, (3,4) stores DOM height, and (4,3)
    contains the exact RGB signature (17, 34, 51).
    """
    if pixels.shape[0] < 5 or pixels.shape[1] < 5:
        return False, 0, 0
    if tuple(int(value) for value in pixels[3, 4, :3]) != (17, 34, 51):
        return False, 0, 0
    if int(pixels[3, 3, 2]) != 255 or int(pixels[4, 3, 2]) != 255:
        return False, 0, 0
    scroll_w = int(pixels[3, 3, 0]) * 256 + int(pixels[3, 3, 1])
    scroll_h = int(pixels[4, 3, 0]) * 256 + int(pixels[4, 3, 1])
    return (scroll_w > 0 and scroll_h > 0), scroll_w, scroll_h


def _clear_marker(arr: Any) -> None:
    """Paint over exactly the renderer-owned 10x10 marker area."""
    s = min(10, arr.shape[0], arr.shape[1])
    h, w = arr.shape[:2]
    if w > s:
        arr[:s, :s] = arr[:s, s : s + 1]
    elif h > s:
        arr[:s, :s] = arr[s : s + 1, :s]


def _looks_vertically_clipped(pixels: Any) -> bool:
    """Best-effort safe-mode clipping check without executing JavaScript."""
    np = require_optional(_np, "numpy")
    if pixels.shape[0] < 4:
        return False
    bg_i16 = np.array(_BG_COLOR_RGBA, dtype=np.int16)
    bottom = pixels[-4:].astype(np.int16)
    return bool(np.abs(bottom - bg_i16).max() > 0)


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
    try:
        img_scaled = img.resize((target_w, target_h), _LANCZOS)
        try:
            scaled = np.array(img_scaled, dtype=np.uint8)
        finally:
            img_scaled.close()
    finally:
        img.close()
    return scaled, target_w, target_h


@dataclass(frozen=True)
class _ChromeSession:
    """One isolated html2image instance and its temporary directory."""

    hti: Any
    temp_dir: Any
    output_path: str

    def cleanup(self) -> None:
        self.temp_dir.cleanup()


@dataclass(frozen=True)
class _PendingRender:
    """Immutable worker output applied by the DPG frame poll."""

    generation: int
    full_array: Any
    full_width: int
    full_height: int
    doc_array: Any
    doc_width: int
    doc_height: int
    chrome_width: int
    elapsed_ms: float
    vertically_clipped: bool
    error: str | None = None


@dataclass(frozen=True)
class _PendingResize:
    """Immutable debounced resize output applied by the DPG frame poll."""

    request_id: int
    width: int
    height: int
    content_width: int
    scaled_doc: tuple[Any, int, int] | None


# ── HTMLRenderer class ─────────────────────────────────────────


class HTMLRenderer:
    """Renders HTML into a scrollable DPG raw_texture via Chrome Headless.

    ``open()`` renders files in safe mode unless ``trusted=True`` is explicitly
    passed. ``open_string()`` is always safe and is used for Markdown and Word.
    Workers only run Chrome/Pillow/numpy; all DPG state is applied by a frame
    callback while holding the DPG mutex.

    The rendering pipeline is:
    1. Sanitize and wrap untrusted input, or inject trusted-only helpers.
    2. Create an isolated temporary Chrome session for this render.
    3. Screenshot, optionally widening from the signed trusted marker.
    4. Auto-trim, scale, and queue an immutable result.
    5. Apply the result and update the texture in the serialized frame callback.

    Uses the same generation-counter pattern as PDFRenderer and
    DirectoryIndex to safely cancel stale background renders.
    """

    _chrome_proc_lock: threading.Lock = threading.Lock()
    _chrome_procs: list[tuple[Any, Any]] = []
    _poll_targets: list[HTMLRenderer] = []
    _poll_armed: bool = False

    def __init__(self, config_tag: str) -> None:
        self._config_tag = config_tag
        self._current_path: str = ""
        self._html_content: str = ""
        self._trusted: bool = False

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
        self._last_chrome_w: int = 0
        self._last_render_time: float = 0
        self._vertically_clipped: bool = False
        self._status_text: str = ""
        self._pending_lock = threading.Lock()
        self._pending_render: _PendingRender | None = None
        self._pending_resize: _PendingResize | None = None

        # Resize debounce (JobManager.schedule_timer returns a TimerTask)
        self._resize_timer: TimerTask | None = None
        self._resize_generation: int = 0
        self._resize_waiting: bool = False

        # Callbacks are invoked by the DPG frame poll.
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

    # ── Chrome process ownership and DPG frame poll ───────────

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
    def _create_chrome_session(cls, *, trusted: bool) -> _ChromeSession:
        """Create one isolated html2image/profile session for one render."""
        html2image = require_optional(_Html2Image, "html2image")
        _ensure_chromium_run_hook()
        temp_dir = tempfile.TemporaryDirectory(prefix="dpg_nav_chrome_")
        try:
            output_dir = os.path.join(temp_dir.name, "output")
            input_dir = os.path.join(temp_dir.name, "input")
            profile_dir = os.path.join(temp_dir.name, "profile")
            crash_dir = os.path.join(temp_dir.name, "crash")
            for path in (output_dir, input_dir, profile_dir, crash_dir):
                os.makedirs(path)
            chrome_bin = _chrome_executable_cache or _discover_chrome_executable()
            if chrome_bin is None:
                raise FileNotFoundError("Chrome/Chromium executable not found")
            hti_kwargs: dict[str, Any] = {
                "output_path": output_dir,
                "temp_path": input_dir,
                "custom_flags": _chrome_custom_flags(profile_dir, crash_dir=crash_dir, trusted=trusted),
                "browser_executable": chrome_bin,
                # CI: keep Chrome stderr so a hung screenshot is diagnosable.
                "disable_logging": os.environ.get("DPG_CHROME_NO_SANDBOX") != "1",
            }
            hti = html2image(**hti_kwargs)
            # chrome-headless-shell wants plain --headless rather than
            # html2image's newer full-Chrome switch.
            exe = chrome_bin or str(getattr(hti.browser, "executable", "") or "")
            try:
                if _is_headless_shell(exe):
                    hti.browser.use_new_headless = None
                else:
                    hti.browser.use_new_headless = True
            except (AttributeError, TypeError):  # pragma: no cover
                pass
            try:
                hti.browser._subprocess_run_kwargs["timeout"] = _CHROME_TIMEOUT
            except (AttributeError, TypeError):  # pragma: no cover
                pass
        except Exception:
            temp_dir.cleanup()
            raise
        return _ChromeSession(hti=hti, temp_dir=temp_dir, output_path=output_dir)

    def _arm_poll(self) -> None:
        """Register this renderer for polling from the DPG thread."""
        cls = type(self)
        if self not in cls._poll_targets:
            cls._poll_targets.append(self)
        if cls._poll_armed:
            return
        cls._poll_armed = True
        dpg.set_frame_callback(dpg.get_frame_count() + 1, cls._poll_frame)

    def _unregister_poll(self) -> None:
        cls = type(self)
        cls._poll_targets = [item for item in cls._poll_targets if item is not self]

    @classmethod
    def _poll_frame(cls, sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
        """Apply worker results and schedule the next DPG-thread poll."""
        del sender, app_data, user_data
        cls._poll_armed = False
        remaining: list[HTMLRenderer] = []
        for renderer in list(cls._poll_targets):
            try:
                # DearPyGui dispatches frame callbacks on its callback thread.
                # DPG >= 2.2 fixes the historical mutex/GIL inversion, so this
                # serializes texture writes with delete_item/render safely.
                with dpg.mutex():
                    renderer._apply_pending()
            except Exception:
                _log.exception("Applying an HTML preview result failed")
                renderer._is_rendering = False
                renderer._resize_waiting = False
                renderer._status_text = "Render failed"
            if renderer._poll_needed():
                remaining.append(renderer)
        cls._poll_targets = remaining
        if remaining:
            cls._poll_armed = True
            dpg.set_frame_callback(dpg.get_frame_count() + 1, cls._poll_frame)

    def _poll_needed(self) -> bool:
        with self._pending_lock:
            has_pending = self._pending_render is not None or self._pending_resize is not None
        return self.is_open and (has_pending or self._is_rendering or self._resize_waiting)

    def _queue_render_result(self, result: _PendingRender) -> None:
        """Publish a render result without calling DearPyGui."""
        with self._pending_lock:
            if result.generation == self._render_generation and self.is_open:
                self._pending_render = result

    def _queue_resize_result(self, result: _PendingResize) -> None:
        """Publish a resize result without calling DearPyGui."""
        with self._pending_lock:
            if result.request_id == self._resize_generation and self.is_open:
                self._pending_resize = result

    # ── Open / close ──────────────────────────────────────────

    def open(
        self,
        path: str,
        w: int,
        h: int,
        on_complete: Callable[..., Any] | None = None,
        on_resize_complete: Callable[..., Any] | None = None,
        *,
        trusted: bool = False,
    ) -> bool:
        """Open an HTML file and start a safe or explicitly trusted render.

        Args:
            path: Path to the HTML file.
            w: Texture width (full panel width).
            h: Texture height (panel height minus status bar).
            on_complete: Optional callback invoked from the serialized frame
                callback when the background render finishes.
            on_resize_complete: Optional serialized callback after resize.
            trusted: Preserve raw HTML behavior, including scripts and resource
                loads. This is intended only for an explicit user opt-in.

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
        raw_html = raw_bytes.decode("utf-8-sig", errors="replace")
        try:
            if trusted:
                base_href = Path(path).resolve().parent.as_uri().rstrip("/") + "/"
                html_content = _inject_helpers(raw_html, base_href=base_href)
            else:
                html_content = _prepare_safe_document(raw_html)
        except Exception:
            _log.exception("Preparing HTML preview failed")
            self._status_text = "Cannot prepare safe HTML preview"
            return False

        self._current_path = path
        self._html_content = html_content
        self._trusted = trusted
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
        *,
        css: str = "",
        wrapper_class: str = "safe-wrapper",
    ) -> bool:
        """Open an HTML fragment using the mandatory safe policy.

        Used by Markdown and mammoth Word preview. There is intentionally no
        trusted option on this entry point.

        Returns True if rendering started.
        """
        self.close()

        if len(html_content.encode("utf-8", errors="replace")) > _MAX_HTML_BYTES:
            self._status_text = "Content too large for preview"
            return False
        try:
            prepared = _prepare_safe_document(html_content, css=css, wrapper_class=wrapper_class)
        except Exception:
            _log.exception("Preparing generated HTML preview failed")
            self._status_text = "Cannot prepare safe HTML preview"
            return False

        self._current_path = ""
        self._html_content = prepared
        self._trusted = False
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
        self._resize_generation += 1
        self._cancel_render_future()
        type(self)._kill_owned_chrome(self)
        self._unregister_poll()

        if self._resize_timer is not None:
            JobManager.cancel_timer(self._resize_timer)
            self._resize_timer = None
        self._resize_waiting = False
        with self._pending_lock:
            self._pending_render = None
            self._pending_resize = None

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
        self._last_chrome_w = 0
        self._last_render_time = 0
        self._vertically_clipped = False
        self._is_rendering = False
        self._html_content = ""
        self._trusted = False
        self._current_path = ""
        self._on_complete = None
        self._on_resize_complete = None
        self._status_text = ""

    @classmethod
    def shutdown_shared(cls) -> None:
        """Kill any in-flight Chrome subprocesses after the last dialog closes."""
        cls._kill_owned_chrome(None)
        with cls._chrome_proc_lock:
            cls._chrome_procs.clear()
        cls._poll_targets.clear()
        cls._poll_armed = False
        global _chrome_available_cache, _chrome_executable_cache
        _chrome_available_cache = None
        _chrome_executable_cache = None

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
        session: _ChromeSession,
        html_content: str,
        width: int,
        height: int,
        generation: int,
    ) -> Any:
        """Take a Chrome Headless screenshot with overscan compensation.

        Renders +20px wider to mask the Windows OS scrollbar reservation
        artifact, then crops the extra width.
        """
        temp_name = f"dpg_html_{uuid.uuid4().hex[:12]}.png"
        target_path = os.path.join(session.output_path, temp_name)
        _chrome_owner.renderer = self
        _chrome_owner.generation = generation
        try:
            session.hti.screenshot(
                html_str=html_content,
                save_as=temp_name,
                size=(width + _OVERSCAN, height),
            )
        finally:
            _chrome_owner.renderer = None
            _chrome_owner.generation = None
        if not os.path.exists(target_path):
            raise RuntimeError("Chrome did not create the requested screenshot")
        pil = require_optional(_PILImage, "Pillow")
        try:
            img_full = pil.open(target_path)
            try:
                img_full.load()
                return img_full.crop((0, 0, width, height))
            finally:
                img_full.close()
        finally:
            try:
                os.remove(target_path)
            except OSError:
                pass

    # ── Background rendering ──────────────────────────────────

    def _start_render(self, content_w: int) -> None:
        """Start a background Chrome render with a new generation counter."""
        self._cancel_render_future()
        self._render_generation += 1
        type(self)._kill_owned_chrome(self)
        self._is_rendering = True
        self._status_text = "Rendering..."
        gen = self._render_generation
        self._arm_poll()
        self._render_future = JobManager.submit(
            self._render_worker,
            content_w,
            gen,
            self._html_content,
            self._trusted,
        )

    def _render_worker(self, content_w: int, gen: int, html_content: str, trusted: bool) -> None:
        """Render with Chrome/Pillow/numpy and queue a DPG-free result."""
        t0 = time.perf_counter()
        chrome_w = max(content_w, 100)
        session: _ChromeSession | None = None
        try:
            np = require_optional(_np, "numpy")
            pil = require_optional(_PILImage, "Pillow")
            if self._render_generation != gen:
                return
            session = self._create_chrome_session(trusted=trusted)
            img = self._hti_screenshot(session, html_content, chrome_w, _RENDER_H, gen)
            try:
                if self._render_generation != gen:
                    raise _ChromeCancelled()
                img_rgba = img.convert("RGBA")
            finally:
                img.close()

            pixels = np.array(img_rgba)
            marker_present = False
            scroll_w = 0
            scroll_h = 0
            if trusted:
                marker_present, scroll_w, scroll_h = _read_overflow_marker(pixels)

            if marker_present and scroll_w > chrome_w + 5:
                img_rgba.close()
                render_w = min(scroll_w + 10, _MAX_RENDER_W)
                img2 = self._hti_screenshot(session, html_content, render_w, _RENDER_H, gen)
                try:
                    if self._render_generation != gen:
                        raise _ChromeCancelled()
                    img_rgba = img2.convert("RGBA")
                finally:
                    img2.close()
                pixels = np.array(img_rgba)
                marker_present, _second_w, scroll_h = _read_overflow_marker(pixels)
                chrome_w = render_w

            if marker_present:
                _clear_marker(pixels)
            vertically_clipped = scroll_h > _RENDER_H if marker_present else _looks_vertically_clipped(pixels)
            img_clean = pil.fromarray(pixels)
            img_rgba.close()
            try:
                img_trimmed = _auto_trim(img_clean)
            finally:
                img_clean.close()
            try:
                arr = np.array(img_trimmed, dtype=np.uint8)
                raw_w, raw_h = img_trimmed.size
            finally:
                img_trimmed.close()

            new_doc_array, new_doc_w, new_doc_h = _get_scaled_doc(
                arr,
                raw_w,
                content_w,
                raw_h,
            )
            elapsed = (time.perf_counter() - t0) * 1000
            self._queue_render_result(
                _PendingRender(
                    generation=gen,
                    full_array=arr,
                    full_width=raw_w,
                    full_height=raw_h,
                    doc_array=new_doc_array,
                    doc_width=new_doc_w,
                    doc_height=new_doc_h,
                    chrome_width=chrome_w,
                    elapsed_ms=elapsed,
                    vertically_clipped=vertically_clipped,
                )
            )
        except _ChromeCancelled:
            pass
        except Exception:
            _log.exception("HTML preview render failed")
            self._queue_render_result(
                _PendingRender(
                    generation=gen,
                    full_array=None,
                    full_width=0,
                    full_height=0,
                    doc_array=None,
                    doc_width=0,
                    doc_height=0,
                    chrome_width=0,
                    elapsed_ms=(time.perf_counter() - t0) * 1000,
                    vertically_clipped=False,
                    error="Render failed",
                )
            )
        finally:
            if session is not None:
                session.cleanup()

    def _apply_pending(self) -> None:
        """Apply queued results while the frame poll holds the DPG mutex."""
        with self._pending_lock:
            pending_resize = self._pending_resize
            pending_render = self._pending_render
            self._pending_resize = None
            self._pending_render = None
        if pending_resize is not None:
            self._apply_resize_result(pending_resize)
        if pending_render is not None:
            self._apply_render_result(pending_render)

    def _apply_render_result(self, result: _PendingRender) -> None:
        if result.generation != self._render_generation or not self.is_open:
            return
        self._render_future = None
        self._is_rendering = False
        self._last_render_time = result.elapsed_ms
        if result.error is not None:
            self._status_text = result.error
            if self._on_complete is not None:
                self._on_complete()
            return
        self._full_array = result.full_array
        self._full_w = result.full_width
        self._full_h = result.full_height
        self._doc_array = result.doc_array
        self._doc_w = result.doc_width
        self._doc_h = result.doc_height
        self._last_chrome_w = result.chrome_width
        self._vertically_clipped = result.vertically_clipped
        self._scroll_y = 0
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
        if self._vertically_clipped:
            parts.append(f"Clipped at {_RENDER_H}px")
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
        with dpg.mutex():
            self._update_texture()

    # ── Resize ────────────────────────────────────────────────

    def on_resize(self, w: int, h: int) -> None:
        """Debounce scaling on a worker and apply texture changes via the poll."""
        if not self.is_open:
            return
        if w == self._tex_w and h == self._tex_h and self._tex_exists:
            return

        if self._resize_timer is not None:
            JobManager.cancel_timer(self._resize_timer)

        target_w, target_h = w, h
        content_w = max(1, target_w - 2 * _MARGIN)
        self._resize_generation += 1
        request_id = self._resize_generation
        self._resize_waiting = True
        full_array = self._full_array
        full_w = self._full_w
        full_h = self._full_h
        self._arm_poll()

        def _debounced() -> None:
            scaled_doc = None
            try:
                if full_array is not None:
                    scaled_doc = _get_scaled_doc(full_array, full_w, content_w, full_h)
            except Exception:
                _log.exception("Scaling an HTML preview for resize failed")
            self._queue_resize_result(
                _PendingResize(
                    request_id=request_id,
                    width=target_w,
                    height=target_h,
                    content_width=content_w,
                    scaled_doc=scaled_doc,
                )
            )

        self._resize_timer = JobManager.schedule_timer(_RESIZE_DEBOUNCE, _debounced)

    def _apply_resize_result(self, result: _PendingResize) -> None:
        """Apply a debounced resize under the DPG mutex and start a fresh render."""
        if result.request_id != self._resize_generation or not self.is_open:
            return
        self._resize_timer = None
        self._resize_waiting = False
        self._render_generation += 1
        self._cancel_render_future()
        type(self)._kill_owned_chrome(self)
        self._is_rendering = False
        self._recreate_texture(result.width, result.height)
        if result.scaled_doc is not None:
            self._doc_array, self._doc_w, self._doc_h = result.scaled_doc
            self._scroll_y = 0
            self._update_texture()
        if self._on_resize_complete is not None:
            self._on_resize_complete()
        if self.is_open:
            self._start_render(result.content_width)
