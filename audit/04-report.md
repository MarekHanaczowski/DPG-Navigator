# Raport audytu technicznego — `dpg-navigator`

**Data audytu:** 2026-07-22  
**Aktualizacja klasyfikacji:** 2026-07-22  
**Audytowany commit:** `b0372f6` (`HEAD -> main`)  
**Wersja pakietu:** `1.0.0b4`  
**Zakres:** `dpg_navigator/` (kod produkcyjny, testy, CI, dokumentacja), z uwzględnieniem wykonanej remediacji i testów regresyjnych.  
**Wyniki pomocnicze:** `audit/00-scope.md`, `audit/01-inventory.md`, `audit/02-tooling.md`, `audit/03-plan.md`, `audit/A7-platform-os-integration-round1.md`.

> **Granica ważności raportu:** lokalny `main` (`b0372f6`) jest **8 commitów za `origin/main`**. Raport jest zatem wiarygodny wyłącznie dla lokalnego commitu; nie stanowi oceny bieżącego `origin/main` ani artefaktu planowanego do publikacji. Przed decyzją release należy powtórzyć kontrole na dokładnym commitcie wydania, w czystym środowisku CI.

---

## 1. Streszczenie zarządcze

`dpg-navigator` jest biblioteką-beta widżetu file/directory pickera dla DearPyGui z panelem podglądu obrazów, PDF, Office, HTML/Markdown, archiwów, SQLite, fontów i kodu. Refaktor do modułów `dialog/`, `renderers/`, `vfs/` oraz `JobManager` poprawił separację logiki bez-GUI od renderowania DPG.

**Ocena lokalnego commitu: 3.8/5 (średnia pewność).** Po remediacji testy, Ruff, lokalna bramka `mypy`, build i `twine check` przechodzą. Wynik Bandit dla kodu bez testów wynosi 0 HIGH / 0 MEDIUM / 8 LOW. Najważniejsze pozostające zadania dotyczą pełnego matrixa CI oraz opcjonalnych testów DPG/Xvfb; testy Chrome i opóźnionego mountu są już objęte regresjami.

---

## 2. Metodologia i poziom dowodu

1. **Analiza statyczna kodu** — odczyt kluczowych modułów (`_dialog.py`, `dialog/*.py`, `vfs/*.py`, `renderers/*.py`, `_html.py`, `_pdf.py`, `_platform.py`, `_preview*.py`).
2. **Kontrole automatyczne** uruchomione z katalogu repo:
   - `python -m pytest -q dpg_navigator/tests`
   - `python -m ruff check .`
   - `python -m mypy <lista 17 modułów z ci.yml>`
   - `pip-audit -l --desc=auto --progress-spinner=off .`
   - `python -m bandit -r dpg_navigator`
   - `python -m bandit -r dpg_navigator -x dpg_navigator/tests -f json`
3. **Przegląd poprzednich audytów** w `docs/audits/` i `audit/`.
4. **Klasyfikacja dowodów:**
   - **potwierdzone** — wynik został powtórzony lokalnie albo bezpośrednio wynika z konfiguracji/kodu;
   - **potencjalne** — narzędzie lub analiza wskazuje klasę ryzyka, lecz nie ma reproduktora ani dowodu wykorzystania;
   - **informacyjne / false positive** — alert narzędzia nie opisuje podatności w danym przepływie danych.
5. **Zastrzeżenie środowiskowe:** wcześniejsze kontrole wykonywano w globalnym środowisku Python, ale po remediacji powtórzono testy, Ruff, mypy i `pip-audit` w świeżym środowisku z `pip install -e ".[dev]"`. Pełny matrix CI nadal wymaga uruchomienia na platformach CI.

---

## 3. Zbiorcze wyniki kontroli automatycznych

