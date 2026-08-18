# 00 — Zakres i rozpoznanie środowiska audytu

Data rozpoznania: 2026-07-19
Katalog repozytorium: `O:\Projekty\DPG Navigator`

> **Historyczny snapshot.** Ten dokument jest tylko rozpoznaniem (scope) stanu z
> 2026-07-19. Nie modyfikowano kodu produkcyjnego —
> wszystkie artefakty audytu trafiają wyłącznie do katalogu `audit/`.

## 1. Tożsamość projektu

- **Nazwa pakietu:** `dpg-navigator` (PyPI), import root: `dpg_navigator`
- **Opis:** widget file/directory picker dla [DearPyGui](https://github.com/hoffstadt/DearPyGui)
  z rozbudowanym panelem podglądu (obrazy, PDF, Word, Excel, PowerPoint, Markdown, HTML,
  CSV, SQLite, fonty, archiwa, kod z podświetlaniem składni).
- **Wersja bieżąca:** `1.0.0b4` (`dpg_navigator/__init__.py:40`, czytana przez hatchling
  regexem z `pyproject.toml` → `[tool.hatch.version]`).
- **Status:** Development Status :: 4 - Beta (`pyproject.toml` classifiers).
- **Licencja:** MIT, Copyright (c) 2024–2026 HACE.
- **Wspierane Pythony:** `>=3.8` (3.8–3.13 w klasyfikatorach i macierzy CI).
- **Platformy:** Windows / Linux / macOS (cross-platform, kod platform-specific w `_platform.py`).
- **Autor / maintainer:** HACE.
- Brak wcześniejszej wersji stabilnej `1.0.0` — projekt jest w fazie beta hardeningu
  (patrz `docs/ROADMAP.md`, sekcje P1/P2).

## 2. Stan Git

- **Branch:** `main`
- **HEAD (lokalny):** `b0372f6` — "Harden previews and CI: HTML limits, Polish font
  glyphs, SBOM, SHA-pinned actions."
- **Rozbieżność z `origin/main`:** gałęzie **rozjechały się** — lokalny `main` ma
  **1 commit**, którego nie ma na `origin/main`, a `origin/main` ma **8 commitów**,
  których nie ma lokalnie (wspólny przodek: `783b489`).
  - Commity tylko na `origin/main` (nieobecne lokalnie), m.in.:
    `51075d1` "fix(renderers): complete the abandoned MVC/ctx migration (repo was
    import-broken)", plus poprawki `from __future__ import annotations` dla 3.8/3.9
    (`006fc13`, `cfd2c2e`, `28c115e`), poprawka wiring PreviewPanel (`1f37cb10`/`1f37c…`),
    zmiany w CI (`cccab10`, `fd54f76`), `adb6c6f` (concurrency cancel + timeout).
  - **To jest istotne dla audytu:** repozytorium lokalne audytowane w tym przebiegu
    (`b0372f6`) NIE zawiera najnowszych poprawek z `origin/main`, w tym poprawki opisanej
    jako "repo was import-broken". Audyt merytoryczny powinien jasno zaznaczyć, względem
    którego commit-a (lokalnego `b0372f6`) formułuje ustalenia, i osobno odnotować, że
    część z nich może być już naprawiona na `origin/main`.
- **Working tree:** czysty względem śledzonych plików; **untracked**:
  `CLAUDE.md` (nowy, nie ma historii — `git log --all -- CLAUDE.md` pusty),
  `pyright_output*.txt` (4 pliki, artefakty lokalnego uruchomienia pyright, nieistotne
  dla audytu, nie są częścią repo).
- **Remote:** `origin = https://github.com/MarekHanaczowski/DPG-Navigator.git` (fetch+push).
- **`.gitignore`:** standardowy Python (`__pycache__`, `.venv`, `dist/`, `build/`,
  cache pytest/ruff), `.claude/` jest ignorowany.

## 3. Dokumentacja repo

- **`CLAUDE.md`** (root, untracked): wytyczne dla Claude Code — komendy dev, architektura
  (`FileDialog` jako orkiestrator + `DialogState`/`DialogLogic`/`DialogUIBuilder`,
  VFS provider pattern, routing podglądu przez `_preview_registry.py`, `JobManager`,
  reguły współbieżności z DPG single-threaded, generation counters, reference-counted
  zasoby współdzielone). Bardzo szczegółowa, wewnętrznie spójna z faktycznym kodem
  (zweryfikowano pobieżnie strukturę katalogów — zgadza się).
