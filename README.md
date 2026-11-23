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

`fd.tag` is the DearPyGui tag of the dialog window. It is usually
`DialogConfig.tag`, but when that tag is already taken (two dialogs with the
default config) a `_xxxxxxxx` suffix is added, so read it from `fd.tag`
rather than assuming the configured value.

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
- `dialog/_state.py`, `dialog/_logic.py`, and `dialog/_ui.py` hold state, GUI-free behavior, and widget construction. Drive lists are computed off-thread and applied on the DearPyGui thread.
- `_preview_registry.py` routes file extensions, while `PreviewPanel` delegates rendering to format-specific classes in `renderers/`.
- Preview loaders such as `_preview_word.py` and `_preview_spreadsheet.py` return plain data and can be tested without a DearPyGui context.

## Rich Preview Panel

The integrated preview panel renders files directly inside the dialog:

- **Images** — native stb_image loading (PNG, JPEG, BMP, GIF, TGA, PSD, HDR, PNM) with Pillow for WebP, TIFF, ICO, DDS, PCX and AVIF; the first view fits the pane without cropping. Mouse wheel zooms toward the cursor; left-button drag pans. With Pillow and NumPy installed, large photos are shown from a texture capped at 2048 px on the long edge so they appear without stalling the UI.
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
| `preview` | `pip install dpg-navigator[preview]` | Pillow: more image formats (WebP, TIFF, ICO, ...) and faster large-image loading |
| `pdf` | `pip install dpg-navigator[pdf]` | PDF page rendering |
| `word` | `pip install dpg-navigator[word]` | Word document preview |
| `pptx` | `pip install dpg-navigator[pptx]` | PowerPoint slide preview |
| `html` | `pip install dpg-navigator[html]` | HTML rendered preview |
| `markdown` | `pip install dpg-navigator[markdown]` | Markdown rendered preview |
| `excel` | `pip install dpg-navigator[excel]` | Excel spreadsheet preview |
| `archive` | `pip install dpg-navigator[archive]` | 7z archive browsing |
| `all` | `pip install dpg-navigator[all]` | All of the above |

