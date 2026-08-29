"""dpg_navigator -- customizable file dialog component for DearPyGui.

Provides FileDialog, a modal or non-modal file/directory picker with
sidebar shortcuts, directory tree navigation, real-time search (with
recursive subfolder search via background index), extension filtering,
multi-selection, drag-and-drop support, and an optional preview panel
supporting images, text, PDF, Word (.docx), PowerPoint (.pptx),
Markdown, HTML, CSV/TSV, Excel (.xlsx), SQLite databases, fonts
(.ttf/.otf), ZIP/7z archives, and source code as text.

Usage::

    from dpg_navigator import FileDialog

    fd = FileDialog(callback=my_handler, default_path="..")
    fd.show()

MIT licensed.
"""

from __future__ import annotations

from ._availability import (
    chrome_available,
    excel_available,
    html_available,
    mammoth_available,
    markdown_available,
    pdf_available,
    pptx_available,
    py7zr_available,
    pygments_available,
    word_available,
)
from ._dialog import FileDialog
from ._types import DEFAULT_FILTER_LIST, DialogConfig, DialogMode, FileEntry, SelectionCallback, StyleVariant

__version__ = "1.0.0b5"

__all__ = [
    "FileDialog",
    "DialogConfig",
    "DialogMode",
    "StyleVariant",
    "FileEntry",
    "DEFAULT_FILTER_LIST",
    "SelectionCallback",
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