| Kontrola | Polecenie | Wynik | Wniosek |
|---|---|---|---|
| Testy jednostkowe | `python -m pytest -q dpg_navigator/tests --tb=short` | **PASS** — `511 passed, 17 skipped` (integracja wyłączona) | Potwierdza bieżący testowany kontrakt; pominięcia obejmują testy zależne od DPG/backendów lub platformy. |
| Lint | `python -m ruff check .` | **PASS** — `All checks passed!` | Potwierdza tylko wąsko skonfigurowane reguły Ruff. |
| Type check (lista CI) | `python -m mypy <17 modułów z ci.yml>` | **PASS** — 0 błędów | Lokalna bramka type-check przechodzi. |
| Audyt zależności | `pip-audit -l --desc=auto --progress-spinner=off .` | Brak znanych podatności w bieżącym środowisku | Kontrola w świeżym środowisku `.[dev]`: brak znanych podatności; lokalny pakiet `dpg-navigator` pominięty, ponieważ nie jest opublikowany na PyPI. |
| Bandit — cały katalog | `python -m bandit -r dpg_navigator` | Historyczny wynik przed triage'em: `2 High, 32 Medium, 656 Low` | Wynik zdominowany przez testy i heurystyki; aktualny wynik kodu bez testów jest podany poniżej. |
| Bandit — kod bez testów | `python -m bandit -r dpg_navigator -x dpg_navigator/tests -f json` | `0 High, 0 Medium, 8 Low` | Po triage'u pozostały alerty subprocess oraz niskopoziomowe wyjątki opcjonalnych backendów. |

**Komentarze:**

- `ruff` celowo sprawdza wyłącznie `E9,F63,F7,F82`; PASS nie stanowi oceny stylu, złożoności ani kompletności typowania.
- `ci.yml` uruchamia `mypy` bez `continue-on-error` dla Pythonów 3.10–3.13, czyli sześciu z dziewięciu wpisów macierzy. `publish.yml` wymaga całego reusable workflow CI; lokalna bramka `mypy` jest zielona, ale pełny matrix wymaga potwierdzenia.
- Job `audit` w CI instaluje `.[all]` i ma `continue-on-error: true`; lokalna kontrola świeżego środowiska nie zastępuje pełnego jobu CI, ale potwierdziła brak znanych podatności w dostępnych zależnościach.
- Bandit identyfikuje wzorce składniowe. Każdy alert z Medium/High został w tabeli ustaleń sklasyfikowany osobno na podstawie przepływu danych i testów, zamiast traktowania poziomu Bandit jako severity produktu.

---

## 4. Historyczne błędy `mypy` — zamknięte

```
dpg_navigator\_html.py:397: error: Argument 1 to "cancel_timer" of "JobManager" has incompatible type "Timer"; expected "TimerTask | None"  [arg-type]
dpg_navigator\_html.py:700: error: Argument 1 to "cancel_timer" of "JobManager" has incompatible type "Timer"; expected "TimerTask | None"  [arg-type]
dpg_navigator\_html.py:738: error: Incompatible types in assignment (expression has type "TimerTask", variable has type "Timer | None")  [assignment]
dpg_navigator\_preview.py:79: error: Library stubs not installed for "markdown"  [import-untyped]
dpg_navigator\_preview.py:85: error: Library stubs not installed for "pygments"  [import-untyped]
dpg_navigator\_preview.py:91: error: Library stubs not installed for "openpyxl"  [import-untyped]
dpg_navigator\_dialog.py:194: error: Cannot override writeable attribute with read-only property  [override]
dpg_navigator\_dialog.py:198: error: Cannot override writeable attribute with read-only property  [override]
dpg_navigator\_dialog.py:218: error: Cannot override writeable attribute with read-only property  [override]
dpg_navigator\_dialog.py:222: error: Cannot override writeable attribute with read-only property  [override]
Found 10 errors in 3 files (checked 17 source files)
```

**Interpretacja:**
- Błędy w `_html.py` wskazują, że adnotacja `_resize_timer` pozostała typu `threading.Timer | None`, choć runtime przypisuje wynik `JobManager.schedule_timer()` typu `TimerTask`. To niespójność kontraktu typów po zmianie mechanizmu debounce'a.
- Błędy w `_preview.py` to brak stubów dla opcjonalnych bibliotek (`markdown`, `pygments`, `openpyxl`) — można rozwiązać przez `ignore_missing_imports` lub `types-*`.
- Błędy w `_dialog.py` dotyczą kompatybilności adapterów właściwości (`@property` bez settera dla `_size_cache`, `_dir_index` itd. w `KeyboardMixin`) — źródło niespójności między typem a runtime.

