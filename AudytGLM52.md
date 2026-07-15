# Audyt projektu dpg-navigator — kompleksowe podsumowanie

## 1. Architektura i struktura kodu

### Struktura modułów

Projekt składa się z 18 modułów Python w `dpg_navigator/`:

| Moduł | Linie | Odpowiedzialność |
|---|---|---|
| `_dialog.py` | 1238 | Główna klasa `FileDialog` — UI, nawigacja, selekcja, wyszukiwanie |
| `_preview.py` | 2023 | `PreviewPanel` — routing formatów, renderowanie wszystkich typów |
| `_filesystem.py` | 679 | `DirectoryLister`, `DirectoryIndex`, ekstrakcja archiwów |
| `_html.py` | 708 | `HTMLRenderer` — Chrome Headless, scroll, auto-trim, resize |
| `_pdf.py` | 322 | `PDFRenderer` — pypdfium2, LRU cache, prefetch |
| `_platform.py` | 148 | Abstrakcje cross-platform (drives, special dirs, hidden files) |
| `_styles.py` | 271 | Sidebar renderers (Labeled/Compact) |
| `_keyboard.py` | 254 | Keyboard mixin — skróty, nawigacja tabeli |
| `_icons.py` | 164 | Icon registry — ładowanie PNG, mapowanie rozszerzeń |
| `_types.py` | 138 | Dataclasss: `DialogConfig`, `FileEntry`, `DialogMode` |
| `_preview_registry.py` | 159 | Routing formatów preview (bez zależności DPG) |
| `_preview_archive.py` | 140 | Ładowanie metadanych ZIP/7z |
| `_preview_table.py` | 85 | Parsowanie CSV/TSV |
| `_preview_spreadsheet.py` | 114 | Ładowanie Excel .xlsx |
| `_preview_sqlite.py` | 104 | Ładowanie SQLite (read-only) |
| `_preview_word.py` | 110 | Ładowanie Word .docx |
| `_preview_presentation.py` | 150 | Ładowanie PowerPoint .pptx |
| `__init__.py` | 57 | Public API, `__version__`, eksport `*_available()` |

### Ocena architektury

**Mocne strony:**
- Dobre wydzielenie modułów czystych danych (`_preview_registry`, `_preview_table`, `_preview_archive`, `_preview_spreadsheet`, `_preview_sqlite`, `_preview_word`, `_preview_presentation`) — testowalne bez GUI
- `PreviewCapabilities` dataclass umożliwia testowanie routing'u bez zależności
- Wzorzec generation-counter dla bezpiecznego anulowania wątków (`_bg_generation`, `_index_generation`, `_render_generation`, `_prefetch_generation`)
- `KeyboardMixin` poprawnie wydzielony jako mixin z deklaracjami atrybutów

**Dług techniczny:**
- **`_dialog.py` (1238 linii)** — wciąż monolityczny: UI construction, navigation, search, selection, background tasks, message boxes, new folder — wszystko w jednej klasie. Brak formalnego lifecycle managementu
- **`_preview.py` (2023 linie)** — największy moduł, zawiera routing + wszystkie metody renderowania (text, image, HTML, markdown, CSV, Excel, XML, code, ZIP, 7z, font, SQLite, PDF, Word, PowerPoint). Renderery Word/PPTX/CSV/XML/Code/Text/Font powinny być wydzielone do osobnych modułów tak jak już zrobiono z archive/spreadsheet/sqlite/word/presentation
- `FileDialog` używa klasowych atrybutów współdzielonych (`_shared_selec_theme`, `_instance_count`) — potencjalne problemy przy wielu instancjach

## 2. Bezpieczeństwo

### Zaimplementowane mechanizmy

