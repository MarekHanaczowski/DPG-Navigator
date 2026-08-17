"""Live preview backends: Chrome HTML, Word HTML/text switch, archive extract.

Opt-in (``DPG_INTEGRATION=1``). Chrome cases skip when no browser binary is
resolvable so the suite still runs on a display-only machine.
"""

from __future__ import annotations

import zipfile
from unittest.mock import patch

import pytest

import dearpygui.dearpygui as dpg

from dpg_navigator._html import chrome_available
from dpg_navigator._preview_registry import PreviewKind
from dpg_navigator._preview_word import word_available

from .dpg_harness import entry_named, make_dialog, pump, wait_until

pytestmark = pytest.mark.integration


def _document_renderer(dialog, kind=PreviewKind.HTML):
    return dialog._preview._renderers[kind]


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
            dialog._preview.update(entry_named(dialog, "page.html"))
            html = _document_renderer(dialog)._html
            assert html is not None
            assert wait_until(lambda: not html.is_rendering, timeout=25)
            assert "fail" not in html.status_text.lower()
            assert html.tex_id is not None
        finally:
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
                dialog._preview.update(entry_named(dialog, "note.docx"))
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
            dialog._preview.update(entry_named(dialog, "note.docx"))
            renderer = _document_renderer(dialog, PreviewKind.WORD)
            html = renderer._html
            if html is None:
                pytest.skip("mammoth+Chrome Word path not selected in this environment")
            assert wait_until(lambda: not html.is_rendering, timeout=25)
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