- **`README.md`**: dokumentacja użytkownika — instalacja, quick start, lista funkcji
  preview, extras (`pip install dpg-navigator[all]`), wymaganie Chrome/Chromium na PATH
  dla HTML/Markdown/code/Word-HTML, sekcja "Security and Reliability" (path traversal,
  SQL injection hardening, ZipSlip protection, ostrzeżenie że podgląd HTML/MD/Word/kodu
  wykonuje JS w headless Chrome — traktować jak przeglądanie niezaufanej zawartości),
  HiDPI note dla Windows, sekcja Development z pełną listą modułów objętych mypy.
- **`CHANGELOG.md`**: prowadzony, sekcja `[Unreleased]` + `1.0.0b3` z listy fixów
  bezpieczeństwa/współbieżności (m.in. mutex w search worker, cap na ekstrakcję z
  archiwum, timeout na subprocess Chrome).
- **`docs/ROADMAP.md`**: świadomie spisany dług — P1 (lifecycle `JobManager`, budżety
  zasobów [DONE], testy integracyjne DPG [IN PROGRESS]) i P2 (split `PreviewPanel`/
  `FileDialog`, szersze ruff/mypy, supply chain, typed public API). Zawiera też sekcję
  "Explicitly out of scope (non-issues)" — przydatne do odróżnienia świadomych decyzji
  od przeoczeń.
- **`docs/releasing.md`**: kroki wydania (trusted publishing PyPI).
- **`docs/audits/`**: historia poprzednich audytów tego repo — `Audyt SWE16.md`,
  `AudytGLM52.md`, `AudytSWE17.md`, `PROGRAM_NAPRAWCZY_RAPORT.md`, `REKOMENDACJE_REPO.md`.
  **Do przejrzenia przed pisaniem nowych ustaleń**, żeby nie duplikować już zgłoszonych
  i już naprawionych punktów (memory projektu wskazuje serię audytów zewnętrznych
  1–3, wszystkie zweryfikowane i wdrożone przez poprzednie sesje).
- **`benchmarks/README.md`**: krótki opis profilu benchmarków.

## 4. Języki i frameworki

- **Język:** Python 100% kodu źródłowego (63 pliki `.py` śledzone w git; ~7 556 linii
  w `dpg_navigator/` wg `wc -l`). Zero JS/TS/inny język aplikacyjny w repo.
