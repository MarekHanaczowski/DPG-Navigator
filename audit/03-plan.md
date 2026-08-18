# 03 — Plan audytu: architektura, granice zaufania, obszary

Data: 2026-07-19
Commit audytowany: `b0372f6` (lokalny `main`; `origin/main` +8 commitów — patrz
`audit/00-scope.md` §2). Ustalenia planu dotyczą stanu **lokalnego**.

> Dokument planistyczny i historyczny. Nie modyfikowano kodu produkcyjnego; artefakt
> wyłącznie w `audit/`. Bazuje na `audit/01-inventory.md` (inwentaryzacja) + bezpośrednim
> odczycie kodu (VFS, `_html.py`, `_job_manager.py`, `dialog/_logic.py`,
> `_filesystem.py`, `_dialog.py`, `_preview_sqlite.py`).

---

## 1. Charakterystyka systemu (istotna dla routingu)

`dpg-navigator` to **jednoprocesowa biblioteka** (widget file/dir-picker do
osadzenia w aplikacji-hoście DearPyGui). To **nie** jest system rozproszony:

- **Brak wielu usług / monorepo** — jeden pakiet Python, jeden proces.
- **Brak granic usług sieciowych** — brak REST/gRPC/serwera nasłuchującego, brak
  bazy danych własnej, brak message queue (Celery/RQ/Redis).
- **Brak uwierzytelniania i autoryzacji** — biblioteka nie ma tożsamości
  użytkownika, sesji, ról ani tokenów. Nie propaguje tożsamości.
- **Brak transakcji** (w sensie DB/ACID). SQLite jest wyłącznie **czytany** w
  trybie `mode=ro` jako format podglądu.

**Konsekwencja dla rubryki routingu:** klasyczne sygnały rozproszone (>1 usługa,
przekroczenie granicy usługi, async między usługami, propagacja tożsamości przez
warstwy) w większości **nie zapalają się**. Rubrykę stosuję adaptacyjnie do
realnych granic tego systemu (rozdz. 5):

- **granica procesu** — subprocess Chrome Headless (`_html.py`) traktuję jak
  granicę „usługi zewnętrznej" (osobny wykonywalny proces, wykonuje niezaufaną
  treść, może żądać sieci, ma timeout/kill i anulowanie generacyjne) ⇒ liczę
  sygnały „granica usługi" i „async między usługami";
- **granica zaufania danych** — niezaufana zawartość plików (archiwa, HTML,
  formaty biurowe) przekraczająca do zapisu na FS / do parserów in-process;
- **substrat współbieżny in-process** — `JobManager` (wątki daemon + kopiec
  timerów) + marshaling wyników z tła na jednowątkowy main thread DPG
  (`dpg.mutex()` + liczniki generacji) — liczę jako „async" oraz „głębokie
  łańcuchy na ścieżce krytycznej".

Każdy obszar (rozdz. 6) ma jawny zliczbnik sygnałów w kolumnie „Routing".

---

## 2. Mapa architektury

Warstwy (ścisły rozdział logiki bez-GUI od renderowania DPG — reguła CLAUDE.md):

