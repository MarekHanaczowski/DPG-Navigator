# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

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
