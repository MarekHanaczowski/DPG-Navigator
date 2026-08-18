# 02 — Kontrole automatyczne (tooling)

Data uruchomienia: 2026-07-19
Katalog repozytorium: `O:\Projekty\DPG Navigator`
Commit audytowany (HEAD lokalny): `b0372f6` — "Harden previews and CI: HTML limits, Polish
font glyphs, SBOM, SHA-pinned actions." Working tree czysty względem plików śledzonych
(zob. `audit/00-scope.md` §2 w sprawie rozjazdu z `origin/main`).

> Ten dokument tylko **uruchamia i raportuje** wyniki dostępnych kontroli automatycznych.
> Nie modyfikowano żadnego pliku produkcyjnego ani testowego. Nie instalowano żadnych
> nowych narzędzi — użyto wyłącznie tego, co było już obecne w środowisku.

## 0. Zastrzeżenie środowiskowe (dotyczy wszystkich sekcji poniżej)

Wszystkie polecenia uruchomiono interpreterem `C:\Users\hanac\AppData\Local\Programs\
Python\Python313\python.exe` (Python 3.13.8) — **globalnym środowiskiem użytkownika**,
nie izolowanym `venv` dedykowanym temu projektowi. Repozytorium ma zainstalowany pakiet
`dpg-navigator` w trybie `editable`, ale wpis w `site-packages` wskazuje na inną,
nieistniejącą już ścieżkę tymczasową z poprzedniej sesji
(`C:\Users\hanac\AppData\Local\Temp\claude\...\DPG-Navigator`). **Zweryfikowano, że mimo
to `import dpg_navigator` uruchomiony z katalogu repo (`O:\Projekty\DPG Navigator`)
poprawnie rozwiązuje się do lokalnych plików** (`dpg_navigator.__file__` →
`O:\Projekty\DPG Navigator\dpg_navigator\__init__.py`), bo bieżący katalog roboczy ma
pierwszeństwo w `sys.path` nad wpisem editable. Odnotowanie: gdyby ktokolwiek uruchomił
`pytest`/`mypy` spoza katalogu repo, mógłby przez pomyłkę przetestować nieistniejący/stary
kod — warto rozważyć uporządkowanie tego wpisu editable (`pip install -e .` ponownie
z tego katalogu), poza zakresem tego dokumentu (bez zmian w środowisku bez zgody).

To globalne środowisko zawiera setki pakietów niezwiązanych z tym projektem (inne
projekty użytkownika: `torch`, `transformers`, `gradio`, `chromadb`, `fastmcp`, `civilfem-rcf`
itd.). Ma to bezpośredni wpływ na wiarygodność skanu zależności (§4) — patrz zastrzeżenie
tam.

Wersje narzędzi użytych w tej sesji: `ruff 0.15.22`, `mypy 2.3.0 (compiled: yes)`,
`pytest 9.0.1`, `pip-audit 2.10.0`, `pyright 1.1.409` (bonus, nieoficjalne narzędzie
projektu — patrz §2b). Wszystkie były już zainstalowane przed startem tej sesji;
**nie zainstalowano niczego nowego**.

Zbadane opcjonalne backendy podglądu (`dpg_navigator.*_available()`) — wszystkie `True`
w tym środowisku: `word_available, mammoth_available, pptx_available, markdown_available,
pdf_available, html_available, chrome_available, excel_available, py7zr_available,
pygments_available`. Oznacza to, że pełny zestaw ekstrasów (`[all]`) jest zainstalowany
globalnie, w tym Chrome/Chromium widoczny na PATH.

---

## 1. Lint — `ruff`

**Polecenie (identyczne z `.github/workflows/ci.yml` → job `test` → krok `Lint`):**

```
python -m ruff check .
```

**Wynik: PASS** (exit code 0)

```
All checks passed!
```

`python -m ruff check . --statistics` potwierdza zero naruszeń. Konfiguracja
(`pyproject.toml` → `[tool.ruff.lint]`) celowo ogranicza reguły do poprawnościowych
(`E9, F63, F7, F82`) — to świadoma decyzja projektu (patrz `docs/ROADMAP.md`), nie
przeoczenie tego audytu. Brak ostrzeżeń, brak błędów.

---

## 2. Typy — `mypy`

**Polecenie (dokładna kopia z `ci.yml` → krok `Type check pure modules`, lista 17 modułów
uznanych za "czyste"/bez-GUI):**

