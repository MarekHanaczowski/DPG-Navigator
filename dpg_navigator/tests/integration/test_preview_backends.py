"""Live preview backends: Chrome HTML, Word HTML/text switch, archive extract.

Opt-in (``DPG_INTEGRATION=1``). Chrome cases skip when no browser binary is
resolvable so the suite still runs on a display-only machine.
"""

from __future__ import annotations

import time
import zipfile
from unittest.mock import MagicMock, patch

import dearpygui.dearpygui as dpg
import pytest

from dpg_navigator._availability import markdown_available
from dpg_navigator._html import _CHROME_TIMEOUT, chrome_available
from dpg_navigator._preview_registry import PreviewKind
from dpg_navigator._preview_word import word_available

from .dpg_harness import entry_named, make_dialog, pump, show_preview, wait_until

pytestmark = pytest.mark.integration

# Allow the 30s Chrome Popen timeout to fire and the worker to set status
# before the wait expires (previous 25s wait lost the race to the hang).
_HTML_RENDER_WAIT = _CHROME_TIMEOUT + 15.0


def _document_renderer(dialog, kind=PreviewKind.HTML):
    return dialog._preview._renderers[kind]


class TestPreviewAndListingPollsCoexist:
    """The HTML preview poll and the dialog's listing poll both need a frame
    callback every frame, and DearPyGui keeps one callback per frame. When
    each registered its own, one of them starved: either the preview stayed
    on "Rendering..." or the listing stopped updating."""

    def test_markdown_preview_finishes_and_the_listing_still_updates(self, dpg_viewport, tmp_path):
        if not chrome_available():
            pytest.skip("Chrome/Chromium not resolvable")
        if not markdown_available():
            pytest.skip("markdown backend not installed")
        (tmp_path / "readme.md").write_text("# Title\n\nSome **bold** text.\n", encoding="utf-8")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "inner.txt").write_text("x", encoding="utf-8")
        dialog = make_dialog(tmp_path)
        try:
            dialog.show()
            pump()
            show_preview(dialog, entry_named(dialog, "readme.md"))
            html = _document_renderer(dialog, PreviewKind.MARKDOWN)._html
            assert html is not None
            assert wait_until(lambda: not html.is_rendering, timeout=_HTML_RENDER_WAIT), "preview never finished"
            assert "fail" not in html.status_text.lower()
            assert html.tex_id is not None

            dialog.logic.navigate_to(str(sub))
            assert wait_until(
                lambda: [entry.name for entry in dialog.state.row_entries.values()] == ["inner.txt"],
                timeout=10.0,
            ), "listing was not applied after a preview render"
        finally:
            dialog.destroy()
            pump()


class TestChromeHtmlPreview:
    def test_html_file_renders_texture(self, dpg_viewport, tmp_path):
        if not chrome_available():
            pytest.skip("Chrome/Chromium not resolvable")
        (tmp_path / "page.html").write_text(
            "<html><body><p>dpg-navigator chrome smoke</p></body></html>",
            encoding="utf-8",
        )
        dialog = make_dialog(tmp_path)
        try:
            dialog.show()
            pump()
            show_preview(dialog, entry_named(dialog, "page.html"))
            html = _document_renderer(dialog)._html
            assert html is not None
            assert wait_until(lambda: not html.is_rendering, timeout=_HTML_RENDER_WAIT)
            assert "fail" not in html.status_text.lower()
            assert html.tex_id is not None
        finally:
            dialog.destroy()
            pump()

    def test_safe_blocks_js_while_trusted_opt_in_executes_it(self, dpg_viewport, tmp_path):
        if not chrome_available():
            pytest.skip("Chrome/Chromium not resolvable")
        np = pytest.importorskip("numpy")
        (tmp_path / "page.html").write_text(
            "<html><body><script>"
            "document.body.style.background='rgb(250,0,0)';"
            "</script><p>policy probe</p></body></html>",
            encoding="utf-8",
        )
        safe = make_dialog(tmp_path, modal=False)
        trusted = make_dialog(tmp_path, modal=False, trusted_html_preview=True)
        try:
            safe.show()
            trusted.show()
            pump()
            show_preview(safe, entry_named(safe, "page.html"))
            show_preview(trusted, entry_named(trusted, "page.html"))
            safe_html = _document_renderer(safe)._html
            trusted_html = _document_renderer(trusted)._html
            assert safe_html is not None and trusted_html is not None
            assert safe_html is not trusted_html
            assert safe_html._viewport_buf is not None
            assert trusted_html._viewport_buf is not None
            with (
                patch.object(safe_html, "close", wraps=safe_html.close) as safe_close,
                patch.object(trusted_html, "close", wraps=trusted_html.close) as trusted_close,
            ):
                assert wait_until(
                    lambda: not safe_html.is_rendering and not trusted_html.is_rendering,
                    timeout=_HTML_RENDER_WAIT,
                )
                safe_close.assert_not_called()
                trusted_close.assert_not_called()
            safe_pixels = safe_html._full_array
            trusted_pixels = trusted_html._full_array
            assert safe_pixels is not None and trusted_pixels is not None
            safe_red = (safe_pixels[..., 0] > 245) & (safe_pixels[..., 1] < 20) & (safe_pixels[..., 2] < 20)
            trusted_red = (trusted_pixels[..., 0] > 245) & (trusted_pixels[..., 1] < 20) & (trusted_pixels[..., 2] < 20)
            assert not bool(np.any(safe_red))
            assert bool(np.any(trusted_red))
        finally:
            safe.destroy()
            trusted.destroy()
            pump()

    def test_safe_mode_does_not_load_relative_local_image(self, dpg_viewport, tmp_path):
        if not chrome_available():
            pytest.skip("Chrome/Chromium not resolvable")
        image = pytest.importorskip("PIL.Image")
        np = pytest.importorskip("numpy")
        image.new("RGB", (40, 40), (250, 0, 0)).save(tmp_path / "local.png")
        (tmp_path / "page.html").write_text('<img src="./local.png">', encoding="utf-8")
        dialog = make_dialog(tmp_path)
        try:
            dialog.show()
            pump()
            show_preview(dialog, entry_named(dialog, "page.html"))
            html = _document_renderer(dialog)._html
            assert html is not None
            assert wait_until(lambda: not html.is_rendering, timeout=_HTML_RENDER_WAIT)
            pixels = html._full_array
            assert pixels is not None
            red = (pixels[..., 0] > 245) & (pixels[..., 1] < 20) & (pixels[..., 2] < 20)
            assert not bool(np.any(red))
        finally:
            dialog.destroy()
            pump()

    def test_two_dialogs_render_concurrently_with_isolated_sessions(self, dpg_viewport, tmp_path):
        if not chrome_available():
            pytest.skip("Chrome/Chromium not resolvable")
        (tmp_path / "one.html").write_text("<p>first dialog</p>", encoding="utf-8")
        (tmp_path / "two.html").write_text("<p>second dialog</p>", encoding="utf-8")
        first = make_dialog(tmp_path, modal=False)
        second = make_dialog(tmp_path, modal=False)
        try:
            first.show()
            second.show()
            pump()
            show_preview(first, entry_named(first, "one.html"))
            show_preview(second, entry_named(second, "two.html"))
            first_html = _document_renderer(first)._html
            second_html = _document_renderer(second)._html
            assert first_html is not None and second_html is not None
            assert wait_until(
                lambda: not first_html.is_rendering and not second_html.is_rendering,
                timeout=_HTML_RENDER_WAIT,
            )
            assert "fail" not in first_html.status_text.lower()
            assert "fail" not in second_html.status_text.lower()
        finally:
            first.destroy()
            second.destroy()
            pump()

    def test_resize_then_close_has_no_late_callback(self, dpg_viewport, tmp_path):
        if not chrome_available():
            pytest.skip("Chrome/Chromium not resolvable")
        (tmp_path / "page.html").write_text("<p>resize and close</p>", encoding="utf-8")
        dialog = make_dialog(tmp_path)
        late_callback = MagicMock()
        try:
            dialog.show()
            pump()
            show_preview(dialog, entry_named(dialog, "page.html"))
            html = _document_renderer(dialog)._html
            assert html is not None
            html._on_resize_complete = late_callback
            html.on_resize(420, 320)
            dialog.destroy()
            deadline = time.time() + 1.0
            while time.time() < deadline:
                pump(1)
                time.sleep(0.02)
            late_callback.assert_not_called()
        finally:
            if not dialog._destroyed:
                dialog.destroy()
            pump()


