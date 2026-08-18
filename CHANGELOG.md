# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added

- Font preview loads Unicode-aware fonts with Polish diacritics and common
  punctuation (€, dashes, quotes); explicit glyph-range registration is used only
  on DearPyGui versions that require it, with pangrams including „Zazółć gęślą jaźń”.
- CI generates a CycloneDX SBOM (`sbom.cdx.json`, artifact `sbom-cyclonedx`).
- PDF preview supports mouse-wheel page navigation and updates the page counter.
- Preview routing now includes the live `.ttf`/`.otf` font renderer.
- Public `SelectionCallback` protocol types the host OK handler as
  `list[str] → None`. `FileDialog` constructor overloads distinguish
  `DialogConfig` from keyword options. `DialogConfig` validates sizes, filters,
  paths, and `custom_dirs` at construction.
- `THIRD_PARTY_NOTICES.md` lists bundled Icons8 assets and SPDX licenses for
  packages declared in `pyproject.toml`. The file ships in the sdist and is
  force-included in the wheel.
- `.pre-commit-config.yaml` runs ruff, `ruff format`, and mypy from the
  active `[dev]` environment. `pre-commit` is a `[dev]` extra on Python >= 3.9.
- CI enforces 75% coverage on GUI-free preview loaders, VFS, and dialog logic
  (Ubuntu 3.13 job only).

### Changed

- GitHub Actions third-party steps are pinned to commit SHAs (not floating tags)
  in `ci.yml` and `publish.yml`.
- Tests cover ZipSlip extraction (ZIP/7z), DialogLogic archive navigation
  (`navigate_to`, `go_up`, `go_back`), Word HTML vs text preview switching, and
  FileDialog refusal of oversize archive members on OK/Enter.
- Source-code preview is documented as monospace text; the `[code]` extra no
  longer claims Pygments/Chrome highlighting or pulls html2image.
- HTML preview docs match Chrome flags: JavaScript is disabled and network
  access is blocked; the overflow marker does not run while JS is off.
- CI jobs run with `permissions: contents: read`. Dependabot watches GitHub
  Actions and pip dependencies weekly.
- Background work runs on a bounded daemon thread pool (8 workers) instead of
  one OS thread per task. Shutdown cancels queued jobs so they never start, and
  logs a warning if workers are still running after the join timeout.
- HTML and PDF preview cancel the previous render/prefetch `Future` on close and
  when a new job is submitted, so a queued Chrome/pypdfium2 task is skipped.
- HTML preview owns in-flight Chrome child processes: `close()` kills that
  preview's browser tree, and last `FileDialog.destroy()` kills any leftover
  before deleting the session profile. The 30s subprocess timeout remains a
  backstop.
- CI runs the opt-in DearPyGui smoke tests under xvfb (`continue-on-error`),
  installing Chrome and `chrome-headless-shell`, and setting
  `DPG_CHROME_NO_SANDBOX=1` so HTML/Word-HTML screenshots can start. Cases still
  skip when no browser is resolvable. The xvfb job points html2image at
  `chrome-headless-shell` via `DPG_CHROME_BIN`.
- `requirements.txt` no longer duplicates dependency pins; it installs this
  project from `pyproject.toml`.
- Ruff lint covers pyflakes, whitespace, isort, bugbear, pyupgrade, and
  simplify (`target-version` py38). CI also runs `ruff format --check`.
- mypy type-checks the whole `dpg_navigator` package (tests excluded) from
  `[tool.mypy] files` with `disallow_untyped_defs`, `warn_return_any`, and
  `disallow_any_generics`. Optional backends use `OptionalModule` instead of
  `cast(Any, None)`.
- `ruff format --check` skips Markdown (`*.md`). Ruff 0.16+ otherwise rewrites
  Python fences in README and audit notes.

### Fixed

- HTML preview Chrome flags: the dead proxy is unquoted
  `--proxy-server=http://127.0.0.1:1` (quoted `127.0.0.1:0` can hang the
  screenshot on POSIX). `file://` HTML bypasses that proxy
  (`--proxy-bypass-list=<-loopback>`). CI/`DPG_CHROME_NO_SANDBOX` adds
  `--no-zygote` and skips `--disable-gpu`. The xvfb job runs
  `chrome-headless-shell` because full Chrome for Testing hangs on
  html2image's `--screenshot` CLI. Integration smokes wait past the 30s
  Chrome subprocess timeout.
- Sidebar drive lists are applied on the DearPyGui thread via a frame
  callback, not from a worker inside `dpg.mutex()`, so two dialogs no longer
  segfault under xvfb during `render_dearpygui_frame`.
- Text preview binary/UTF-16 detection now inspects real BOM and NUL bytes
  instead of escaped ASCII lookalikes, so UTF-16 files decode and binary files
  are no longer shown as cp1250 garbage.
- Background listing and directory-size updates marshal through `FileDialog`'s
  `_safe_*` helpers (destroyed check + `dpg.mutex()`), instead of calling DPG
  directly from worker threads.
