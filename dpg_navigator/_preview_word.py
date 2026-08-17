"""Word document loading for the preview panel.

Extracts document blocks without depending on DearPyGui.
"""

from __future__ import annotations

# MIT licensed
from dataclasses import dataclass
from typing import Any, Callable, Union

_DocxDocument: Any
try:
    from docx import Document as _DocxDocument  # type: ignore[import-untyped]
except Exception:  # optional backend absent or incompatible (e.g. old Python)
    _DocxDocument = None


class WordPreviewError(Exception):
    """Word document data could not be loaded."""


@dataclass(frozen=True)
class WordRun:
    """Inline text with the formatting used by the preview panel."""

    text: str
    bold: bool
    italic: bool


@dataclass(frozen=True)
class WordParagraph:
    """Paragraph text and formatting metadata."""

    text: str
    style_name: str
    runs: list[WordRun]


@dataclass(frozen=True)
class WordTable:
    """Table rows extracted from a Word document."""

    rows: list[list[str]]


# Runtime type alias — a plain assignment (not an annotation), so
# `from __future__ import annotations` does not stringify it; use Union so it
# evaluates on Python < 3.10.
WordBlock = Union[WordParagraph, WordTable]


@dataclass(frozen=True)
class WordDocument:
    """Preview-ready Word document blocks."""

    blocks: list[WordBlock]


def word_available() -> bool:
    """Return True when Word document loading is available."""
    return _DocxDocument is not None


def load_word_document(
    path: str,
    *,
    document_loader: Callable[..., Any] | None = _DocxDocument,
) -> WordDocument:
    """Load Word document blocks in display order."""
    if document_loader is None:
        raise WordPreviewError("python-docx is not installed")

    try:
        document = document_loader(path)
    except Exception as exc:
        raise WordPreviewError(str(exc)) from exc

    try:
        source_blocks = document.iter_inner_content()
    except AttributeError:
        source_blocks = document.paragraphs

    blocks: list[WordBlock] = []
    try:
        for block in source_blocks:
            if hasattr(block, "rows"):
                blocks.append(WordTable([[cell.text.strip() for cell in row.cells] for row in block.rows]))
                continue

            style_name = ""
            if block.style and block.style.name:
                style_name = block.style.name.lower()
            blocks.append(
                WordParagraph(
                    text=block.text,
                    style_name=style_name,
                    runs=[WordRun(run.text, bool(run.bold), bool(run.italic)) for run in block.runs],
                )
            )
    except Exception as exc:
        raise WordPreviewError(str(exc)) from exc

    return WordDocument(blocks)
