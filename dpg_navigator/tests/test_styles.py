"""Tests for dpg_navigator._styles — sidebar renderers.

Tests pure logic and constants; DPG widget calls are mocked.
"""

import os
from unittest.mock import MagicMock, patch, call

import pytest

from dpg_navigator._types import StyleVariant
from dpg_navigator._styles import (
    SidebarRenderer,
    LabeledSidebar,
    CompactSidebar,
    STYLE_REGISTRY,
    _SHORTCUT_ICON_MAP,
)


# ── STYLE_REGISTRY ──────────────────────────────────────────────


class TestStyleRegistry:
    def test_is_dict(self):
        assert isinstance(STYLE_REGISTRY, dict)

    def test_has_labeled(self):
        assert StyleVariant.LABELED in STYLE_REGISTRY

    def test_has_compact(self):
        assert StyleVariant.COMPACT in STYLE_REGISTRY

    def test_labeled_maps_to_class(self):
        assert STYLE_REGISTRY[StyleVariant.LABELED] is LabeledSidebar

    def test_compact_maps_to_class(self):
        assert STYLE_REGISTRY[StyleVariant.COMPACT] is CompactSidebar

    def test_covers_all_variants(self):
        for variant in StyleVariant:
            assert variant in STYLE_REGISTRY, f"{variant} missing from STYLE_REGISTRY"

    def test_all_values_are_sidebar_subclasses(self):
        for cls in STYLE_REGISTRY.values():
            assert issubclass(cls, SidebarRenderer)


# ── _SHORTCUT_ICON_MAP ──────────────────────────────────────────


class TestShortcutIconMap:
    def test_is_dict(self):
        assert isinstance(_SHORTCUT_ICON_MAP, dict)

    def test_has_expected_keys(self):
        expected = {"Home", "Desktop", "Downloads", "Pictures", "Documents", "Music", "Videos"}
        assert set(_SHORTCUT_ICON_MAP.keys()) == expected

    def test_all_values_are_strings(self):
        for name, icon in _SHORTCUT_ICON_MAP.items():
            assert isinstance(icon, str), f"{name}: icon is not string"
            assert len(icon) > 0, f"{name}: icon is empty"

    def test_all_icon_names_exist_in_icon_registry(self):
        """Every icon name in _SHORTCUT_ICON_MAP must exist in ICON_NAMES."""
        from dpg_navigator._icons import ICON_NAMES
        icon_set = set(ICON_NAMES)
        for name, icon in _SHORTCUT_ICON_MAP.items():
            assert icon in icon_set, (
                f"_SHORTCUT_ICON_MAP[{name!r}] = {icon!r} not in ICON_NAMES"
            )


# ── LabeledSidebar ──────────────────────────────────────────────


class TestLabeledSidebar:
    def test_init_attributes(self):
        sidebar = LabeledSidebar()
        assert sidebar._on_navigate is None
        assert sidebar._icons is None
        assert sidebar._drives == []
        assert sidebar._expanded == set()
        assert sidebar._tree_container is None

    def test_get_width(self):
        assert LabeledSidebar().get_width() == 200

    def test_is_resizable(self):
        assert LabeledSidebar().is_resizable() is True

    def test_on_row_click_expand_navigates(self):
        """Expanding a node should call on_navigate."""
        sidebar = LabeledSidebar()
        sidebar._on_navigate = MagicMock()
        sidebar._expanded = set()
        sidebar._icons = MagicMock()
        sidebar._drives = []
        sidebar._tree_container = MagicMock()

        with patch("dpg_navigator._styles.dpg") as mock_dpg:
            mock_dpg.delete_item = MagicMock()
            mock_dpg.table = MagicMock(return_value=MagicMock(__enter__=MagicMock(), __exit__=MagicMock()))
            mock_dpg.add_table_column = MagicMock()

            sidebar._on_row_click("/some/path")

        assert "/some/path" in sidebar._expanded
        sidebar._on_navigate.assert_called_once_with("/some/path")

    def test_on_row_click_collapse_does_not_navigate(self):
        """Collapsing a node should NOT call on_navigate."""
        sidebar = LabeledSidebar()
        sidebar._on_navigate = MagicMock()
        sidebar._expanded = {"/some/path"}
        sidebar._icons = MagicMock()
        sidebar._drives = []
        sidebar._tree_container = MagicMock()

        with patch("dpg_navigator._styles.dpg") as mock_dpg:
            mock_dpg.delete_item = MagicMock()
            mock_dpg.table = MagicMock(return_value=MagicMock(__enter__=MagicMock(), __exit__=MagicMock()))
            mock_dpg.add_table_column = MagicMock()

            sidebar._on_row_click("/some/path")

        assert "/some/path" not in sidebar._expanded
        sidebar._on_navigate.assert_not_called()

    def test_on_row_click_toggle(self):
        """Clicking twice should expand then collapse."""
        sidebar = LabeledSidebar()
        sidebar._on_navigate = MagicMock()
        sidebar._expanded = set()
        sidebar._icons = MagicMock()
        sidebar._drives = []
        sidebar._tree_container = MagicMock()

        with patch("dpg_navigator._styles.dpg") as mock_dpg:
            mock_dpg.delete_item = MagicMock()
            mock_dpg.table = MagicMock(return_value=MagicMock(__enter__=MagicMock(), __exit__=MagicMock()))
            mock_dpg.add_table_column = MagicMock()

            sidebar._on_row_click("/path")
            assert "/path" in sidebar._expanded

            sidebar._on_row_click("/path")
            assert "/path" not in sidebar._expanded


# ── CompactSidebar ──────────────────────────────────────────────


class TestCompactSidebar:
    def test_get_width(self):
        assert CompactSidebar().get_width() == 40

    def test_is_resizable(self):
        assert CompactSidebar().is_resizable() is False


# ── SidebarRenderer ABC ────────────────────────────────────────


class TestSidebarRendererABC:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            SidebarRenderer()

    def test_subclass_must_implement_all(self):
        """Incomplete subclass should raise TypeError on instantiation."""
        class Incomplete(SidebarRenderer):
            def get_width(self):
                return 100
            # Missing is_resizable and render

        with pytest.raises(TypeError):
            Incomplete()

    def test_complete_subclass_works(self):
        class Complete(SidebarRenderer):
            def get_width(self):
                return 100
            def is_resizable(self):
                return False
            def render(self, parent, shortcuts, drives, icons, on_navigate):
                pass

        instance = Complete()
        assert instance.get_width() == 100
        assert instance.is_resizable() is False