- Confirming a selection inside an archive (Enter or OK, not only double-click)
  extracts the member before invoking the host callback.
- The Subfolders checkbox now updates `search_subfolders` and drops deep-search
  rows when unchecked.
- `html_available()` / `chrome_available()` are implemented once in `_html.py`
  (`html2image` + numpy + Pillow, cached Chrome binary). `_availability`
  delegates instead of probing html2image alone.
- Excel preview stops after the display bound instead of scanning the whole
  sheet, and reports `N+` when more rows remain.
- Alt+Up, Enter on the `..` row, and double-click on `..` call `DialogLogic.go_up()`,
  so archive virtual paths leave the archive instead of mangling the `|` path.
- PDF and STB/Pillow image previews refuse files above a size cap before decode.
- HTML preview strips `file:` URLs and keeps Chrome's user-data dir plus PNG
  output in a per-session temp folder removed on last `FileDialog.destroy()`.
- HTML screenshot PNGs are read from Chrome's session output directory, not the
  process temp root.

## [1.0.0b3] - 2026-07-10

### Fixed

- HTML preview now falls back to raw-text rendering when the HTML backend
  (html2image + Chrome) is unavailable, instead of leaving a stale preview.
- Extracted archive temp files are cleaned up only when the last dialog
  instance is destroyed, so closing one dialog no longer deletes preview
  files another dialog is still using.
- Recursive search index now honors `show_hidden` (hidden directories are
  descended only when enabled) and no longer follows symlinked directories,
  which could let the index escape the selected tree or loop on cycles.
- Search input reads (`get_value`/`does_item_exist`) in the debounced search
  worker now happen inside `dpg.mutex()`; only plain Python values cross the
  mutex boundary, closing a race with dialog teardown and navigation.
- Selecting a member inside an archive (double-click) now extracts with an
  anti-bomb size cap instead of extracting unbounded data to disk.
- Word `.docx` files are again rendered pixel-perfect through mammoth + Chrome
  when that backend is available (the router previously always used the
  python-docx text fallback), matching the documented behavior.
- The Chrome screenshot subprocess now runs with a timeout, so a hung browser
  is killed and the render fails cleanly instead of leaving the panel stuck on
  "Rendering..." forever.
- Removed a stray trailing-whitespace line in the text-preview pager.

### Added

- `chrome_available()` detects whether a Chrome/Chromium binary is resolvable
  (not just the Python packages). HTML preview now degrades to raw text when
  the browser binary is missing, instead of failing at render time.

### Changed

- Documented that HTML, Markdown, Word-HTML, and code previews require a
  Chrome/Chromium binary in addition to the Python `[html]` extra, with a
  security note about rendering untrusted HTML in headless Chrome.
- The publish workflow now runs the full CI quality gate (ruff, mypy, pytest)
  before building or publishing any distribution.
- CI now covers macOS and Python 3.11/3.12 (matching the declared support) and
  runs an informational `pip-audit` dependency scan.
- Lowered the minimum supported Python from 3.10 to **3.8**. All modules now use
  `from __future__ import annotations`, the `slots=True` dataclass option (3.10+)
  was dropped, and the non-cryptographic MD5 naming falls back gracefully where
  `usedforsecurity` is unavailable (3.8). Note: on 3.8/3.9 some optional preview
  backends resolve to older releases, since their latest versions require newer
  Python.

### Performance

- The recursive search index is capped at 50,000 entries; a huge tree keeps a
  usable partial index instead of growing unbounded in memory.
- Archive member listing uses a top-k selection instead of sorting the full
  member list, keeping the cost roughly linear for archives with many members.
- SQLite previews use a bounded row count (scanning at most 100,000 rows and
  reporting `N+`) instead of a full `COUNT(*)` on large tables.

## [1.0.0b2] - 2026-06-01

### Added

- Linux and Windows CI for Python 3.10 and 3.13 with ruff, mypy, and pytest.
- Pytest annotations for failures reported by GitHub Actions.
- Maintainer release checklist in `docs/releasing.md`.
- Pure preview data loaders and focused tests for ZIP/7z, CSV/TSV, Excel, and SQLite.
- Pure Word and PowerPoint content loaders with focused tests.
- Heavy-path benchmark runner and a Windows/Python 3.13 baseline.

### Changed

- Centralized archive member extraction in `DirectoryLister.extract_from_archive()`.
- Made dialog and preview resource cleanup idempotent.
- Extracted preview format routing into a dedicated registry.
- Expanded mypy coverage across pure filesystem, preview, platform, icon, style, and keyboard modules.

### Fixed

- Blocked oversized archive members before extraction while allowing configured preview-safe formats.
- Escaped SQLite table identifiers and bounded displayed rows and columns.
- Made filesystem and platform tests portable across CI runners.
- Released PowerPoint inline-image textures when previews change or the panel is destroyed.

## [1.0.0b1]

- Initial beta release.