```
                    APLIKACJA-HOST (DearPyGui)
                            │  DialogConfig ↓        ↑ callback(list[str])
  ┌─────────────────────────────────────────────────────────────────┐
  │  WARSTWA ORKIESTRACJI / UI (DPG, single-thread)                   │
  │    _dialog.py  FileDialog(KeyboardMixin)  ── show/hide/destroy    │
  │      ├─ dialog/_ui.py     DialogUIBuilder  (drzewo widgetów)      │
  │      ├─ _keyboard.py      KeyboardMixin    (globalne handlery)    │
  │      ├─ _styles.py        sidebar (labeled/compact)               │
  │      ├─ _icons.py         IconRegistry (tekstury PNG)             │
  │      └─ _preview.py       PreviewPanel → renderers/*              │
  │            renderers/: image · text · data · archive ·           │
  │                        document(HTML/MD/Word/PPTX/PDF) · font     │
  └───────────────┬───────────────────────────────┬──────────────────┘
     _safe_*() marshaling (dpg.mutex)              │ routing podglądu
     ▲ liczniki generacji                          ▼ _preview_registry.py
  ┌───────────────┴──────────────────┐  ┌──────────┴───────────────────┐
  │  WARSTWA LOGIKI (bez DPG)         │  │  LOADERY DANYCH (bez DPG)     │
  │    dialog/_state.py  DialogState  │  │    _preview_sqlite / _table / │
  │    dialog/_logic.py  DialogLogic  │  │    _spreadsheet / _word /     │
  │      nav · search · index · size  │  │    _presentation / _archive   │
  └───────────────┬──────────────────┘  └──────────┬───────────────────┘
                  │                                 │
  ┌───────────────┴─────────────────────────────────┴──────────────────┐
  │  WARSTWA ZASOBÓW / GRANIC                                            │
  │    _filesystem.py  DirectoryLister · DirectoryIndex (bg walk)       │
  │    vfs/  VFSRegistry → LocalVFSProvider | ArchiveVFSProvider        │
  │    _job_manager.py  JobManager (wątki daemon + kopiec timerów)      │
  │    _platform.py  drives · special dirs · hidden · mod-key           │
  │    _pdf.py  PDFRenderer (pypdfium2, wątki prefetch)                 │
  │    _html.py  HTMLRenderer ── subprocess ⇒ [Chrome Headless]        │
  │    _availability.py  sondowanie opcjonalnych backendów             │
  └─────────────────────────────────────────────────────────────────────┘
        │ os.scandir / zipfile / py7zr    │ winreg · subprocess(xdg) · ctypes
        ▼ FILESYSTEM (lokalny + tempdir)  ▼ SYSTEM OPERACYJNY   ▼ Chrome(proc)
```

Przepływ sterowania (ścieżka krytyczna kliknięcia):
`DPG event → FileDialog._on_entry_click → DialogLogic.navigate_to/refresh_listing
→ DirectoryLister → VFSRegistry → (Local|Archive)VFSProvider → FileEntry[]
→ _safe_refresh_ui (dpg.mutex) → DialogUIBuilder._render_entries_list`.

---

## 3. Krytyczne przepływy