---

## 5. Tabela ustaleń po triage'u

| ID | Klasyfikacja | Priorytet | Status dowodu | Wniosek i rekomendacja |
|---|---|---|---|---|
| **SEC-01** | Poprawność HTML/Chrome | P1 | **Zweryfikowane + regresja** | Opt-in test z realnym Chrome potwierdza działanie `_OVERFLOW_MARKER` przy produkcyjnych flagach, w tym `--disable-javascript`, dla dokumentu o szerokości przekraczającej viewport. |
| **SEC-02** | Alert Bandit B324 | P3 | **Informacyjne / false positive** | MD5 tworzy krótki identyfikator katalogu tymczasowego, nie zabezpiecza danych. `usedforsecurity=False` jest już stosowane tam, gdzie interpreter je wspiera; fallback istnieje dla Python 3.8. Udokumentować intencję i ewentualnie suppressować konkretny alert z uzasadnieniem. |
| **SEC-03** | XML parser | P1 | **Naprawione + regresja** | XML użytkownika jest parsowany przez `defusedxml.minidom`; test regresyjny potwierdza brak ekspansji external entity. Niebezpieczne lub uszkodzone XML są prezentowane jako tekst i logowane. |
| **SEC-04** | Alert Bandit B608 | P3 | **Informacyjne / false positive** | Tabela pochodzi z `sqlite_master`, identyfikator jest escapowany, baza działa w `mode=ro`, a test obejmuje nazwę z cudzysłowem. Nie wykazano SQL injection. Parametryzacja `LIMIT` może być obroną w głąb, nie remediacją potwierdzonej luki. |
| **SEC-05** | Diagnostyka archiwów | P2 | **Naprawione + regresja** | `ArchiveRenderer` loguje wyjątki, pokazuje bezpieczny komunikat oraz obsługuje przypadek, w którym ekstrakcja zwraca `None`. |
| **PLAT-01** | XDG Downloads | P1 | **Naprawione + regresja** | Dodano mapowanie `Downloads` → `DOWNLOAD`; test sprawdza dokładny argument `xdg-user-dir`. |
| **PLAT-02** | Responsywność przy mountach | P2 | **Naprawione + regresja** | Enumeracja `psutil.disk_partitions()` została przeniesiona do workera; sidebar renderuje się z pustą listą i aktualizuje po zakończeniu. Test symuluje opóźniony mount i potwierdza bezblokujący build UI. |
| **PLAT-03** | Przykłady HiDPI | P3 | **Potwierdzone statycznie** | Snippety i przykłady mogą propagować nieobsłużony błąd DPI. Ujednolicić z defensywnym wariantem z `demo.py`. |
| **PLAT-04** | Dekodowanie XDG | P3 | **Naprawione + regresja** | `UnicodeDecodeError` jest obsługiwany defensywnie; test potwierdza zwrot `None`. |
| **PLAT-05** | Nieznana platforma | P3 | **Naprawione statycznie** | Dodano jawną gałąź `elif _SYSTEM == "Windows"` oraz konwencjonalny fallback dla nieznanej platformy. |
| **QUAL-01** | Bramka CI `mypy` | P0 | **Naprawione + zweryfikowane** | Poprawiono typ `TimerTask`, properties adapterów oraz importy opcjonalnych zależności. Kontrola `mypy` przechodzi bez błędów dla modułów objętych bramką CI. |
| **QUAL-02** | Ciche błędy UI | P2 | **Naprawione** | Błąd renderowania wpisu jest logowany wraz ze ścieżką elementu, a pętla nadal przechodzi do kolejnych wpisów. |
| **QUAL-03** | Ciche błędy cleanupu | P3 | **Częściowo naprawione** | Dodano logi `DEBUG` dla cleanupu, PDF i zamykania współdzielonego renderera; pozostały niskopoziomowe wyjątki opcjonalnych backendów. |
| **ARCH-01** | Rozmiar komponentów | P2 | **Potwierdzone** | Refaktor ograniczył monolit, jednak `DocumentRenderer` nadal obsługuje pięć formatów, a `FileDialog` ma adaptery kompatybilności. Rozbijać dalej wyłącznie przy zmianach funkcjonalnych. |
| **ARCH-02** | Pokrycie GUI | P1 | **Potwierdzone** | Testy jednostkowe przechodzą, lecz 14 integracyjnych jest opt-in, a pokrycie modułów DPG jest niskie. Dodać testy z mockiem DPG i job z displayem/Xvfb. |
| **DEP-01** | Pinowanie akcji i SBOM | — | **Zweryfikowana kontrola** | Akcje są przypięte do SHA, a CI generuje i archiwizuje CycloneDX SBOM. Nie jest to otwarte ustalenie. |

