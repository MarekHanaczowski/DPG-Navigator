"""Image preview renderer.

Loads a raster into a DearPyGui texture, then draws it on a fixed-size
drawlist so zoom and pan do not depend on the preview pane's scrollbar.
The first view fits the pane without cropping or upscaling; the mouse
wheel zooms toward the cursor, and a left-button drag pans the picture.
"""

from __future__ import annotations  # PEP 604/585 annotations need this on py3.8/3.9

import os
import tempfile
from typing import Any

import dearpygui.dearpygui as dpg  # type: ignore[import-untyped]

from .._optional import OptionalModule, as_optional
from .._preview_limits import (
    IMAGE_PREVIEW_MAX_BYTES,
    PreviewLimitError,
    assert_image_within_limits,
    exceeds_bytes,
    load_preview_rgba,
    probe_image_size,
)
from .._types import FileEntry
from ._base import BaseRenderer, PreviewContext

_PILImage: OptionalModule | None
try:
    from PIL import Image as _PILImage_mod

    _PILImage = as_optional(_PILImage_mod)
except Exception:
    _PILImage = None

# Inset so the drawlist does not sit flush against the preview pane edge.
_PANEL_INSET = 8
_ZOOM_STEP = 1.25
_ZOOM_MIN = 0.25
_ZOOM_MAX = 8.0


def fit_image_to_panel(img_w: int, img_h: int, panel_w: int, panel_h: int) -> tuple[int, int]:
    """Return the display size that fits *img* inside *panel*.

    Preserves aspect ratio, never crops, and never upscales a smaller image.
    """
    if img_w <= 0 or img_h <= 0:
        return 1, 1
    if panel_w <= 0 or panel_h <= 0:
        return img_w, img_h
    scale = min(panel_w / img_w, panel_h / img_h, 1.0)
    return max(1, int(img_w * scale)), max(1, int(img_h * scale))


def next_image_zoom(zoom: float, wheel_delta: float) -> float:
    """Return the zoom factor after one mouse-wheel notch.

    A factor of ``1.0`` is the fitted (contain) size. Positive
    *wheel_delta* (scroll up) zooms in. The result is clamped to
    ``[_ZOOM_MIN, _ZOOM_MAX]``.
    """
    if wheel_delta == 0:
        return zoom
    if wheel_delta > 0:
        zoom *= _ZOOM_STEP
    else:
        zoom /= _ZOOM_STEP
    return min(_ZOOM_MAX, max(_ZOOM_MIN, zoom))


def pan_image_offset(
    start_offset: tuple[float, float],
    start_mouse: tuple[float, float],
    mouse: tuple[float, float],
) -> tuple[float, float]:
    """Return the drawlist offset so the image follows a left-button drag."""
    return (
        start_offset[0] + (mouse[0] - start_mouse[0]),
        start_offset[1] + (mouse[1] - start_mouse[1]),
    )


def zoom_offset_to_cursor(
    offset: tuple[float, float],
    cursor: tuple[float, float],
    scale_ratio: float,
) -> tuple[float, float]:
    """Return a drawlist offset that keeps the pixel under *cursor* fixed.

    *cursor* is in canvas coordinates. The screen-space relation is
    ``cursor = offset + image_point * scale``; after multiplying the scale
    by *scale_ratio* the new offset is solved so that same image point
    stays under the cursor (radial zoom).
    """
    if scale_ratio <= 0:
        return offset
    return (
        cursor[0] - (cursor[0] - offset[0]) * scale_ratio,
        cursor[1] - (cursor[1] - offset[1]) * scale_ratio,
    )


