"""Tests for dpg_navigator._pdf — PDFRenderer (pure logic, no DPG runtime)."""

from __future__ import annotations

import importlib.util
import threading
from unittest.mock import MagicMock, patch

import pytest

HAS_NUMPY = importlib.util.find_spec("numpy") is not None

# ── pdf_available ────────────────────────────────────────────────


class TestPdfAvailable:
    def test_available_when_all_installed(self):
        with (
            patch("dpg_navigator._pdf._pdfium", MagicMock()),
            patch("dpg_navigator._pdf._np", MagicMock()),
            patch("dpg_navigator._pdf._PILImage", MagicMock()),
        ):
            from dpg_navigator._pdf import pdf_available

            assert pdf_available() is True

    def test_unavailable_without_pypdfium2(self):
        with (
            patch("dpg_navigator._pdf._pdfium", None),
            patch("dpg_navigator._pdf._np", MagicMock()),
            patch("dpg_navigator._pdf._PILImage", MagicMock()),
        ):
            from dpg_navigator._pdf import pdf_available

            assert pdf_available() is False

    def test_unavailable_without_numpy(self):
        with (
            patch("dpg_navigator._pdf._pdfium", MagicMock()),
            patch("dpg_navigator._pdf._np", None),
            patch("dpg_navigator._pdf._PILImage", MagicMock()),
        ):
            from dpg_navigator._pdf import pdf_available

            assert pdf_available() is False

    def test_unavailable_without_pillow(self):
        with (
            patch("dpg_navigator._pdf._pdfium", MagicMock()),
            patch("dpg_navigator._pdf._np", MagicMock()),
            patch("dpg_navigator._pdf._PILImage", None),
        ):
            from dpg_navigator._pdf import pdf_available

            assert pdf_available() is False

    def test_unavailable_when_all_missing(self):
        with (
            patch("dpg_navigator._pdf._pdfium", None),
            patch("dpg_navigator._pdf._np", None),
            patch("dpg_navigator._pdf._PILImage", None),
        ):
            from dpg_navigator._pdf import pdf_available

            assert pdf_available() is False


# ── PDFRenderer unit tests (mocked DPG + pypdfium2) ──────────────

pytestmark = pytest.mark.skipif(not HAS_NUMPY, reason="numpy required")


@pytest.fixture
def mock_dpg():
    """Mock DPG functions used by PDFRenderer."""
    with patch("dpg_navigator._pdf.dpg") as m:
        m.mvFormat_Float_rgba = 0
        m.does_item_exist.return_value = False

        # mvBuffer returns a bytearray-like object with ctypes support
        def fake_mvbuffer(size):
            import ctypes

            return (ctypes.c_float * size)()

        m.mvBuffer = fake_mvbuffer

        # texture_registry returns a context manager
        m.texture_registry.return_value.__enter__ = MagicMock()
        m.texture_registry.return_value.__exit__ = MagicMock(return_value=False)

        # add_raw_texture returns an integer ID
        m.add_raw_texture.return_value = 99999

        yield m


@pytest.fixture
def make_renderer(mock_dpg):
    """Create a PDFRenderer with mocked DPG."""
    from dpg_navigator._pdf import PDFRenderer

    return PDFRenderer("test_tag")


class TestPDFRendererInit:
    def test_initial_state(self, make_renderer):
        r = make_renderer
        assert r.is_open is False
        assert r.current_page == 0
        assert r.total_pages == 0
        assert r.tex_id is None

    def test_close_on_not_open_is_safe(self, make_renderer):
        r = make_renderer
        r.close()  # should not raise
        assert r.is_open is False

    def test_open_rejects_oversized_file(self, make_renderer):
        from dpg_navigator._pdf import _MAX_PDF_BYTES

        r = make_renderer
        with (
            patch("dpg_navigator._pdf.os.path.getsize", return_value=_MAX_PDF_BYTES + 1),
            patch("dpg_navigator._pdf._pdfium") as pdfium,
        ):
            assert r.open("huge.pdf", 100, 100) is False
            pdfium.PdfDocument.assert_not_called()


