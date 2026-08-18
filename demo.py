"""Interactive demo for dpg-navigator.

Opens a FileDialog with preview enabled. Needs a display. Bind a Unicode
font so Polish filenames render; see README "Unicode filenames".
"""

import os
import sys

if sys.platform == "win32":
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass

import dearpygui.dearpygui as dpg  # type: ignore[import-untyped]

from dpg_navigator import DialogConfig, FileDialog


def _bind_ui_font() -> None:
    candidates = []
    if sys.platform == "win32":
        windir = os.environ.get("WINDIR", r"C:\Windows")
        candidates.extend(
            [
                os.path.join(windir, "Fonts", "segoeui.ttf"),
                os.path.join(windir, "Fonts", "arial.ttf"),
                os.path.join(windir, "Fonts", "tahoma.ttf"),
            ]
        )
    elif sys.platform == "darwin":
        candidates.extend(
            [
                "/System/Library/Fonts/SFNS.ttf",
                "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
                "/Library/Fonts/Arial.ttf",
            ]
        )
    else:
        candidates.extend(
            [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
                "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
            ]
        )
    font_path = next((path for path in candidates if os.path.isfile(path)), None)
    if font_path is None:
        return
    try:
        from dpg_navigator.renderers.font import load_font_with_unicode

        with dpg.font_registry():
            font = load_font_with_unicode(font_path, 16)
    except Exception:
        try:
            with dpg.font_registry():
                font = dpg.add_font(font_path, 16)
        except Exception:
            return
    dpg.bind_font(font)


def main():
    dpg.create_context()
    _bind_ui_font()
    dpg.create_viewport(title="DPG Navigator - Modular Architecture Demo", width=1200, height=800)
    dpg.setup_dearpygui()
    config = DialogConfig(
        title="Choose a file",
        show_preview=True,
        default_path=os.getcwd(),
    )
    dialog = FileDialog(config)
    dialog.show()
    dpg.show_viewport()
    dpg.start_dearpygui()
    dialog.destroy()
    dpg.destroy_context()


if __name__ == "__main__":
    main()