| Przepływ | Ścieżka | Uwagi bezpieczeństwa / poprawności |
|---|---|---|
| **Ekstrakcja z archiwum** (podgląd + double-click select) | `_on_entry_click` (`_dialog.py:522`) → `DirectoryLister.extract_from_archive` → `ArchiveVFSProvider.extract_file` → `zipfile/py7zr .extract` → tempdir | Zapis niezaufanej treści na FS. Ochrona ZipSlip (`os.path.realpath` + prefiks `real_root`), odmowa zaszyfrowanych (`flag_bits & 0x1` / `z.password`), limit `_MAX_ARCHIVE_EXTRACT_SIZE=512 MB`. Ekstrakcja jest **synchroniczna w handlerze UI** (blokuje main thread; brak paska postępu poza zmianą tytułu). |
| **Renderowanie HTML/MD/Word** | `PreviewPanel.update` → `DocumentRenderer` → `HTMLRenderer.open/open_string` → `_start_render` (wątek) → `_hti_screenshot` → subprocess **Chrome** → PNG → trim/scale → raw_texture → marshaling do DPG | Najniebezpieczniejszy przepływ: niezaufana treść trafia do osobnego procesu Chrome. Flagi hardeningu (`--disable-javascript`, `--proxy-server="http://127.0.0.1:0"`, `--block-new-web-contents`), timeout 30 s wstrzyknięty w `_subprocess_run_kwargs`, limit wejścia 2 MB. **Sprzeczność do weryfikacji:** `_inject_helpers` nadal wstrzykuje JS `_OVERFLOW_MARKER` (`_html.py:129`), a `_get_hti` ustawia `--disable-javascript` (`_html.py:303`) — detekcja przepełnienia szerokości zależy od JS, którego flaga zakazuje. |
| **Wyszukiwanie głębokie** | `trigger_search` → debounce 0.3 s (`JobManager.schedule_timer`) → `_run_search` → listing płytki + `DirectoryIndex.search` (indeks budowany w tle rekurencyjnym `os.scandir`) | Anulowanie przez `index_generation`; indeks **nie podąża za symlinkami katalogów** (ochrona przed ucieczką z drzewa i cyklami); twarde limity `INDEX_MAX_ENTRIES=50k`, `INDEX_MAX_RESULTS=500`, `INDEX_TTL=60s`. Czytanie `_local_entries` bez locka z wątku tła (`_perform_deep_search`) — potencjalny wyścig do przeglądu. |
| **Tworzenie folderu** | `_create_new_folder` → `validate_folder_name` → `os.makedirs(exist_ok=False)` | Ochrona traversal: odrzuca `.`/`..`/separatory + kontrola `realpath` w obrębie `current_dir` (pokrywa symlinki). Odmowa wewnątrz archiwum. |
| **Zwrot wyboru do hosta** | `_on_ok/_return_selection` → `build_selection_list(selected, typed, current_dir)` → `callback(list[str])` | Dane opuszczają bibliotekę do aplikacji-hosta. `build_selection_list` odrzuca wpisywane ścieżki uciekające z `current_dir`, ale **absolutne ścieżki wpisane ręcznie przepuszcza jako jawną intencję** — świadoma decyzja do potwierdzenia w modelu zagrożeń hosta. |
| **Obliczanie rozmiaru katalogu** | `start_size_computation` → `JobManager.submit` → `compute_dir_size` (`os.walk`, `MAX_SCAN_DEPTH=3`) → `update_size_cell` (dpg.mutex) | Anulowanie przez `bg_generation`; cache TTL 60 s. |
| **Podgląd SQLite** | `DataRenderer` → `load_sqlite_table` → `sqlite3.connect(uri?mode=ro)` | Otwarcie **tylko-do-odczytu** (URI `?mode=ro`), cudzysłowienie identyfikatorów (`_quote_identifier`), limit skanu `COUNT(*)` (`MAX_COUNT_SCAN=100k`). Powierzchnia SQL injection przez nazwy tabel/kolumn — do adwersaryjnej weryfikacji. |
| **Cykl życia / sprzątanie** | `destroy` → `logic.cancel_background_tasks` + `preview.shutdown` + (przy ostatniej instancji) `JobManager.shutdown` + `cleanup_temp_files` + `HTMLRenderer.shutdown_shared` + zwolnienie współdzielonych motywów | Reference counting `_instance_count`; tempdir czyszczony dopiero przy ostatniej instancji (współdzielony między dialogami). Częściowe niepowodzenia: `shutdown(timeout=2s)` może zostawić wątek roboczy; Chrome in-flight nie jest force-killowany. |

**Operacje uprzywilejowane (w sensie zdolności, nie uprawnień OS):** spawn
subprocess Chrome (wykonuje niezaufaną treść), zapis na FS (ekstrakcja + tempy
Chrome + tworzenie folderów), odczyt rejestru Windows (`HKCU`, read-only),
subprocess `xdg-user-dir` (Linux, read-only, timeout 2 s), wywołania `ctypes`
WinAPI (read-only atrybuty pliku). Brak eskalacji uprawnień, brak sudo/UAC/setuid.

**Współbieżność / częściowe niepowodzenia (przekrojowo):** DPG jest
single-threaded — każdy wynik z tła musi wrócić na main thread w `dpg.mutex()`
(`_safe_refresh_ui`/`_safe_update_path_input`/`_safe_update_size_cell`).
Anulowanie nieaktualnych wyników: liczniki generacji `bg_generation`,
`index_generation`, `_render_generation`, `_prefetch_generation`. Ryzyka do
weryfikacji: wyścigi TOCTOU przy odczycie `DialogState` z wątku tła bez locka,
double-checked locking w `_get_hti`/`Html2Image`, żywotność wątków po `shutdown`.

---

## 4. Granice zaufania (podsumowanie)

- **TB-1 (proces):** niezaufana treść HTML/Markdown/Word-HTML → **subprocess
  Chrome Headless** (wykonuje JS*, zdolny do żądań sieciowych, timeout/kill).
- **TB-2 (FS):** niezaufana zawartość archiwum ZIP/7z → **zapis na filesystem**
  (tempdir; ZipSlip, limit rozmiaru, odmowa szyfrowanych).
- **TB-3 (parser):** niezaufane bajty pliku → **parsery in-process**
  (sqlite3, openpyxl, python-docx, python-pptx, pypdfium2, Pillow, csv, xml,
  markdown→bleach) — DoS/decompression-bomb/injection/XSS-do-Chrome.
