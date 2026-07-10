"""Tests for dpg_navigator.__init__ — public API re-exports and __all__."""

import pytest


class TestPublicAPI:
    """Verify that __init__.py correctly re-exports the public API."""

    def test_all_contains_expected_names(self):
        import dpg_navigator
        expected = {
            "FileDialog", "DialogConfig", "DialogMode", "StyleVariant",
            "FileEntry", "DEFAULT_FILTER_LIST",
            "word_available", "mammoth_available", "pptx_available",
            "markdown_available", "pdf_available", "html_available",
            "chrome_available",
            "excel_available", "py7zr_available", "pygments_available",
        }
        assert set(dpg_navigator.__all__) == expected

    def test_all_length(self):
        import dpg_navigator
        assert len(dpg_navigator.__all__) == 16

    def test_dialog_config_importable(self):
        from dpg_navigator import DialogConfig
        assert DialogConfig is not None

    def test_dialog_mode_importable(self):
        from dpg_navigator import DialogMode
        assert DialogMode is not None

    def test_style_variant_importable(self):
        from dpg_navigator import StyleVariant
        assert StyleVariant is not None

    def test_file_entry_importable(self):
        from dpg_navigator import FileEntry
        assert FileEntry is not None

    def test_dpg_navigator_importable(self):
        from dpg_navigator import FileDialog
        assert FileDialog is not None

    def test_reexports_match_source(self):
        """Verify re-exports point to the same objects as direct imports."""
        from dpg_navigator import DialogConfig, DialogMode, StyleVariant, FileEntry
        from dpg_navigator._types import (
            DialogConfig as _DC,
            DialogMode as _DM,
            StyleVariant as _SV,
            FileEntry as _FE,
        )
        assert DialogConfig is _DC
        assert DialogMode is _DM
        assert StyleVariant is _SV
        assert FileEntry is _FE

    def test_dpg_navigator_is_same_class(self):
        from dpg_navigator import FileDialog
        from dpg_navigator._dialog import FileDialog as _FD
        assert FileDialog is _FD

    def test_default_filter_list_in_all(self):
        """DEFAULT_FILTER_LIST is exported in __all__."""
        import dpg_navigator
        assert "DEFAULT_FILTER_LIST" in dpg_navigator.__all__

    def test_default_filter_list_importable(self):
        from dpg_navigator import DEFAULT_FILTER_LIST
        assert DEFAULT_FILTER_LIST is not None

    def test_version_defined(self):
        import dpg_navigator
        assert hasattr(dpg_navigator, "__version__")
        assert isinstance(dpg_navigator.__version__, str)
