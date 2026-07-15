"""Dependency checking module.

Provides functions to check if optional dependencies are installed.
"""

from typing import Any, cast

# PDF
try:
    import pypdfium2 as _pdfium
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


# HTML & Chrome
try:
    from html2image import Html2Image as _Html2Image
except Exception:
    _Html2Image = cast(Any, None)

def html_available() -> bool:
    """Return True if html2image is installed."""
    return _Html2Image is not None

def chrome_available() -> bool:
    """Return True if html_available and Chrome is found."""
    if not html_available():
        return False
    try:
        _h2i = _Html2Image()
        return bool(_h2i.browser.executable)
    except Exception:
        return False


# Word
try:
    from docx import Document as _DocxDocument
except Exception:
    _DocxDocument = cast(Any, None)
try:
    import mammoth as _mammoth
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
    from openpyxl import load_workbook as _load_workbook
except Exception:
    _load_workbook = cast(Any, None)

def excel_available() -> bool:
    """Return True if Excel (.xlsx) preview dependencies are installed."""
    return _load_workbook is not None


# Markdown
try:
    import markdown as _markdown
except Exception:
    _markdown = cast(Any, None)

def markdown_available() -> bool:
    """Return True if rendered Markdown preview is available."""
    return _markdown is not None and html_available()


# Pygments
try:
    from pygments import highlight as _highlight
    from pygments.lexers import get_lexer_for_filename as _get_lexer
    from pygments.formatters import HtmlFormatter as _HtmlFormatter
    from pygments.util import ClassNotFound as _ClassNotFound
except Exception:
    _highlight = cast(Any, None)
    _get_lexer = cast(Any, None)
    _HtmlFormatter = cast(Any, None)
    _ClassNotFound = cast(Any, None)

def pygments_available() -> bool:
    """Return True if Pygments code highlighting dependencies are installed."""
    return _highlight is not None and html_available()


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