```
python -m mypy \
  dpg_navigator/_types.py \
  dpg_navigator/_filesystem.py \
  dpg_navigator/_platform.py \
  dpg_navigator/_icons.py \
  dpg_navigator/_styles.py \
  dpg_navigator/_keyboard.py \
  dpg_navigator/_preview_registry.py \
  dpg_navigator/_preview_table.py \
  dpg_navigator/_preview_archive.py \
  dpg_navigator/_preview_spreadsheet.py \
  dpg_navigator/_preview_sqlite.py \
  dpg_navigator/_preview_word.py \
  dpg_navigator/_preview_presentation.py \
  dpg_navigator/_preview.py \
  dpg_navigator/_dialog.py \
  dpg_navigator/_pdf.py \
  dpg_navigator/_html.py
```

**Wynik: FAIL** (exit code 1) — **30 błędów w 10 plikach** (sprawdzono 17 plików
podanych bezpośrednio jako argumenty).

```
dpg_navigator\renderers\text.py:21: error: Incompatible types in assignment (expression has type "FileEntry", variable has type "None")  [assignment]
dpg_navigator\_job_manager.py:50: error: Need type annotation for "future"  [var-annotated]
dpg_navigator\_preview_spreadsheet.py:15: error: Incompatible types in assignment (expression has type "None", variable has type "Callable[[str | PathLike[str] | IO[bytes] | SupportsRead[bytes], bool, bool, bool, bool, bool], Workbook]")  [assignment]
dpg_navigator\_html.py:397: error: Argument 1 to "cancel_timer" of "JobManager" has incompatible type "Timer"; expected "TimerTask | None"  [arg-type]
dpg_navigator\_html.py:700: error: Argument 1 to "cancel_timer" of "JobManager" has incompatible type "Timer"; expected "TimerTask | None"  [arg-type]
dpg_navigator\_html.py:738: error: Incompatible types in assignment (expression has type "TimerTask", variable has type "Timer | None")  [assignment]
dpg_navigator\_availability.py:10: error: Skipping analyzing "pypdfium2": module is installed, but missing library stubs or py.typed marker  [import-untyped]
dpg_navigator\_availability.py:29: error: Skipping analyzing "html2image": module is installed, but missing library stubs or py.typed marker  [import-untyped]
dpg_navigator\_availability.py:54: error: Skipping analyzing "mammoth": module is installed, but missing library stubs or py.typed marker  [import-untyped]
dpg_navigator\_availability.py:109: error: Cannot assign to a type  [misc]
dpg_navigator\_availability.py:110: error: Cannot assign to a type  [misc]
dpg_navigator\renderers\document.py:8: error: Skipping analyzing "dearpygui.dearpygui": module is installed, but missing library stubs or py.typed marker  [import-untyped]
dpg_navigator\renderers\document.py:8: error: Skipping analyzing "dearpygui": module is installed, but missing library stubs or py.typed marker  [import-untyped]
dpg_navigator\renderers\document.py:11: error: Library stubs not installed for "bleach"  [import-untyped]
dpg_navigator\renderers\document.py:11: note: Hint: "python3 -m pip install types-bleach"
dpg_navigator\renderers\document.py:11: note: (or run "mypy --install-types" to install all missing stub packages)
dpg_navigator\renderers\document.py:73: error: Need type annotation for "_pptx_texture_tags" (hint: "_pptx_texture_tags: set[<type>] = ...")  [var-annotated]
dpg_navigator\renderers\document.py:78: error: Incompatible types in assignment (expression has type "PreviewContext", variable has type "None")  [assignment]
dpg_navigator\renderers\document.py:79: error: Incompatible types in assignment (expression has type "int | str", variable has type "None")  [assignment]
dpg_navigator\renderers\data.py:6: error: Skipping analyzing "dearpygui.dearpygui": module is installed, but missing library stubs or py.typed marker  [import-untyped]
dpg_navigator\renderers\data.py:6: note: See https://mypy.readthedocs.io/en/stable/running_mypy.html#missing-imports
dpg_navigator\renderers\data.py:6: error: Skipping analyzing "dearpygui": module is installed, but missing library stubs or py.typed marker  [import-untyped]
dpg_navigator\renderers\archive.py:2: error: Skipping analyzing "dearpygui.dearpygui": module is installed, but missing library stubs or py.typed marker  [import-untyped]
dpg_navigator\renderers\archive.py:2: error: Skipping analyzing "dearpygui": module is installed, but missing library stubs or py.typed marker  [import-untyped]
dpg_navigator\renderers\archive.py:30: error: Incompatible types in assignment (expression has type "PreviewContext", variable has type "None")  [assignment]
dpg_navigator\renderers\archive.py:31: error: Incompatible types in assignment (expression has type "FileEntry", variable has type "None")  [assignment]
dpg_navigator\renderers\archive.py:32: error: Incompatible types in assignment (expression has type "int | str", variable has type "None")  [assignment]
dpg_navigator\dialog\_ui.py:2: error: Skipping analyzing "dearpygui.dearpygui": module is installed, but missing library stubs or py.typed marker  [import-untyped]
dpg_navigator\dialog\_ui.py:2: error: Skipping analyzing "dearpygui": module is installed, but missing library stubs or py.typed marker  [import-untyped]
dpg_navigator\_dialog.py:194: error: Cannot override writeable attribute with read-only property  [override]
dpg_navigator\_dialog.py:198: error: Cannot override writeable attribute with read-only property  [override]
dpg_navigator\_dialog.py:218: error: Cannot override writeable attribute with read-only property  [override]
dpg_navigator\_dialog.py:222: error: Cannot override writeable attribute with read-only property  [override]
Found 30 errors in 10 files (checked 17 source files)
```