class ImageRenderer(BaseRenderer):
    """Fit a raster into the preview pane and let the user zoom and pan it.

    STB (via ``dpg.load_image``) is used for common formats; Pillow covers
    the rest. Interaction is applied by moving a ``draw_image`` on a
    ``drawlist``, not by resizing a widget or changing child-window scroll.
    """

    _MAX_IMAGE_BYTES = IMAGE_PREVIEW_MAX_BYTES
    """Skip STB/Pillow decode when the file is larger than this."""

    _STB_IMAGE_EXTS = frozenset(
        {
            ".png",
            ".jpg",
            ".jpeg",
            ".bmp",
            ".tga",
            ".gif",
            ".psd",
            ".hdr",
            ".pic",
            ".pgm",
            ".ppm",
            ".pnm",
        }
    )

    def __init__(self) -> None:
        self._ctx: PreviewContext | None = None
        self._img_w = 0
        self._img_h = 0
        self._canvas_id: int | str | None = None
        self._image_id: int | str | None = None
        self._zoom = 1.0
        self._offset = (0.0, 0.0)
        self._panning = False
        self._drag_origin = (0.0, 0.0)
        self._offset_origin = (0.0, 0.0)

    @staticmethod
    def load_image_pillow(path: str) -> tuple[int, int, Any]:
        """Fallback loader using Pillow for unsupported formats."""
        return load_preview_rgba(path)

    def _panel_size(self) -> tuple[int, int]:
        """Return the preview pane size in pixels, or ``(0, 0)`` if unknown."""
        if self._ctx is None or self._ctx.panel_id is None:
            return 0, 0
        try:
            panel_w, panel_h = dpg.get_item_rect_size(self._ctx.panel_id)
        except Exception:
            return 0, 0
        return int(panel_w), int(panel_h)

    def _display_size(self) -> tuple[int, int]:
        """Return the current on-canvas image size (fit × zoom)."""
        panel_w, panel_h = self._panel_size()
        if panel_w > 0:
            panel_w = max(1, panel_w - _PANEL_INSET)
        if panel_h > 0:
            panel_h = max(1, panel_h - _PANEL_INSET)
        fit_w, fit_h = fit_image_to_panel(self._img_w, self._img_h, panel_w, panel_h)
        return max(1, int(fit_w * self._zoom)), max(1, int(fit_h * self._zoom))

    def _canvas_size(self) -> tuple[int, int]:
        """Return the inset drawlist size that fills the preview pane."""
        panel_w, panel_h = self._panel_size()
        return max(1, panel_w - _PANEL_INSET), max(1, panel_h - _PANEL_INSET)

    def _apply_transform(self) -> None:
        """Write the current zoom and pan onto the drawlist image."""
        if self._image_id is None or not dpg.does_item_exist(self._image_id):
            return
        disp_w, disp_h = self._display_size()
        x, y = self._offset
        dpg.configure_item(
            self._image_id,
            pmin=(x, y),
            pmax=(x + disp_w, y + disp_h),
        )

    def _cursor_in_canvas(self) -> tuple[float, float] | None:
        """Return the cursor in canvas coordinates, or ``None`` if unknown.

        Mouse and ``get_item_rect_min`` must both be in viewport space;
        ``get_mouse_pos()`` defaults to window-local coordinates.
        """
        if self._canvas_id is None:
            return None
        try:
            mouse = dpg.get_mouse_pos(local=False)
            origin = dpg.get_item_rect_min(self._canvas_id)
            return (float(mouse[0]) - float(origin[0]), float(mouse[1]) - float(origin[1]))
        except Exception:
            return None

    def render(self, entry: FileEntry, ctx: PreviewContext) -> None:
        """Load *entry* and show it fitted to the pane (zoom and pan reset)."""
        if ctx.panel_id is None:
            return

        try:
            if exceeds_bytes(entry.full_path, self._MAX_IMAGE_BYTES):
                ctx.show_error("Preview unavailable", "File too large for preview")
                return
        except OSError as exc:
            ctx.show_error("Failed to load image", str(exc))
            return

        ext = os.path.splitext(entry.name)[1].lower()
        use_pillow = ext not in self._STB_IMAGE_EXTS

        try:
            probed = probe_image_size(entry.full_path)
            if probed is not None:
                assert_image_within_limits(*probed)
            elif not use_pillow:
                if _PILImage is None:
                    ctx.show_error("Preview unavailable", "Cannot determine image dimensions")
                    return
                use_pillow = True
        except PreviewLimitError as exc:
            ctx.show_error("Preview unavailable", str(exc))
            return

        if use_pillow:
            try:
                img_w, img_h, data = self.load_image_pillow(entry.full_path)
            except Exception as e:
                ctx.show_error("Preview failed", str(e))
                return
        else:
            try:
                img_w, img_h, _, data = dpg.load_image(entry.full_path)
            except Exception:
                try:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                        tmp_path = tmp.name
                    try:
                        import shutil

                        shutil.copy2(entry.full_path, tmp_path)
                        img_w, img_h, _, data = dpg.load_image(tmp_path)
                    finally:
                        try:
                            os.unlink(tmp_path)
                        except OSError:
                            pass
                except Exception as e:
                    ctx.show_error("Failed to load image", str(e))
                    return

        tex_tag = f"_preview_tex_{ctx.config_tag}"
        if dpg.does_item_exist(tex_tag):
            dpg.delete_item(tex_tag)

        with dpg.texture_registry():
            dpg.add_static_texture(width=img_w, height=img_h, default_value=data, tag=tex_tag)

        self._ctx = ctx
        self._img_w = img_w
        self._img_h = img_h
        self._zoom = 1.0
        self._offset = (0.0, 0.0)
        self._panning = False
        ctx.image_cache = (img_w, img_h, tex_tag)
        disp_w, disp_h = self._display_size()
        canvas_w, canvas_h = self._canvas_size()
        self._canvas_id = dpg.add_drawlist(
            width=canvas_w,
            height=canvas_h,
            parent=ctx.panel_id,
        )
        self._image_id = dpg.draw_image(
            tex_tag,
            pmin=(0.0, 0.0),
            pmax=(float(disp_w), float(disp_h)),
            parent=self._canvas_id,
        )

    def on_resize(self, sender: Any, app_data: Any, user_data: Any) -> None:
        """Resize the canvas with the pane; keep the current zoom and pan."""
        if self._panning:
            return
        if self._canvas_id is not None and dpg.does_item_exist(self._canvas_id):
            canvas_w, canvas_h = self._canvas_size()
            dpg.configure_item(self._canvas_id, width=canvas_w, height=canvas_h)
        self._apply_transform()

    def on_mouse_down(self, sender: Any, app_data: Any, user_data: Any) -> None:
        """Start a left-button pan from the current viewport mouse position."""
        if self._image_id is None:
            return
        try:
            mouse = dpg.get_mouse_pos(local=False)
        except Exception:
            return
        self._panning = True
        self._drag_origin = (float(mouse[0]), float(mouse[1]))
        self._offset_origin = self._offset

    def on_mouse_drag(self, sender: Any, app_data: Any, user_data: Any) -> bool:
        """Pan the picture with the cursor. ``True`` if a pan is in progress."""
        if not self._panning:
            return False
        try:
            mouse = dpg.get_mouse_pos(local=False)
        except Exception:
            return True
        self._offset = pan_image_offset(
            self._offset_origin,
            self._drag_origin,
            (float(mouse[0]), float(mouse[1])),
        )
        self._apply_transform()
        return True

    def on_mouse_up(self, sender: Any, app_data: Any, user_data: Any) -> None:
        """End a left-button pan."""
        self._panning = False

    def on_mouse_wheel(self, sender: Any, app_data: Any, user_data: Any) -> None:
        """Zoom toward the cursor; scroll up enlarges, scroll down shrinks."""
        try:
            delta = float(app_data)
        except (TypeError, ValueError):
            return
        if delta == 0 or self._image_id is None:
            return
        old_zoom = self._zoom
        cursor = self._cursor_in_canvas()
        self._zoom = next_image_zoom(self._zoom, delta)
        if self._zoom == old_zoom:
            return
        if cursor is not None:
            self._offset = zoom_offset_to_cursor(
                self._offset,
                cursor,
                self._zoom / old_zoom,
            )
        self._apply_transform()

    def clear(self) -> None:
        """Drop widget ids and view state; the panel deletes the drawlist."""
        self._ctx = None
        self._img_w = 0
        self._img_h = 0
        self._canvas_id = None
        self._image_id = None
        self._zoom = 1.0
        self._offset = (0.0, 0.0)
        self._panning = False
