"""Tests for image preview limits, fit-to-pane, cursor-anchored zoom, and pan."""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from dpg_navigator._preview_limits import IMAGE_PREVIEW_TEXTURE_MAX_DIMENSION, PreviewRaster, load_preview_raster
from dpg_navigator._types import FileEntry
from dpg_navigator.renderers.image import (
    _ZOOM_MAX,
    _ZOOM_MIN,
    ImageRenderer,
    fit_image_to_panel,
    next_image_zoom,
    pan_image_offset,
    zoom_offset_to_cursor,
)


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
        with (
            patch(
                "dpg_navigator.renderers.image.os.path.getsize",
                return_value=ImageRenderer._MAX_IMAGE_BYTES + 1,
            ),
            patch("dpg_navigator.renderers.image.dpg") as mock_dpg,
        ):
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

        with patch("dpg_navigator._preview_limits._PILImage") as pil:
            pil.open.return_value = _Img()
            width, height, data = ImageRenderer.load_image_pillow("huge.webp")

        assert order == ["thumbnail", "convert"]
        assert width == 8192
        assert height == 41
        assert len(data) >= 4

    def test_stb_path_skips_decode_when_header_is_huge(self):
        renderer = ImageRenderer()
        ctx = MagicMock()
        ctx.panel_id = 1
        entry = FileEntry(
            "bomb.png",
            "/tmp/bomb.png",
            is_dir=False,
            size_bytes=100,
            modified_time=0.0,
            is_hidden=False,
        )
        with (
            patch("dpg_navigator.renderers.image.exceeds_bytes", return_value=False),
            patch(
                "dpg_navigator.renderers.image.probe_image_size",
                return_value=(30000, 30000),
            ),
            patch("dpg_navigator.renderers.image.dpg") as mock_dpg,
        ):
            renderer.render(entry, ctx)
        ctx.show_error.assert_called_once()
        mock_dpg.load_image.assert_not_called()


class TestFitImageToPanel:
    def test_downscales_wide_image_to_panel(self):
        assert fit_image_to_panel(1200, 800, 300, 400) == (300, 200)

    def test_downscales_tall_image_to_panel(self):
        assert fit_image_to_panel(400, 1200, 300, 400) == (133, 400)

    def test_does_not_upscale_small_image(self):
        assert fit_image_to_panel(80, 60, 300, 400) == (80, 60)

    def test_unknown_panel_keeps_native_size(self):
        assert fit_image_to_panel(640, 480, 0, 0) == (640, 480)

    def test_invalid_image_falls_back_to_one_pixel(self):
        assert fit_image_to_panel(0, 10, 100, 100) == (1, 1)


