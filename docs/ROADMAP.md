# Roadmap — path to a stable 1.0.0

This tracks the work deferred from the beta hardening rounds (see
[`CHANGELOG.md`](../CHANGELOG.md) for what is already done). Nothing here blocks
the `1.0.0b*` beta; these are the investments to reach a production-grade,
high-assurance `1.0.0`.

Priorities: **P1** = do before the first stable tag; **P2** = quality/maturity,
can trail the first stable release.

## P1 — before stable 1.0.0

### 1. Worker / process lifecycle (`JobManager`)
- **Why:** background workers, debounce timers and the Chrome render process are
  daemon threads. `destroy()` bumps generation counters but keeps no task
  registry, never `join()`s with a deadline, and does not own the browser
  process. A dialog torn down mid-render leaks a thread (and possibly a Chrome
  process). The render timeout added in `1.0.0b3` is the first piece of this.
- **Scope:** a small `JobManager` owning `(generation, threading.Event, futures)`
  with a controlled shutdown; route the size-computation, index-build, deep
  search, PDF prefetch and HTML render threads through it.
- **First step:** inventory every `threading.Thread(...)` / `threading.Timer`
  in `_dialog.py`, `_html.py`, `_pdf.py`; give each a cancel token and a
  join-with-timeout in `destroy()`.
- **Effort:** large. **Risk:** medium — touches concurrency; land with the
  integration tests below.

### 2. Resource budgets for previews — **DONE** (`3f1cc0d`)
- Index entry cap (`INDEX_MAX_ENTRIES = 50k`, partial index kept), archive
  listing via `heapq.nlargest` top-k instead of full sort, and a bounded
  SQLite row count (`N+` past 100k) instead of a full `COUNT(*)`. The Chrome
  subprocess timeout landed earlier in `1.0.0b3`.
- **Remaining (optional):** an explicit HTML/Office pixel budget beyond the
  existing `_MAX_RENDER_W`/`_RENDER_H` caps, if a real case needs it.

### 3. Integration smoke tests (real DPG + optional backends)
- **Why:** GUI/render modules sit around 15–20% coverage and the dialog tests
  deliberately mock DearPyGui. Behaviour under a real context (create context,
  build dialog, resize, destroy during workers, real Chrome render, Word
  HTML/text switch, oversize archive) is unverified.
- **Scope:** an `integration` pytest marker, a headless-DPG context fixture, and
  a job that runs it where the optional backends (Chrome, pypdfium2, …) exist.
- **First step:** one test that creates a context, constructs and destroys a
  `FileDialog`, and asserts no leaked threads.
- **Effort:** medium. **Risk:** low (new tests, no product change).

## P2 — quality / maturity

### 4. Split `PreviewPanel` and `FileDialog`
- **Why:** `_preview.py` (~2000 lines) and `_dialog.py` (~1200) mix routing,
  lifecycle, per-format rendering and background services.
- **Scope:** extract renderers into `preview/renderers/*` behind the existing
  registry; split `FileDialog` into `DialogState` / `DialogController` /
  `BackgroundServices`.
- **Effort:** large. **Risk:** low functionally (pure refactor) but broad diff —
  do it after the P1 tests exist so regressions are caught.

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

### 6. Supply chain & release provenance
- Pin GitHub Actions to commit SHAs and enable Dependabot/Renovate.
- Generate an SBOM (CycloneDX) and a `THIRD_PARTY_NOTICES.md` / `pip-licenses`
  report (bundled icons + transitive deps). `pip-audit` already runs in CI.
- Make `pyproject.toml` the single source of truth for dependencies (drop or
  auto-generate `requirements.txt`).

### 7. Typed public API
- Replace the generic `callback: Callable` / `**kwargs` with a `Protocol`
  (`Callable[[list[str]], None]`) and constructor overloads for
  `DialogConfig` vs kwargs; add `DialogConfig` validation (sizes, filter,
  paths, `custom_dirs`).

## Explicitly out of scope (non-issues)
- **ZipSlip check:** the current `realpath` + `startswith(root + os.sep)` guard
  is correct; `commonpath` is only marginally more idiomatic.
- **`build_selection_list` path escape:** returning an absolute/`..` path typed
  by the user is standard file-dialog behaviour; validation belongs to the
  caller of the selection callback.