class TestLRUCache:
    """Test the LRU cache logic using _get_page with mocked rendering."""

    def test_cache_stores_rendered_page(self, make_renderer):
        import numpy as np

        r = make_renderer
        r._tex_w = 100
        r._tex_h = 100
        arr = np.ones(100 * 100 * 4, dtype=np.float32)

        with patch.object(r, "_render_to_array", return_value=arr) as mock_render:
            result = r._get_page(0)
            mock_render.assert_called_once_with(0, 100, 100)
            assert 0 in r._page_cache
            np.testing.assert_array_equal(result, arr)

    def test_cache_hit_does_not_re_render(self, make_renderer):
        import numpy as np

        r = make_renderer
        r._tex_w = 100
        r._tex_h = 100
        arr = np.ones(100 * 100 * 4, dtype=np.float32)
        r._page_cache[5] = arr

        with patch.object(r, "_render_to_array") as mock_render:
            result = r._get_page(5)
            mock_render.assert_not_called()
            np.testing.assert_array_equal(result, arr)

    def test_cache_hit_moves_to_end(self, make_renderer):
        import numpy as np

        r = make_renderer
        r._tex_w = 10
        r._tex_h = 10
        for i in range(3):
            r._page_cache[i] = np.zeros(10 * 10 * 4, dtype=np.float32)

        with patch.object(r, "_render_to_array"):
            r._get_page(0)  # access page 0, should move to end

        keys = list(r._page_cache.keys())
        assert keys[-1] == 0

    def test_cache_eviction_at_capacity(self, make_renderer):
        import numpy as np

        r = make_renderer
        r._tex_w = 10
        r._tex_h = 10
        # Fill cache to capacity
        for i in range(r._CACHE_SIZE):
            r._page_cache[i] = np.zeros(10 * 10 * 4, dtype=np.float32)

        new_arr = np.ones(10 * 10 * 4, dtype=np.float32)
        with patch.object(r, "_render_to_array", return_value=new_arr):
            r._get_page(99)  # new page, triggers eviction

        assert 99 in r._page_cache
        assert 0 not in r._page_cache  # oldest evicted
        assert len(r._page_cache) == r._CACHE_SIZE


class TestPageNavigation:
    def test_next_page_increments(self, make_renderer):
        import numpy as np

        r = make_renderer
        r._doc = MagicMock()
        r._total_pages = 10
        r._current_page = 3
        r._tex_w = 10
        r._tex_h = 10
        r._buf_ptr = 0

        arr = np.ones(10 * 10 * 4, dtype=np.float32)
        with (
            patch.object(r, "_get_page", return_value=arr),
            patch("dpg_navigator._pdf.ctypes"),
            patch.object(r, "_start_prefetch"),
        ):
            page_info = r.next_page()
            assert page_info == (4, 10)
            assert r._current_page == 4

    def test_next_page_at_last_does_not_advance(self, make_renderer):
        r = make_renderer
        r._doc = MagicMock()
        r._total_pages = 5
        r._current_page = 4
        page_info = r.next_page()
        assert page_info == (4, 5)

    def test_prev_page_decrements(self, make_renderer):
        import numpy as np

        r = make_renderer
        r._doc = MagicMock()
        r._total_pages = 10
        r._current_page = 3
        r._tex_w = 10
        r._tex_h = 10
        r._buf_ptr = 0

        arr = np.ones(10 * 10 * 4, dtype=np.float32)
        with (
            patch.object(r, "_get_page", return_value=arr),
            patch("dpg_navigator._pdf.ctypes"),
            patch.object(r, "_start_prefetch"),
        ):
            page_info = r.prev_page()
            assert page_info == (2, 10)
            assert r._current_page == 2

    def test_prev_page_at_first_does_not_go_negative(self, make_renderer):
        r = make_renderer
        r._doc = MagicMock()
        r._total_pages = 5
        r._current_page = 0
        page_info = r.prev_page()
        assert page_info == (0, 5)

    def test_show_page_clamps_to_valid_range(self, make_renderer):
        import numpy as np

        r = make_renderer
        r._doc = MagicMock()
        r._total_pages = 5
        r._tex_w = 10
        r._tex_h = 10
        r._buf_ptr = 0

        arr = np.ones(10 * 10 * 4, dtype=np.float32)
        with (
            patch.object(r, "_get_page", return_value=arr),
            patch("dpg_navigator._pdf.ctypes"),
            patch.object(r, "_start_prefetch"),
        ):
            page_info = r.show_page(100)
            assert page_info == (4, 5)

            page_info = r.show_page(-5)
            assert page_info == (0, 5)


