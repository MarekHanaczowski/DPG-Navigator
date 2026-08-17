# Roadmap — path to a stable 1.0.0

This tracks the work deferred from the beta hardening rounds (see
[`CHANGELOG.md`](../CHANGELOG.md) for what is already done). Nothing here blocks
the `1.0.0b*` beta; these are the investments to reach a production-grade,
high-assurance `1.0.0`.

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

### 3. Integration smoke tests (real DPG + optional backends) — **PARTIAL**
- **Done:** verified lifecycle/concurrency tests that drive the real
  `DirectoryIndex` build + `FileDialog` background-index thread against a real
  temp filesystem (generation cancellation, thread settle, no leak) —
  `tests/test_lifecycle.py`. Opt-in scaffolding for real-DPG smoke tests:
  the `integration` marker, an env-gated `tests/integration/` (not collected
  unless `DPG_INTEGRATION=1`). Coverage:
  - construct → render frames → destroy (window gone, threads settle)
  - Chrome HTML preview (skipped when no browser binary)
  - Word `.docx` HTML path vs python-docx text fallback
  - oversize archive member on OK: error status, dialog stays open, no callback
  Unit tests cover the same Word switch and archive-OK glue without DPG.
  CI runs the suite under xvfb + software GL with `continue-on-error`.
- **Remaining:** treat the xvfb job as a required gate once it is stable.
- **Run locally:** `DPG_INTEGRATION=1 pytest -m integration`.

## P2 — quality / maturity

### 4. Split `PreviewPanel` and `FileDialog` — **DONE**
- `FileDialog` now orchestrates `DialogState`, `DialogLogic`, `DialogUIBuilder`,
  `PreviewPanel`, and the sidebar renderer.
- Preview routing lives in `_preview_registry.py`; format-specific DPG renderers
  live in `renderers/`, while parsing remains in the pure `_preview_*.py` loaders.
- Remaining maintenance is limited to keeping the compatibility adapters thin and
  adding focused integration coverage for the live DearPyGui paths.

### 5. Tooling gates
- **Broader ruff + `ruff format --check`:** expand beyond `E9/F63/F7/F82` to
  import order, bugbear, pyupgrade, simplify. **Note:** the first run surfaces a
  backlog (trailing whitespace, imports) — budget a dedicated cleanup pass, do
  not fold it into a feature commit.
- **Whole-package mypy:** move from the hand-maintained file list to
  `files = ["dpg_navigator"]`, then progressively enable `warn_return_any`,
  `disallow_any_generics`, `disallow_untyped_defs`; replace `cast(Any, None)`
  optional-dependency shims with `Protocol`s.
- **`pre-commit`** as the single local entry point (ruff, ruff-format, mypy),
  and a **coverage gate** (`pytest-cov`) with a threshold for the pure-data
  modules only — do not force a high GUI number.

### 6. Supply chain & release provenance — **PARTIAL**
- GitHub Actions are pinned to commit SHAs, CI generates a CycloneDX SBOM, and
  Dependabot watches GitHub Actions and pip weekly.
- **Remaining:** generate a `THIRD_PARTY_NOTICES.md` / `pip-licenses` report for
  bundled icons and transitive dependencies.
- Make `pyproject.toml` the single source of truth for dependencies (drop or
  auto-generate `requirements.txt`).

### 7. Typed public API — **DONE**
- Host selection callback is `SelectionCallback` (`Protocol` for
  `Callable[[list[str]], None]`); `FileDialog.__init__` has overloads for
  `DialogConfig` vs kwargs; `change_callback` uses the same type.
- `DialogConfig` validates sizes, `file_filter` membership, paths (no NUL),
  and `custom_dirs` `(label, path)` pairs in `__post_init__`.

## Explicitly out of scope (non-issues)
- **ZipSlip check:** the current `realpath` + `startswith(root + os.sep)` guard
  is correct; `commonpath` is only marginally more idiomatic.
- **`build_selection_list` path escape:** returning an absolute/`..` path typed
  by the user is standard file-dialog behaviour; validation belongs to the
  caller of the selection callback.
