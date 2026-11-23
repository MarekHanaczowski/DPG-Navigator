# Roadmap — path to a stable 1.0.0

This tracks the work deferred from the beta hardening rounds (see
[`CHANGELOG.md`](../CHANGELOG.md) for what is already done). All P1 and P2
items below are done; what is left is the release path at the end.

Priorities: **P1** = do before the first stable tag; **P2** = quality/maturity,
can trail the first stable release.

## P1 — before stable 1.0.0

### 1. Worker / process lifecycle (`JobManager`) — **DONE**
- Bounded pool of 8 daemon workers (`JobManager.submit`); shutdown cancels
  queued futures, joins with a timeout, and logs leftover workers.
- HTML/PDF hold render/prefetch `Future`s and `cancel()` them on close or a
  replacement job; generation checks still drop in-flight results.
- html2image Chrome launches go through a `Popen` hook: each screenshot is
  tracked per `HTMLRenderer`, `close()` kills that preview's process tree
  (psutil, including Chrome children), and `shutdown_shared()` kills leftovers
  before removing the session profile. The 30s communicate timeout remains a
  hang backstop.

### 2. Resource budgets for previews — **DONE** (`3f1cc0d`)
- Index entry cap (`INDEX_MAX_ENTRIES = 50k`, partial index kept), archive
  listing via `heapq.nlargest` top-k instead of full sort, and a bounded
  SQLite row count (`N+` past 100k) instead of a full `COUNT(*)`. The Chrome
  subprocess timeout landed earlier in `1.0.0b3`.
- **Remaining (optional):** an explicit HTML/Office pixel budget beyond the
  existing `_MAX_RENDER_W`/`_RENDER_H` caps, if a real case needs it.

### 3. Integration smoke tests (real DPG + optional backends) — **DONE**
- **Done:** verified lifecycle/concurrency tests that drive the real
  `DirectoryIndex` build + `FileDialog` background-index thread against a real
  temp filesystem (generation cancellation, thread settle, no leak) —
  `tests/test_lifecycle.py`. Opt-in scaffolding for real-DPG smoke tests:
  the `integration` marker, an env-gated `tests/integration/` (not collected
  unless `DPG_INTEGRATION=1`). Coverage:
  - construct → render frames → destroy (window gone, threads settle)
  - two default dialogs get distinct tags without segfault
  - Chrome HTML preview (skipped when no browser binary)
  - Word `.docx` HTML path vs python-docx text fallback
  - oversize archive member on OK: error status, dialog stays open, no callback
  Unit tests cover the same Word switch and archive-OK glue without DPG.
  CI runs the suite under xvfb + software GL as a **required** job, installs
  Chrome (`browser-actions/setup-chrome`, SHA-pinned), sets
  `DPG_CHROME_NO_SANDBOX=1` (including `--no-zygote`) so headless Chrome can
  start on the runner, and points html2image at `chrome-headless-shell`
  (Chrome for Testing package; the full `chrome` binary hangs on the
  `--screenshot` CLI). Sidebar drive widgets are applied on the DPG thread
  (frame callback) so two live dialogs do not segfault under xvfb.
- **Run locally:** `DPG_INTEGRATION=1 pytest -m integration`.

## P2 — quality / maturity

### 4. Split `PreviewPanel` and `FileDialog` — **DONE**
- `FileDialog` now orchestrates `DialogState`, `DialogLogic`, `DialogUIBuilder`,
  `PreviewPanel`, and the sidebar renderer.
- Preview routing lives in `_preview_registry.py`; format-specific DPG renderers
  live in `renderers/`, while parsing remains in the pure `_preview_*.py` loaders.
- Remaining maintenance is limited to keeping the compatibility adapters thin and
  adding focused integration coverage for the live DearPyGui paths.

### 5. Tooling gates — **DONE**
- **Broader ruff + `ruff format --check`:** **DONE.** Lint selects `E9`, `F`,
  `W`, `I` (isort), `B` (bugbear), `UP` (pyupgrade), `SIM` (simplify), with
  `SIM105`/`SIM108` ignored on purpose. CI runs `ruff check .` and
  `ruff format --check .`. Format skips Markdown (`*.md`); Ruff 0.16+ would
  otherwise rewrite Python fences in README and audit notes.
