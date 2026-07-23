"""Sidebar style renderers for the dpg_navigator package.

Provides SidebarRenderer ABC and two implementations:
- LabeledSidebar: icon + text labels with resizable directory tree.
- CompactSidebar: icon-only buttons in a narrow sidebar.
"""

from __future__ import annotations
# MIT licensed

import os
from abc import ABC, abstractmethod
from typing import Callable

import dearpygui.dearpygui as dpg  # type: ignore[import-untyped]

from ._types import StyleVariant
from ._icons import IconRegistry
from . import _platform

# Mapping: shortcut display name -> icon name
_SHORTCUT_ICON_MAP = {
    "Home": "home",
    "Desktop": "desktop",
    "Downloads": "downloads",
    "Pictures": "picture_folder",
    "Documents": "documents",
    "Music": "music",
    "Videos": "videos",
}


class SidebarRenderer(ABC):
    """Abstract base for sidebar renderers."""

    @abstractmethod
    def get_width(self) -> int:
        """Return the default width in pixels for this sidebar style."""
        ...

    @abstractmethod
    def is_resizable(self) -> bool:
        """Return whether the sidebar supports user-resizing."""
        ...

    @abstractmethod
    def render(
        self,
        parent: int | str,
        shortcuts: dict[str, str],
        drives: list[str],
        icons: IconRegistry,
        on_navigate: Callable[[str], None],
        custom_dirs: list[tuple[str, str]] | None = None,
    ) -> None:
        """Build the sidebar widgets inside the given parent container."""
        ...

    def update_drives(self, drives: list[str]) -> None:
        """Update mounted drives after background enumeration."""
        ...


class LabeledSidebar(SidebarRenderer):
    """Style 0: icon + text label, resizable sidebar with directory tree."""

    _MAX_TREE_DEPTH: int = 10

    def __init__(self):
        """Initialize the labeled sidebar renderer.

        All instance attributes are declared here; they are populated
        in render() when the sidebar is built.
        """
        self._on_navigate: Callable[[str], None] | None = None
        self._icons: IconRegistry | None = None
        self._drives: list[str] = []
        self._expanded: set[str] = set()
        self._tree_container: int | None = None

    def get_width(self) -> int:
        """Return the default width in pixels for this sidebar style."""
        return 200

    def is_resizable(self) -> bool:
        """Return whether the sidebar supports user-resizing."""
        return True

    def render(self, parent, shortcuts, drives, icons, on_navigate, custom_dirs=None):
        """Build icon + text shortcut list and expandable drive tree."""
        self._on_navigate = on_navigate
        self._icons = icons
        self._drives = drives
        self._expanded = set()

        # Shortcuts (Home, Desktop, etc.) — flat list
        for name, path in shortcuts.items():
            icon_name = _SHORTCUT_ICON_MAP.get(name, "folder")
            icon_tag = icons.get(icon_name)
            with dpg.group(horizontal=True, parent=parent):
                if icon_tag:
                    dpg.add_image(icon_tag)
                dpg.add_menu_item(
                    label=name,
                    callback=lambda s, ad, ud: on_navigate(ud),
                    user_data=path,
                )

        # Custom user directories
        if custom_dirs:
            dpg.add_separator(parent=parent)
            folder_tag = icons.get("folder")
            for label, path in custom_dirs:
                with dpg.group(horizontal=True, parent=parent):
                    if folder_tag:
                        dpg.add_image(folder_tag)
                    dpg.add_menu_item(
                        label=label,
                        callback=lambda s, ad, ud: on_navigate(ud),
                        user_data=path,
                    )

        dpg.add_separator(parent=parent)

        # Container for the tree table (rebuilt on expand/collapse)
        self._tree_container = dpg.add_group(parent=parent)
        self._rebuild_tree()

    def update_drives(self, drives: list[str]) -> None:
        self._drives = drives
        if self._tree_container is not None and dpg.does_item_exist(self._tree_container):
            self._rebuild_tree()

    def _rebuild_tree(self) -> None:
        """Rebuild the entire drive tree table from current expanded state."""
        dpg.delete_item(self._tree_container, children_only=True)
        with dpg.table(
            parent=self._tree_container,
            header_row=False,
            policy=dpg.mvTable_SizingStretchProp,
            pad_outerX=False,
            borders_innerH=False,
            borders_outerH=False,
            borders_innerV=False,
            borders_outerV=False,
        ):
            dpg.add_table_column()
            for drive in self._drives:
                self._add_tree_row(drive, drive, "hd", 0)

    def _add_tree_row(self, dir_path: str, label: str, icon_name: str, depth: int) -> None:
        """Add a single directory row to the current tree table context."""
        if depth > self._MAX_TREE_DEPTH:
            return
        if self._icons is None:
            return
        is_expanded = dir_path in self._expanded
        arrow_char = "v " if is_expanded else "> "
        indent = "  " * depth

        with dpg.table_row():
            with dpg.group(horizontal=True):
                dpg.add_text(indent + arrow_char)
                icon_tag = self._icons.get(icon_name)
                if icon_tag:
                    dpg.add_image(icon_tag)
                dpg.add_selectable(
                    label=label,
                    span_columns=True,
                    callback=lambda s, ad, ud: self._on_row_click(ud),
                    user_data=dir_path,
                )

        if is_expanded:
            try:
                items = sorted(os.listdir(dir_path), key=str.lower)
                found = False
                for item_name in items:
                    full_path = os.path.join(dir_path, item_name)
                    try:
                        if os.path.isdir(full_path) and not _platform.is_hidden(full_path):
                            self._add_tree_row(full_path, item_name, "mini_folder", depth + 1)
                            found = True
                    except OSError:
                        continue
                if not found:
                    with dpg.table_row():
                        dpg.add_text("  " * (depth + 1) + "  (empty)")
            except PermissionError:
                with dpg.table_row():
                    dpg.add_text("  " * (depth + 1) + "  (access denied)")
            except OSError:
                with dpg.table_row():
                    dpg.add_text("  " * (depth + 1) + "  (error)")

    def _on_row_click(self, dir_path: str) -> None:
        """Toggle expand/collapse for a directory tree node.

        Navigates to the directory only when expanding, not when collapsing.
        """
        if dir_path in self._expanded:
            self._expanded.discard(dir_path)
        else:
            self._expanded.add(dir_path)
            if self._on_navigate is not None:
                self._on_navigate(dir_path)
        self._rebuild_tree()