- **GUI framework:** [DearPyGui](https://github.com/hoffstadt/DearPyGui) (`dearpygui>=1.9.1`)
  — biblioteka jest komponentem/widgetem do osadzenia w aplikacji DPG, nie samodzielną apką.
- **Zależności rdzeniowe (zawsze wymagane):** `dearpygui>=1.9.1`, `psutil>=5.9.0`,
  `bleach>=6.0` (sanityzacja HTML/Markdown).
- **Zależności opcjonalne (extras w `pyproject.toml`):** `preview` (Pillow), `pdf`
  (pypdfium2+numpy+Pillow), `word` (python-docx+mammoth+html2image+numpy+Pillow),
  `pptx` (python-pptx+Pillow), `html` (html2image+numpy+Pillow), `markdown`
  (markdown+html2image+numpy+Pillow), `excel` (openpyxl), `archive` (py7zr),
  `code` (Pygments+html2image+numpy+Pillow), `all` (suma wszystkich), `dev` (pytest,
  ruff, mypy, `dpg-navigator[all]`).
- **Zewnętrzna zależność systemowa (poza pip):** binarka Chrome/Chromium na PATH —
  wymagana przez `html2image` dla podglądu HTML/Markdown/kodu/Word-HTML; bez niej
  biblioteka degraduje się do tekstu (opisane w README i `_availability.py`).
- **Plik `requirements.txt`:** istnieje równolegle do `pyproject.toml` (duplikacja
  źródła prawdy o zależnościach — już odnotowane jako dług w `docs/ROADMAP.md` §6:
  "Make `pyproject.toml` the single source of truth... drop or auto-generate
  `requirements.txt`").

## 5. System budowania / packaging

- **Build backend:** `hatchling` (`pyproject.toml` → `[build-system]`).
- **Wersjonowanie:** `[tool.hatch.version] source = "regex"`, czyta `__version__` z
  `dpg_navigator/__init__.py` — **jedyne miejsce do bumpowania wersji przy release**.
- **Wheel:** pakuje `dpg_navigator/`, wyklucza `dpg_navigator/tests/`.
- **Sdist:** dołącza `dpg_navigator/`, `benchmarks/`, `docs/`, `CHANGELOG.md`,
  `LICENSE`, `README.md`; wyklucza testy.
- **Instalacja dev:** `pip install -e ".[dev]"`.
- **Dystrybucja:** publikowana na PyPI jako `dpg-navigator`; publish przez GitHub
  Actions `trusted publishing` (OIDC `id-token: write`, brak sekretów API tokenów
  w repo dla publikacji) — `.github/workflows/publish.yml`.

## 6. CI/CD (`.github/workflows/`)

### `ci.yml` (triggers: `push`, `pull_request`, `workflow_call`)

- **`test`** — macierz 9 kombinacji OS×Python: ubuntu (3.8–3.13), windows (3.8, 3.13),
  macos (3.13). Kroki: `pip install -e ".[dev]"` → `ruff check .` → `mypy` (tylko gdy
  Python ≠ 3.8/3.9, na jawnej liście "czystych" modułów) → `pytest -q`.
- **`audit`** — `pip-audit` na zależnościach (`continue-on-error: true`, więc **nie
  blokuje** CI przy podatności — tylko informacyjnie).
- **`sbom`** — generuje CycloneDX SBOM (`cyclonedx-bom`), publikuje jako artefakt
  (retencja 30 dni).
- Akcje `actions/checkout`, `actions/setup-python`, `actions/upload-artifact` **pinowane
  do SHA commitów** (nie floating tagów) — świadoma twarda praktyka supply-chain.

### `publish.yml` (triggers: `release: published`, `workflow_dispatch`)

- `test` job wywołuje cały `ci.yml` jako gate (`uses: ./.github/workflows/ci.yml`) —
  broken commit nie dojdzie do builda/publikacji.
- `build` → `python -m build` + `twine check dist/*` → upload artefaktu (7 dni).
- `publish-testpypi` (na `workflow_dispatch`) i `publish-pypi` (na `release`) — oba przez
  `pypa/gh-action-pypi-publish` pinowany do SHA, environment `testpypi`/`pypi`,
  trusted publishing (OIDC), brak długożyjących sekretów PyPI w repo.

### Braki / obserwacje (informacyjnie, do ewentualnego audytu, bez modyfikacji)

- **Brak dedykowanego skanu sekretów** w CI (brak joba/kroku gitleaks, trufflehog,
  detect-secrets czy podobnego) i **brak configu** takiego narzędzia w repo (sprawdzono:
  brak `.gitleaks.toml`, `.pre-commit-config.yaml`, configu trufflehog/bandit).
  W środowisku lokalnym też brak zainstalowanych binarek (`gitleaks`, `trufflehog`,
  `detect-secrets`, `bandit`, `git-secrets` — żadne nie jest na `PATH`).
  GitHub ma domyślny "secret scanning" na poziomie platformy dla repo publicznych,
  ale nie ma potwierdzenia w repo lokalnym, czy jest włączony (to ustawienie GitHub,
  nie plik w repo).
- Job `audit` (`pip-audit`) ma `continue-on-error: true` — podatności w zależnościach
  nie blokują merge'a, tylko są widoczne w logach.
- Ruff jest ograniczony do reguł poprawnościowych (`E9,F63,F7,F82`) — świadomie wąski
  zestaw (patrz `docs/ROADMAP.md` §5 "Broader ruff... budget a dedicated cleanup pass").
- mypy nie obejmuje całego pakietu, tylko jawną listę "czystych" (GUI-free) modułów —
  świadoma decyzja architektoniczna udokumentowana w CLAUDE.md i README, nie przeoczenie.

## 7. Polecenia zweryfikowane lokalnie (uruchomione w tej sesji)

| Cel | Polecenie | Wynik w tej sesji |
|---|---|---|
| Lint | `python -m ruff check .` | **PASS** — "All checks passed!" (ruff 0.15.22) |
| Test (zbieranie) | `python -m pytest --collect-only -q` | **522 testy** zebrane bez błędów (pytest 9.0.1) |
| Test (pełny) | `python -m pytest -q` | nieuruchomiony w tym rozpoznaniu (zbieranie potwierdza wykonywalność; pełny przebieg zostawiony właściwemu etapowi audytu ze względu na czas/import DPG) |
| Typy (moduły "czyste") | `python -m mypy <jawna lista z README/CI>` | polecenie zidentyfikowane, nieuruchomione w tym kroku |
| Audyt zależności | `python -m pip_audit` | pip-audit 2.10.0 obecny w środowisku; nieuruchomiony w tym kroku (wymaga `pip install -e ".[all]"` + pip-audit, sieciowe zapytanie do bazy podatności) |
| SBOM | `python -m cyclonedx_py environment --of JSON -o sbom.cdx.json` | tylko w CI (`cyclonedx-bom` niepotwierdzone lokalnie) |
| Import smoke | `python -c "import dpg_navigator"` | **PASS** — import bez błędu na lokalnym `b0372f6` z zainstalowanym `[dev]` |
| Uruchomienie interaktywne | `python demo.py` | wymaga wyświetlacza (GUI), nieuruchomione |
| Testy integracyjne (real DPG) | `DPG_INTEGRATION=1 pytest -m integration` | opt-in, wymaga display/GPU; nieuruchomione |
| Benchmarki | `python benchmarks/benchmark_heavy_paths.py --profile default --iterations 3` | zidentyfikowane, nieuruchomione |

Środowisko: Python 3.13.8, ruff 0.15.22, mypy 2.3.0, pytest 9.0.1, pip-audit 2.10.0 —
wszystkie narzędzia dev są zainstalowane i wykonywalne w tym środowisku.

## 8. Punkty wejścia

- **Biblioteczne (główne):** `from dpg_navigator import FileDialog` — konstruktor
  `FileDialog(callback=..., config: DialogConfig | None, **kwargs)`, metody publiczne
  `show()/hide()/destroy()/change_callback()`. Brak CLI / `console_scripts` w
  `pyproject.toml` — to czysto biblioteka do embedowania w aplikacji DPG hosta.
  Publiczny re-export w `dpg_navigator/__init__.py`: `FileDialog`, `DialogConfig`,
  `DialogMode`, `StyleVariant`, `FileEntry`, `DEFAULT_FILTER_LIST`, oraz predykaty
  dostępności backendów (`word_available`, `mammoth_available`, `pptx_available`,
  `markdown_available`, `pdf_available`, `html_available`, `chrome_available`,
  `excel_available`, `py7zr_available`, `pygments_available`).
- **Demo/manualne uruchomienie:** `demo.py` (root) — interaktywna aplikacja DPG do
  ręcznego testowania dialogu (wymaga wyświetlacza).
- **Przykłady:** `examples/example.py`, `examples/example_folders.py`.
- **Testy jako punkt wejścia audytu:** `dpg_navigator/tests/` (522 testy jednostkowe,
  bez GUI) + `dpg_navigator/tests/integration/` (opt-in, prawdziwy DPG, env-gated).
- **Benchmark:** `benchmarks/benchmark_heavy_paths.py`.

## 9. Mapa architektury (na potrzeby audytu, ze źródeł: CLAUDE.md + struktura katalogów)

```
dpg_navigator/
├── __init__.py            re-eksport publicznego API, __version__
├── _dialog.py              FileDialog — orkiestrator (KeyboardMixin), show/hide/destroy
├── dialog/
│   ├── _state.py           DialogState — cały mutowalny stan (dataclass)
│   ├── _logic.py           DialogLogic — logika bez DPG (nawigacja, listing, search, index)
│   └── _ui.py              DialogUIBuilder — budowa drzewa widgetów DPG
├── vfs/                    Virtual filesystem: LocalVFSProvider, ArchiveVFSProvider,
│                            VFSRegistry (konwencja ścieżki archiwum: "plik.zip|/wewnątrz")
├── _filesystem.py          DirectoryLister (fasada), DirectoryIndex (bg search index)
├── _preview_registry.py    routing bez DPG: PreviewKind, resolve_preview_kind() —
│                            KOLEJNOŚĆ SPRAWDZEŃ JEST ISTOTNA (ma dedykowane testy)
├── _preview.py             PreviewPanel — mapuje PreviewKind → renderer
├── renderers/               ImageRenderer, TextRenderer, DataRenderer, ArchiveRenderer,
│                            DocumentRenderer (HTML/MD/PDF/Word/PPTX), FontRenderer
├── _preview_word.py, _preview_presentation.py, _preview_archive.py,
│   _preview_spreadsheet.py, _preview_sqlite.py, _preview_table.py
│                            pure data loaders (bez DPG) konsumowane przez renderers/
├── _pdf.py                 PDFRenderer — pypdfium2, raw_texture, LRU cache, prefetch
├── _html.py                HTMLRenderer — html2image/Chrome Headless, scrollable viewport
├── _availability.py        probing opcjonalnych backendów przy imporcie (*_available())
├── _job_manager.py         JobManager — statyczny, wątki daemon + jeden timer-heap
├── _platform.py            drives, special dirs, hidden-file rules (cross-platform)
├── _icons.py                IconRegistry (images/)
├── _styles.py               STYLE_REGISTRY: labeled vs compact sidebar
├── _keyboard.py             KeyboardMixin — globalne handlery klawiatury DPG
├── _types.py                 DialogConfig, DialogMode, StyleVariant, FileEntry (frozen)
├── images/                   44 pliki .png — ikony 3D Fluency (Icons8)
└── tests/                    522 testy jednostkowe + tests/integration/ (opt-in)
```

**Reguła architektoniczna (CLAUDE.md):** ścisły rozdział logiki bez-GUI (unit-testable
bez kontekstu DPG) od renderowania DPG. DPG jest single-threaded — workery w tle muszą
marshalować wywołania DPG z powrotem na main thread wewnątrz `dpg.mutex()`
(`FileDialog._safe_*`), a odrzucanie nieaktualnych wyników używa liczników generacji
(`bg_generation`, `index_generation` na `DialogState`).

## 10. Poprzednie audyty tego repo (kontekst historyczny)

W `docs/audits/` istnieją wcześniejsze raporty: `Audyt SWE16.md`, `AudytGLM52.md`,
`AudytSWE17.md`, `PROGRAM_NAPRAWCZY_RAPORT.md`, `REKOMENDACJE_REPO.md`. Pamięć projektu
(`MEMORY.md`) wskazuje dodatkowo serię audytów zewnętrznych (1–3), wszystkie
zweryfikowane i z wdrożonymi poprawkami do commita `99170f4` i późniejszych, oraz trzeci
audyt strategiczny z jedną realną luką (double-click extract bez limitu w `_dialog.py:654`
— **uwaga:** ta linia referuje strukturę sprzed obecnego MVC-splitu na `dialog/_logic.py`,
do zweryfikowania czy nadal aktualna w obecnej strukturze modułów). Właściwy audyt
merytoryczny powinien najpierw przejrzeć te dokumenty, żeby nie duplikować już
zamkniętych ustaleń i skupić się na przyroście od tamtego czasu — w szczególności na
dużym refaktorze MVC (`dialog/`, `renderers/`, `vfs/`) widocznym w historii commitów
(`ebca2ae` "Refactor: MVC architecture..." i seria commitów `51075d1`…`fd54f76`
obecnych na `origin/main`, ale nie na lokalnym `main`, patrz §2).

## 11. Ograniczenia tego rozpoznania

- Nie uruchomiono pełnego `pytest -q` (tylko `--collect-only`) ani `mypy`, ani
  `pip_audit` na żywo — z tego etapu do zrobienia we właściwym przebiegu audytu.
- Nie oceniano treści kodu pod kątem podatności — to zadanie kolejnych etapów audytu
  (ten dokument to wyłącznie rozpoznanie środowiska/scope, zgodnie z poleceniem).
- Rozbieżność lokalny `main` vs `origin/main` (§2) oznacza, że ustalenia audytu
  odnoszą się do stanu **lokalnego** repozytorium (commit `b0372f6`) — warto to
  zaznaczyć w raporcie końcowym, żeby uniknąć zgłaszania jako "błąd" czegoś, co jest
  już naprawione na `origin/main`.