class TestImageFitsPanel:
    def _entry(self) -> FileEntry:
        return FileEntry(
            "plot.png",
            "/tmp/plot.png",
            is_dir=False,
            size_bytes=100,
            modified_time=0.0,
            is_hidden=False,
        )

    def test_add_image_uses_fitted_display_size(self):
        renderer = ImageRenderer()
        ctx = MagicMock()
        ctx.panel_id = 1
        ctx.config_tag = "dlg"
        with (
            patch("dpg_navigator.renderers.image.exceeds_bytes", return_value=False),
            patch("dpg_navigator.renderers.image.probe_image_size", return_value=(1200, 800)),
            patch.object(
                ImageRenderer, "load_image_preview", return_value=PreviewRaster(1200, 800, 1200, 800, [0.0] * 16)
            ),
            patch("dpg_navigator.renderers.image.dpg") as mock_dpg,
        ):
            mock_dpg.get_item_rect_size.return_value = (308, 408)
            mock_dpg.does_item_exist.return_value = False
            mock_dpg.add_drawlist.return_value = 88
            mock_dpg.draw_image.return_value = 99
            renderer.render(self._entry(), ctx)

        mock_dpg.add_drawlist.assert_called_once_with(width=300, height=400, parent=1)
        mock_dpg.draw_image.assert_called_once_with(
            "_preview_tex_dlg",
            pmin=(0.0, 0.0),
            pmax=(300.0, 200.0),
            parent=88,
        )
        assert renderer._canvas_id == 88
        assert renderer._image_id == 99

    def test_on_resize_reconfigures_display_size(self):
        renderer = ImageRenderer()
        renderer._ctx = MagicMock()
        renderer._ctx.panel_id = 1
        renderer._img_w = 1200
        renderer._img_h = 800
        renderer._canvas_id = 88
        renderer._image_id = 99
        with patch("dpg_navigator.renderers.image.dpg") as mock_dpg:
            mock_dpg.does_item_exist.return_value = True
            mock_dpg.get_item_rect_size.return_value = (208, 408)
            renderer.on_resize(None, None, None)
        assert mock_dpg.configure_item.call_args_list == [
            ((88,), {"width": 200, "height": 400}),
            ((99,), {"pmin": (0.0, 0.0), "pmax": (200.0, 133.0)}),
        ]

    def test_wheel_up_enlarges_display(self):
        renderer = ImageRenderer()
        renderer._ctx = MagicMock()
        renderer._ctx.panel_id = 1
        renderer._img_w = 1200
        renderer._img_h = 800
        renderer._image_id = 99
        renderer._zoom = 1.0
        with patch("dpg_navigator.renderers.image.dpg") as mock_dpg:
            mock_dpg.does_item_exist.return_value = True
            mock_dpg.get_item_rect_size.return_value = (308, 408)
            renderer.on_mouse_wheel(None, 1.0, None)
        assert renderer._zoom == next_image_zoom(1.0, 1.0)
        mock_dpg.configure_item.assert_called_once_with(
            99,
            pmin=(0.0, 0.0),
            pmax=(375.0, 250.0),
        )

    def test_wheel_down_shrinks_and_clamps(self):
        renderer = ImageRenderer()
        renderer._ctx = MagicMock()
        renderer._ctx.panel_id = 1
        renderer._img_w = 100
        renderer._img_h = 100
        renderer._image_id = 99
        renderer._zoom = _ZOOM_MIN
        with patch("dpg_navigator.renderers.image.dpg") as mock_dpg:
            mock_dpg.does_item_exist.return_value = True
            mock_dpg.get_item_rect_size.return_value = (308, 408)
            renderer.on_mouse_wheel(None, -1.0, None)
        assert renderer._zoom == _ZOOM_MIN

    def test_wheel_keeps_point_under_cursor(self):
        renderer = ImageRenderer()
        renderer._ctx = MagicMock()
        renderer._ctx.panel_id = 1
        renderer._img_w = 1200
        renderer._img_h = 800
        renderer._canvas_id = 88
        renderer._image_id = 99
        renderer._zoom = 1.0
        with patch("dpg_navigator.renderers.image.dpg") as mock_dpg:
            mock_dpg.does_item_exist.return_value = True
            mock_dpg.get_item_rect_size.return_value = (308, 408)
            mock_dpg.get_item_rect_min.return_value = (100.0, 50.0)
            mock_dpg.get_mouse_pos.return_value = (250.0, 150.0)
            renderer.on_mouse_wheel(None, 1.0, None)
        # Fitted 300x200 → 375x250; cursor in pane is (150, 100)
        mock_dpg.get_mouse_pos.assert_called_once_with(local=False)
        mock_dpg.configure_item.assert_called_once_with(
            99,
            pmin=(-37.5, -25.0),
            pmax=(337.5, 225.0),
        )


class TestNextImageZoom:
    def test_scroll_up_zooms_in(self):
        assert next_image_zoom(1.0, 1.0) == 1.25

    def test_scroll_down_zooms_out(self):
        assert next_image_zoom(1.25, -1.0) == 1.0

    def test_clamps_to_max(self):
        assert next_image_zoom(_ZOOM_MAX, 1.0) == _ZOOM_MAX

    def test_clamps_to_min(self):
        assert next_image_zoom(_ZOOM_MIN, -1.0) == _ZOOM_MIN

    def test_zero_delta_is_noop(self):
        assert next_image_zoom(2.0, 0.0) == 2.0