class CompactSidebar(SidebarRenderer):
    """Style 1: icon-only buttons, narrow sidebar (~40px)."""

    def __init__(self):
        self._on_navigate: Callable[[str], None] | None = None
        self._icons: IconRegistry | None = None
        self._drive_container: int | str | None = None

    def get_width(self) -> int:
        """Return the default width in pixels for this sidebar style."""
        return 40

    def is_resizable(self) -> bool:
        """Return whether the sidebar supports user-resizing."""
        return False

    def render(self, parent, shortcuts, drives, icons, on_navigate, custom_dirs=None):
        """Render icon-only shortcut buttons and drive buttons in a narrow sidebar."""
        self._on_navigate = on_navigate
        self._icons = icons
        for name, path in shortcuts.items():
            icon_name = _SHORTCUT_ICON_MAP.get(name, "folder")
            icon_tag = icons.get(icon_name)
            if icon_tag:
                dpg.add_image_button(
                    icon_tag,
                    callback=lambda s, ad, ud: on_navigate(ud),
                    user_data=path,
                    parent=parent,
                )

        # Custom user directories
        if custom_dirs:
            dpg.add_separator(parent=parent)
            folder_tag = icons.get("folder")
            for label, path in custom_dirs:
                if folder_tag:
                    btn = dpg.add_image_button(
                        folder_tag,
                        callback=lambda s, ad, ud: on_navigate(ud),
                        user_data=path,
                        parent=parent,
                    )
                else:
                    btn = dpg.add_button(
                        label=label[:2],
                        callback=lambda s, ad, ud: on_navigate(ud),
                        user_data=path,
                        parent=parent,
                    )
                with dpg.tooltip(btn):
                    dpg.add_text(label)

        dpg.add_separator(parent=parent)

        self._drive_container = dpg.add_group(parent=parent)
        self._render_drives(drives)

    def update_drives(self, drives: list[str]) -> None:
        if self._drive_container is None or self._icons is None:
            return
        if dpg.does_item_exist(self._drive_container):
            dpg.delete_item(self._drive_container, children_only=True)
            self._render_drives(drives)

    def _render_drives(self, drives: list[str]) -> None:
        if self._icons is None or self._drive_container is None or self._on_navigate is None:
            return
        hd_tag = self._icons.get("hd")
        for drive in drives:
            if hd_tag:
                dpg.add_image_button(
                    hd_tag,
                    user_data=drive,
                    callback=lambda s, ad, ud: self._on_navigate(ud),
                    parent=self._drive_container,
                )
            else:
                dpg.add_button(
                    label=os.path.basename(drive) or drive,
                    user_data=drive,
                    callback=lambda s, ad, ud: self._on_navigate(ud),
                    parent=self._drive_container,
                )


STYLE_REGISTRY: dict[StyleVariant, type[SidebarRenderer]] = {
    StyleVariant.LABELED: LabeledSidebar,
    StyleVariant.COMPACT: CompactSidebar,
}