**Obserwacja istotna dla audytu:** 7 z 10 plików z błędami (`renderers/text.py`,
`renderers/document.py`, `renderers/data.py`, `renderers/archive.py`, `dialog/_ui.py`,
`_job_manager.py`, `_availability.py`) **nie są na jawnej liście 17 modułów** przekazanej
do mypy w `ci.yml` — pojawiają się, bo mypy domyślnie podąża za importami i raportuje
błędy w modułach transytywnie importowanych przez pliki z listy (`pyproject.toml
[tool.mypy]` nie ustawia `follow_imports = "silent"` ani żadnych per-modułowych
wykluczeń — zweryfikowano pełną zawartość sekcji `[tool.mypy]`, ma tylko
`warn_unused_configs`, `check_untyped_defs`, `no_implicit_optional`).

Krok `Type check pure modules` w `ci.yml` **nie ma `continue-on-error: true`** — jest
twardą bramką dla joba `test` na wszystkich kombinacjach macierzy poza Python 3.8/3.9
(gdzie krok jest jawnie pomijany warunkiem `if`). Powyższe polecenie to **dokładna kopia**
kroku CI. Jeśli ten wynik jest odtwarzalny na runnerach GitHub Actions, oznacza to, że
job `test` jest obecnie **czerwony** dla ubuntu 3.10–3.13, windows 3.13 i macos 3.13 (6 z
9 kombinacji macierzy) na commicie `b0372f6`.

**Ważny kontekst z `audit/00-scope.md` §2:** lokalny `main` (`b0372f6`, audytowany tutaj)
jest **8 commitów za `origin/main`**, w tym commit opisany jako *"fix(renderers): complete
the abandoned MVC/ctx migration (repo was import-broken)"*. Część lub całość powyższych
30 błędów mypy może już być naprawiona na `origin/main` — ten dokument raportuje wyłącznie
stan **lokalnego** repozytorium na commicie `b0372f6`, zgodnie z zakresem audytu. Nie
zweryfikowano stanu mypy na `origin/main` (brak instrukcji do przełączania gałęzi w tym
kroku).

### 2b. Bonus (informacyjnie) — `pyright` (narzędzie nieoficjalne, spoza toolchainu projektu)

`pyright 1.1.409` był już zainstalowany globalnie (obecność potwierdzają też nieśledzone
pliki `pyright_output*.txt` w korzeniu repo, artefakty poprzednich ręcznych uruchomień —
nie są częścią repo, `git status` pokazuje je jako untracked). **Nie jest to narzędzie
zadeklarowane w `pyproject.toml`, `ci.yml` ani w README** — repo nie ma
`pyrightconfig.json`, więc uruchomiono w trybie domyślnym ("basic"), bez żadnego
dostrojenia do specyfiki projektu (brak wykluczeń dla brakujących stubów DearPyGui itp.).
Traktować wyłącznie jako dodatkową, nieoficjalną daną — **nie** jako wynik kontroli
wymaganej przez projekt.