- **ZipSlip protection** — `extract_from_archive` w `_filesystem.py` weryfikuje ścieżki ekstrakcji
- **Path traversal validation** — `validate_folder_name` blokuje `..`, separatory ścieżek
- **SQLite read-only** — połączenie przez URI `?mode=ro` z timeout 5s, identyfikatory escapowane (`_preview_sqlite.py:38-40`)
- **Binary file detection** — null-byte heuristic w `_load_text_content` (`_preview.py:624-627`)
- **Archive size limits** — `max_size` w `extract_from_archive`, `allow_large_extensions` dla PDF
- **Chrome subprocess timeout** — 30s timeout wstrzykiwany do `subprocess.run` (`_html.py:302-305`)
- **Bounded SQLite count** — `MAX_COUNT_SCAN = 100_000` zapobiega pełnemu skanowaniu tabeli (`_preview_sqlite.py:15-20`)

### Ryzyka bezpieczeństwa

- **HTML/Markdown/Word/Code rendering via Chrome Headless** — pliki HTML są renderowane przez `html2image` (Chrome). `_inject_helpers` wstrzykuje CSS reset i JS overflow marker, ale **nie sanitizuje** zawartości HTML. Chrome Headless uruchomiony jest z flagami `--disable-gpu`, `--hide-scrollbars`, `--force-device-scale-factor=1`, `--log-level=3` — **brak `--no-sandbox`** (dobrze), ale też brak `--disable-javascript` (JS jest celowo włączony dla overflow marker). Dla niezaufanych plików HTML to ryzyko — złośliwy JS może wykonać się w Chrome, choć sandbox Chrome'a ogranicza wpływ na system
- **Markdown → HTML → Chrome** — `_markdown.markdown()` nie sanitizuje raw HTML wewnątrz markdown. Złośliwy plik `.md` może zawierać `<script>` tags
- **Word mammoth → Chrome** — mammoth konwertuje .docx → HTML, następnie renderowany w Chrome. Mammoth powinien produkować bezpieczny HTML, ale to zależy od implementacji biblioteki
- **Temp file cleanup** — `extract_from_archive` tworzy pliki tymczasowe; cleanup zależy od `destroy()` lub `clear()`. Jeśli dialog zostanie zamknięty nietypowo, pliki mogą pozostać

### Rekomendacje P0 (krytyczne)

1. **Dodaj `--disable-javascript` dla HTML preview** — overflow marker można zastąpić analizą DOM po renderowaniu (np. przez `--dump-dom` lub CDP)
2. **Sanitizuj Markdown** — użyj `markdown` z `extensions=["tables", "fenced_code"]` + `bleach` do sanitizacji raw HTML
3. **Rozważ `--no-sandbox` tylko jeśli potrzebne** — obecnie nie dodane (dobrze), ale na CI bez Chrome może powodować problemy

## 3. Niezawodność i zarządzanie zasobami

### Wątki i timery

Projekt używa **daemon threads** wszędzie:
- `_compute_sizes_bg` — obliczanie rozmiarów katalogów (`_dialog.py:885`)
- `DirectoryIndex.build` — indeksowanie w tle (`_dialog.py:905`)
- `PDFRenderer._prefetch_worker` — prefetch stron PDF (`_pdf.py:299`)
- `HTMLRenderer._render_worker` — renderowanie HTML w tle (`_html.py:489`)
- `threading.Timer` dla debounced search i resize (`_html.py:705`)

**Brak formalnego JobManagera** — każdy wątek jest daemonem, więc proces Pythona może się zakończyć pozostawiając niedokończone operacje. Generation-counter zapobiega race conditions, ale:
- `_search_debounce_timer` w `FileDialog` — timer nie jest zawsze anulowany przy `destroy()`
- `_resize_timer` w `HTMLRenderer` — anulowany w `close()`, ale `close()` może nie być wywołane jeśli DPG context jest niszczony pierwsze

### Cleanup