> **Chrome/Chromium required for some previews.** The `html`, `markdown`,
> and the pixel-perfect `word` previews render through **Chrome Headless**
> (driven by `html2image`'s `--screenshot` CLI). Installing the extra pulls in
> the Python packages but **not** a browser. The binary is looked up in
> `DPG_CHROME_BIN` (preferred), `CHROME_BIN`, `CHROME_PATH`, and then in the
> usual Chrome/Chromium install locations of each platform. Full Chrome for
> Testing can hang on `--screenshot`; the old-headless `chrome-headless-shell`
> binary from [Chrome for Testing](https://googlechromelabs.github.io/chrome-for-testing/)
> is the reliable CLI. Without a browser (or without the extra), HTML files are
> shown as raw text, and Markdown/Word fall back to their text extractors.
> What the browser is allowed to do is described in
> [HTML preview policy](#html-preview-policy).

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
    trusted_html_preview=False,
    file_filter=".*",
    allow_drag=True,
    show_dir_size=False,
)
```

Or via a `DialogConfig` object for full control (`DialogConfig` validates
sizes, filters, paths, and `custom_dirs` at construction; its fields are
keyword-only):

```python
from dpg_navigator import FileDialog, DialogConfig, DialogMode, StyleVariant

config = DialogConfig(
    mode=DialogMode.OPEN_DIRS,
    style=StyleVariant.COMPACT,
)
fd = FileDialog(callback=on_select, config=config)
```

`FileDialog(...)` keyword arguments and `DialogConfig` fields are the same set.
An invalid value raises `ValueError` or `TypeError` when the dialog or config
is created.

| Field | Default | Meaning |
|-------|---------|---------|
| `title` | `"File Dialog"` | Window title. |
| `tag` | `"dpg_navigator"` | DearPyGui tag of the window. If it is already taken, a `_xxxxxxxx` suffix is added; read the tag in use from `fd.tag`. |
| `width`, `height` | `950`, `650` | Initial window size in pixels; at least `min_size`. |
| `min_size` | `(460, 320)` | Smallest size the user can resize the window to. |
| `mode` | `DialogMode.OPEN_FILES` | `OPEN_FILES` lists files and folders and returns files; `OPEN_DIRS` lists and returns folders only. |
| `default_path` | `None` | Starting folder. `None` means the current working directory. |
| `filter_list` | `None` | Extensions in the filter combo, e.g. `[".*", ".py", ".txt"]`. `None` uses `DEFAULT_FILTER_LIST`; `[]` leaves the combo empty. |
| `file_filter` | `".*"` | Filter selected at start. Must be in `filter_list`. |
| `multi_selection` | `True` | Ctrl+click and Ctrl+A select several entries. |
| `show_preview` | `False` | Show the preview panel. |
| `preview_width` | `300` | Initial preview panel width in pixels; the user can resize it. |
| `trusted_html_preview` | `False` | Let raw `.html`/`.htm` previews run scripts and load resources. See [HTML preview policy](#html-preview-policy). |
| `show_hidden` | `False` | Show hidden files and folders. |
| `show_dir_size` | `False` | Compute folder sizes in the background (cached for 60 s). |
| `search_subfolders` | `True` | Show the "Subfolders" checkbox for recursive search. |
| `show_shortcuts` | `True` | Show the sidebar with special folders and drives. |
| `style` | `StyleVariant.LABELED` | Sidebar style: `LABELED` (icon and text) or `COMPACT` (icons only). |
| `custom_dirs` | `None` | Extra sidebar shortcuts as `(label, path)` pairs, e.g. `[("Projects", "D:/Projects")]`. |
| `allow_drag` | `True` | Rows can be dragged. See [Known limitations](#known-limitations). |
| `modal` | `True` | Block the other windows while the dialog is open. |
| `no_resize` | `False` | Lock the window at its initial size. |

## Public API and Versioning

From 1.0.0 the project follows [Semantic Versioning](https://semver.org/).
The public API, which breaking-change rules apply to, is:

- the names in `dpg_navigator.__all__`: `FileDialog`, `DialogConfig`,
  `DialogMode`, `StyleVariant`, `DEFAULT_FILTER_LIST`, `SelectionCallback`,
  `load_font_with_unicode`, and the `*_available()` probes;
- `FileDialog(...)` construction, the methods `show()`, `hide()`,
  `destroy()`, `change_callback()`, and the read-only `tag` property;
- the `DialogConfig` fields and their validation. Fields are keyword-only, so
  new fields may be added in a minor release.

Everything else is internal and may change in any release: modules whose
name starts with `_`, the `dialog/`, `renderers/` and `vfs/` subpackages,
and `FileDialog` attributes such as `state`, `logic` or `ui`.
`DEFAULT_FILTER_LIST` is public, but its entries may grow in a minor
release. New preview formats and new optional extras are minor-release
changes; removing an extra or a `*_available()` probe is a major-release
change.

## Security and Reliability

- **Path traversal protection** — rigorous validation of paths and folder names.
- **SQL injection hardening** — quoted identifiers for SQLite table browsing.
- **Binary file detection** — automatic detection of non-text files to prevent UI hangs.
- **ZipSlip protection** — safe extraction of archive entries with path validation.
- **Graceful degradation** — missing optional libraries are logged, never crash the dialog.
- **Memory efficiency** — LRU texture caching and background indexing for deep searches.
- **Safe HTML by default** — HTML, Markdown and Word previews cannot run
  scripts or reach the network unless you opt in. See
  [HTML preview policy](#html-preview-policy).
- **Thread-safe previews** — Chrome and image processing run in bounded workers;
  DearPyGui texture, widget, and callback work is applied by a frame callback
  under the DPG mutex. This requires DearPyGui 2.2 or newer.

## HTML preview policy

HTML, Markdown and Word (through mammoth) previews are rendered by headless
Chrome to an image. Each render gets a fresh temporary profile and output
folder, which are removed afterwards.

**Safe mode (default).** Before Chrome sees the page:

- the HTML is parsed against a structural allow-list (`bleach`). Scripts,
  event-handler attributes, `javascript:` URLs, forms, frames and author CSS
  are removed;
- local and network URLs are removed; only verified embedded `data:image`
  rasters (up to 512 KiB each) are kept;
- the page is wrapped in a Content-Security-Policy with `script-src 'none'`;
- Chrome sends all traffic, including loopback HTTP, to a dead proxy, so a
  leftover reference cannot reach the network.

**Trusted mode** (`trusted_html_preview=True`) applies only to raw
`.html`/`.htm` files. The file is rendered as it is: **JavaScript runs** and
the page may load local and network resources. Use it only for files you
trust. Markdown and Word previews always use safe mode.

Both modes keep the Chrome sandbox, a 2 MiB input limit and a 30-second
timeout per render. Containers or CI runners that cannot start the sandbox may
set `DPG_CHROME_NO_SANDBOX=1`, which weakens isolation and is never the
default.

## Known limitations

- **Legacy and OpenDocument formats** (`.doc`, `.xls`, `.ppt`, `.odt`,
  `.ods`, `.odp`) have no preview. Word preview covers `.docx`, Excel
  `.xlsx`/`.xlsm`, PowerPoint `.pptx`.
- **SVG cannot be previewed**: Pillow has no SVG decoder. **HEIC/HEIF** need
  the [`pillow-heif`](https://pypi.org/project/pillow-heif/) plugin registered
  by the host application (`pillow_heif.register_heif_opener()`); **AVIF**
  needs a Pillow build with AVIF support.
- **Previews are capped** to keep the dialog responsive: images up to 32 MiB
  and 8192 x 8192 px (shown from a texture of at most 2048 px), PDF up to
  50 MiB, Office files up to 32 MiB compressed (128 MiB unpacked), fonts up to
  16 MiB, HTML input up to 2 MiB. Text is read in 256 KiB pages. Tables (CSV,
  Excel, SQLite) show the first 200 rows and 50 columns; archives list their
  200 largest members.
- **Subfolder search** indexes up to 8 levels and 50,000 entries and shows at
  most 500 results.
- **Files opened inside an archive** are extracted to a session temp folder
  (members larger than 512 MiB are refused) and deleted when the last
  `FileDialog` is destroyed.
- **Drag and drop**: with `allow_drag=True` a row can be dragged (payload type
  `ws_<tag>`), but the payload carries no data yet, so a drop target cannot
  tell which file was dragged.
- **Non-ASCII filenames** need a font with the right glyphs; see
  [Unicode filenames](#unicode-filenames).

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
from dpg_navigator import load_font_with_unicode

with dpg.font_registry():
    ui_font = load_font_with_unicode("C:/Windows/Fonts/segoeui.ttf", 16)
dpg.bind_font(ui_font)
```

## Requirements

- Python >= 3.10
- [DearPyGui](https://pypi.org/project/dearpygui/) >= 2.2
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
# same ruff/mypy checks as a git hook (Python >= 3.10, venv must be active)
pre-commit install
pre-commit run --all-files
# opt-in real DearPyGui smoke (needs a display). CI runs this under xvfb
# as a required job (DPG_CHROME_NO_SANDBOX=1, chrome-headless-shell).
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