**Polecenie:**

```
python -m pyright dpg_navigator
```

**Wynik:** exit code 1 — **363 błędy, 2 ostrzeżenia** (cały pakiet `dpg_navigator/`,
łącznie z testami; znacznie szerszy zakres niż 17-plikowa lista mypy).

Rozkład błędów wg reguły:

| Reguła | Liczba |
|---|---|
| `reportGeneralTypeIssues` | 292 |
| `reportArgumentType` | 15 |
| `reportAttributeAccessIssue` | 14 |
| `reportInvalidTypeForm` | 11 |
| `reportIncompatibleVariableOverride` | 8 |
| `reportOptionalMemberAccess` | 7 |
| `reportOperatorIssue` | 5 |
| `reportOptionalIterable` | 3 |
| `reportSelfClsParameterName` | 2 |
| `reportPossiblyUnboundVariable` | 2 |
| `reportOptionalSubscript` | 2 |
| `reportAbstractUsage` | 2 |
| `reportReturnType` | 1 |
| `reportIncompatibleMethodOverride` | 1 |

80% błędów (`reportGeneralTypeIssues`) najprawdopodobniej pochodzi z braku stubów/
`py.typed` dla DearPyGui (ten sam problem co `[import-untyped]` w mypy, ale pyright w
trybie domyślnym raportuje go dużo agresywniej niż mypy). Pełny surowy log (854 linii)
zapisany lokalnie w `%TEMP%\pyright_out.txt` (plik tymczasowy poza repo, nie dołączony
tutaj ze względu na objętość) — nie kopiowano go do `audit/`, zgodnie z poleceniem
"pliki audytu tylko w audit/" (ten dokument jest jedynym plikiem audytu z tej sesji).

**Ograniczenie:** wynik pyright **nie powinien być traktowany jako lista realnych
defektów** bez ręcznej weryfikacji — narzędzie nie jest skonfigurowane pod ten projekt
(brak `pyrightconfig.json`, brak wykluczeń dla `reportMissingTypeStubs`/DPG), w
przeciwieństwie do mypy, który świadomie ogranicza się do modułów bez zależności GUI.

---

## 3. Testy — `pytest`

**Polecenie (identyczne z `ci.yml` → krok `Test`):**

```
python -m pytest -q
```

**Wynik: PASS** (exit code 0)

```
508 passed, 14 skipped in 1.61s
```

Zebrano `522 tests` (`pytest --collect-only -q` → `522 tests collected in 0.18s`,
zgodne z 508+14). Brak błędów, brak ostrzeżeń w standardowym uruchomieniu.

**Powody 14 pominięć** (`pytest -q -rs`), wszystkie platformowe/uzasadnione na tym
środowisku (Windows 11, brak uprawnień do symlinków):

```
SKIPPED [1] dpg_navigator\tests\test_dialog.py:221: Symlinks need privileges on Windows
SKIPPED [1] dpg_navigator\tests\test_dialog.py:229: Symlinks need privileges on Windows
SKIPPED [1] dpg_navigator\tests\test_filesystem.py:373: Symlinks require elevated privileges on Windows
SKIPPED [1] dpg_navigator\tests\test_filesystem.py:386: Symlinks require elevated privileges on Windows
SKIPPED [1] dpg_navigator\tests\test_filesystem.py:397: Symlinks require elevated privileges on Windows
SKIPPED [1] dpg_navigator\tests\test_platform.py:277: Unix-only
SKIPPED [1] dpg_navigator\tests\test_platform.py:317: Unix root path test
SKIPPED [1] dpg_navigator\tests\test_platform.py:321: Symlinks need privileges on Windows
SKIPPED [1] dpg_navigator\tests\test_platform.py:330: Symlinks need privileges on Windows
SKIPPED [1] dpg_navigator\tests\test_platform.py:425: Linux-only test
SKIPPED [1] dpg_navigator\tests\test_platform.py:434: Linux-only test
SKIPPED [1] dpg_navigator\tests\test_platform.py:443: Linux-only test
SKIPPED [1] dpg_navigator\tests\test_platform.py:451: Linux-only test
SKIPPED [1] dpg_navigator\tests\test_platform.py:458: Linux-only test
```

