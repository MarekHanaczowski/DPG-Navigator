# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

## [1.0.0b3] - 2026-07-08

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
- Removed a stray trailing-whitespace line in the text-preview pager.

### Changed

- Documented that HTML, Markdown, Word-HTML, and code previews require a
  Chrome/Chromium binary in addition to the Python `[html]` extra, with a
  security note about rendering untrusted HTML in headless Chrome.

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