- **TB-4 (ścieżki):** nazwy wpisywane przez użytkownika (folder/plik) →
  operacje ścieżkowe FS (path traversal / symlink escape).
- **TB-5 (wątki):** wątki robocze tła → **jednowątkowy main thread DPG**
  (marshaling `dpg.mutex()` + liczniki generacji).
- **TB-6 (API):** aplikacja-host ↔ biblioteka (`DialogConfig` w jedną stronę,
  `list[str]` wyboru przez callback w drugą).
- **TB-7 (OS):** rejestr Windows / `xdg-user-dir` / `ctypes` WinAPI / `psutil`.
- **TB-8 (supply chain):** zależności PyPI + systemowa binarka Chrome + CI /
  trusted publishing (OIDC).

\* Uwaga: flaga `--disable-javascript` w `_get_hti` może realnie wyłączać JS —
status TB-1 „wykonuje JS" wymaga weryfikacji względem README (rozdz. 3, wiersz
HTML). To jedno z pierwszych ustaleń do potwierdzenia.

---

## 5. Rubryka routingu — stosowanie

Sygnały (wg polecenia): +2 (>1 usługa/monorepo), +2 (przepływ przekracza granicę
usługi), +2 (retry/kolejki/async między usługami), +1 (propagacja tożsamości
przez ≥2 warstwy), +1 (głębokie łańcuchy na krytycznej ścieżce).
Progi: 0–1 → **sonnet**, 2–4 → **opus**, ≥5 → **fable**.

Adaptacja do biblioteki jednoprocesowej (uzasadnienie w rozdz. 1): granicę
„usługi" zapala wyłącznie **subprocess Chrome** (osobny proces). Async „między
usługami" liczę tam, gdzie jest realna granica procesu (Chrome) **lub**
nietrywialny substrat współbieżny (`JobManager` + marshaling do DPG). Sygnał
tożsamości (auth) nie zapala się nigdzie (brak uwierzytelniania) — gdzie użyto
„+1 propagacja", oznacza **propagację kontekstu/danych** (np. wyboru użytkownika
lub `current_dir`) przez ≥2 warstwy, co jawnie zaznaczam.

---

## 6. Obszary audytu (OBSZARY)

| # | Klucz obszaru | Priorytet | Model | Routing (sygnały → suma) |
|---|---|---|---|---|
| A1 | `archive-vfs-path-safety` | **P0** | opus | granica zaufania FS (niezaufane archiwum→zapis) +2; głęboki łańcuch na ścieżce krytycznej +1 → **3** |
| A2 | `html-chrome-preview` | **P0** | fable | granica procesu Chrome +2; async lib↔Chrome (timeout/kill/generacje) +2; głęboki łańcuch podglądu +1 → **5** |
| A3 | `concurrency-lifecycle` | **P1** | opus | async substrat (JobManager + marshaling DPG) +2; głębokie łańcuchy anulowania/shutdown +1 → **3** |
| A4 | `data-preview-untrusted-parsing` | **P1** | opus | granica zaufania parserów (niezaufane bajty→sqlite/office/pdf) +2; głęboki łańcuch routingu podglądu +1 → **3** |
| A5 | `dialog-orchestration-navigation` | **P2** | opus | głęboki łańcuch klik→logika→stan→UI +1; propagacja kontekstu wyboru/`current_dir` przez ≥2 warstwy do callbacku hosta +1 → **2** |
| A6 | `packaging-ci-supply-chain` | **P1** | sonnet | brak sygnałów rozproszonych; przegląd konfiguracji/procesu → **0** |
| A7 | `platform-os-integration` | **P3** | sonnet | subprocess/OS tylko-odczyt, stałe argumenty, timeout; brak głębokich łańcuchów → **1** |

