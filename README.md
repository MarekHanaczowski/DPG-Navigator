# dpg-navigator

File dialog with rich preview panel for [DearPyGui](https://github.com/hoffstadt/DearPyGui) — images, PDF, Word, Excel, code highlighting, archives, and more.

Inspired by [file_dialog](https://github.com/totallynotdrait/file_dialog) by Dr. AIT. Rebuilt from scratch as a modular, fully typed, cross-platform library.

## Installation

From PyPI:

```bash
pip install dpg-navigator
```

With all optional preview dependencies:

```bash
pip install dpg-navigator[all]
```

From source:

```bash
pip install .
```

## Quick Start

```python
import dearpygui.dearpygui as dpg
from dpg_navigator import FileDialog

dpg.create_context()

def on_select(selected_files):
    for f in selected_files:
        print(f)

fd = FileDialog(callback=on_select, default_path="..")

with dpg.window(label="Main", width=400, height=200):
    dpg.add_button(label="Open file dialog", callback=lambda: fd.show())

dpg.create_viewport(title="Example")
dpg.setup_dearpygui()
dpg.show_viewport()
dpg.start_dearpygui()
fd.destroy()
dpg.destroy_context()
```

The callback can be changed at any time via `fd.change_callback(new_handler)`.

## Features

- Modal or non-modal file and directory picker
- Modern 3D Fluency icons for 100+ file extensions
- Sidebar with special directories and an expandable drive tree
- Real-time search with recursive subfolder indexing
- File type filtering and multi-selection (Ctrl+click, Ctrl+A)
- Asynchronous directory size calculation with caching
- Keyboard navigation: Esc, F5, Ctrl+A, Alt+Up (Cmd on macOS)
- Drag-and-drop payload support
- Hidden files toggle
- New folder creation with path traversal protection
- Two sidebar styles: labeled (icon + text) and compact (icon-only)
- Cross-platform: Windows, Linux, macOS

## Rich Preview Panel

The integrated preview panel renders files directly inside the dialog:

- **Images** — native stb_image loading with Pillow fallback for WebP, TIFF, HEIC, and SVG; aspect-ratio scaling and centering.
- **PDF** — page-by-page rendering via pypdfium2 with mouse wheel navigation, LRU cache, and background prefetch.
- **Word (.docx)** — pixel-perfect HTML render via mammoth + Chrome Headless, or python-docx styled text extraction as fallback.
- **PowerPoint (.pptx)** — slide text, tables, speaker notes, and inline image extraction via python-pptx.
- **Markdown** — rendered preview using the `markdown` library piped through Chrome Headless with a dark theme.
- **HTML** — Chrome Headless rendering with a scrollable viewport, overflow detection, auto-trim, and responsive resize.
- **CSV / TSV** — native DPG table with automatic delimiter detection via `csv.Sniffer`.
- **Excel (.xlsx)** — read-only table display via openpyxl with sheet switching.
- **SQLite (.db)** — read-only table browsing with table switching.
- **Fonts (.ttf / .otf)** — live glyph preview with pangrams.
- **Archives (.zip / .7z)** — file list with compression ratios; click a row to extract and preview.
- **Source code** — syntax highlighting for 500+ languages via Pygments, rendered through Chrome Headless.
- **XML** — pretty-printed via minidom.

Each renderer is optional — missing dependencies are detected at import time and the dialog gracefully falls back to a plain text view.

## Optional Dependencies

Preview features are organized into installable extras:

| Extra | Command | What it enables |
|-------|---------|-----------------|
| `preview` | `pip install dpg-navigator[preview]` | Enhanced image formats (WebP, TIFF, SVG) |
| `pdf` | `pip install dpg-navigator[pdf]` | PDF page rendering |
| `word` | `pip install dpg-navigator[word]` | Word document preview |
| `pptx` | `pip install dpg-navigator[pptx]` | PowerPoint slide preview |
| `html` | `pip install dpg-navigator[html]` | HTML rendered preview |
| `markdown` | `pip install dpg-navigator[markdown]` | Markdown rendered preview |
| `excel` | `pip install dpg-navigator[excel]` | Excel spreadsheet preview |
| `archive` | `pip install dpg-navigator[archive]` | 7z archive browsing |
| `code` | `pip install dpg-navigator[code]` | Syntax-highlighted source code |
| `all` | `pip install dpg-navigator[all]` | All of the above |

## Configuration

All options can be passed as keyword arguments:

```python
fd = FileDialog(
    callback=on_select,
    title="Open File",
    width=950,
    height=650,
    default_path="/home/user",
    modal=True,
    multi_selection=True,
    show_hidden=False,
    show_preview=True,
    file_filter=".*",
    allow_drag=True,
    show_dir_size=False,
)
```

Or via a `DialogConfig` object for full control:

```python
from dpg_navigator import FileDialog, DialogConfig, DialogMode, StyleVariant

config = DialogConfig(
    mode=DialogMode.OPEN_DIRS,
    style=StyleVariant.COMPACT,
)
fd = FileDialog(callback=on_select, config=config)
```

## Security and Reliability

- **Path traversal protection** — rigorous validation of paths and folder names.
- **SQL injection hardening** — quoted identifiers for SQLite table browsing.
- **Binary file detection** — automatic detection of non-text files to prevent UI hangs.
- **ZipSlip protection** — safe extraction of archive entries with path validation.
- **Graceful degradation** — missing optional libraries are logged, never crash the dialog.
- **Memory efficiency** — LRU texture caching and background indexing for deep searches.

## HiDPI / 4K Displays (Windows)

Add this **before** `dpg.create_context()` to prevent blurry fonts under Windows display scaling:

```python
import sys
if sys.platform == "win32":
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
```

## Requirements

- Python >= 3.10
- [DearPyGui](https://pypi.org/project/dearpygui/) >= 1.9.1
- [psutil](https://pypi.org/project/psutil/) >= 5.9.0

## Development

```bash
pip install -e ".[dev]"
python -m ruff check .
python -m mypy dpg_navigator/_types.py dpg_navigator/_filesystem.py dpg_navigator/_platform.py dpg_navigator/_icons.py dpg_navigator/_styles.py dpg_navigator/_keyboard.py dpg_navigator/_preview_registry.py dpg_navigator/_preview_table.py dpg_navigator/_preview_archive.py dpg_navigator/_preview_spreadsheet.py dpg_navigator/_preview_sqlite.py dpg_navigator/_preview_word.py dpg_navigator/_preview_presentation.py dpg_navigator/_preview.py dpg_navigator/_dialog.py dpg_navigator/_pdf.py dpg_navigator/_html.py
pytest
```

Maintainer release steps are documented in [docs/releasing.md](docs/releasing.md).

Performance-sensitive pure-data paths can be measured with:

```bash
python benchmarks/benchmark_heavy_paths.py --profile default --iterations 3
```

See [benchmarks/README.md](benchmarks/README.md) for the quick profile and JSON output.

## Author

Created and maintained by **HACE**.

## Credits

- Original concept: [file_dialog](https://github.com/totallynotdrait/file_dialog) by Dr. AIT
- Icons: [Icons8 — 3D Fluency](https://icons8.com/icons/3d-fluency)

## License

[MIT](LICENSE) — Copyright (c) 2024–2026 HACE