- `FileDialog.destroy()` wywołuje `_cancel_background_tasks()`, `_preview.destroy()`, `_icons.destroy()`
- `PreviewPanel.destroy()` wywołuje `_close_active_renderers(force=True)`, `_delete_temp_font()`, `_delete_pptx_textures()`
- `PDFRenderer.close()` i `HTMLRenderer.close()` poprawnie zwalniają tekstury i buffery
- **Brak zwalniania `mvBuffer`** — `dpg.mvBuffer` tworzy bufor, ale `close()` tylko nulluje referencję Python. DPG powinien GC'ować przy `delete_item`, ale to zależy od implementacji DPG

### Rekomendacje P1 (strukturalne)

1. **Wprowadź `JobManager`** — centralne zarządzanie wątkami/timerami z `join()` przy shutdown
2. **Anuluj wszystkie timery w `destroy()`** — `_search_debounce_timer`, `_resize_timer`
3. **Dodaj `__enter__`/`__exit__`** do `FileDialog` dla context manager pattern

## 4. Testy

### Stan testów

- **18 plików testowych** w `dpg_navigator/tests/`
- **530 testów passing, 14 skipped** (według dokumentacji w `audyt1.md`)
- Testy pokrywają: filesystem, dialog logic, preview registry, archive/spreadsheet/sqlite/word/presentation/table, HTML, PDF, icons, styles, types, lifecycle, init
- **Integration test** — `test_dpg_smoke.py` (marker `@pytest.mark.integration`)
- **Lifecycle tests** — `test_lifecycle.py` testuje generation-counter cancellation, thread termination, restart supersedes

### Jakość testów

**Mocne strony:**
- Testy pure-data modułów bez zależności DPG (mockowane tylko na granicy)
- Testy path traversal — wyczerpujące przypadki (`..`, separatory, alt-separatory, unicode)
- Testy lifecycle z realnymi wątkami i filesystem
- Benchmark suite w `benchmarks/benchmark_heavy_paths.py` z profilami quick/standard

**Luki:**
- **Brak testów bezpieczeństwa** — nie testuje się czy Chrome otrzymuje `--disable-javascript`, nie testuje się sanitizacji HTML/Markdown
- **Brak testów `_preview.py` routing** — `PreviewPanel.update()` i `resolve_preview_kind()` są testowane osobno, ale integracja routing→renderer nie
- **Brak testów `_html.py`** — `HTMLRenderer` ma testy (`test_html.py`), ale nie pokrywają `_render_worker` (Chrome screenshot, overflow detection, auto-trim)
- **Brak testów `_pdf.py`** — `PDFRenderer` ma testy (`test_pdf.py`), ale LRU cache i prefetch nie są w pełni pokryte
- **14 skipped tests** — głównie integration tests wymagające DPG context

## 5. CI/CD

### Pipeline CI (`ci.yml`)

- **Matrix**: Ubuntu 3.8-3.13, Windows 3.8+3.13, macOS 3.13 (9 konfiguracji)
- **Lint**: `ruff check .`
- **Type check**: `mypy` na 17 modułach (tylko 3.10+)
- **Test**: `pytest -q`
- **Dependency audit**: `pip-audit` z `continue-on-error: true` (informational)

### Pipeline Publish (`publish.yml`)

- **Quality gate**: wywołuje `ci.yml` przed buildem — testy muszą przejść
- **Build**: `python -m build` + `twine check`
- **Publish**: TestPyPI (workflow_dispatch) + PyPI (release published)
- **OIDC trusted publishing** — `id-token: write`, brak API tokenów

### Ocena CI/CD

**Mocne strony:**
- Quality gate przed publish — testy muszą przejść
- Ekonomiczna matrix (nie pełny kartezjan)
- pip-audit jako informational check
- OIDC publishing (best practice)