class TestWordPreviewSwitch:
    def _write_docx(self, path) -> None:
        pytest.importorskip("docx")
        from docx import Document

        document = Document()
        document.add_paragraph("Hello from dpg-navigator")
        document.save(str(path))

    def test_text_fallback_when_chrome_unavailable(self, dpg_viewport, tmp_path):
        if not word_available():
            pytest.skip("python-docx not installed")
        self._write_docx(tmp_path / "note.docx")
        dialog = make_dialog(tmp_path)
        try:
            dialog.show()
            pump()
            with patch("dpg_navigator.renderers.document.chrome_available", return_value=False):
                show_preview(dialog, entry_named(dialog, "note.docx"))
            pump()
            renderer = _document_renderer(dialog, PreviewKind.WORD)
            assert renderer._html is None or not renderer._html.is_open
            children = dpg.get_item_children(dialog._preview._panel_id, 1) or []
            assert children, "text Word preview should add widgets to the panel"
        finally:
            dialog.destroy()
            pump()

    def test_html_path_when_chrome_available(self, dpg_viewport, tmp_path):
        if not chrome_available():
            pytest.skip("Chrome/Chromium not resolvable")
        pytest.importorskip("mammoth")
        if not word_available():
            pytest.skip("python-docx not installed")
        self._write_docx(tmp_path / "note.docx")
        dialog = make_dialog(tmp_path)
        try:
            dialog.show()
            pump()
            show_preview(dialog, entry_named(dialog, "note.docx"))
            renderer = _document_renderer(dialog, PreviewKind.WORD)
            html = renderer._html
            if html is None:
                pytest.skip("mammoth+Chrome Word path not selected in this environment")
            assert wait_until(lambda: not html.is_rendering, timeout=_HTML_RENDER_WAIT)
            assert html.is_open
            assert "fail" not in html.status_text.lower()
        finally:
            dialog.destroy()
            pump()


class TestOversizeArchiveSelection:
    def test_oversized_member_keeps_dialog_open(self, dpg_viewport, tmp_path):
        archive = tmp_path / "bundle.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("large.txt", "x" * 32)

        chosen: list[list[str]] = []
        dialog = make_dialog(tmp_path, callback=lambda paths: chosen.append(list(paths)))
        dialog._MAX_ARCHIVE_EXTRACT_SIZE = 8
        try:
            dialog.show()
            pump()
            dialog.logic.navigate_to(f"{archive}|/")
            pump()
            entry = entry_named(dialog, "large.txt")
            dialog.state.selected_files = [entry.full_path]
            dpg.set_value(dialog._filename_input, "")
            dialog._return_selection()
            pump()

            assert chosen == []
            assert dpg.is_item_shown(dialog._config.tag)
            status = dpg.get_value(dialog._status_label)
            assert "Extraction Error" in status
            assert "large.txt" in status
        finally:
            dialog.destroy()
            pump()