---

## 6. Szczegółowa analiza per obszar

### 6.1 Bezpieczeństwo

**Zweryfikowane kontrole:**
- Ekstrakcja archiwów używa sprawdzenia `realpath`, limitu rozmiaru oraz odmawia podglądu zaszyfrowanych elementów.
- SQLite jest otwierany przez URI w trybie `mode=ro`; lista tabel pochodzi z `sqlite_master`, a cudzysłowy w identyfikatorach są escapowane. Test obejmuje tabelę o nazwie zawierającej `"`.
- Nazwy nowych folderów są walidowane przed utworzeniem.
- Renderer Chrome ma limit wejścia 2 MiB, timeout 30 s, osobny profil oraz flagi ograniczające nowe okna i ruch przez proxy.

**Rozróżnienie ryzyk:**
- **SEC-01** został zweryfikowany testem runtime z dostępным Chrome: marker został odczytany i zwrócił szerokość większą od viewportu przy produkcyjnych flagach.
- **SEC-03** został zamknięty przez `defusedxml` i regresję external entity; nadal warto utrzymywać test dla niebezpiecznych konstrukcji XML.
- **SEC-02** i **SEC-04** nie są potwierdzonymi lukami: MD5 nie pełni funkcji bezpieczeństwa, a SQLite identyfikator jest allowlistowany i escapowany. Pozostają zadaniami higieny kodu/konfiguracji narzędzia.

### 6.2 Niezawodność i cykl życia

- `JobManager` centralizuje harmonogramowanie timerów i ma kontrolowany `shutdown()` z ograniczonym `join()` wątków.
- `QUAL-01` został zamknięty poprawkami adnotacji; pozostaje test integracyjny resize z realnym DPG.
- Błędy podglądu archiwów i renderowania UI są logowane oraz komunikowane użytkownikowi; nie są dowodem awarii lub podatności.
- **PLAT-02** został zamknięty: opóźniona enumeracja mountów działa poza ścieżką budowania UI, a wynik jest bezpiecznie stosowany przez `dpg.mutex()`.

### 6.3 Architektura

- Moduły `dialog/`, `renderers/` i `vfs/` są istotnym postępem względem wcześniejszych monolitów.
- `PreviewPanel` pozostaje routerem, natomiast `DocumentRenderer` skupia pięć formatów. To problem utrzymaniowy, nie błąd funkcjonalny.
- Adaptery w `FileDialog` zachowują kompatybilność z `KeyboardMixin`; test regresyjny potwierdza współdzielenie stanu z `DialogState` i `DialogLogic`.

### 6.4 Testy i pokrycie

- `513 passed, 17 skipped` potwierdza stan testów w lokalnym środowisku po dodaniu regresji XML, XDG, archiwów, adapterów dialogu i opóźnionych mountów.
- Historyczny pomiar pokrycia wynosi 62% całego pakietu; wartości dla modułów GUI są niższe niż dla loaderów pure-data.
- Realny DPG/Chrome przeszedł 3 testy integracyjne; pozostaje uruchomienie pełnego matrixa CI oraz testu z rzeczywistym odpiętym zasobem sieciowym.

### 6.5 CI / łańcuch dostaw

