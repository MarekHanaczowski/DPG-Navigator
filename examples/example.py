import sys
import os

# Windows HiDPI fix — must be called before dpg.create_context()
if sys.platform == "win32":
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(2)

import dearpygui.dearpygui as dpg
from dpg_navigator import FileDialog

if __name__ == "__main__":
    dpg.create_context()

    # --- Font with Polish / Central European characters ---
    # DPG default font only covers Basic Latin.
    # To display filenames with ąćęłńóśźż etc., load a system font
    # with Latin Extended-A range (0x0100-0x017F).
    _FONT_PATH = "C:/Windows/Fonts/segoeui.ttf"  # Windows default
    # Linux:  "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    # macOS:  "/System/Library/Fonts/SFNS.ttf"
    if os.path.isfile(_FONT_PATH):
        try:
            from dpg_navigator.renderers.font import load_font_with_unicode
            with dpg.font_registry():
                font = load_font_with_unicode(_FONT_PATH, 16)
        except Exception:
            with dpg.font_registry():
                font = dpg.add_font(_FONT_PATH, 16)
        dpg.bind_font(font)

    def on_select(selected_files):
        dpg.delete_item("txt_child", children_only=True)
        for file in selected_files:
            dpg.add_text(file, parent="txt_child")

    fd = FileDialog(callback=on_select, default_path="..", show_dir_size=True, show_preview=True)

    with dpg.window(label="Example", height=480, width=600):
        dpg.add_button(label="Open file dialog", callback=lambda: fd.show())
        dpg.add_child_window(width=-1, height=-1, tag="txt_child")

    dpg.create_viewport(title="dpg_navigator example")
    dpg.setup_dearpygui()
    dpg.show_viewport()
    dpg.start_dearpygui()
    fd.destroy()
    dpg.destroy_context()