class TestDocumentRendererWheel:
    def _make_renderer(self):
        from dpg_navigator.renderers.document import DocumentRenderer

        renderer = DocumentRenderer(lambda path, offset: (None, False))
        renderer._pdf = MagicMock()
        renderer._pdf.is_open = True
        renderer._pdf_page_label = "page_label"
        return renderer

    def test_wheel_up_shows_previous_page(self):
        renderer = self._make_renderer()
        renderer._pdf.prev_page.return_value = (1, 4)

        with patch("dpg_navigator.renderers.document.dpg") as mock_dpg:
            mock_dpg.does_item_exist.return_value = True
            renderer.on_mouse_wheel(None, 1.0, None)

        renderer._pdf.prev_page.assert_called_once_with()
        renderer._pdf.next_page.assert_not_called()
        mock_dpg.set_value.assert_called_once_with("page_label", "Page 2 / 4")

    def test_wheel_down_shows_next_page(self):
        renderer = self._make_renderer()
        renderer._pdf.next_page.return_value = (2, 4)

        with patch("dpg_navigator.renderers.document.dpg") as mock_dpg:
            mock_dpg.does_item_exist.return_value = True
            renderer.on_mouse_wheel(None, -1.0, None)

        renderer._pdf.next_page.assert_called_once_with()
        renderer._pdf.prev_page.assert_not_called()
        mock_dpg.set_value.assert_called_once_with("page_label", "Page 3 / 4")


class TestResourceCleanup:
    def test_close_clears_all_state(self, make_renderer):
        import numpy as np

        r = make_renderer
        r._doc = MagicMock()
        r._total_pages = 10
        r._current_page = 5
        r._current_path = "/some/path.pdf"
        r._page_cache[0] = np.zeros(100, dtype=np.float32)
        r._tex_exists = True
        r._tex_id = 99999
        r._tex_buffer = MagicMock()
        r._buf_ptr = 12345

        r.close()

        assert r.is_open is False
        assert r.total_pages == 0
        assert r.current_page == 0
        assert r._current_path == ""
        assert len(r._page_cache) == 0
        assert r._tex_buffer is None
        assert r._buf_ptr is None
        assert r.tex_id is None
        assert r._tex_exists is False

    def test_double_close_is_safe(self, make_renderer):
        r = make_renderer
        r._doc = MagicMock()
        r._tex_exists = False
        r.close()
        r.close()  # should not raise
        assert r.is_open is False

    def test_close_bumps_prefetch_generation(self, make_renderer):
        r = make_renderer
        gen_before = r._prefetch_generation
        r.close()
        assert r._prefetch_generation == gen_before + 1


class TestRenderToArray:
    """Test the rendering pipeline with real numpy but mocked pypdfium2/PIL."""

    def test_produces_correct_shape(self, make_renderer):
        import numpy as np

        r = make_renderer
        r._doc_lock = threading.Lock()

        # Mock a PDF page
        mock_page = MagicMock()
        mock_page.get_size.return_value = (200.0, 300.0)
        mock_bitmap = MagicMock()

        # Create a small test image via PIL
        from PIL import Image

        test_img = Image.new("RGBA", (50, 75), (255, 0, 0, 255))
        mock_bitmap.to_pil.return_value = test_img

        mock_page.render.return_value = mock_bitmap
        r._doc = MagicMock()
        r._doc.__getitem__ = MagicMock(return_value=mock_page)

        result = r._render_to_array(0, 100, 100)

        assert result.dtype == np.float32
        assert result.shape == (100 * 100 * 4,)
        assert result.flags["C_CONTIGUOUS"]

    def test_page_fitting_preserves_aspect(self, make_renderer):

        r = make_renderer
        r._doc_lock = threading.Lock()

        mock_page = MagicMock()
        mock_page.get_size.return_value = (100.0, 200.0)  # tall page
        mock_bitmap = MagicMock()

        from PIL import Image

        # After scaling to fit 200x200, page becomes 100x200
        test_img = Image.new("RGBA", (100, 200), (0, 255, 0, 255))
        mock_bitmap.to_pil.return_value = test_img
        mock_page.render.return_value = mock_bitmap

        r._doc = MagicMock()
        r._doc.__getitem__ = MagicMock(return_value=mock_page)

        result = r._render_to_array(0, 200, 200)
        assert result.shape == (200 * 200 * 4,)

        # The canvas should have white pixels at the horizontal margins
        # Left edge center row should be white (1.0 for all RGBA)
        center_row = 100
        left_pixel_start = center_row * 200 * 4
        # First pixel should be white (margin)
        assert result[left_pixel_start] == pytest.approx(1.0)


class TestCanvasCentering:
    """Test that rendered pages are centered on the white canvas."""

    def test_centered_horizontally(self):
        import numpy as np

        # Simulate: page is 50 wide, canvas is 100 wide
        # offset_x should be (100 - 50) // 2 = 25
        iw, ih = 50, 100
        w, h = 100, 100

        arr = np.zeros(iw * ih * 4, dtype=np.float32)
        arr[::4] = 0.5  # R channel = 0.5 for all pixels

        canvas = np.ones(w * h * 4, dtype=np.float32)
        ox = (w - iw) // 2
        oy = (h - ih) // 2

        for row in range(ih):
            src_s = row * iw * 4
            dst_s = ((oy + row) * w + ox) * 4
            canvas[dst_s : dst_s + iw * 4] = arr[src_s : src_s + iw * 4]

        # Check left margin is white
        assert canvas[0] == 1.0
        # Check centered pixel has our color
        center_idx = (0 * w + 25) * 4  # row 0, col 25
        assert canvas[center_idx] == pytest.approx(0.5)

    def test_exact_fit_no_canvas_needed(self):

        iw, ih = 100, 100
        w, h = 100, 100

        # When iw == w and ih == h, no canvas embedding needed
        assert iw == w and ih == h