- CI ma dziewięć konfiguracji OS×Python. Mypy działa dla sześciu z nich, bez `continue-on-error`; lokalna bramka `mypy` przechodzi, ale wynik matrixa CI nadal wymaga potwierdzenia.
- Publikacja zależy od reusable workflow CI; dlatego błąd jobu `test` zatrzymuje build artefaktów.
- Akcje są przypięte do SHA. CI generuje CycloneDX SBOM i publikuje go jako artefakt.
- Audyt zależności jest świadomie nieblokujący (`continue-on-error: true`), więc wynik CVE wymaga osobnej polityki release.

---

## 7. Plan remediacji

### P0 — przed decyzją release

1. **[Wykonane] Naprawić i powtórzyć `mypy`** (QUAL-01) na lokalnym środowisku dev; bramka `mypy` przechodzi bez błędów.
2. **[Wykonane lokalnie] Przeprowadzić release validation**: testy, Ruff, mypy i `pip-audit` przechodzą w świeżym środowisku `.[dev]`; build i `twine check` również przechodzą. Pozostaje pełny matrix CI oraz walidacja na dokładnym commicie release.

### P1 — następny sprint

1. **[Wykonane] SEC-01** — test z realnym Chrome potwierdził `_OVERFLOW_MARKER` przy produkcyjnych flagach, w tym `--disable-javascript`.
2. **[Wykonane] SEC-03** — przejście na `defusedxml` oraz regresja external entity.
3. **[Wykonane] PLAT-01** — mapowanie `Downloads` → `DOWNLOAD` i test dokładnego klucza.
4. **ARCH-02** — uruchamiać testy DPG z displayem/Xvfb oraz objąć regresjami resize, archive preview i brak backendów.

### P2 — poprawa odporności i utrzymania

1. **[Wykonane] PLAT-02** — enumeracja mountów działa w workerze, a test symuluje opóźnioną odpowiedź. `PLAT-04` i `PLAT-05` są wykonane.
2. **SEC-05, QUAL-02, QUAL-03** — komunikaty i logi zostały dodane; pozostały niskopoziomowe wyjątki opcjonalnych backendów do ewentualnego uporządkowania.
3. **ARCH-01** — rozdzielać `DocumentRenderer` przy kolejnych zmianach funkcjonalnych, bez refaktoru „dla samego rozmiaru”.
4. **SEC-02, SEC-04** — udokumentować false positive Bandit / wprowadzić defense in depth, bez podnoszenia ich do poziomu luki bezpieczeństwa.

---

## 8. Ocena końcowa per obszar

| Obszar | Ocena | Uzasadnienie |
|---|---:|---|
| Architektura | 4.0/5 | Refaktor MVC/VFS jest wyraźnym postępem; `DocumentRenderer` i adaptery kompatybilności pozostają kosztowne w utrzymaniu. |
| Jakość kodu | 4.0/5 | Czytelny kod, testowalne loadery i zamknięcie błędów `mypy`; pozostały ciche wyjątki w opcjonalnych backendach. |
| Bezpieczeństwo | 4.0/5 | Skuteczne kontrole ścieżek/archiwów/SQLite i bezpieczny parser XML; SEC-01 potwierdzono testem realnego Chrome. |
| Niezawodność | 3.5/5 | Centralny `JobManager` poprawia lifecycle; platformowe scenariusze availability nie zostały przetestowane. |
| Testy | 3.5/5 | Testy jednostkowe przechodzą, a SEC-01 ma opt-in regresję realnego Chrome; integracja DPG/Chrome pozostaje domyślnie pomijana. |
| CI / DevOps | 4.0/5 | SHA pinning, OIDC i SBOM są wdrożone; lokalne quality gates oraz build i `twine check` przechodzą, a CVE audit pozostaje nieblokujący. |
| Dokumentacja | 4.0/5 | README, CHANGELOG i materiały utrzymaniowe istnieją; raport wymaga ponowienia na branchu release. |
| Zależności | 3.5/5 | Sensowne extras; brak lockfile'a, a lokalny wynik CVE jest zależny od środowiska. |
| **Średnia / ogólna** | **3.8/5** | Ocena lokalnego commitu przy średniej pewności; nie jest automatyczną decyzją o gotowości `origin/main` do release. |

---

## 9. Wnioski