class TestZoomOffsetToCursor:
    def test_zoom_in_shifts_scroll_to_hold_cursor_point(self):
        assert zoom_offset_to_cursor((0.0, 0.0), (150.0, 100.0), 1.25) == (-37.5, -25.0)

    def test_zoom_out_moves_offset_toward_cursor(self):
        assert zoom_offset_to_cursor((-50.0, -25.0), (100.0, 75.0), 0.8) == (-20.0, -5.0)

    def test_invalid_ratio_keeps_offset(self):
        assert zoom_offset_to_cursor((5.0, 6.0), (1.0, 1.0), 0.0) == (5.0, 6.0)


class TestPanImageOffset:
    def test_drag_right_moves_image_right(self):
        assert pan_image_offset((100.0, 40.0), (10.0, 20.0), (40.0, 25.0)) == (130.0, 45.0)

    def test_drag_left_moves_image_left(self):
        assert pan_image_offset((0.0, 0.0), (50.0, 50.0), (20.0, 10.0)) == (-30.0, -40.0)


class TestImagePan:
    def _renderer(self) -> ImageRenderer:
        renderer = ImageRenderer()
        renderer._ctx = MagicMock()
        renderer._ctx.panel_id = 7
        renderer._image_id = 99
        renderer._img_w = 100
        renderer._img_h = 100
        return renderer

    def test_drag_updates_scroll_from_click_origin(self):
        renderer = self._renderer()
        with patch("dpg_navigator.renderers.image.dpg") as mock_dpg:
            mock_dpg.get_mouse_pos.return_value = (10.0, 20.0)
            renderer.on_mouse_down(None, None, None)
            mock_dpg.get_mouse_pos.return_value = (40.0, 10.0)
            mock_dpg.does_item_exist.return_value = True
            mock_dpg.get_item_rect_size.return_value = (108, 108)
            handled = renderer.on_mouse_drag(None, None, None)
        assert handled is True
        assert mock_dpg.get_mouse_pos.call_args_list == [
            ((), {"local": False}),
            ((), {"local": False}),
        ]
        assert renderer._offset == (30.0, -10.0)
        mock_dpg.configure_item.assert_called_once_with(
            99,
            pmin=(30.0, -10.0),
            pmax=(130.0, 90.0),
        )

    def test_drag_ignored_before_mouse_down(self):
        renderer = self._renderer()
        with patch("dpg_navigator.renderers.image.dpg") as mock_dpg:
            assert renderer.on_mouse_drag(None, None, None) is False
        mock_dpg.set_x_scroll.assert_not_called()

    def test_resize_skipped_while_panning(self):
        renderer = self._renderer()
        renderer._panning = True
        with patch("dpg_navigator.renderers.image.dpg") as mock_dpg:
            mock_dpg.does_item_exist.return_value = True
            renderer.on_resize(None, None, None)
        mock_dpg.configure_item.assert_not_called()

    def test_mouse_up_ends_pan(self):
        renderer = self._renderer()
        renderer._panning = True
        renderer.on_mouse_up(None, None, None)
        assert renderer._panning is False


