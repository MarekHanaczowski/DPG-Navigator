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

### Changed

- GitHub Actions third-party steps are pinned to commit SHAs (not floating tags)
  in `ci.yml` and `publish.yml`.

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
