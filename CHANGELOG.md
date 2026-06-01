# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added

- Linux and Windows CI for Python 3.10 and 3.13 with ruff, mypy, and pytest.
- Pytest annotations for failures reported by GitHub Actions.
- Maintainer release checklist in `docs/releasing.md`.
- Pure preview data loaders and focused tests for ZIP/7z, CSV/TSV, Excel, and SQLite.

### Changed

- Centralized archive member extraction in `DirectoryLister.extract_from_archive()`.
- Made dialog and preview resource cleanup idempotent.
- Extracted preview format routing into a dedicated registry.
- Expanded mypy coverage across pure filesystem and preview modules.

### Fixed

- Blocked oversized archive members before extraction while allowing configured preview-safe formats.
- Escaped SQLite table identifiers and bounded displayed rows and columns.
- Made filesystem and platform tests portable across CI runners.

## [1.0.0b1]

- Initial beta release.
