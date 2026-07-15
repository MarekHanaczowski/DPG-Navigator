import sys
import os

# Add parent directory to path so we can import dpg_navigator
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dearpygui.dearpygui as dpg  # type: ignore[import-untyped]
from dpg_navigator import FileDialog, DialogConfig

def main():
    dpg.create_context()
    
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
