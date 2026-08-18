# dpg-navigator

File dialog with rich preview panel for [DearPyGui](https://github.com/hoffstadt/DearPyGui) — images, PDF, Word, Excel, archives, and more.

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

Runtime and extra dependencies are declared only in [`pyproject.toml`](pyproject.toml).
`requirements.txt` is a pointer so `pip install -r requirements.txt` still
installs this project; do not add version pins there.

Third-party licenses (including bundled Icons8 assets) are listed in
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

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

Selecting a file **inside** an archive (Enter, OK, or double-click) extracts it
to a session temp directory and passes that real filesystem path to the
callback. Those temp files are deleted when the **last** `FileDialog` in the
process is `destroy()`ed — copy or open them before tearing down the dialog if
the host still needs the bytes.

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

## Architecture

The package keeps filesystem/search logic separate from DearPyGui rendering:

- `FileDialog` orchestrates the dialog and public lifecycle.
- `dialog/_state.py`, `dialog/_logic.py`, and `dialog/_ui.py` hold state, GUI-free behavior, and widget construction.
- `_preview_registry.py` routes file extensions, while `PreviewPanel` delegates rendering to format-specific classes in `renderers/`.
- Preview loaders such as `_preview_word.py` and `_preview_spreadsheet.py` return plain data and can be tested without a DearPyGui context.

## Rich Preview Panel

The integrated preview panel renders files directly inside the dialog:

- **Images** — native stb_image loading with Pillow fallback for WebP, TIFF, HEIC, and SVG; aspect-ratio scaling and centering.
- **PDF** — page-by-page rendering via pypdfium2 with mouse wheel navigation over the preview panel (wheel down = next page, wheel up = previous page), LRU cache, and background prefetch.
- **Word (.docx)** — pixel-perfect HTML render via mammoth + Chrome Headless, or python-docx styled text extraction as fallback.
- **PowerPoint (.pptx)** — slide text, tables, speaker notes, and inline image extraction via python-pptx.
- **Markdown** — rendered preview using the `markdown` library piped through Chrome Headless with a dark theme.
- **HTML** — Chrome Headless rendering with a scrollable viewport, auto-trim, and responsive resize.
- **CSV / TSV** — native DPG table with automatic delimiter detection via `csv.Sniffer`.
- **Excel (.xlsx)** — read-only table display via openpyxl with sheet switching.
- **SQLite (.db)** — read-only table browsing with table switching.
- **Fonts (.ttf / .otf)** — live glyph preview with pangrams.
- **Archives (.zip / .7z)** — file list with compression ratios; click a row to extract and preview.
- **Source code** — monospace text preview (same encoding detection as other text files).
- **XML** — pretty-printed via minidom.

Optional preview backends are detected at import time. When a preview-specific dependency or browser is unavailable, the dialog falls back to a text view or an explanatory message instead of failing during import.

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
| `code` | `pip install dpg-navigator[code]` | Source-code files as text (`pygments_available()` / routing) |
| `all` | `pip install dpg-navigator[all]` | All of the above |

> **Chrome/Chromium required for some previews.** The `html`, `markdown`,
> and the pixel-perfect `word` previews render through **Chrome
> Headless** (driven by `html2image`). Installing the extra pulls in the Python
> packages but **not** a browser — a Chrome or Chromium binary must be present
> on the system `PATH`. If none is found (or a preview extra is not installed),
> HTML files fall back to raw-text rendering, and Markdown/Word degrade to
> their text extractors, so the dialog stays usable. Chrome is launched with
> JavaScript disabled and network access blocked through a dead proxy.

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

Or via a `DialogConfig` object for full control (`DialogConfig` validates
sizes, filters, paths, and `custom_dirs` at construction):

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
- **Untrusted HTML** — HTML, Markdown, and Word HTML previews are rendered by a
  headless Chrome subprocess. JavaScript is disabled (`--disable-javascript`)
  and outbound network access is blocked (`--proxy-server=http://127.0.0.1:1`
  with `--proxy-bypass-list=<-loopback>` so `file://` preview HTML is not
  proxied, `--block-new-web-contents`). Width overflow detection still injects a JS
  marker, which does not run while JS is off, so very wide documents may not
  trigger a second screenshot. Local `file:` URLs are stripped from HTML before
  render. Preview only content you trust.

## HiDPI / 4K Displays (Windows)

Add this **before** `dpg.create_context()` to prevent blurry fonts under Windows display scaling:

```python
import sys
if sys.platform == "win32":
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
```

## Unicode filenames

DearPyGui's default font does not contain every Unicode glyph. If the dialog must
show filenames with Polish or other non-ASCII characters, bind a system font with
Unicode coverage after `dpg.create_context()` and before creating `FileDialog`.
The demo and examples use the helper below, which also handles older DearPyGui
versions that need explicit glyph ranges:

```python
from dpg_navigator.renderers.font import load_font_with_unicode

with dpg.font_registry():
    ui_font = load_font_with_unicode("C:/Windows/Fonts/segoeui.ttf", 16)
dpg.bind_font(ui_font)
```

## Requirements

- Python >= 3.8
- [DearPyGui](https://pypi.org/project/dearpygui/) >= 1.9.1
- [psutil](https://pypi.org/project/psutil/) >= 5.9.0
- [bleach](https://pypi.org/project/bleach/) >= 6.0
- [defusedxml](https://pypi.org/project/defusedxml/) >= 0.7.1

## Development

```bash
pip install -e ".[dev]"
python -m ruff check .
python -m ruff format --check .
python -m mypy
pytest
python -m pytest -q --cov=dpg_navigator --cov-report=term-missing
# same ruff/mypy checks as a git hook (Python >= 3.9, venv must be active)
pre-commit install
pre-commit run --all-files
# opt-in real DearPyGui smoke (needs a display)
DPG_INTEGRATION=1 pytest -m integration
# headless Linux:
xvfb-run -a env DPG_INTEGRATION=1 pytest -m integration
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
- Icons: [Icons8 — 3D Fluency](https://icons8.com/icons/3d-fluency) ([icons8.com](https://icons8.com))

## License

[MIT](LICENSE) — Copyright (c) 2024–2026 HACE

Bundled icons and declared third-party packages: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
