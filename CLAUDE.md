# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`dpg-navigator` — a file/directory picker widget for [DearPyGui](https://github.com/hoffstadt/DearPyGui) with a rich preview panel (images, PDF, Word, Excel, PowerPoint, Markdown, HTML, CSV, SQLite, fonts, archives, source code as text). Installable library; import root is `dpg_navigator`. Supports Python 3.8–3.13, Windows/Linux/macOS. Version is `__version__` in `dpg_navigator/__init__.py` (currently a `1.0.0b*` beta).

## Commands

```bash
pip install -e ".[dev]"          # dev install (pulls in the [all] preview extras)

python -m ruff check .           # lint (E9,F,W,I,B,UP,SIM; target py38)
python -m ruff format --check .  # format gate (same as CI)
python -m mypy                   # package type check via [tool.mypy] files= (skip 3.8/3.9 in CI)
                                 # flags include disallow_untyped_defs, warn_return_any, disallow_any_generics
python -m pytest -q              # run the unit test suite
python -m pytest -q --cov=dpg_navigator --cov-report=term-missing
                                 # coverage gate on pure loaders/VFS/dialog logic (fail_under=75)
pre-commit install               # git hooks: ruff + format + mypy (Python >= 3.9, venv active)
pre-commit run --all-files       # same checks on the whole tree
pytest dpg_navigator/tests/test_filesystem.py::test_name   # single test

python demo.py                   # launch the interactive demo dialog (needs a display)
python benchmarks/benchmark_heavy_paths.py --profile default --iterations 3
```

Integration tests (real DearPyGui + GPU/display) are **not** collected by a normal `pytest` run. They are gated behind an env var:

```bash
DPG_INTEGRATION=1 pytest -m integration           # needs a display
xvfb-run -a env DPG_INTEGRATION=1 pytest -m integration   # headless Linux
# GitHub Actions runs the same suite under xvfb as a required CI job.
# Sandbox-less runners also need DPG_CHROME_NO_SANDBOX=1 and (for HTML
# smoke) DPG_CHROME_BIN pointing at chrome-headless-shell — html2image
# uses Chrome's ``--screenshot`` CLI, which hangs on full Chrome for Testing.
```

### Release / tooling notes (don't trip on these)