Lokalny commit `b0372f6` miał dobre podstawy architektoniczne i stabilny zestaw testów jednostkowych. Głównym historycznym ustaleniem blokującym pipeline było **10 błędów `mypy`**. Po wykonanej remediacji lokalne kontrole `mypy`, `ruff` i `pytest` przechodzą; alerty Bandit zostały ograniczone do poziomu `LOW`; build i `twine check` również przechodzą.

Przed stabilnym wydaniem należy nadal powtórzyć pełną walidację na dokładnym commitcie release w CI, ze szczególną uwagą na pełny matrix OS/Python oraz rzeczywisty zasób sieciowy. Lokalne testy DPG/Chrome, build, `twine check` i audyt świeżego środowiska są już zielone.

---

## 10. Załącznik — kluczowe fragmenty kodu

### 10.1 `_html.py` — zweryfikowany test runtime (SEC-01)

```python
# _html.py:91-103
_OVERFLOW_MARKER = (
    '<script>window.addEventListener("load",function(){...});</script>'
)

# _html.py:296-307 (w _get_hti)
cls._hti = _Html2Image(
    output_path=tempfile.gettempdir(),
    custom_flags=[
        '--hide-scrollbars',
        '--force-device-scale-factor=1',
        '--disable-gpu',
        '--log-level=3',
        '--disable-javascript',          # <- wyłącza JS
        '--proxy-server="http://127.0.0.1:0"',
        '--block-new-web-contents',
        f'--user-data-dir={profile_dir}',
    ],
    disable_logging=True,
)
```

### 10.2 `vfs/_archive.py` — alert Bandit o użyciu niekryptograficznym (SEC-02)

```python
def _short_md5(data: bytes) -> str:
    try:
        return hashlib.md5(data, usedforsecurity=False).hexdigest()[:8]
    except TypeError:
        return hashlib.md5(data).hexdigest()[:8]
```

### 10.3 `renderers/data.py` — XML via minidom (SEC-03)

```python
import xml.dom.minidom
...
parsed = xml.dom.minidom.parseString(raw_text)
formatted_text = parsed.toprettyxml(indent="    ")
```

### 10.4 `_preview_sqlite.py` — defense in depth, nie potwierdzony injection (SEC-04)

```python
cursor.execute(f'SELECT * FROM "{safe_table_name}" LIMIT {max_rows};')
cursor.execute(
    f'SELECT COUNT(*) FROM '
    f'(SELECT 1 FROM "{safe_table_name}" LIMIT {MAX_COUNT_SCAN + 1});'
)
```

### 10.5 `dialog/_ui.py` — ciche `continue` (QUAL-02)

```python
self._render_entry(entry, relative_label=relative)
except Exception:
    continue
```

---

## 11. Wykonana remediacja (po wstępnym raporcie)

W ramach polecenia *wykonaj* wdrożono poprawki zgodnie z planem P0–P2. Niektóre ustalenia pozostały otwarte, ponieważ wymagają scenariuszy runtime (Chrome, SMB/NFS) lub decyzji projektowych, a nie jedynie poprawek statycznych.

### 11.1 Zmiany w kodzie i zależnościach