class TestPrefetchGeneration:
    """Test that prefetch generation counter prevents stale renders."""

    def test_generation_incremented_on_close(self, make_renderer):
        r = make_renderer
        gen = r._prefetch_generation
        r.close()
        assert r._prefetch_generation == gen + 1

    def test_generation_incremented_on_recreate_texture(self, make_renderer):
        r = make_renderer
        gen = r._prefetch_generation
        r._recreate_texture(100, 100)
        assert r._prefetch_generation == gen + 1

    def test_stale_prefetch_aborts(self, make_renderer):
        r = make_renderer
        r._doc = MagicMock()
        r._total_pages = 5
        r._tex_w = 10
        r._tex_h = 10

        # Use a stale generation
        stale_gen = r._prefetch_generation - 1
        with patch.object(r, "_render_to_array") as mock_render:
            r._prefetch_worker(2, stale_gen)
            mock_render.assert_not_called()

    def test_close_cancels_prefetch_future(self, make_renderer):
        r = make_renderer
        fut = MagicMock()
        r._prefetch_future = fut
        r.close()
        fut.cancel.assert_called_once()
        assert r._prefetch_future is None

    def test_start_prefetch_cancels_previous_future(self, make_renderer):
        r = make_renderer
        old = MagicMock()
        new = MagicMock()
        r._prefetch_future = old
        with patch("dpg_navigator._pdf.JobManager.submit", return_value=new):
            r._start_prefetch(1)
        old.cancel.assert_called_once()
        assert r._prefetch_future is new


class TestTextureLifecycle:
    """Test that tex_id is correctly managed through create/resize/close."""

    def test_recreate_texture_sets_tex_id(self, make_renderer):
        r = make_renderer
        assert r.tex_id is None
        r._recreate_texture(100, 100)
        assert r.tex_id == 99999
        assert r._tex_exists is True

    def test_close_clears_tex_id(self, make_renderer):
        r = make_renderer
        r._recreate_texture(50, 50)
        assert r.tex_id is not None
        r.close()
        assert r.tex_id is None
        assert r._tex_exists is False

    def test_close_resets_tex_exists_even_without_tex_id(self, make_renderer):
        """Defensive: _tex_exists is reset even if _tex_id is somehow None."""
        r = make_renderer
        r._tex_exists = True
        r._tex_id = None
        r.close()
        assert r._tex_exists is False


class TestOnResize:
    """Test on_resize return values and behavior."""

    def test_returns_none_when_doc_not_open(self, make_renderer):
        r = make_renderer
        assert r.on_resize(100, 100) is None

    def test_returns_none_when_size_unchanged(self, make_renderer):
        r = make_renderer
        r._doc = MagicMock()
        r._tex_w = 100
        r._tex_h = 100
        r._tex_exists = True
        assert r.on_resize(100, 100) is None

    def test_returns_page_info_when_size_changed(self, make_renderer):
        import numpy as np

        r = make_renderer
        r._doc = MagicMock()
        r._total_pages = 3
        r._current_page = 1
        r._tex_w = 100
        r._tex_h = 100
        r._tex_exists = True

        arr = np.ones(200 * 200 * 4, dtype=np.float32)
        with (
            patch.object(r, "_get_page", return_value=arr),
            patch("dpg_navigator._pdf.ctypes"),
            patch.object(r, "_start_prefetch"),
        ):
            result = r.on_resize(200, 200)
            assert result == (1, 3)


class TestCloseThreadSafety:
    """Test that close() acquires _doc_lock before closing the document."""

    def test_close_acquires_doc_lock(self, make_renderer):
        """Verify close() uses _doc_lock to protect doc.close()."""
        r = make_renderer
        mock_doc = MagicMock()
        r._doc = mock_doc

        lock_acquired = []
        original_lock = r._doc_lock

        class TrackingLock:
            def __enter__(self_lock):
                original_lock.acquire()
                lock_acquired.append(True)
                return self_lock

            def __exit__(self_lock, *args):
                original_lock.release()
                return False

        r._doc_lock = TrackingLock()
        r.close()

        assert len(lock_acquired) == 1
        mock_doc.close.assert_called_once()
