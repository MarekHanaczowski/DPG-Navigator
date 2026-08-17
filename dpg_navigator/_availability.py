"""Dependency checking module.

Provides functions to check if optional dependencies are installed.
"""

from __future__ import annotations

from typing import Any, cast

# PDF
try:
    import pypdfium2 as _pdfium  # type: ignore[import-untyped]
except Exception:
    _pdfium = cast(Any, None)
try:
    import numpy as _np
except Exception:
    _np = cast(Any, None)
try:
    from PIL import Image as _PILImage
except Exception:
    _PILImage = cast(Any, None)


def pdf_available() -> bool:
    """Return True if all PDF preview dependencies are installed."""
    return _pdfium is not None and _np is not None and _PILImage is not None


# HTML & Chrome — canonical probes live in _html.py (html2image + numpy +
# Pillow, and a cached Chrome binary lookup). Imported lazily so this module
# stays GUI-free at import time.
def html_available() -> bool:
    """Return True if html2image, numpy, and Pillow are installed."""
    from ._html import html_available as _html_available

    return _html_available()


def chrome_available() -> bool:
    """Return True if HTML packages are present and a Chrome binary is found."""
    from ._html import chrome_available as _chrome_available

    return _chrome_available()


# Word
try:
    from docx import Document as _DocxDocument
except Exception:
    _DocxDocument = cast(Any, None)
try:
    import mammoth as _mammoth  # type: ignore[import-untyped]
except Exception:
    _mammoth = cast(Any, None)


def word_available() -> bool:
    """Return True if Word text-extraction dependencies are installed."""
    return _DocxDocument is not None


def mammoth_available() -> bool:
    """Return True if mammoth + html2image Word preview is available."""
    return _mammoth is not None and html_available()


# PowerPoint
try:
    from pptx import Presentation as _Presentation
except Exception:
    _Presentation = cast(Any, None)


def pptx_available() -> bool:
    """Return True if PowerPoint preview dependencies are installed."""
    return _Presentation is not None


# Excel
try:
    from openpyxl import load_workbook as _load_workbook  # type: ignore[import-untyped]
except Exception:
    _load_workbook = cast(Any, None)


def excel_available() -> bool:
    """Return True if Excel (.xlsx) preview dependencies are installed."""
    return _load_workbook is not None


# Markdown
try:
    import markdown as _markdown  # type: ignore[import-untyped]
except Exception:
    _markdown = cast(Any, None)


def markdown_available() -> bool:
    """Return True if rendered Markdown preview is available."""
    return _markdown is not None and html_available()


# Pygments — installed for PreviewKind.CODE routing; highlighting is not rendered.
try:
    import pygments as _pygments  # type: ignore[import-untyped]
except Exception:
    _pygments = cast(Any, None)


def pygments_available() -> bool:
    """Return True if Pygments is installed."""
    return _pygments is not None


# 7z
try:
    import py7zr as _py7zr
except Exception:
    _py7zr = cast(Any, None)


def seven_zip_available() -> bool:
    """Return True if py7zr dependencies are installed for .7z support."""
    return _py7zr is not None


def py7zr_available() -> bool:
    """Return True if py7zr dependencies are installed for .7z support."""
    return seven_zip_available()
