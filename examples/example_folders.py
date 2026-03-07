"""Example: folder picker dialog.

Demonstrates using FileDialog in OPEN_DIRS mode to select one or
multiple folders.  Selected folder paths are displayed in the main
window.
"""

import sys
import os

# Windows HiDPI fix — must be called before dpg.create_context()
if sys.platform == "win32":
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(2)

import dearpygui.dearpygui as dpg
from dpg_navigator import FileDialog, DialogMode

if __name__ == "__main__":
    dpg.create_context()

    # --- Font with Polish / Central European characters ---
    _FONT_PATH = "C:/Windows/Fonts/segoeui.ttf"
    if os.path.isfile(_FONT_PATH):
        with dpg.font_registry():
            font = dpg.add_font(_FONT_PATH, 16)
            dpg.add_font_range(0x0100, 0x017F, parent=font)
        dpg.bind_font(font)

    def on_folders(selected):
        dpg.delete_item("result", children_only=True)
        for path in selected:
            dpg.add_text(path, parent="result")

    fd = FileDialog(
        callback=on_folders,
        title="Select Folder(s)",
        default_path="..",
        mode=DialogMode.OPEN_DIRS,
        multi_selection=True,
        show_dir_size=True,
    )

    with dpg.window(label="Folder Picker Example", height=480, width=600):
        dpg.add_button(label="Pick folder(s)", callback=lambda: fd.show())
        dpg.add_child_window(width=-1, height=-1, tag="result")

    dpg.create_viewport(title="Folder picker example")
    dpg.setup_dearpygui()
    dpg.show_viewport()
    dpg.start_dearpygui()
    fd.destroy()
    dpg.destroy_context()
