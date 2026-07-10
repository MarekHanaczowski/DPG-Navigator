"""Tests for Word document loading used by the preview panel."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from dpg_navigator._preview_word import (
    WordParagraph,
    WordPreviewError,
    WordTable,
    load_word_document,
)


class TestLoadWordDocument:
    def test_loads_paragraphs_and_tables_in_document_order(self):
        paragraph = SimpleNamespace(
            text="Heading",
            style=SimpleNamespace(name="Heading 1"),
            runs=[
                SimpleNamespace(text="Head", bold=True, italic=False),
                SimpleNamespace(text="ing", bold=False, italic=True),
            ],
        )
        table = SimpleNamespace(rows=[
            SimpleNamespace(cells=[
                SimpleNamespace(text=" A "),
                SimpleNamespace(text=" B "),
            ]),
        ])
        document = SimpleNamespace(iter_inner_content=lambda: [paragraph, table])

        result = load_word_document(
            "sample.docx",
            document_loader=lambda path: document,
        )

        assert isinstance(result.blocks[0], WordParagraph)
        assert result.blocks[0].style_name == "heading 1"
        assert result.blocks[0].runs[0].bold is True
        assert result.blocks[0].runs[1].italic is True
        assert isinstance(result.blocks[1], WordTable)
        assert result.blocks[1].rows == [["A", "B"]]

    def test_falls_back_to_paragraphs_for_older_python_docx(self):
        paragraph = SimpleNamespace(text="Body", style=None, runs=[])
        document = SimpleNamespace(paragraphs=[paragraph])

        result = load_word_document(
            "legacy.docx",
            document_loader=lambda path: document,
        )

        assert result.blocks == [WordParagraph("Body", "", [])]

    def test_missing_backend_raises_preview_error(self):
        with pytest.raises(WordPreviewError):
            load_word_document("sample.docx", document_loader=None)