**Luki:**
- **macOS tylko 3.13** — brak testów na starszych macOS/Python kombinacjach
- **Brak coverage report** — pytest nie generuje raportu pokrycia w CI
- **Brak artifact caching** dla build dependencies
- **pip-audit non-blocking** — CVEs nie blokują builda (akceptowalne dla beta, ale dla GA powinno być blocking)
- **Brak `mypy` na 3.8/3.9** — uzasadnione brakiem stubs, ale runtime compat zależy tylko od testów

## 6. Zależności

### Core (zawsze wymagane)
- `dearpygui >=0.9` — GUI framework
- `psutil >=5.9` — informacje o dyskach

### Optional extras (`pyproject.toml`)
- `[preview]`: Pillow, numpy, pypdfium2, html2image, markdown, pygments, openpyxl, python-docx, python-pptx, mammoth, py7zr
- `[dev]`: pytest, ruff, mypy
- `[all]`: łączy preview + dev

### Ocena zależności
- Wszystkie optional deps mają graceful degradation (try/except import + `*_available()` check)
- `html2image` wymaga Chrome/Chromium na systemie — `chrome_available()` sprawdza to
- Brak pinningu wersji (tylko `>=`) — może prowadzić do breaking changes
- `requirements.txt` jest redundantny względem `pyproject.toml` (komentarze wskazują optional)

## 7. Dokumentacja

- **README.md** (208 linii) — wyczerpujący: instalacja, quick start, features, security notes, HiDPI setup, dev guidelines
- **CHANGELOG.md** (91 linii) — wersje 1.0.0b1-b3 ze szczegółami
- **audyt1.md** (221 linii) — poprzedni audyt z oceną 3.2/5
- **REKOMENDACJE_REPO.md** (572 linie) — historyczne rekomendacje P0/P1/P2
- **Brak**: API reference (docstrings są dobre, ale brak Sphinx/MkDocs), CONTRIBUTING.md, LICENSE plik (wspomniany MIT w kodzie)

## 8. Ocena ogólna

| Obszar | Ocena | Uwagi |
|---|---|---|
| Architektura | 3.5/5 | Dobre wydzielenie pure-data, ale `_dialog.py` i `_preview.py` monolityczne |
| Jakość kodu | 3.5/5 | Czytelny, type-hinted, ale brak formalnego lifecycle |
| Bezpieczeństwo | 3.0/5 | ZipSlip/SQLite/path traversal OK, ale HTML/JS rendering bez sanitizacji |
| Niezawodność | 3.0/5 | Generation-counter dobry, ale brak JobManager, timer cleanup gaps |
| Testy | 3.5/5 | 530 testów, dobre pokrycie pure logic, luki w security i renderowaniu |
| CI/CD | 3.5/5 | Quality gate, OIDC, pip-audit, ale brak coverage i pełnej macOS matrix |
| Dokumentacja | 3.5/5 | README i CHANGELOG dobre, brak API docs i CONTRIBUTING |
| Zależności | 3.5/5 | Graceful degradation wzorowe, brak pinningu |

**Ocena ogólna: 3.4/5** — solidna beta, gotowa do kontrolowanego użycia, ale nie do high-assurance production.

## 9. Priorytety remediacji

### P0 — Krytyczne (przed GA)
1. Sanitizacja HTML/Markdown przed Chrome rendering (lub `--disable-javascript`)
2. Testy bezpieczeństwa dla preview pipeline
3. Coverage report w CI

### P1 — Strukturalne (następny sprint)
1. Refaktor `_preview.py` — wydzielenie rendererów do osobnych modułów
2. Wprowadzenie `JobManager` dla zarządzania wątkami/timerami
3. Refaktor `_dialog.py` — wydzielenie UI construction, navigation, search
4. Anulowanie wszystkich timerów w `destroy()`

### P2 — Rozwojowe
1. Pełna macOS matrix w CI
2. Pinning zależności (minimum wersje)
3. API docs (Sphinx/MkDocs)
4. `CONTRIBUTING.md` i `LICENSE` plik
5. Coverage target ≥90% dla core modułów