- **`dpg_navigator/_html.py`** — typ `_resize_timer` zmieniony na `TimerTask | None`; dodany import `TimerTask` z `_job_manager`.
- **`dpg_navigator/_dialog.py`** — adaptery `KeyboardMixin` (`_size_cache`, `_dir_index`, `_selected_files`, `_selected_elements`, `_row_entries`, `_current_dir`, `_focused_row_index`, `_last_clicked_element`) uzupełnione o typy i setery; usunięto błędy `mypy` dotyczące nadpisywania atrybutów tylko do odczytu.
- **`dpg_navigator/_preview.py`** — dodano komentarze `# type: ignore[import-untyped]` dla opcjonalnych bibliotek `markdown`, `pygments`, `openpyxl`.
- **`dpg_navigator/_platform.py`** — dodano mapowanie nazw XDG (`Downloads` → `DOWNLOAD` itd.), obsługę `UnicodeDecodeError` oraz jawną gałąź `elif _SYSTEM == "Windows"` z fallbackiem dla nieznanych platform.
- **`dpg_navigator/renderers/archive.py`** — ciche `except Exception: pass` przy podglądzie elementu archiwum zastąpione logiem `ERROR` i komunikatem w panelu.
- **`dpg_navigator/dialog/_ui.py`** — ciche `except Exception: continue` w pętli renderowania wpisów zastąpione logiem `ERROR` z pełną ścieżką elementu.
- **`dpg_navigator/_filesystem.py`** — cleanup katalogu tymczasowego loguje wyjątek na poziomie `DEBUG`.
- **`dpg_navigator/_pdf.py`** — `DEBUG` logi dla błędów zamykania dokumentu i prefetchu stron.
- **`dpg_navigator/_dialog.py`** — błąd `HTMLRenderer.shutdown_shared()` logowany na `DEBUG`.
- **`dpg_navigator/_preview_sqlite.py`** — wartości `LIMIT` sparametryzowane przez `?`; dodano komentarze `# nosec B608` z uzasadnieniem.
- **`dpg_navigator/renderers/data.py`** — parser XML zmieniony z `xml.dom.minidom` na `defusedxml.minidom`.
- **`dpg_navigator/vfs/_archive.py`** — fallback `hashlib.md5(data)` w Pythonie 3.8 oznaczony `# nosec B324`.
- **`dpg_navigator/_filesystem.py`** — fallback `hashlib.md5(data)` w Pythonie 3.8 oznaczony `# nosec B324`.
- **`pyproject.toml`** — dodano `defusedxml>=0.7.1` do zależności głównych.
- **`requirements.txt`** — uzupełniono ręczną listę zależności o `defusedxml>=0.7.1`.

### 11.2 Wyniki kontroli po remediacji

Lokalne uruchomienie przybliżonych kontroli CI:

| Narzędzie | Wynik |
|---|---|
| `mypy` (zadeklarowane moduły) | **0 issues** |
| `ruff check .` | **All checks passed!** |
| `pytest dpg_navigator/tests -q` | **513 passed, 17 skipped** (integracja wyłączona) |
| `bandit -r dpg_navigator` (HIGH/MEDIUM) | **0 / 0** (pozostało 8 alertów LOW) |
| `python -m build` | **wheel i sdist zbudowane** (`1.0.0b4`) |
| `twine check dist/*` | **passed** |
| Czysty `venv` z `pip install -e ".[dev]"` | **smoke import PASS; pytest 511 passed, 16 skipped; Ruff PASS; mypy 0 issues** |
| `pip-audit` w świeżym środowisku `.[all]` | **No known vulnerabilities**; lokalny pakiet pominięty jako nieopublikowany na PyPI |
| `pytest -m integration` z `DPG_INTEGRATION=1` | **3 passed** — real DPG/Chrome integration |
| Test PLAT-02 z opóźnionym workerem | **2 passed** — sidebar build nie wywołuje synchronicznego `get_drives()`; wynik aktualizuje UI |

Pozostałe alerty `LOW` Bandit to:
- `B404/B607/B603` w `_platform.py` — użycie `subprocess` i `xdg-user-dir` (stała nazwa binarki, brak shella, input pochodzi z wewnętrznej listy nazw).
- `B110` w `renderers/font.py` i `_preview_presentation.py` — ciche wyjątki przy czyszczeniu DPG / ładowaniu kształtów prezentacji (nieblokujące, opcjonalne backendy).

### 11.3 Ustalenia pozostawione do późniejszej weryfikacji

- **SEC-01** — zamknięte: test z realnym Chrome przeszedł przy `--disable-javascript`.
- **PLAT-02** — zamknięte: test symuluje opóźnioną enumerację mountu i potwierdza aktualizację sidebaru poza ścieżką budowania UI.
- **ARCH-01 / ARCH-02** — refaktor `DocumentRenderer` oraz pełniejsze testy DPG/Xvfb to zmiany architektoniczne, a nie naprawy błędów.

---

*Pierwotna wersja raportu została przygotowana bez modyfikacji kodu produkcyjnego. Niniejsza wersja uwzględnia wykonaną remediację kodu i zaktualizowane wyniki narzędzi.*