- **Version** lives in `dpg_navigator/__init__.py` as `__version__` (hatchling reads it via regex). Bump it there for a release.
- **Do not pin `python_version` in `[tool.mypy]`.** It's deliberately unpinned so mypy targets the running interpreter and matches each version's third-party stubs (numpy's PEP 695 `type` aliases only parse on newer Python). Pinning breaks stub parsing on newer CI runners.
- pytest writes temp dirs under `.pytest_tmp/` (`--basetemp` in `pyproject.toml`); that's why those dirs and `.pytest_tmp_cache/` exist.
- New `.py` files **must** start with `from __future__ import annotations` (3.8 support). Don't use `slots=True` on dataclasses (3.10+). Guard every optional-backend import with `try/except Exception`.

## Architecture

The codebase is organized around one hard rule: **pure (GUI-free) logic is separated from DearPyGui rendering** so the logic can be unit-tested without a DPG context. Anything importing `dearpygui` and needing a live context is an integration test; everything else is a normal unit test.

### Dialog composition (`_dialog.py` + `dialog/`)

`FileDialog` (in `_dialog.py`) is a thin orchestrator (`KeyboardMixin` subclass) that wires together three collaborators and exposes the public API (`show`/`hide`/`destroy`/`change_callback`):

- **`dialog/_state.py` — `DialogState`**: a plain dataclass holding *all* mutable state (nav history, selection, search, size cache, generation counters). No behavior beyond `navigate()`.
- **`dialog/_logic.py` — `DialogLogic`**: GUI-free business logic (navigation, listing, debounced search, background index build, dir-size computation). It never touches DPG directly — it calls back into the UI through injected callbacks (`refresh_ui_cb`, `show_error_cb`, `update_path_input_cb`, `update_size_cell_cb`).
- **`dialog/_ui.py` — `DialogUIBuilder`**: builds the DPG widget tree.

`FileDialog` also defines a set of `@property` **compatibility adapters** (`_current_dir`, `_selected_files`, `_row_entries`, …) that forward to `self.state`. These exist so `KeyboardMixin` (which predates the state split) keeps working. If you add navigation/selection state, put it on `DialogState` and add an adapter if `KeyboardMixin` needs it.

### Virtual filesystem (`vfs/` + `_filesystem.py`)

`DirectoryLister` (in `_filesystem.py`) is a **static facade**. It does not scan the disk itself — it asks `VFSRegistry.get_provider(path)` for a provider and delegates. Two providers exist:

- `LocalVFSProvider` — physical paths.
- `ArchiveVFSProvider` — virtual paths *inside* zip/7z archives.

**Archive virtual-path convention:** `C:\path\to\file.zip|/inner/dir` — a `|` separates the physical archive from the path inside it. This string format is threaded through navigation (`DialogLogic.navigate_to`/`go_up`), listing, and extraction. When you see `"|" in path` checks, that's archive handling.

`DirectoryIndex` (also in `_filesystem.py`) is the background recursive search index used for "search subfolders".

### Preview subsystem

Routing and rendering are split:

- **`_preview_registry.py`** — GUI-free routing. Extension `frozenset`s, the `PreviewKind` enum, `PreviewCapabilities`, and `resolve_preview_kind()`. **The order of checks in `resolve_preview_kind()` is load-bearing** (e.g. HTML and code are matched before generic text). Change it carefully; it has dedicated tests.
- **`_preview.py` — `PreviewPanel`**: owns the panel, maps `PreviewKind → BaseRenderer`, and drives the active renderer.
- **`renderers/`** — the DPG-facing renderer objects (`ImageRenderer`, `TextRenderer`, `DataRenderer`, `ArchiveRenderer`, `DocumentRenderer`, `FontRenderer`), each conforming to the `BaseRenderer` protocol in `renderers/_base.py` and receiving a `PreviewContext`. `DocumentRenderer` covers HTML/Markdown/PDF/Word/PPTX by delegating to the heavy renderers and pure loaders.
- **`_availability.py`** — every optional backend is probed once at import via `try/except` and exposed as a `*_available()` predicate. `chrome_available()` (in `_html.py`) checks `DPG_CHROME_BIN` / `CHROME_BIN` / `CHROME_PATH`, then bounded platform-specific Chrome locations without invoking html2image's unbounded search. Failed imports are `None` typed as `OptionalModule` (`_optional.py`), not `cast(Any, None)`.
- **HTML policy (`_html.py`)** — raw HTML is safe by default: parser allow-list + controlled CSP wrapper, no scripts or local/network resources. `DialogConfig.trusted_html_preview=True` is an explicit opt-in for raw `.html`/`.htm` only; Markdown and mammoth output always use the safe string entry point. Every Chrome render owns a separate temporary profile/output directory.
- **`_preview_*.py`** (`_preview_word`, `_preview_presentation`, `_preview_archive`, `_preview_spreadsheet`, `_preview_sqlite`, `_preview_table`) — **pure data loaders**: they parse a file and return plain Python data structures, no DPG. The `renderers/` objects consume them. This is why they're unit-testable.

### Concurrency (`_job_manager.py`)

`JobManager` is a static class. `submit()` queues work on a **bounded pool of 8 daemon workers** so a burst of index/size/preview jobs cannot spawn one OS thread per task. `schedule_timer()`/`cancel_timer()` share **one** min-heap timer thread; due timers dispatch into the same pool. `shutdown()` cancels queued jobs, then joins.

**DPG is single-threaded.** Two invariants follow:

1. Background workers must not call DearPyGui at all. Listing, size, sidebar, HTML render, and HTML resize results are stored as plain Python state. HTML results are applied by a `set_frame_callback` poll while holding `dpg.mutex()` because DPG dispatches frame callbacks on its callback thread; DearPyGui 2.2 fixes the older mutex/GIL inversion and is the minimum supported version. A worker taking `dpg.mutex()` directly is still forbidden.
2. Stale-result cancellation uses **generation counters** on `DialogState` (`bg_generation`, `index_generation`). A background task captures the counter value when it starts and bails if it no longer matches — navigating away or refreshing bumps the counter.

### Shared-resource lifecycle

Themes, Chrome process tracking, the extraction temp dir, and `JobManager` are process-wide, reference-counted by `FileDialog._instance_count`. They are only torn down when the **last** `FileDialog` is destroyed. Individual HTML renders have isolated temporary Chrome sessions that clean themselves up. When touching shared cleanup code, preserve the last-dialog rule.

### Supporting modules

`_platform.py` (drives, special dirs, hidden-file rules, modifier keys — cross-platform), `_icons.py` (`IconRegistry`, loads the bundled `images/` icon set), `_styles.py` (`STYLE_REGISTRY`: labeled vs compact sidebar), `_keyboard.py` (`KeyboardMixin`; DPG keyboard handlers are global so they're guarded by a dialog-active check), `_types.py` (`DialogConfig`, `DialogMode`, `StyleVariant`, frozen `FileEntry`).

## DearPyGui gotchas (recurring in this codebase)

- The default DPG font has incomplete Unicode coverage — use ASCII (`v`, `>`, `<`) for built-in labels, or bind a Unicode-capable font when displaying international filenames. The demo uses `load_font_with_unicode()`.
- Use `with dpg.table() as id:` (context manager); `dpg.add_table()` returns an int, not a CM.
- Store `add_raw_texture()`'s **integer** return value and pass it around; string tags for raw textures are unreliable across delete/recreate cycles.
- `self.state.current_dir` is used everywhere instead of `os.chdir()` — never mutate the process CWD.
