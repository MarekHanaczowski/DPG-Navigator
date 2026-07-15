"""Tests for DocumentRenderer (rendering router for HTML, MD, PDF, Word, PPTX)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch, mock_open
import pytest

from dpg_navigator._types import FileEntry
from dpg_navigator._preview_registry import PreviewCapabilities
from dpg_navigator.renderers._base import PreviewContext
from dpg_navigator.renderers.document import DocumentRenderer


@pytest.fixture(autouse=True)
def mock_dpg():
    with patch("dpg_navigator.renderers.document.dpg") as m:
        m.does_item_exist.return_value = True
        m.get_item_rect_size.return_value = (800, 600)
        yield m


@pytest.fixture
def mock_backends():
    with patch("dpg_navigator.renderers.document.chrome_available", return_value=True), \
         patch("dpg_navigator.renderers.document.HTMLRenderer") as mock_html, \
         patch("dpg_navigator.renderers.document.PDFRenderer") as mock_pdf:

        # Configure HTMLRenderer mock
        html_instance = mock_html.return_value
        html_instance.open.return_value = True
        html_instance.open_string.return_value = True
        html_instance.is_open = True
        html_instance.tex_id = 12345
        html_instance.status_text = "Ready"

        # Configure PDFRenderer mock
        pdf_instance = mock_pdf.return_value
        pdf_instance.open.return_value = True
        pdf_instance.is_open = True
        pdf_instance.show_page.return_value = (0, 5)
        pdf_instance.tex_id = 67890

        yield mock_html, mock_pdf


def test_document_renderer_init():
    load_text_cb = MagicMock()
    renderer = DocumentRenderer(load_text_cb)
    assert renderer._load_text_content == load_text_cb
    assert renderer._current_entry is None


def test_document_renderer_clear(mock_backends):
    load_text_cb = MagicMock()
    renderer = DocumentRenderer(load_text_cb)

    # Initialize some state
    entry = FileEntry("test.html", "test.html", is_dir=False, size_bytes=100, modified_time=0.0, is_hidden=False)
    ctx = PreviewContext(panel_id=1, table_wrapper=2, config_tag="test_tag", capabilities=PreviewCapabilities())
    renderer.render(entry, ctx)

    assert renderer._html is not None
    renderer.clear()

    assert renderer._current_entry is None
    assert renderer._html is None
    assert renderer._pdf is None


def test_render_html(mock_backends):
    load_text_cb = MagicMock()
    renderer = DocumentRenderer(load_text_cb)

    entry = FileEntry("index.html", "index.html", is_dir=False, size_bytes=100, modified_time=0.0, is_hidden=False)
    ctx = PreviewContext(panel_id=1, table_wrapper=2, config_tag="test_tag", capabilities=PreviewCapabilities())

    renderer.render(entry, ctx)

    renderer._html.open.assert_called_once_with(
        "index.html", 800, 600 - 42,
        on_complete=renderer._on_html_render_done,
        on_resize_complete=renderer._on_html_resize_done
    )


def test_render_pdf(mock_backends):
    load_text_cb = MagicMock()
    renderer = DocumentRenderer(load_text_cb)

    entry = FileEntry("report.pdf", "report.pdf", is_dir=False, size_bytes=2000, modified_time=0.0, is_hidden=False)
    ctx = PreviewContext(panel_id=1, table_wrapper=2, config_tag="test_tag", capabilities=PreviewCapabilities())

    renderer.render(entry, ctx)

    renderer._pdf.open.assert_called_once_with("report.pdf", 800, 600 - 42)
    renderer._pdf.show_page.assert_called_once_with(0)


def test_render_word_mammoth(mock_backends):
    load_text_cb = MagicMock()
    renderer = DocumentRenderer(load_text_cb)

    entry = FileEntry("doc.docx", "doc.docx", is_dir=False, size_bytes=2000, modified_time=0.0, is_hidden=False)
    ctx = PreviewContext(
        panel_id=1,
        table_wrapper=2,
        config_tag="test_tag",
        capabilities=PreviewCapabilities(mammoth=True),
    )

    with patch("dpg_navigator.renderers.document._mammoth") as mock_mam:
        mock_mam.convert_to_html.return_value = MagicMock(value="<p>hello</p>")
        with patch("builtins.open", mock_open(read_data=b"mock-docx-data")):
            renderer.render(entry, ctx)

    renderer._html.open_string.assert_called_once()


def test_on_resize(mock_backends):
    load_text_cb = MagicMock()
    renderer = DocumentRenderer(load_text_cb)

    entry = FileEntry("index.html", "index.html", is_dir=False, size_bytes=100, modified_time=0.0, is_hidden=False)
    ctx = PreviewContext(panel_id=1, table_wrapper=2, config_tag="test_tag", capabilities=PreviewCapabilities())
    renderer.render(entry, ctx)

    renderer.on_resize(None, None, None)
    renderer._html.on_resize.assert_called_once_with(800, 600 - 42)


def test_on_mouse_wheel(mock_backends):
    load_text_cb = MagicMock()
    renderer = DocumentRenderer(load_text_cb)

    entry = FileEntry("index.html", "index.html", is_dir=False, size_bytes=100, modified_time=0.0, is_hidden=False)
    ctx = PreviewContext(panel_id=1, table_wrapper=2, config_tag="test_tag", capabilities=PreviewCapabilities())
    renderer.render(entry, ctx)

    renderer.on_mouse_wheel(None, 1, None)
    renderer._html.on_scroll.assert_called_once_with(1)