class TestTextureCap:
    """The worker shrinks big pictures; layout and the reported size stay the source size."""

    @staticmethod
    def _entry(path: str) -> FileEntry:
        return FileEntry(
            os.path.basename(path),
            path,
            is_dir=False,
            size_bytes=100,
            modified_time=0.0,
            is_hidden=False,
        )

    @staticmethod
    def _ctx() -> Any:
        ctx = MagicMock()
        ctx.panel_id = 1
        ctx.config_tag = "cap"
        ctx.image_cache = None
        return ctx

    @staticmethod
    def _finish(renderer: ImageRenderer, entry: FileEntry, ctx: Any) -> MagicMock:
        """Run the worker job with DearPyGui unreachable, then the finish step on a mock."""
        with patch("dpg_navigator.renderers.image.dpg") as worker_dpg:
            finish = renderer.prepare(entry, ctx)()
        assert worker_dpg.mock_calls == []
        with patch("dpg_navigator.renderers.image.dpg") as mock_dpg:
            mock_dpg.get_item_rect_size.return_value = (1008, 1008)
            mock_dpg.does_item_exist.return_value = False
            finish()
        return mock_dpg

    def test_default_cap(self):
        assert ImageRenderer._MAX_TEXTURE_DIMENSION == IMAGE_PREVIEW_TEXTURE_MAX_DIMENSION == 2048

    def test_big_image_texture_capped_and_size_reported_as_source(self, tmp_path):
        image = pytest.importorskip("PIL.Image")
        pytest.importorskip("numpy")
        path = tmp_path / "big.png"
        image.new("RGB", (300, 150), (10, 20, 30)).save(path)
        renderer = ImageRenderer()
        ctx = self._ctx()
        with patch.object(ImageRenderer, "_MAX_TEXTURE_DIMENSION", 64):
            mock_dpg = self._finish(renderer, self._entry(str(path)), ctx)

        tex = mock_dpg.add_static_texture.call_args.kwargs
        assert (tex["width"], tex["height"]) == (64, 32)
        assert len(tex["default_value"]) == 64 * 32 * 4
        assert ctx.image_cache[:2] == (300, 150)
        assert (renderer._img_w, renderer._img_h) == (300, 150)
        # Laid out at the source size: it fits the 1000 px canvas, so no upscaling.
        assert mock_dpg.draw_image.call_args.kwargs["pmax"] == (300.0, 150.0)

    def test_tall_image_keeps_aspect(self, tmp_path):
        image = pytest.importorskip("PIL.Image")
        pytest.importorskip("numpy")
        path = tmp_path / "tall.png"
        image.new("RGB", (150, 300), (10, 20, 30)).save(path)
        ctx = self._ctx()
        with patch.object(ImageRenderer, "_MAX_TEXTURE_DIMENSION", 64):
            mock_dpg = self._finish(ImageRenderer(), self._entry(str(path)), ctx)

        tex = mock_dpg.add_static_texture.call_args.kwargs
        assert (tex["width"], tex["height"]) == (32, 64)
        assert ctx.image_cache[:2] == (150, 300)

    def test_default_cap_applies_to_a_real_decode(self, tmp_path):
        image = pytest.importorskip("PIL.Image")
        pytest.importorskip("numpy")
        path = tmp_path / "wide.png"
        image.new("RGB", (2100, 1050), (10, 20, 30)).save(path)
        ctx = self._ctx()
        mock_dpg = self._finish(ImageRenderer(), self._entry(str(path)), ctx)

        tex = mock_dpg.add_static_texture.call_args.kwargs
        assert (tex["width"], tex["height"]) == (2048, 1024)
        assert ctx.image_cache[:2] == (2100, 1050)

    def test_small_image_untouched(self, tmp_path):
        image = pytest.importorskip("PIL.Image")
        pytest.importorskip("numpy")
        path = tmp_path / "small.png"
        image.new("RGB", (64, 32), (255, 0, 0)).save(path)
        ctx = self._ctx()
        mock_dpg = self._finish(ImageRenderer(), self._entry(str(path)), ctx)

        tex = mock_dpg.add_static_texture.call_args.kwargs
        assert (tex["width"], tex["height"]) == (64, 32)
        assert list(tex["default_value"][:4]) == [1.0, 0.0, 0.0, 1.0]
        assert ctx.image_cache[:2] == (64, 32)

    def test_zoom_maps_onto_the_scaled_texture(self, tmp_path):
        image = pytest.importorskip("PIL.Image")
        pytest.importorskip("numpy")
        path = tmp_path / "big.png"
        image.new("RGB", (400, 200), (10, 20, 30)).save(path)
        renderer = ImageRenderer()
        with patch.object(ImageRenderer, "_MAX_TEXTURE_DIMENSION", 50):
            self._finish(renderer, self._entry(str(path)), self._ctx())
        renderer._image_id = 99
        renderer._zoom = 2.0
        with patch("dpg_navigator.renderers.image.dpg") as mock_dpg:
            mock_dpg.get_item_rect_size.return_value = (208, 208)
            mock_dpg.does_item_exist.return_value = True
            renderer._apply_transform()
        # The 400x200 source fits a 200 px canvas at 200x100; x2 zoom doubles it.
        # The 50x25 texture is stretched over that rectangle.
        mock_dpg.configure_item.assert_called_once_with(99, pmin=(0.0, 0.0), pmax=(400, 200))

    def test_stb_fallback_is_not_capped(self, tmp_path):
        path = tmp_path / "p.png"
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + (4).to_bytes(4, "big") * 2 + b"\x00" * 16)
        ctx = self._ctx()
        renderer = ImageRenderer()
        with (
            patch("dpg_navigator.renderers.image._PILImage", None),
            patch.object(ImageRenderer, "_MAX_TEXTURE_DIMENSION", 2),
        ):
            with patch("dpg_navigator.renderers.image.dpg"):
                finish = renderer.prepare(self._entry(str(path)), ctx)()
            with patch("dpg_navigator.renderers.image.dpg") as mock_dpg:
                mock_dpg.load_image.return_value = (4, 4, 4, [0.0] * 64)
                mock_dpg.get_item_rect_size.return_value = (108, 108)
                mock_dpg.does_item_exist.return_value = False
                finish()
        tex = mock_dpg.add_static_texture.call_args.kwargs
        assert (tex["width"], tex["height"]) == (4, 4)
        assert ctx.image_cache[:2] == (4, 4)