Uruchomiono też `pytest -q -m integration` (bez `DPG_INTEGRATION=1`) →
`522 deselected in 0.16s`, co potwierdza, że testy integracyjne (prawdziwe DPG, wymagają
wyświetlacza) poprawnie się nie uruchamiają domyślnie, zgodnie z markerem opt-in
zdefiniowanym w `pyproject.toml`. Testów integracyjnych **nie uruchomiono** z
`DPG_INTEGRATION=1` — wymagałoby to żywego kontekstu DPG/wyświetlacza, poza zakresem
bezobsługowego przebiegu w tej sesji (ograniczenie, nie błąd).

### 3b. Bonus (informacyjnie) — pokrycie kodu (`pytest-cov`, narzędzie nieoficjalne)

`pytest-cov 7.0.0` był już zainstalowany globalnie, ale **nie jest zadeklarowany** w
`pyproject.toml` (`[project.optional-dependencies].dev` zawiera tylko `pytest`, nie
`pytest-cov`) — nie ma też sekcji `[tool.coverage.*]`. Traktować jako dodatkową,
nieoficjalną daną, nie jako wynik wymaganej kontroli projektu.

**Polecenie:**

```
python -m pytest --cov=dpg_navigator --cov-report=term-missing -q
```

**Wynik:** `508 passed, 14 skipped, 4 warnings in 2.52s`, **`TOTAL` pokrycie 62%**
(6789 instrukcji, 2548 nieobjętych). Rozkład bardzo nierówny i **zgodny z architekturą
projektu** opisaną w `audit/00-scope.md` §9: moduły logiki bez-DPG (`_types.py`,
`_preview_registry.py`, `dialog/_state.py`, `vfs/`) mają pokrycie 90–100%, moduły
renderujące UI wymagające żywego kontekstu DPG (`dialog/_ui.py` 10%, `renderers/data.py`
13%, `dialog/_logic.py` 13%, `renderers/text.py` 17%, `_preview.py` 18%,
`renderers/archive.py` 22%, `renderers/image.py` 23%, `_keyboard.py` 24%,
`_job_manager.py` 29%, `renderers/font.py` 30%, `renderers/document.py` 32%,
`_styles.py` 39%, `_html.py` 36%) są objęte w małym stopniu — to spójne z rozmyślnym
podziałem "logika unit-testable / renderowanie DPG testowane integracyjnie (opt-in)",
nieuruchomionym w tej sesji (patrz wyżej). **Uwaga metodologiczna:** to nieoficjalne
uruchomienie liczy do pokrycia też sam katalog `dpg_navigator/tests/` (brak konfiguracji
wykluczającej), co nieznacznie zawyża `TOTAL` względem "czystego" pokrycia kodu
bibliotecznego — traktować liczbę jako orientacyjną.

**Ustalenie (obserwacja z uruchomienia testów, nie modyfikowano kodu):** przebieg z
pokryciem konsekwentnie zgłasza **4 identyczne `ResourceWarning`** (odtworzono w dwóch
niezależnych uruchomieniach, ten sam wzorzec za każdym razem):

```
dpg_navigator/tests/test_styles.py::TestLabeledSidebar::test_on_row_click_expand_navigates
  ...\unittest\mock.py:2247: ResourceWarning: unclosed database in <sqlite3.Connection object at 0x...>
```

Test `test_on_row_click_expand_navigates` (`dpg_navigator/tests/test_styles.py:95-112`)
**nie używa sqlite3** — ostrzeżenie jest błędnie przypisane do niego przez pytest, bo
pojawia się w momencie, gdy garbage collector finalizuje **inny, wcześniej utworzony**
obiekt `sqlite3.Connection`, akurat podczas wykonywania tego testu. Zidentyfikowane
źródło: `dpg_navigator/tests/test_preview_sqlite.py` linie 16, 39, 57, 74 — wszystkie
cztery używają wzorca `with sqlite3.connect(database_path) as connection:`. To znany
"gotcha" stdlib: **kontekst-menedżer `sqlite3.Connection` na `__exit__` tylko
commit/rollback transakcji, NIE zamyka połączenia** (w przeciwieństwie do większości
innych menedżerów kontekstu w Pythonie) — połączenie zostaje otwarte do czasu GC, stąd
`ResourceWarning: unclosed database` przy późniejszym sprzątaniu, zaobserwowane pod
`--cov` (prawdopodobnie inny timing GC niż bez instrumentacji coverage; bez `--cov`
w zwykłym `pytest -q` ostrzeżenie nie pojawiło się w tej sesji — próba izolowanego
uruchomienia samego `test_on_row_click_expand_navigates` z `-W always::ResourceWarning`
też go nie odtworzyła, co potwierdza, że to efekt kolejności/GC całego przebiegu, a nie
tego testu). To nieszkodliwy wyciek zasobu ograniczony do **kodu testowego** (nie
produkcyjnego) — zgłaszane wyłącznie informacyjnie, bez modyfikacji.