- **Whole-package mypy:** **DONE.** `[tool.mypy] files = ["dpg_navigator"]`
  (tests excluded); CI runs `python -m mypy` on every Python in the matrix. Flags:
  `check_untyped_defs`, `no_implicit_optional`, `disallow_untyped_defs`,
  `warn_return_any`, `disallow_any_generics`. Optional backends use
  `OptionalModule` / `require_optional()` instead of `cast(Any, None)`.
- **`pre-commit`:** **DONE.** `.pre-commit-config.yaml` runs ruff check (with
  `--fix`), `ruff format`, and `python -m mypy` from the active `[dev]`
  environment (`language: system`, so versions match CI). Install with
  `pre-commit install` after `pip install -e ".[dev]"` (Python >= 3.10).
- **Coverage gate** (`pytest-cov`): **DONE.** Report is limited to preview
  loaders (`_preview_*.py`, not `PreviewPanel`), `vfs/`, and
  `dialog/_logic.py` + `_state.py`. `fail_under = 75` (measured ~80% on
  3.13). CI runs `--cov` only on the Ubuntu 3.13 job; other matrix legs stay
  `pytest -q`. Do not raise this into a GUI/renderer target.

### 6. Supply chain & release provenance — **DONE**
- GitHub Actions are pinned to commit SHAs, CI generates a CycloneDX SBOM, and
  Dependabot watches GitHub Actions and pip weekly.
- [`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md) covers the MIT project
  license, bundled Icons8 3D Fluency PNGs (free-use link attribution), and
  SPDX identifiers for packages declared in `pyproject.toml` (including the
  LGPL `py7zr` extra). Transitive versions live in the CI SBOM, not a second
  hand-maintained pin list.
- `pyproject.toml` is the single source of truth for dependencies.
  `requirements.txt` is a pointer (`pip install .`) so old `-r` links keep
  working.

### 7. Typed public API — **DONE**
- Host selection callback is `SelectionCallback` (`Protocol` for
  `Callable[[list[str]], None]`); `FileDialog.__init__` has overloads for
  `DialogConfig` vs kwargs; `change_callback` uses the same type.
- `DialogConfig` validates sizes, `file_filter` membership, paths (no NUL),
  and `custom_dirs` `(label, path)` pairs in `__post_init__`.

### 8. API freeze and dependency floors — **DONE**
- The public API is defined in the README ("Public API and Versioning"):
  the names in `__all__`, the documented `FileDialog` methods and `tag`
  property, and the keyword-only `DialogConfig` fields. `FileEntry`,
  `pygments_available()` and the `[code]` extra were removed before the
  freeze; `load_font_with_unicode` and `FileDialog.drag_payload_type` became
  public, and dragged rows now carry their path (`list[str]`) as payload data.
- Every declared dependency floor was installed and tested; four that did not
  work were raised (Pillow 9.3, python-docx 0.8.11, html2image 2.0.4,
  py7zr 1.0). The **Lowest dependencies** CI job keeps them honest.
- README documents every `DialogConfig` field, the HTML preview policy and the
  known limitations; [`docs/releasing.md`](releasing.md) covers the rc and
  stable release flow.

## Release path

1. **1.0.0rc1** — version bump and changelog only, no new features.
2. **Soak** — use the rc in real projects. Only fixes for bugs found in the rc
   go in, each as the next rc.
3. **1.0.0** — the last rc's code with the version number, the changelog
   heading and the `Production/Stable` classifier changed.

## After 1.0.0

- **Drag a multi-selection:** a drag currently carries only the dragged
  row. The payload is already a list, so dragging every selected row is a
  backwards-compatible addition for a minor release.
- **Optional pixel budget** for HTML/Office renders beyond the existing
  `_MAX_RENDER_W`/`_RENDER_H` caps, if a real case needs it.

## Explicitly out of scope (non-issues)
- **ZipSlip check:** the current `realpath` + `startswith(root + os.sep)` guard
  is correct; `commonpath` is only marginally more idiomatic.
- **`build_selection_list` path escape:** returning an absolute/`..` path typed
  by the user is standard file-dialog behaviour; validation belongs to the
  caller of the selection callback.
