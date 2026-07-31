import sys
import os

# Add parent directory to path so we can import dpg_navigator
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dearpygui.dearpygui as dpg  # type: ignore[import-untyped]
from dpg_navigator import FileDialog, DialogConfig


def _bind_ui_font() -> None:
    windows_dir = os.environ.get("WINDIR", r"C:\Windows")
    font_candidates = {
        "win32": [
            os.path.join(windows_dir, "Fonts", "segoeui.ttf"),
            os.path.join(windows_dir, "Fonts", "arial.ttf"),
        ],
        "linux": [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        ],
        "darwin": [
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/System/Library/Fonts/SFNS.ttf",
        ],
    }
    for font_path in font_candidates.get(sys.platform, []):
        if os.path.isfile(font_path):
            with dpg.font_registry():
                font = dpg.add_font(font_path, 16)
            dpg.bind_font(font)
            return


def main():
    dpg.create_context()
    _bind_ui_font()
    
    # Configure DPG
    dpg.create_viewport(title="DPG Navigator - Modular Architecture Demo", width=1200, height=800)
    dpg.setup_dearpygui()

    # Use the new modular preview!
    config = DialogConfig(
        title="Choose a file (Modular Dialog + Preview ON)",
        show_preview=True,
        default_path=os.getcwd()
    )

    dialog = FileDialog(config)
    dialog.show()

    dpg.show_viewport()
    dpg.start_dearpygui()
    dpg.destroy_context()

if __name__ == "__main__":
    main()