---

## 4. Skan zależności — `pip-audit`

**Polecenie (identyczne z `ci.yml` → job `audit` → krok `Audit dependencies`, minus
wcześniejszy krok instalacji, bo pakiety już były zainstalowane globalnie):**

```
python -m pip_audit
```

**Wynik: exit code 1** — pip-audit zwraca kod błędu, gdy znajdzie jakiekolwiek znane
podatności (to jego standardowe zachowanie, nie błąd narzędzia). W CI ten job ma
**`continue-on-error: true`**, więc nie blokuje builda — informacyjnie.

### ZASTRZEŻENIE KRYTYCZNE dla wiarygodności tego wyniku

To polecenie **audytuje CAŁE globalne środowisko Python 3.13** (zob. §0), nie izolowany
`venv` z wyłącznie zależnościami `dpg-navigator`. Wynik: **92 znane podatności w 34
pakietach**, z czego **zdecydowana większość dotyczy pakietów innych projektów
użytkownika** (`torch`, `transformers`, `gradio`, `chromadb`, `fastmcp`, `starlette`,
`mcp`, `authlib`, `cryptography` w wersjach niepowiązanych z `dpg-navigator` itd.) —
**nie jest to wiarygodny, odtwarzalny audyt zależności `dpg-navigator`**. CI robi to
poprawnie (`pip install -e ".[all]"` w czystym runnerze przed `pip-audit`) — ten job
(`ci.yml` → `audit`) jest **jedynym miarodajnym źródłem** dla tego typu skanu; nie
odtworzono go lokalnie w izolowanym `venv`, bo wymagałoby to nowej instalacji pakietów,
a zgodnie z poleceniem nie instalowano niczego bez zgody.

### Podzbiór istotny dla `dpg-navigator` (przefiltrowano 92 wpisy względem zależności
zadeklarowanych w `pyproject.toml`: core + wszystkie extras + `dev`)

| Pakiet | Wersja w tym środowisku | Gdzie w `dpg-navigator` | Podatności (ID) | Wersja z poprawką |
|---|---|---|---|---|
| `pillow` | 11.3.0 | extras `preview/pdf/word/pptx/html/markdown/code` (`Pillow>=9.0`) | 12 wpisów: PYSEC-2026-165 (×2), 2250, 2253, 2251, 2255, 2257, 2256, 2254, 2252, 2249, 2874, 3453, 3451 | 12.1.1–12.3.0 (różnie wg CVE) |
| `py7zr` | 1.1.0 | extra `archive` (`py7zr>=0.20.0`) | PYSEC-2026-2974, 2973, 2972 | 1.1.3 |
| `pygments` | 2.19.2 | extra `code` (`Pygments>=2.15.0`) | PYSEC-2026-2987 | 2.20.0 |
| `pytest` | 9.0.1 | `dev` (`pytest>=7.0`) | PYSEC-2026-1845 | 9.0.3 |
| `setuptools` | 80.9.0 | pośrednia (build/pip toolchain, nie zależność runtime projektu) | PYSEC-2026-3447 | 83.0.0 |

**Nie znaleziono** żadnych znanych podatności dla pozostałych bezpośrednich zależności
`dpg-navigator` obecnych w tym środowisku: `dearpygui` (2.1.0 — uwaga: nowsza niż pin
`>=1.9.1`, ale bez CVE w bazie), `psutil`, `bleach` (6.4.0), `numpy`, `pypdfium2`,
`python-docx`, `mammoth`, `html2image`, `python-pptx`, `openpyxl`, `markdown`, `ruff`,
`mypy` — brak wpisu w wyniku pip-audit oznacza brak znanej podatności dla zainstalowanej
wersji, **nie** brak audytu.

**Ograniczenia tego skanu:**
- Wersje pakietów to wersje **ambientne** tego globalnego środowiska (używanego też do
  innych, niepowiązanych projektów), **nie** wersje, które faktycznie zainstalowałoby
  `pip install -e ".[dev]"` z tego repo w czystym środowisku — mogą się różnić od tego,
  co dostaje świeży użytkownik/CI.
