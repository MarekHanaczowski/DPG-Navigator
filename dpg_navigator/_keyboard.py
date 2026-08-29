"""Keyboard shortcut and table navigation mixin for FileDialog.

Provides ESC, F5, Ctrl+A, Up/Down/Enter, and Alt+Up (go up) key handlers,
arrow-key table navigation, and mouse wheel/drag handlers for preview
panel resize, cursor-anchored image zoom, image pan, PDF page scrolling,
and HTML scroll.  This is a mixin class — it accesses ``self._*``
attributes defined by the host :class:`FileDialog`.
"""

from __future__ import annotations

# MIT licensed
from typing import TYPE_CHECKING, Any

import dearpygui.dearpygui as dpg  # type: ignore[import-untyped]

from . import _platform
from ._filesystem import DirectoryIndex
from ._types import DialogConfig, DialogMode, FileEntry

if TYPE_CHECKING:
    from ._preview import PreviewPanel
    from .dialog._logic import DialogLogic


class KeyboardMixin:
    """Mixin: Esc/F5/Ctrl+A/arrows/Enter and Alt+Up (archive-aware go up).

    Expected attributes on the mixing-in class (provided by FileDialog):

    - ``_config`` (DialogConfig)
    - ``_explorer_table`` (int)
    - ``_row_entries`` (dict[int, FileEntry])
    - ``_selected_files`` (list[str])
    - ``_selected_elements`` (list[int])
    - ``_last_clicked_element`` (int | None)
    - ``_focused_row_index`` (int)
    - ``_filename_input`` (int)
    - ``_path_input`` (int)
    - ``_new_folder_input`` (int)
    - ``_search_input`` (int)
    - ``_size_cache`` (dict)
    - ``_dir_index`` (DirectoryIndex)
    - ``_preview`` (PreviewPanel)
    - ``hide()``, ``_navigate_to()``, ``_refresh_listing()``,
      ``_return_selection()``, ``_start_index_build()``
    - ``logic`` (DialogLogic)
    """

    _config: DialogConfig
    _explorer_table: int
    _row_entries: dict[int, FileEntry]
    _selected_files: list[str]
    _selected_elements: list[int]
    _last_clicked_element: int | None
    _focused_row_index: int
    _filename_input: int
    _path_input: int
    _new_folder_input: int
    _search_input: int
    _size_cache: dict[Any, Any]
    _dir_index: DirectoryIndex
    _preview: PreviewPanel
    _current_dir: str
    _key_handler: int
    logic: DialogLogic

    if TYPE_CHECKING:

        def hide(self) -> None: ...
        def _navigate_to(self, path: str) -> None: ...
        def _refresh_listing(self) -> None: ...
        def _return_selection(self) -> None: ...
        def _start_index_build(self) -> None: ...

    def _is_dialog_active(self) -> bool:
        """True when this dialog is shown and has focus (window or a child).

        Global DPG key handlers must not steal Esc/Enter/Ctrl+A from the host
        while a non-modal dialog is merely visible.
        """
        tag = self._config.tag
        if not (dpg.does_item_exist(tag) and dpg.is_item_shown(tag)):
            return False
        try:
            if dpg.get_active_window() == tag:
                return True
        except Exception:
            pass
        try:
            if dpg.is_item_focused(tag):
                return True
        except Exception:
            pass
        for item in (
            getattr(self, "_path_input", None),
            getattr(self, "_filename_input", None),
            getattr(self, "_new_folder_input", None),
            getattr(self, "_search_input", None),
            getattr(self, "_explorer_table", None),
        ):
            if item is None:
                continue
            try:
                if dpg.does_item_exist(item) and (dpg.is_item_focused(item) or dpg.is_item_active(item)):
                    return True
            except Exception:
                continue
        return False

    def _dialog_text_input_active(self) -> bool:
        """True when a dialog text input or filter combo is capturing keys."""
        for item in (
            getattr(self, "_path_input", None),
            getattr(self, "_filename_input", None),
            getattr(self, "_new_folder_input", None),
            getattr(self, "_search_input", None),
            getattr(self, "_filter_combo", None),
        ):
            if item is None:
                continue
            try:
                if dpg.does_item_exist(item) and dpg.is_item_active(item):
                    return True
            except Exception:
                continue
        return False

    # ── Key handlers ───────────────────────────────────────────

    def _on_key_escape(self, sender: Any, app_data: Any, user_data: Any) -> None:
        """ESC: close the dialog."""
        if self._is_dialog_active():
            self.hide()

    def _on_key_f5(self, sender: Any, app_data: Any, user_data: Any) -> None:
        """F5: refresh the file listing and clear size/index caches."""
        if self._is_dialog_active():
            self._size_cache.clear()
            self._dir_index.invalidate()
            self._refresh_listing()

    def _on_key_a(self, sender: Any, app_data: Any, user_data: Any) -> None:
        """Ctrl+A: select all visible entries."""
        if (
            not self._is_dialog_active()
            or not _platform.is_mod_key_down()
            or not self._config.multi_selection
            or self._dialog_text_input_active()
        ):
            return
        for child in dpg.get_item_children(self._explorer_table, 1):
            row_children = dpg.get_item_children(child, 1)
            for widget in row_children:
                ud = dpg.get_item_user_data(widget)
                if isinstance(ud, FileEntry):
                    dpg.set_value(widget, True)
                    if ud.full_path not in self._selected_files:
                        self._selected_files.append(ud.full_path)
                        self._selected_elements.append(widget)
                    break

    def _on_key_up(self, sender: Any, app_data: Any, user_data: Any) -> None:
        """Up: move focus to previous row. Alt+Up: navigate to parent."""
        if not self._is_dialog_active():
            return
        if dpg.is_key_down(dpg.mvKey_LAlt) or dpg.is_key_down(dpg.mvKey_RAlt):
            self.logic.go_up()
        else:
            self._move_focus(-1)

    def _on_key_down(self, sender: Any, app_data: Any, user_data: Any) -> None:
        """Down: move focus to next row in the explorer table."""
        if self._is_dialog_active():
            self._move_focus(1)

    def _on_key_enter(self, sender: Any, app_data: Any, user_data: Any) -> None:
        """Enter: activate the focused row (navigate dir or select file).

        Skipped when an input field is active so that path/filename/search
        inputs keep their normal Enter behaviour.
        """
        if not self._is_dialog_active() or self._focused_row_index < 0:
            return
        if self._dialog_text_input_active():
            return
        self._activate_focused_row()

    # ── Table navigation ───────────────────────────────────────

    def _move_focus(self, delta: int) -> None:
        """Move the keyboard focus by *delta* rows (+1 = down, -1 = up)."""
        rows = dpg.get_item_children(self._explorer_table, 1)
        if not rows:
            return
        if self._focused_row_index < 0:
            new_index = 0 if delta > 0 else len(rows) - 1
        else:
            new_index = self._focused_row_index + delta
        new_index = max(0, min(new_index, len(rows) - 1))
        if new_index == self._focused_row_index:
            return
        self._select_row_by_index(new_index)

    def _select_row_by_index(self, index: int) -> None:
        """Visually select a table row by its index and update state.

        Handles both the ".." back-row (no ``FileEntry``) and regular
        data rows.  Deselects any previous selection first.
        """
        rows = dpg.get_item_children(self._explorer_table, 1)
        if index < 0 or index >= len(rows):
            return

        # Deselect previous
        for elem in self._selected_elements:
            if dpg.does_item_exist(elem):
                dpg.set_value(elem, False)
        self._selected_files.clear()
        self._selected_elements.clear()
        if self._last_clicked_element is not None and dpg.does_item_exist(self._last_clicked_element):
            dpg.set_value(self._last_clicked_element, False)

        self._focused_row_index = index
        row_id = rows[index]
        entry = self._row_entries.get(row_id)

        if entry is None:
            # ".." back row — single selectable as direct child
            children = dpg.get_item_children(row_id, 1)
            if children:
                dpg.set_value(children[0], True)
                self._last_clicked_element = children[0]
            self._preview.clear()
            return

        # Data row — find first selectable that carries the FileEntry.
        # The Name selectable is inside a horizontal group, so we must
        # also search one level deeper in group children.
        found = False
        for widget in dpg.get_item_children(row_id, 1):
            if isinstance(dpg.get_item_user_data(widget), FileEntry):
                dpg.set_value(widget, True)
                self._last_clicked_element = widget
                self._selected_elements.append(widget)
                found = True
                break
            for child in dpg.get_item_children(widget, 1) or []:
                if isinstance(dpg.get_item_user_data(child), FileEntry):
                    dpg.set_value(child, True)
                    self._last_clicked_element = child
                    self._selected_elements.append(child)
                    found = True
                    break
            if found:
                break

        if entry.is_dir:
            if self._config.mode == DialogMode.OPEN_DIRS:
                self._selected_files = [entry.full_path]
        else:
            self._selected_files = [entry.full_path]
            dpg.set_value(self._filename_input, entry.name)

        self._preview.update(entry)

    def _activate_focused_row(self) -> None:
        """Activate the currently focused row (Enter key action)."""
        rows = dpg.get_item_children(self._explorer_table, 1)
        if self._focused_row_index < 0 or self._focused_row_index >= len(rows):
            return
        row_id = rows[self._focused_row_index]
        entry = self._row_entries.get(row_id)

        if entry is None:
            self.logic.go_up()
        elif entry.is_dir:
            self._navigate_to(entry.full_path)
        else:
            self._return_selection()

    # ── Handler registry construction ──────────────────────────

    def _build_keyboard_handlers(self) -> None:
        """Create the global DPG handler registry with keyboard shortcuts.

        If preview is enabled, also registers left-button click/drag/release
        (image pan plus the resizable-x splitter re-layout) and a mouse
        wheel handler (cursor-anchored image zoom, PDF paging, HTML scroll).
        """
        with dpg.handler_registry() as self._key_handler:
            dpg.add_key_press_handler(dpg.mvKey_Escape, callback=self._on_key_escape)
            dpg.add_key_press_handler(dpg.mvKey_F5, callback=self._on_key_f5)
            dpg.add_key_press_handler(dpg.mvKey_A, callback=self._on_key_a)
            dpg.add_key_press_handler(dpg.mvKey_Up, callback=self._on_key_up)
            dpg.add_key_press_handler(dpg.mvKey_Down, callback=self._on_key_down)
            dpg.add_key_press_handler(dpg.mvKey_Return, callback=self._on_key_enter)
            if self._config.show_preview:
                dpg.add_mouse_click_handler(
                    button=dpg.mvMouseButton_Left,
                    callback=self._preview.on_mouse_down,
                )
                dpg.add_mouse_drag_handler(
                    button=dpg.mvMouseButton_Left,
                    threshold=0,
                    callback=self._preview.on_mouse_drag,
                )
                dpg.add_mouse_release_handler(
                    button=dpg.mvMouseButton_Left,
                    callback=self._preview.on_mouse_up,
                )
                dpg.add_mouse_drag_handler(
                    button=dpg.mvMouseButton_Left,
                    callback=self._preview.on_resize,
                )
                dpg.add_mouse_wheel_handler(
                    callback=self._preview.on_mouse_wheel,
                )
