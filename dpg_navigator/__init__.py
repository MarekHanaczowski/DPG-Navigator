"""dpg_navigator -- customizable file dialog component for DearPyGui.

Provides FileDialog, a modal or non-modal file/directory picker with
sidebar shortcuts, directory tree navigation, real-time search (with
recursive subfolder search via background index), extension filtering,
multi-selection, drag-and-drop support, and an optional preview panel
supporting images, text, PDF, Word (.docx), PowerPoint (.pptx),
Markdown, HTML, CSV/TSV, Excel (.xlsx), SQLite databases, fonts
(.ttf/.otf), ZIP/7z archives, and syntax-highlighted source code
(via Pygments).

Usage::

    from dpg_navigator import FileDialog

    fd = FileDialog(callback=my_handler, default_path="..")
    fd.show()
"""

from __future__ import annotations
# MIT licensed

from ._types import DialogConfig, DialogMode, StyleVariant, FileEntry, DEFAULT_FILTER_LIST

class FileDialog:
    def __new__(cls, *args, **kwargs):
        config = kwargs.get("config")
        if config is None:
            config = DialogConfig(**kwargs)
        from ._dialog import FileDialog as InternalFileDialog
        return InternalFileDialog(*args, **kwargs)

from ._availability import (
    word_available,
    mammoth_available,
    pptx_available,
    markdown_available,
    excel_available,
    py7zr_available,
    pygments_available,
    pdf_available,
    html_available,
    chrome_available,
)

__version__ = "1.0.0b4"

__all__ = [
    "FileDialog",
    "DialogConfig",
    "DialogMode",
    "StyleVariant",
    "FileEntry",
    "DEFAULT_FILTER_LIST",
    "word_available",
    "mammoth_available",
    "pptx_available",
    "markdown_available",
    "pdf_available",
    "html_available",
    "chrome_available",
    "excel_available",
    "py7zr_available",
    "pygments_available",
]