- Skan wymaga zapytań sieciowych do bazy podatności (OSV/PyPA) — wykonano z powodzeniem
  (odpowiedź otrzymana), ale środowisko offline dawałoby inny/brak wyniku.
- `pip-audit` **nie skanuje** zależności systemowej Chrome/Chromium (wymaganej przez
  `html2image` dla podglądu HTML/MD/kod/Word-HTML) — to poza zakresem narzędzi
  Python-owych.
- Rekomendacja: dla wiarygodnego wyniku uruchomić job `ci.yml` → `audit` na GitHub
  Actions (już istnieje i robi to poprawnie) albo, za zgodą użytkownika, powtórzyć
  lokalnie w świeżym `venv` (`python -m venv .audit_venv && ... pip install -e ".[all]"
  && pip install pip-audit && python -m pip_audit`) — nie wykonano tego kroku w tej
  sesji bez wyraźnej zgody na instalację.

---

## 5. Skan sekretów

**Brak dedykowanego narzędzia w środowisku** — sprawdzono obecność na `PATH` oraz jako
pakiet pip: `gitleaks`, `trufflehog`, `detect-secrets`, `bandit`, `git-secrets`, `semgrep`
— **żadne nie jest zainstalowane ani dostępne** w tej sesji. Zgodnie z poleceniem
("nie instaluj globalnych narzędzi bez zgody") **nie zainstalowano żadnego z nich**.
Brak też configu takiego narzędzia w repo (`.gitleaks.toml`, `.pre-commit-config.yaml`,
`bandit.yaml` — brak), potwierdzone też w `audit/00-scope.md` §6.

**Zastępczo wykonano ręczny skan heurystyczny (regex, przez ripgrep/Grep)** — to **nie
jest równoważne** dedykowanemu narzędziu (brak analizy entropii, brak bazy wzorców
dostawców, brak weryfikacji ważności znalezionego sekretu, brak deduplikacji/baseline).
Traktować jako najlepszy dostępny substytut, nie jako pełnoprawny audyt bezpieczeństwa.

### 5a. Drzewo robocze (pliki śledzone i nieśledzone w katalogu repo)

Wzorce przeszukane osobno, wynik dla każdego: **brak trafień**.

| Wzorzec | Cel | Wynik |
|---|---|---|
| `-----BEGIN (RSA\|EC\|OPENSSH\|DSA\|PGP)?PRIVATE KEY-----` | klucze prywatne | brak |
| `AKIA[0-9A-Z]{16}` / `ASIA[0-9A-Z]{16}` | klucze AWS | brak |
| `xox[baprs]-[0-9A-Za-z-]{10,}` | tokeny Slack | brak |
| `gh[pousr]_[A-Za-z0-9]{30,}` | tokeny GitHub | brak |
| `eyJ...\.eyJ...\....` | tokeny JWT | brak |
| `://user:pass@...` | dane logowania w URL/connection string | brak |
| `(api_key\|secret_key\|access_token\|auth_token\|client_secret\|password\|passwd)\s*[:=]\s*"..."` | ogólne przypisania sekretów | brak |
| `Bearer <token>` | nagłówki autoryzacji | brak |
| `TWINE_PASSWORD` / `PYPI_API_TOKEN` / `.pypirc` | sekrety publikacji PyPI | brak |

Dodatkowo sprawdzono nazwy plików śledzonych (`git ls-files`) pod kątem rozszerzeń/nazw
typowych dla sekretów (`.env`, `.pem`, `.key`, `.p12`, `.pfx`, `.crt`, `.cer`,
`id_rsa`/`id_dsa`/`id_ecdsa`/`id_ed25519`, `credentials`, `secrets`) — **0 trafień** wśród
125 plików śledzonych.

### 5b. Pełna historia Git (42 commity, wszystkie gałęzie)

```
git log --all -G'<wzorzec>' --oneline
```

- Klucze prywatne / AWS / Slack / GitHub tokens (`-G` na te same wzorce co wyżej,
  połączone) → **brak trafień w całej historii**.
