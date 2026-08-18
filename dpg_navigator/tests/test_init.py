"""Tests for dpg_navigator.__init__ — public API re-exports and __all__."""

from __future__ import annotations

from unittest.mock import patch


class TestPublicAPI:
    """Verify that __init__.py correctly re-exports the public API."""

    def test_all_contains_expected_names(self):
        import dpg_navigator

        expected = {
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
        }
        assert set(dpg_navigator.__all__) == expected

    def test_all_length(self):
        import dpg_navigator

        assert len(dpg_navigator.__all__) == 17

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
        from dpg_navigator import DialogConfig, DialogMode, FileEntry, SelectionCallback, StyleVariant
        from dpg_navigator._types import (
            DialogConfig as _DC,
        )
        from dpg_navigator._types import (
            DialogMode as _DM,
        )
        from dpg_navigator._types import (
            FileEntry as _FE,
        )
        from dpg_navigator._types import (
            SelectionCallback as _SC,
        )
        from dpg_navigator._types import (
            StyleVariant as _SV,
        )

        assert DialogConfig is _DC
        assert DialogMode is _DM
        assert StyleVariant is _SV
        assert FileEntry is _FE
        assert SelectionCallback is _SC

    def test_default_filter_list_in_all(self):
        """DEFAULT_FILTER_LIST is exported in __all__."""
        import dpg_navigator

        assert "DEFAULT_FILTER_LIST" in dpg_navigator.__all__

    def test_default_filter_list_importable(self):
        from dpg_navigator import DEFAULT_FILTER_LIST

        assert DEFAULT_FILTER_LIST is not None

    def test_html_and_chrome_probes_delegate_to_html_module(self):
        """Public availability probes must use _html.py, not a second copy."""
        import dpg_navigator._html as htmlmod
        from dpg_navigator._availability import chrome_available, html_available

        with patch.object(htmlmod, "html_available", return_value=True):
            assert html_available() is True
        with patch.object(htmlmod, "html_available", return_value=False):
            assert html_available() is False
        with patch.object(htmlmod, "chrome_available", return_value=True):
            assert chrome_available() is True
        with patch.object(htmlmod, "chrome_available", return_value=False):
            assert chrome_available() is False

    def test_version_defined(self):
        import dpg_navigator

        assert hasattr(dpg_navigator, "__version__")
        assert isinstance(dpg_navigator.__version__, str)
