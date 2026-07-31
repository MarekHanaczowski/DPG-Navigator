"""Image preview renderer."""
from __future__ import annotations  # PEP 604/585 annotations need this on py3.8/3.9

import os
import tempfile
import array
from typing import Any, cast
import dearpygui.dearpygui as dpg  # type: ignore[import-untyped]

from ._base import BaseRenderer, PreviewContext
from .._types import FileEntry

try:
    from PIL import Image as _PILImage
except Exception:
    _PILImage = cast(Any, None)

class ImageRenderer(BaseRenderer):
    """Render raster images through DearPyGui or Pillow fallback loading."""

    _STB_IMAGE_EXTS = frozenset({
        ".png", ".jpg", ".jpeg", ".bmp", ".tga",
        ".gif", ".psd", ".hdr", ".pic", ".pgm", ".ppm", ".pnm",
    })

    @staticmethod
    def load_image_pillow(path: str) -> tuple[int, int, Any]:
        """Fallback loader using Pillow for unsupported formats."""
        if _PILImage is None:
            raise RuntimeError("Pillow is not installed or unavailable.")
        with _PILImage.open(path) as img:
            if img.mode != 'RGBA':
                img = img.convert('RGBA')
            img_w, img_h = img.size
            if img_w > 8192 or img_h > 8192:
                img.thumbnail((8192, 8192))
                img_w, img_h = img.size
            raw_data = img.tobytes()
            # Normalize to 0.0-1.0 float array expected by DPG
            float_data = array.array('f', (b / 255.0 for b in raw_data))
            return img_w, img_h, float_data

    def render(self, entry: FileEntry, ctx: PreviewContext) -> None:
        """Load an image and add its texture to the preview panel."""
        if ctx.panel_id is None:
            return

        ext = os.path.splitext(entry.name)[1].lower()
        use_pillow = ext not in self._STB_IMAGE_EXTS

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
            dpg.add_static_texture(
                width=img_w,
                height=img_h,
                default_value=data,
                tag=tex_tag
            )
            
        ctx.image_cache = (img_w, img_h, tex_tag)
        dpg.add_image(tex_tag, parent=ctx.panel_id)

    def clear(self) -> None:
        """Leave texture cleanup to the shared preview context and panel."""