### A1 — `archive-vfs-path-safety` (P0, opus)
**Zakres:** `vfs/_registry.py`, `vfs/_base.py`, `vfs/_local.py`,
`vfs/_archive.py`, `_filesystem.py` (`DirectoryLister.extract_from_archive`,
`_get_session_temp_dir`, `validate_folder_name`, `build_selection_list`),
`_dialog.py` ekstrakcja przy double-click (`:522-546`).
**Cel:** adwersaryjna weryfikacja ZipSlip (`realpath`+prefiks dla ZIP i 7z),
odmowy szyfrowanych, limitu rozmiaru (`_MAX_ARCHIVE_EXTRACT_SIZE`,
`_is_oversized` + `allow_large_extensions`), traversal w nazwach folderów/plików,
symlink-escape, kolizji nazw w tempdir (hash MD5 ścieżki archiwum),
synchronicznej ekstrakcji blokującej UI. **Trust boundary:** TB-2, TB-4.
**Uzasadnienie modelu:** kod bezpieczeństwa wymagający scenariuszy złośliwych
wejść (opus), ale bez granicy procesu/async między usługami (nie fable).

### A2 — `html-chrome-preview` (P0, fable)
**Zakres:** `_html.py` w całości (`HTMLRenderer`, `_get_hti` flagi Chrome,
`_hti_screenshot`, `_start_render`/`_render_worker`, `_inject_helpers`,
`_OVERFLOW_MARKER`, `_read_overflow_marker`, debounce resize, `_recreate_texture`,
marshaling, `shutdown_shared`), oraz `renderers/document.py` w części HTML/MD/Word.
**Cel:** model zagrożeń subprocess Chrome (wykonanie niezaufanej treści, egress
sieciowy, skuteczność `--disable-javascript`/`--proxy`/`--block-new-web-contents`),
cykl życia subprocesu (timeout/kill, wątki in-flight po shutdown), poprawność
async (liczniki generacji, double-checked locking `_get_hti`, marshaling w
`dpg.mutex`), limity wejścia (2 MB, `_MAX_RENDER_W`). **Pierwsze ustalenie do
potwierdzenia:** sprzeczność `--disable-javascript` vs JS-owy `_OVERFLOW_MARKER`
(detekcja szerokości) — patrz rozdz. 3. **Trust boundary:** TB-1, TB-5, TB-8.
**Uzasadnienie modelu:** jedyny obszar z realną granicą procesu + async między
procesami + głęboki łańcuch + najwyższe ryzyko bezpieczeństwa → suma 5 → fable.

### A3 — `concurrency-lifecycle` (P1, opus)
**Zakres:** `_job_manager.py` (kopiec timerów, wątki daemon, `shutdown`),
`dialog/_state.py` + `dialog/_logic.py` (`cancel_background_tasks`, generacje,
`start_index_build`/`start_size_computation`, `_run_search`/`_perform_deep_search`),
`_dialog.py` `_safe_*` + `destroy`/`_instance_count`, `_pdf.py` prefetch,
`DirectoryIndex` thread-safety. **Cel:** wyścigi TOCTOU (odczyt `DialogState` z
tła bez locka), poprawność liczników generacji, wycieki wątków/zasobów po
`shutdown(timeout=2s)`, kolejność sprzątania współdzielonych zasobów
(reference counting), częściowe niepowodzenia (Chrome/PDF in-flight). **Trust
boundary:** TB-5. **Uzasadnienie modelu:** subtelna współbieżność bez granicy
procesu → suma 3 → opus.

### A4 — `data-preview-untrusted-parsing` (P1, opus)
**Zakres:** `_preview_registry.py` (kolejność routingu — ma testy), `_preview.py`,
loadery `_preview_sqlite/_table/_spreadsheet/_word/_presentation/_archive`,
`_pdf.py` (parsowanie), `renderers/data.py`, `renderers/text.py` (detekcja
kodowania, ostrzeżenie binarne), `renderers/image.py` (Pillow, downscale),
Markdown→`bleach` w `renderers/document.py`, `_availability.py`. **Cel:**
SQL injection przez nazwy tabel/kolumn (mimo `mode=ro` + cudzysłowienie), DoS /
decompression-bomb (openpyxl, python-pptx obrazy inline, Pillow, pypdfium2),
skuteczność białej listy `bleach` przed wysyłką do Chrome (XSS-do-TB-1),
poprawność heurystyki kodowania (`utf-8-sig`→UTF-16→cp1250), limity
(`_TABLE_MAX_ROWS/COLS`, `MAX_COUNT_SCAN`, `_TEXT_PREVIEW_MAX_SIZE`). **Trust
boundary:** TB-3. **Uzasadnienie modelu:** wiele powierzchni niezaufanego
parsowania + łańcuch routingu → suma 3 → opus.

