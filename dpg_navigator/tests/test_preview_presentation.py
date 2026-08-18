"""Tests for PowerPoint document loading used by the preview panel."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from dpg_navigator._preview_presentation import (
    PresentationPreviewError,
    load_presentation,
)


class TestLoadPresentation:
    def test_loads_tables_images_text_and_notes(self):
        table_shape = SimpleNamespace(
            has_table=True,
            table=SimpleNamespace(
                rows=[
                    SimpleNamespace(
                        cells=[
                            SimpleNamespace(text=" A "),
                            SimpleNamespace(text=" B "),
                        ]
                    ),
                ]
            ),
        )
        text_shape = SimpleNamespace(
            has_table=False,
            shape_type=1,
            image=SimpleNamespace(blob=b"image-bytes"),
            has_text_frame=True,
            text_frame=SimpleNamespace(
                paragraphs=[
                    SimpleNamespace(
                        text="Indented",
                        level=2,
                        runs=[
                            SimpleNamespace(
                                text="Indented",
                                font=SimpleNamespace(bold=True, italic=False),
                            ),
                        ],
                    ),
                ]
            ),
        )
        slide = SimpleNamespace(
            shapes=[table_shape, text_shape],
            notes_slide=SimpleNamespace(
                notes_text_frame=SimpleNamespace(text=" Speaker note "),
            ),
        )
        presentation = SimpleNamespace(slides=[slide])

        result = load_presentation(
            "sample.pptx",
            presentation_loader=lambda path: presentation,
        )

        loaded_slide = result.slides[0]
        assert loaded_slide.shapes[0].table.rows == [["A", "B"]]
        assert loaded_slide.shapes[1].image_blob == b"image-bytes"
        assert loaded_slide.shapes[1].paragraphs[0].level == 2
        assert loaded_slide.shapes[1].paragraphs[0].runs[0].bold is True
        assert loaded_slide.notes == "Speaker note"

    def test_missing_notes_are_ignored(self):
        slide = SimpleNamespace(shapes=[])
        presentation = SimpleNamespace(slides=[slide])

        result = load_presentation(
            "sample.pptx",
            presentation_loader=lambda path: presentation,
        )

        assert result.slides[0].notes == ""

    def test_missing_backend_raises_preview_error(self):
        with pytest.raises(PresentationPreviewError):
            load_presentation("sample.pptx", presentation_loader=None)
