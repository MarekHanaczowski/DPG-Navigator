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