### A5 — `dialog-orchestration-navigation` (P2, opus)
**Zakres:** `_dialog.py` (orkiestracja, `_on_entry_click`, sort, wybór,
`_return_selection`, adaptery właściwości), `dialog/_logic.py` nawigacja
(`go_back`/`go_up`/`navigate_to`, rozwiązywanie ścieżek wirtualnych archiwum),
`dialog/_ui.py` (`DialogUIBuilder`, drag-and-drop payload), `_keyboard.py`,
`_styles.py`, `_icons.py`. **Cel:** poprawność rozwiązywania ścieżek
archiwum/normpath, edge-case historii nawigacji, spójność zaznaczenia
mono/multi, poprawność `build_selection_list` (absolutne ścieżki wpisane),
globalne handlery klawiatury z guardem widoczności. **Trust boundary:** TB-4,
TB-6. **Uzasadnienie modelu:** hub integracyjny z głębokimi łańcuchami sterowania
+ propagacja kontekstu wyboru do hosta → suma 2 → opus (dolny próg).

### A6 — `packaging-ci-supply-chain` (P1, sonnet)
**Zakres:** `pyproject.toml` (hatchling, extras, `[tool.mypy]`, `[tool.ruff]`,
`[tool.hatch.version]`), `requirements.txt` (duplikat źródła prawdy),
`.github/workflows/ci.yml`+`publish.yml`, `__init__.py` `__version__`,
zależności z CVE (`pillow`/`py7zr`/`pygments`/`pytest`). **Cel:** **bramka mypy
jest czerwona** — `audit/02-tooling.md` §2 raportuje 30 błędów / 10 plików na
`b0372f6`; krok `Type check pure modules` nie ma `continue-on-error`, więc
blokuje `test` na 6/9 kombinacjach macierzy, a `publish.yml` gejtuje na `ci.yml`
⇒ **potencjalny bloker release** (do potwierdzenia względem `origin/main`, który
ma commit „repo was import-broken"). Dalej: `pip-audit` `continue-on-error:true`,
wąski ruff (`E9,F63,F7,F82`), aktualność CVE zależności, single-source-of-truth
zależności. **Trust boundary:** TB-8. **Uzasadnienie modelu:** przegląd
konfiguracji/procesu, zero sygnałów rozproszonych → suma 0 → sonnet. Priorytet
P1 mimo niskiej złożoności, bo dotyczy zdolności do wydania.

### A7 — `platform-os-integration` (P3, sonnet)
**Zakres:** `_platform.py` (`get_drives` przez psutil, `get_special_dirs` przez
`winreg`/`xdg-user-dir`/mapowanie macOS, `is_hidden` przez `ctypes`,
`is_mod_key_down`, `get_file_time`), `demo.py` (DPI awareness, font Polski),
`_icons.py` ładowanie tekstur. **Cel:** timeout/degradacja subprocess
`xdg-user-dir`, poprawność read-only rejestru, brak wstrzyknięcia argumentów do
subprocesu (stała nazwa katalogu), zachowanie cross-platform. **Trust boundary:**
TB-7. **Uzasadnienie modelu:** wywołania OS tylko-odczyt, stałe argumenty,
timeout; brak głębokich łańcuchów → suma 1 → sonnet.

---

## 7. Uwagi metodologiczne dla kolejnych etapów

- Każde ustalenie odnosić do commitu `b0372f6` i osobno sprawdzać, czy nie jest
  już naprawione na `origin/main` (+8 commitów, m.in. „complete abandoned
  MVC/ctx migration (repo was import-broken)" i serie `from __future__`).
- Przed pisaniem ustaleń przejrzeć `docs/audits/*` (SWE16/GLM52/SWE17,
  PROGRAM_NAPRAWCZY, REKOMENDACJE) i pamięć projektu — nie duplikować zamkniętych
  punktów; skupić się na przyroście po refaktorze MVC.
- Priorytet weryfikacji „na wejściu": sprzeczność `--disable-javascript` vs JS
  overflow-marker (A2) i status czerwonej bramki mypy (A6) — oba mają
  natychmiastowy wpływ odpowiednio na poprawność podglądu i zdolność wydania.
