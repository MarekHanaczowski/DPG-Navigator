"""UI Builder for the file dialog."""
from __future__ import annotations  # PEP 604/585 annotations need this on py3.8/3.9
import dearpygui.dearpygui as dpg
import os
import time

from ._state import DialogState
from ._logic import DialogLogic
from .._platform import get_drives, get_special_dirs
from .._types import DialogMode, FileEntry, DialogConfig
from .._filesystem import DirectoryLister
from .._job_manager import JobManager
from .._preview import PreviewPanel

class DialogUIBuilder:
    def __init__(self, dialog, state: DialogState, logic: DialogLogic, config: DialogConfig):
        self.dialog = dialog
        self.state = state
        self.logic = logic
        self.config = config

    def _render_entry(self, entry: FileEntry, *, relative_label: bool = False) -> None:
            """Render a single file/directory entry as a table row with icon.
    
            Args:
                entry: The file entry to render.
                relative_label: If True, display relative path instead of name
                    (used for deep-search results).
            """
            if entry.is_dir:
                icon_tag = self.dialog._icons.get_for_dir()
            else:
                icon_tag = self.dialog._icons.get_for_file(entry.name)
    
            # Label
            if relative_label:
                try:
                    label = os.path.relpath(entry.full_path, self.state.current_dir)
                except ValueError:
                    label = entry.full_path
            else:
                label = entry.name
    
            # Format display values
            display_time = DirectoryLister.format_time(entry.modified_time)
            display_type = "Dir" if entry.is_dir else "File"
            if entry.is_dir and self.config.show_dir_size and not relative_label:
                cached = self.state.size_cache.get(entry.full_path)
                if cached is not None and time.time() - cached[1] < self._SIZE_CACHE_TTL:
                    display_size = DirectoryLister.format_size(cached[0])
                else:
                    display_size = "..."
            else:
                display_size = DirectoryLister.format_size(entry.size_bytes)
    
            tint = (
                [255, 255, 255, self._image_transparency]
                if entry.is_hidden
                else [255, 255, 255, 255]
            )
    
            kwargs_cell = {
                "callback": self.dialog._on_entry_click,
                "span_columns": True,
                "height": self.dialog._selec_height,
                "user_data": entry,
            }
    
            with dpg.table_row(parent=self.dialog._explorer_table) as row_id:
                self.state.row_entries[row_id] = entry
    
                with dpg.group(horizontal=True):
                    if icon_tag:
                        dpg.add_image(icon_tag, tint_color=tint)
                    cell_name = dpg.add_selectable(label=label, **kwargs_cell)
    
                cell_time = dpg.add_selectable(label=display_time, **kwargs_cell)
                cell_type = dpg.add_selectable(label=display_type, **kwargs_cell)
                cell_size = dpg.add_selectable(label=display_size, **kwargs_cell)
    
                if entry.is_dir and self.config.show_dir_size and display_size == "...":
                    self.state.pending_size_cells[entry.full_path] = cell_size
    
                dpg.bind_item_theme(cell_name, self.dialog._selec_theme)
                dpg.bind_item_theme(cell_time, self.dialog._selec_theme)
                dpg.bind_item_theme(cell_type, self.dialog._selec_theme)
                dpg.bind_item_theme(cell_size, self.dialog._size_theme)
    
                if self.config.allow_drag:
                    drag = dpg.add_drag_payload(
                        parent=cell_name, payload_type=self._payload_type
                    )
                    if entry.is_dir:
                        folder_icon = self.dialog._icons.get("folder")
                        if folder_icon:
                            dpg.add_image(folder_icon, parent=drag)
                    elif os.path.splitext(entry.name)[1].lower() in PreviewPanel.preview_image_exts():
                        big_pic = self.dialog._icons.get("big_picture")
                        if big_pic:
                            dpg.add_image(big_pic, parent=drag)
                    else:
                        doc_icon = self.dialog._icons.get("document")
                        if doc_icon:
                            dpg.add_image(doc_icon, parent=drag)
    def _build_ui(self) -> None:
            """Construct the complete DPG widget tree."""
            self._build_themes()
            tag = self.config.tag
            info_px = 56
    
            with dpg.window(
                label=self.config.title,
                tag=tag,
                no_resize=self.config.no_resize,
                show=False,
                modal=self.config.modal,
                width=self.config.width,
                height=self.config.height,
                min_size=self.config.min_size,
                no_collapse=True,
                pos=(50, 50),
            ):
                with dpg.group(horizontal=True):
                    self._build_sidebar(tag, info_px)
                    self._build_explorer_area(info_px)
                self._build_bottom_bar()
                self.dialog._status_label = dpg.add_text(
                    "", color=[255, 80, 80], show=False
                )
    
            self._build_keyboard_handlers()
            if self.config.show_preview:
                self.dialog._preview.build_handlers(tag, self.dialog._is_dialog_active)
    def _build_themes(self) -> None:
            """Create shared selectable themes (once, reused across instances)."""
            if self.dialog._shared_selec_theme is None:
                with dpg.theme() as self.dialog._shared_selec_theme:
                    with dpg.theme_component(dpg.mvThemeCat_Core):
                        dpg.add_theme_style(
                            dpg.mvStyleVar_SelectableTextAlign, x=0, y=0.5
                        )
            if self.dialog._shared_size_theme is None:
                with dpg.theme() as self.dialog._shared_size_theme:
                    with dpg.theme_component(dpg.mvThemeCat_Core):
                        dpg.add_theme_style(
                            dpg.mvStyleVar_SelectableTextAlign, x=1, y=0.5
                        )
            if self.dialog._shared_preview_active_theme is None:
                with dpg.theme() as self.dialog._shared_preview_active_theme:
                    with dpg.theme_component(dpg.mvThemeCat_Core):
                        dpg.add_theme_color(
                            dpg.mvThemeCol_Button, (70, 130, 180, 255)
                        )
                        dpg.add_theme_color(
                            dpg.mvThemeCol_ButtonHovered, (80, 145, 200, 255)
                        )
                        dpg.add_theme_color(
                            dpg.mvThemeCol_ButtonActive, (60, 115, 160, 255)
                        )
            self.dialog._selec_theme = self.dialog._shared_selec_theme
            self.dialog._size_theme = self.dialog._shared_size_theme
            self.dialog._preview_btn: int | None = None
            self.dialog._instance_count += 1
    def _build_sidebar(self, tag: str, info_px: int) -> None:
            """Build the sidebar with shortcuts and drives."""
            if not self.config.show_shortcuts:
                return
            sidebar_tag = f"{tag}_shortcut_menu"
            with dpg.child_window(
                tag=sidebar_tag,
                width=self.dialog._sidebar.get_width(),
                resizable_x=self.dialog._sidebar.is_resizable(),
                height=-info_px,
            ):
                shortcuts = get_special_dirs()
                drives = get_drives()
                self.dialog._sidebar.render(
                    parent=sidebar_tag,
                    shortcuts=shortcuts,
                    drives=drives,
                    icons=self.dialog._icons,
                    on_navigate=self.logic.navigate_to,
                    custom_dirs=self.config.custom_dirs,
                )
    def _build_explorer_area(self, info_px: int) -> None:
            """Build the main explorer area: toolbar, search, table, preview."""
            with dpg.child_window(height=-info_px):
                self._build_toolbar()
                self._build_search_bar()
                self._build_new_folder_bar()
                self._build_explorer_table()
    def _build_toolbar(self) -> None:
            """Build the toolbar row (refresh, back, up, path, preview toggle)."""
            with dpg.group(horizontal=True):
                refresh_icon = self.dialog._icons.get("refresh")
                if refresh_icon:
                    btn = dpg.add_image_button(
                        refresh_icon,
                        callback=lambda s, ad, ud: self.logic.refresh_listing(),
                    )
                    with dpg.tooltip(btn):
                        dpg.add_text("Refresh (F5)")
    
                back_icon = self.dialog._icons.get("back")
                if back_icon:
                    btn = dpg.add_image_button(
                        back_icon,
                        callback=lambda s, ad, ud: self.logic.go_back(),
                    )
                    with dpg.tooltip(btn):
                        dpg.add_text("Back")
    
                up_icon = self.dialog._icons.get("up")
                if up_icon:
                    btn = dpg.add_image_button(
                        up_icon,
                        callback=lambda s, ad, ud: self.logic.go_up(),
                    )
                    with dpg.tooltip(btn):
                        dpg.add_text("Up (Alt+Up)")
    
                self.dialog._path_input = dpg.add_input_text(
                    hint="Path",
                    on_enter=True,
                    callback=self.dialog._on_path_enter,
                    default_value=self.state.current_dir,
                    width=-40 if self.config.show_preview else -1,
                )
                if self.config.show_preview:
                    preview_icon = self.dialog._icons.get("picture")
                    if preview_icon:
                        self.dialog._preview_btn = dpg.add_image_button(
                            preview_icon,
                            callback=lambda s, ad, ud: self.dialog._on_preview_toggle(),
                        )
                    else:
                        self.dialog._preview_btn = dpg.add_button(
                            label="P",
                            callback=lambda s, ad, ud: self.dialog._on_preview_toggle(),
                        )
                    with dpg.tooltip(self.dialog._preview_btn):
                        dpg.add_text("Preview")
                    if self.dialog._preview.visible:
                        dpg.bind_item_theme(
                            self.dialog._preview_btn,
                            self.dialog._shared_preview_active_theme,
                        )
    def _build_search_bar(self) -> None:
            """Build the search input row with new-folder button and optional subfolder checkbox."""
            with dpg.group(horizontal=True):
                add_folder_icon = self.dialog._icons.get("add_folder")
                if add_folder_icon:
                    btn = dpg.add_image_button(
                        add_folder_icon,
                        callback=lambda s, ad, ud: self._show_new_folder_dialog(),
                    )
                    with dpg.tooltip(btn):
                        dpg.add_text("New folder")
                search_icon = self.dialog._icons.get("search")
                if search_icon:
                    dpg.add_image(search_icon)
                self.dialog._search_input = dpg.add_input_text(
                    hint="Search files",
                    callback=self.dialog._on_search,
                    width=-120 if self.config.search_subfolders else -1,
                )
                if self.config.search_subfolders:
                    self.dialog._subfolder_checkbox = dpg.add_checkbox(
                        label="Subfolders",
                        default_value=True,
                        callback=self.dialog._on_subfolder_toggle,
                    )
                    with dpg.tooltip(self.dialog._subfolder_checkbox):
                        dpg.add_text("Search in subfolders")
    def _build_new_folder_bar(self) -> None:
            """Build the inline new-folder input bar (hidden by default)."""
            with dpg.group(
                horizontal=True, show=False
            ) as self.dialog._new_folder_group:
                add_folder_small = self.dialog._icons.get("mini_folder")
                if add_folder_small:
                    dpg.add_image(add_folder_small)
                self.dialog._new_folder_input = dpg.add_input_text(
                    hint="New folder name",
                    on_enter=True,
                    callback=self.dialog._on_new_folder_confirm,
                    width=-150,
                )
                dpg.add_button(
                    label="Create",
                    callback=lambda s, ad, ud: self.dialog._on_new_folder_confirm(s, ad, ud),
                )
                dpg.add_button(
                    label="Cancel",
                    callback=lambda s, ad, ud: dpg.hide_item(self.dialog._new_folder_group),
                )
    def _build_explorer_table(self) -> None:
            """Build the explorer table and optional preview panel."""
            with dpg.group(horizontal=True):
                table_width = (
                    -(self.config.preview_width + 8)
                    if self.config.show_preview
                    else -1
                )
                with dpg.child_window(
                    width=table_width,
                    height=-1,
                    resizable_x=self.config.show_preview,
                ) as table_wrapper:
                    with dpg.table(
                        height=-1,
                        width=-1,
                        resizable=True,
                        policy=dpg.mvTable_SizingStretchProp,
                        borders_innerV=True,
                        reorderable=True,
                        hideable=True,
                        scrollX=True,
                        scrollY=True,
                        sortable=True,
                        callback=self.dialog._on_sort,
                    ) as self.dialog._explorer_table:
                        dpg.add_table_column(label="Name", init_width_or_weight=100)
                        dpg.add_table_column(label="Date", init_width_or_weight=50)
                        dpg.add_table_column(label="Type", init_width_or_weight=10)
                        dpg.add_table_column(label="Size", init_width_or_weight=10)
    
                if self.config.show_preview:
                    with dpg.child_window(
                        width=-1, height=-1,
                        no_scroll_with_mouse=True,
                    ) as preview_panel:
                        dpg.add_text("Preview", color=[128, 128, 128])
                    self.dialog._preview.attach(table_wrapper, preview_panel)
                else:
                    self.dialog._preview.attach(table_wrapper, None)
    def _build_bottom_bar(self) -> None:
            """Build filename input, filter combo, and OK/Cancel buttons."""
            with dpg.group(horizontal=True):
                dpg.add_text("File name:")
                self.dialog._filename_input = dpg.add_input_text(
                    hint="",
                    on_enter=True,
                    callback=lambda s, ad, ud: self.dialog._on_ok(s, ad, ud),
                    width=-250,
                )
                dpg.add_combo(
                    items=self.dialog._filter_list,
                    callback=self.dialog._on_filter_change,
                    default_value=self.state.current_filter,
                    width=-1,
                )
    
            with dpg.table(
                header_row=False,
                policy=dpg.mvTable_SizingStretchProp,
                borders_innerV=False,
                borders_outerV=False,
                borders_innerH=False,
                borders_outerH=False,
                pad_outerX=False,
            ):
                dpg.add_table_column()
                dpg.add_table_column(width_fixed=True)
                dpg.add_table_column(width_fixed=True)
                with dpg.table_row():
                    dpg.add_spacer()
                    btn_ok = dpg.add_button(
                        label="  Open  ",
                        callback=self.dialog._on_ok,
                    )
                    with dpg.tooltip(btn_ok):
                        dpg.add_text("Confirm selection (Enter)")
                    btn_cancel = dpg.add_button(
                        label=" Cancel ",
                        callback=self.dialog._on_cancel,
                    )
                    with dpg.tooltip(btn_cancel):
                        dpg.add_text("Close dialog (Esc)")
    def _render_entries_list(self, entries: list[FileEntry]) -> None:
            with dpg.mutex():
                if hasattr(self, "_status_label") and dpg.does_item_exist(self.dialog._status_label):
                    dpg.hide_item(self.dialog._status_label)
    
                dpg.configure_item(self.dialog._path_input, default_value=self.state.current_dir)
    
                for child in dpg.get_item_children(self.dialog._explorer_table, 1):
                    dpg.delete_item(child)
    
                with dpg.table_row(parent=self.dialog._explorer_table):
                    dpg.add_selectable(
                        label="..",
                        callback=self.dialog._on_back,
                        span_columns=True,
                        height=self.dialog._selec_height,
                    )
    
                for entry in entries:
                    try:
                        self.dialog._render_entry(entry)
                    except Exception:
                        continue