- Szerszy wzorzec ogólny `(api[_-]?key|secret[_-]?key|password|passwd)\s*[:=]` (bez
  wymogu cudzysłowu, żeby złapać więcej) → **2 trafienia**, oba w commitach
  `818a64f` (initial release) i `ebca2ae` (refaktor MVC). Zweryfikowano treść: obie linie
  to `if z.password:` — sprawdzenie atrybutu obiektu archiwum 7z/zip (czy plik archiwum
  jest chroniony hasłem, funkcja obsługi archiwów chronionych hasłem opisana w
  `_preview_archive.py`/`vfs/_archive.py`), **nie** hardkodowany sekret. **Fałszywy
  pozytyw, potwierdzony ręcznie.**

### Wniosek

Brak dowodów na obecność sekretów (kluczy, tokenów, haseł) w drzewie roboczym ani w
historii Git tego repozytorium, w granicach możliwości ręcznego skanu regexowego opisanego
wyżej. **Rekomendacja (bez wykonania w tej sesji):** rozważyć dodanie dedykowanego
narzędzia (`gitleaks` lub `detect-secrets`) jako kroku CI — już odnotowane jako brak w
`audit/00-scope.md` §6 "Braki/obserwacje" — decyzja i instalacja wymagają zgody
użytkownika.

---

## 6. Zbiorcze podsumowanie

| Kontrola | Polecenie | Wynik | Exit code |
|---|---|---|---|
| Lint | `python -m ruff check .` | **PASS** | 0 |
| Typy (lista CI) | `python -m mypy <17 plików z ci.yml>` | **FAIL** — 30 błędów / 10 plików | 1 |
| Typy (bonus, nieoficjalne) | `python -m pyright dpg_navigator` | 363 błędy / 2 ostrzeżenia (nieskonfigurowane) | 1 |
| Testy | `python -m pytest -q` | **PASS** — 508 passed, 14 skipped | 0 |
| Pokrycie (bonus, nieoficjalne) | `python -m pytest --cov=dpg_navigator --cov-report=term-missing -q` | 62% TOTAL, 4 ResourceWarning (leak w teście) | 0 |
| Zależności | `python -m pip_audit` | 92 podatności / 34 pakiety (**środowisko globalne, nie izolowane** — patrz zastrzeżenie §4); z tego 5 pakietów istotnych dla projektu z realnymi CVE (`pillow`, `py7zr`, `pygments`, `pytest`, pośrednio `setuptools`) | 1 |
| Sekrety | ręczny regex-skan (ripgrep) drzewa + pełnej historii Git — brak dedykowanego narzędzia w środowisku | **brak trafień** (2 fałszywe pozytywy zweryfikowane i odrzucone) | n/d |

## 7. Ograniczenia tego przebiegu (zbiorczo)

1. Wszystkie polecenia uruchomiono w **globalnym** środowisku Python użytkownika, nie w
   izolowanym `venv` scoped do `dpg-navigator` — wpływa to głównie na wiarygodność
   skanu zależności (§4), w mniejszym stopniu na pokrycie kodu (obecność ambientnego
   `pytest-cov`, niezadeklarowanego w `pyproject.toml`).
2. Nie zainstalowano żadnego nowego narzędzia (zgodnie z poleceniem) — skan sekretów
   opiera się wyłącznie na ręcznych wzorcach regex, nie na dedykowanym silniku detekcji.
3. Nie uruchomiono testów integracyjnych (`DPG_INTEGRATION=1 pytest -m integration`) —
   wymagają żywego kontekstu DPG/wyświetlacza, poza zakresem bezobsługowej sesji.
4. Nie uruchomiono generowania SBOM (`cyclonedx_py`, moduł niedostępny w tym środowisku)
   — poza zakresem pięciu kontroli wskazanych w poleceniu (testy/lint/typy/zależności/
   sekrety); `ci.yml` → job `sbom` już to pokrywa w CI.
5. Wyniki mypy (§2) dotyczą wyłącznie lokalnego commitu `b0372f6`, który — jak odnotowano
   w `audit/00-scope.md` §2 — jest 8 commitów za `origin/main`, gdzie mogła już zostać
   wdrożona poprawka opisana jako "repo was import-broken". Nie zweryfikowano stanu
   `origin/main` w tej sesji.
6. Skan sekretów w historii Git (§5b) użył `git log -G` (pickaxe) na 42 commitach —
   metoda solidna dla tego rozmiaru historii, ale nie zastępuje dedykowanego narzędzia
   z bazą sygnatur dostawców (AWS/GCP/Azure/Stripe/itd.) i analizą entropii łańcuchów.
