"""Tests for image preview size gating (no DearPyGui runtime)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from dpg_navigator._types import FileEntry
from dpg_navigator.renderers.image import ImageRenderer


class TestImageSizeLimit:
    def test_rejects_oversized_file_before_decode(self):
        renderer = ImageRenderer()
        ctx = MagicMock()
        ctx.panel_id = 1
        entry = FileEntry(
            "huge.png",
            "/tmp/huge.png",
            is_dir=False,
            size_bytes=99,
            modified_time=0.0,
            is_hidden=False,
        )
        with patch(
            "dpg_navigator.renderers.image.os.path.getsize",
            return_value=ImageRenderer._MAX_IMAGE_BYTES + 1,
        ), patch("dpg_navigator.renderers.image.dpg") as mock_dpg:
            renderer.render(entry, ctx)

        ctx.show_error.assert_called_once()
        mock_dpg.load_image.assert_not_called()

    def test_thumbnails_before_rgba_convert(self):
        order: list[str] = []

        class _Img:
            mode = "RGB"
            size = (20000, 100)

            def thumbnail(self, _size):
                order.append("thumbnail")
                self.size = (8192, 41)

            def convert(self, mode):
                order.append("convert")
                assert mode == "RGBA"
                assert self.size[0] <= 8192
                converted = MagicMock()
                converted.size = self.size
                converted.tobytes.return_value = b"\x00\x00\x00\xff"
                return converted

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with patch("dpg_navigator.renderers.image._PILImage") as pil:
            pil.open.return_value = _Img()
            width, height, data = ImageRenderer.load_image_pillow("huge.webp")

        assert order == ["thumbnail", "convert"]
        assert width == 8192
        assert height == 41
        assert len(data) >= 4