class TestLoadPreviewRaster:
    def test_keeps_source_size_next_to_texture_size(self, tmp_path):
        image = pytest.importorskip("PIL.Image")
        path = tmp_path / "r.png"
        image.new("RGB", (100, 40), (0, 0, 0)).save(path)
        raster = load_preview_raster(str(path), max_dim=50)
        assert (raster.width, raster.height) == (100, 40)
        assert (raster.texture_width, raster.texture_height) == (50, 20)
        assert len(raster.data) == 50 * 20 * 4

    def test_cap_never_exceeds_decode_limit(self):
        seen: list[tuple[int, int]] = []

        class _Img:
            mode = "RGB"
            size = (9000, 100)

            def thumbnail(self, size):
                seen.append(size)

            def convert(self, mode):
                converted = MagicMock()
                converted.size = (1, 1)
                converted.tobytes.return_value = b"\x00\x00\x00\xff"
                return converted

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with patch("dpg_navigator._preview_limits._PILImage") as pil:
            pil.open.return_value = _Img()
            load_preview_raster("x.webp", max_dim=100_000)
        assert seen == [(8192, 8192)]

    def test_palette_image_converted_before_shrinking(self):
        order: list[str] = []

        class _Img:
            def __init__(self, mode: str) -> None:
                self.mode = mode
                self.size = (400, 100)

            def thumbnail(self, _size):
                order.append(f"thumbnail:{self.mode}")
                self.size = (40, 10)

            def convert(self, mode):
                order.append(f"convert:{self.mode}->{mode}")
                return _Img(mode)

            def tobytes(self):
                return b"\x00\x00\x00\xff" * (self.size[0] * self.size[1])

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with patch("dpg_navigator._preview_limits._PILImage") as pil:
            pil.open.return_value = _Img("P")
            raster = load_preview_raster("x.gif", max_dim=40)
        assert order == ["convert:P->RGBA", "thumbnail:RGBA"]
        assert (raster.width, raster.height) == (400, 100)
        assert (raster.texture_width, raster.texture_height) == (40, 10)
