# Rekomendacje Rozwoju Repozytorium `dpg-navigator`

## Cel dokumentu

Ten dokument zbiera szczegółowe rekomendacje techniczne dla repozytorium `dpg-navigator` na podstawie analizy kodu, struktury projektu i testów. Celem nie jest tylko wskazanie "co poprawić", ale uporządkowanie prac według ryzyka, wpływu i kosztu wdrożenia.

## Status wdrożenia

Zrealizowane:

- ujednolicenie ekstrakcji archiwów przez `DirectoryLister.extract_from_archive()`;
- blokowanie zbyt dużych elementów archiwum przed ekstrakcją z wyjątkiem dozwolonych typów;
- lokalne katalogi robocze pytest i stabilne uruchamianie pełnego test suite;
- idempotentne `FileDialog.destroy()` oraz helpery anulowania zadań tła;
- wspólny cleanup aktywnych rendererów w `PreviewPanel`;
- wydzielenie registry formatów i routingu do `dpg_navigator/_preview_registry.py`;
- wydzielenie metadanych ZIP/7z do `dpg_navigator/_preview_archive.py`;
- wydzielenie parsera CSV/TSV do `dpg_navigator/_preview_table.py`;
- wydzielenie loaderów Excel i SQLite do czystych modułów bez zależności od DearPyGui;
- CI dla Windows i Linux, `ruff`, stopniowy `mypy` oraz pełne testy.
- rozszerzenie `mypy` na czyste moduły filesystem i preview;
- changelog oraz checklista wydania dla maintainera.

Pozostałe prace rozwojowe:

- dalsze wydzielanie rendererów Office z `PreviewPanel`;
- rozszerzanie zakresu `mypy` po uporządkowaniu modułów zależnych od DearPyGui;
- benchmarki ciężkich ścieżek preview;

Dokument zakłada, że projekt ma pozostać:

- biblioteką Pythona dla DearPyGui,
- projektem cross-platform,
- pakietem z opcjonalnymi preview features zależnymi od extras,
- repozytorium utrzymywalnym przez mały zespół lub jednego maintainera.

## Stan obecny

Projekt ma dobrą bazę:

- publiczne API jest małe i czytelne (`dpg_navigator/__init__.py`, `dpg_navigator/_types.py`);
- model optional dependencies jest sensowny i zgodny z funkcjami preview (`pyproject.toml`);
- logika plikowa, platformowa i część rendererów jest testowana;
- widać świadome podejście do bezpieczeństwa: walidacja nazw katalogów, quoted identifiers dla SQLite, bezpieczna ekstrakcja archiwów;
- architektura modułowa istnieje, ale część modułów jest już zbyt duża.

Główne słabości:

- `dpg_navigator/_preview.py` i `dpg_navigator/_dialog.py` są zbyt rozbudowane i skupiają za dużo odpowiedzialności;
- występuje niespójność w obsłudze ekstrakcji plików z archiwów;
- testy są liczne, ale pipeline jakościowy jest niepełny: brak widocznej konfiguracji CI, lintingu i type-checkingu;
- test suite jest wrażliwy na środowisko uruchomieniowe i katalogi tymczasowe.

## Priorytety

### P0: poprawki wysokiego ryzyka

1. Ujednolicić ekstrakcję plików z archiwów i usunąć ścieżkę omijającą helper bezpieczeństwa.
2. Uporządkować lifecycle plików tymczasowych, zasobów DPG, timerów i wątków.
3. Ustabilizować testy przez izolację `basetemp` i `cache_dir` do katalogu roboczego repo.

### P1: poprawki strukturalne

1. Rozbić `PreviewPanel` na registry rendererów i mniejsze klasy per format.
2. Rozbić `FileDialog` na controller stanu, warstwę UI i usługi tła.
3. Dodać CI oraz narzędzia jakości statycznej.

### P2: poprawki rozwojowe

1. Rozszerzyć dokumentację i przykłady.
2. Dodać benchmarki i pomiary wydajności dla ciężkich preview paths.
3. Doprecyzować kontrakt API i stabilność wersjonowania.

## Najważniejsze rekomendacje

### 1. Ujednolicić ścieżki ekstrakcji archiwów

Najważniejsza konkretna niespójność jest w tym, że część kodu korzysta z bezpiecznego helpera ekstrakcji, a część go omija.

Miejsca istotne:

- `dpg_navigator/_filesystem.py:296` - `DirectoryLister.extract_from_archive()`
- `dpg_navigator/_filesystem.py:314` - wydzielony katalog sesyjny dla ekstrakcji
- `dpg_navigator/_filesystem.py:332`
- `dpg_navigator/_filesystem.py:346` - blokada ZipSlip
- `dpg_navigator/_filesystem.py:69` - cleanup plików tymczasowych
- `dpg_navigator/_preview.py:728` - `_handle_virtual_archive_preview()`
- `dpg_navigator/_preview.py:739` - użycie `tempfile.gettempdir()`
- `dpg_navigator/_preview.py:750`
- `dpg_navigator/_preview.py:767` - bezpośrednia ekstrakcja do temp

Problem:

- `_handle_virtual_archive_preview()` rozpakowuje plik bezpośrednio do systemowego temp, zamiast używać wspólnego helpera z `DirectoryLister`.
- To oznacza duplikację logiki, rozjazd w polityce bezpieczeństwa i gorszą kontrolę nad cleanupem.

Rekomendacja:

1. Usunąć własną logikę ekstrakcji z `PreviewPanel._handle_virtual_archive_preview()`.
2. Zastąpić ją wyłącznie wywołaniem `DirectoryLister.extract_from_archive()`.
3. Przenieść limity rozmiaru ekstrakcji i typów plików do jednej wspólnej polityki.
4. Dodać testy na oba wejścia:
   - preview pliku wewnątrz archiwum,
   - kliknięcie elementu archiwum z listy ZIP/7z.

Efekt:

- jedna ścieżka bezpieczeństwa,
- prostszy kod,
- mniej miejsc do utrzymania,
- mniejsze ryzyko regresji i podatności.

### 2. Rozdzielić `PreviewPanel` na renderery per format

`dpg_navigator/_preview.py` ma obecnie ponad 2200 linii i odpowiada jednocześnie za:

- routing po rozszerzeniach,
- stan panelu,
- obrazy i layout,
- tekst,
- CSV/Excel,
- SQLite,
- PDF,
- HTML/Markdown/Word przez Chrome,
- PPTX,
- archiwa,
- font preview,
- lifecycle zasobów.

Miejsca istotne:

- `dpg_navigator/_preview.py:216` - `PreviewPanel`
- `dpg_navigator/_preview.py:692` - obraz
- `dpg_navigator/_preview.py:789` - HTML
- `dpg_navigator/_preview.py:987` - CSV
- `dpg_navigator/_preview.py:1064` - Excel
- `dpg_navigator/_preview.py:1204` - code preview
- `dpg_navigator/_preview.py:1267` - ZIP
- `dpg_navigator/_preview.py:1628` - SQLite
- `dpg_navigator/_preview.py:1697` - PDF path
- `dpg_navigator/_preview.py:1741` - Word HTML
- `dpg_navigator/_preview.py:1918` - PPTX

Rekomendowana docelowa struktura:

- `preview/base.py`
  - `PreviewRenderer`
  - wspólny kontrakt: `can_render`, `render`, `clear`, `on_resize`
- `preview/registry.py`
  - mapa rozszerzenie -> renderer
  - fallback chain
- `preview/renderers/image.py`
- `preview/renderers/text.py`
- `preview/renderers/html.py`
- `preview/renderers/pdf.py`
- `preview/renderers/table.py`
- `preview/renderers/archive.py`
- `preview/renderers/sqlite.py`
- `preview/renderers/office.py`

`PreviewPanel` powinien po refaktorze odpowiadać tylko za:

- wybór renderera,
- kontener DPG,
- wspólny status panelu,
- delegowanie resize/cleanup.

Korzyści:

- krótsze moduły,
- łatwiejsze testowanie,
- prostsze debugowanie,
- możliwość dodawania nowych formatów bez rozrostu jednego pliku.

### 3. Rozbić `FileDialog` na warstwy odpowiedzialności

`dpg_navigator/_dialog.py` pełni dziś rolę:

- kontrolera UI,
- magazynu stanu,
- routera nawigacji,
- komponentu selekcji,
- menedżera indeksu katalogów,
- menedżera size-cache,
- integratora preview panelu,
- kontrolera obsługi klawiatury.

Miejsca istotne:

- `dpg_navigator/_dialog.py:33` - `FileDialog`
- `dpg_navigator/_dialog.py:259` - `_navigate_to`
- `dpg_navigator/_dialog.py:420` - start size computation
- `dpg_navigator/_dialog.py:566` - click handling
- `dpg_navigator/_dialog.py:663` - budowanie selekcji
- `dpg_navigator/_dialog.py:800` - `_start_size_computation`
- `dpg_navigator/_dialog.py:828` - `_start_index_build`
- `dpg_navigator/_dialog.py:881` - `_build_ui`

Rekomendacja:

1. Wydzielić `DialogState`:
   - current_dir,
   - history,
   - selected_files,
   - current_filter,
   - focused row,
   - cache metadata.
2. Wydzielić `DialogController`:
   - nawigacja,
   - search/filter,
   - selekcja,
   - obsługa OK/Cancel.
3. Wydzielić `DialogBackgroundServices`:
   - directory indexing,
   - size computation,
   - debounce timers.
4. Zostawić w `FileDialog` tylko fasadę API publicznego i bootstrap UI.

Efekt:

- mniejsza złożoność klasy,
- mniej sprzężeń między stanem UI i logiką,
- łatwiejsze testy bez DearPyGui,
- prostsza przyszła rozbudowa.

### 4. Wprowadzić wspólny model lifecycle zasobów

Projekt używa:

- wątków,
- `threading.Timer`,
- cache,
- tekstur DPG,
- tymczasowych plików,
- callbacków zależnych od `dpg.mutex()`.

To jest poprawne kierunkowo, ale rozproszone.

Miejsca istotne:

- `dpg_navigator/_dialog.py:182-196`
- `dpg_navigator/_dialog.py:800-857`
- `dpg_navigator/_html.py:219-227`
- `dpg_navigator/_html.py:440-667`
- `dpg_navigator/_pdf.py:65-67`
- `dpg_navigator/_pdf.py:268-290`

Rekomendacja:

1. Dodać mały wewnętrzny komponent typu `ResourceManager` lub `SessionState`, który rejestruje:
   - aktywne timery,
   - aktywne generation counters,
   - tymczasowe ścieżki,
   - tekstury do cleanupu,
   - background jobs.
2. Ujednolicić pattern:
   - `start()`
   - `cancel()`
   - `cleanup()`
   - `is_stale(generation)`
3. Ograniczyć bezpośrednie operacje `dpg.delete_item(...)` rozsiane po wielu miejscach i zamknąć je w helperach.

Efekt:

- mniejsze ryzyko wycieków zasobów,
- mniejsze ryzyko wywołań na nieistniejących elementach DPG,
- lepsza przewidywalność shutdownu.

### 5. Ustabilizować testy w środowiskach z ograniczonym dostępem

Aktualnie test suite jest duży i wartościowy, ale w tym środowisku uruchomienie `pytest` kończyło się błędami uprawnień do katalogów tymczasowych oraz cache.

Obserwacje:

- merytorycznie wiele testów przechodzi,
- problemy dotyczą `tmp_path` i `.pytest_cache`,
- repo ma tylko podstawową konfigurację `pytest` w `pyproject.toml`.

Rekomendacja:

1. Ustawić lokalne katalogi robocze dla pytest w obrębie repo, np.:
   - `addopts = "--basetemp=.tmp/pytest"`
   - `cache_dir = ".tmp/pytest_cache"`
2. Dodać `.tmp/` do `.gitignore`, jeśli nie jest jeszcze objęte.
3. W CI uruchamiać testy zawsze w izolowanym workspace.
4. Dodać jeden smoke target dla testów bez zależności opcjonalnych oraz drugi dla `.[dev]`.

Efekt:

- powtarzalne lokalne uruchomienia,
- mniej fałszywych błędów środowiskowych,
- szybsza diagnoza realnych regresji.

### 6. Dodać CI, linting i type-checking

W repo nie widać konfiguracji:

- `ruff`,
- `mypy`,
- `coverage`,
- GitHub Actions lub innego CI,
- jawnych quality gates poza `pytest`.

To jest największy brak procesowy.

Rekomendacja minimalna:

1. Dodać `ruff`:
   - styl,
   - import order,
   - podstawowe bug patterns.
2. Dodać `mypy`:
   - najpierw dla `dpg_navigator/_types.py`, `_filesystem.py`, `_platform.py`,
   - później stopniowo dla `_dialog.py` i `_preview.py`.
3. Dodać coverage report i próg minimalny tylko dla modułów logiki bez GUI.
4. Dodać CI workflow:
   - Python 3.10-3.13,
   - install core,
   - install dev,
   - lint,
   - typecheck,
   - tests.

Rekomendacja rozszerzona:

- osobny job dla Windows, bo projekt realnie korzysta z zachowań platformowych;
- opcjonalny nightly job z extras `all`.

### 7. Wzmocnić kontrakt API publicznego

Publiczne API jest małe, co jest zaletą. Warto je teraz doprecyzować, zanim repo urośnie bardziej.

Miejsca istotne:

- `dpg_navigator/__init__.py`
- `dpg_navigator/_types.py:36` - `DialogConfig`
- `dpg_navigator/_dialog.py:171` - `show`
- `dpg_navigator/_dialog.py:180` - `destroy`
- `dpg_navigator/_dialog.py:207` - `change_callback`

Rekomendacje:

1. Doprecyzować typ callbacku, np. `Callable[[list[str]], None]`.
2. Jawnie udokumentować, które elementy są stabilne API, a które są internal-only.
3. Rozważyć oznaczenie bardziej zaawansowanych opcji konfiguracji jako experimental.
4. Dodać sekcję "compatibility promises" do README:
   - co jest objęte semver,
   - co może się zmieniać między wersjami beta.

Efekt:

- mniej niejawnych zależności użytkowników od internal API,
- łatwiejsze bezpieczne refaktoryzacje.

### 8. Uporządkować politykę optional dependencies

Aktualny model extras jest dobry, ale warto go doszlifować operacyjnie.

Miejsca istotne:

- `pyproject.toml:25`
- `pyproject.toml:30`
- `README.md` sekcje o preview i optional dependencies

Rekomendacje:

1. Dodać tabelę "feature -> extra -> external runtime requirements".
2. Wyraźnie zaznaczyć, że część rendererów wymaga nie tylko biblioteki Pythona, ale też działającego Chrome/Chromium dla `html2image`.
3. Dodać helper diagnostyczny, np. `dpg_navigator.diagnostics()` lub `fd.get_capabilities()`, który pokaże:
   - które preview features są aktywne,
   - których zależności brakuje,
   - czy wykryto backend HTML.

Efekt:

- mniej problemów supportowych,
- prostsza diagnoza "dlaczego preview nie działa".

### 9. Wydzielić i przetestować routing rozszerzeń

W `PreviewPanel` zestawy rozszerzeń są zapisane jako stałe klasowe. To działa, ale przy rosnącej liczbie formatów będzie trudniej utrzymać spójność.

Miejsca istotne:

- `dpg_navigator/_preview.py:250-334`

Rekomendacja:

1. Wydzielić registry formatów jako dane:
   - `extension -> renderer`
   - `renderer -> dependency predicate`
   - `renderer -> fallback renderer`
2. Dodać test snapshotowy lub kontraktowy dla mapy rozszerzeń.
3. Sprawić, żeby README i registry były generowane z jednego źródła prawdy lub przynajmniej weryfikowane testem.

Efekt:

- mniej rozjazdów między dokumentacją a implementacją,
- prostsze dodawanie nowych formatów.

### 10. Rozszerzyć testy o przypadki integracyjne bez pełnego GUI E2E

Obecne testy skupiają się głównie na logice. To dobrze, ale brak warstwy integracyjnej pomiędzy logiką a UI.

Rekomendacja:

1. Dodać testy integracyjne dla:
   - wyboru pliku po wpisaniu nazwy,
   - zachowania przy zmianie katalogu,
   - budowy deep search results,
   - preview plików z archiwum,
   - cleanup po `destroy()`.
2. O ile pełne E2E DearPyGui jest zbyt kosztowne, testować kontrakt warstwy pośredniej:
   - mock DPG,
   - fake panel,
   - fake renderer backend.
3. Dodać regresyjne testy na generation counters i anulowanie starych zadań.

Efekt:

- lepsze pokrycie zachowań wieloskładnikowych,
- mniejsze ryzyko subtelnych regresji po refaktorze.

### 11. Wprowadzić dokumentację techniczną utrzymania

Repo ma README i przykłady, ale nie ma widocznej warstwy dokumentacji maintainerskiej.

Rekomendacja:

1. Dodać `docs/architecture.md`:
   - przegląd modułów,
   - przepływ nawigacji,
   - przepływ preview,
   - background tasks.
2. Dodać `docs/dependencies.md`:
   - extras,
   - zależności systemowe,
   - known limitations.
3. Dodać `docs/release.md`:
   - jak publikować,
   - jak budować wheel/sdist,
   - jak weryfikować extras.
4. Dodać `CHANGELOG.md`.

Efekt:

- niższy koszt wejścia dla współmaintainera,
- łatwiejsze release management.

### 12. Dodać benchmarki dla ciężkich ścieżek preview

Nie wszystkie problemy wydajnościowe w takim projekcie wychodzą z samych testów funkcjonalnych.

Szczególnie wrażliwe ścieżki:

- PDF rendering,
- HTML/Markdown render przez Chrome,
- duże katalogi i indeksowanie,
- duże archiwa,
- duże pliki tekstowe,
- Excel/SQLite z większymi tabelami.

Rekomendacja:

1. Dodać prosty zestaw benchmarków lub skryptów pomiarowych dla:
   - czasu pierwszego preview,
   - czasu zmiany strony PDF,
   - czasu wejścia do dużego folderu,
   - czasu budowy indeksu.
2. Dodać fixture datasets w `examples/` lub osobnym katalogu `bench_data/`.
3. Udokumentować limity funkcjonalne:
   - maksymalny rozmiar preview tekstu,
   - limit wierszy tabeli,
   - expected behavior na wolnym sprzęcie.

## Proponowany backlog wdrożeniowy

### Etap 1: bezpieczeństwo i stabilność

1. Ujednolicić ekstrakcję archiwów przez `DirectoryLister.extract_from_archive()`.
2. Dodać testy regresyjne dla preview z archiwów.
3. Ustawić lokalne `basetemp` i `cache_dir` dla pytest.
4. Dodać CI smoke workflow.

### Etap 2: refaktoryzacja o najwyższym zwrocie

1. Rozbić `PreviewPanel` na registry i renderery.
2. Wydzielić background services z `FileDialog`.
3. Dodać `ruff` i podstawowy `mypy`.

### Etap 3: ergonomia utrzymania

1. Dodać dokumentację architektury.
2. Dodać changelog i release guide.
3. Rozbudować przykłady i diagnostykę capabilities.

## Proponowana kolejność plików do pracy

1. `dpg_navigator/_preview.py`
2. `dpg_navigator/_filesystem.py`
3. `dpg_navigator/_dialog.py`
4. `pyproject.toml`
5. `README.md`
6. `dpg_navigator/tests/test_dialog.py`
7. `dpg_navigator/tests/test_filesystem.py`
8. `dpg_navigator/tests/test_platform.py`

## Konkretne zadania techniczne do otwarcia jako issues

### Issue 1

Tytuł: "Unify archive extraction paths and remove unsafe temp extraction duplication"

Zakres:

- refaktor `_handle_virtual_archive_preview()`,
- użycie tylko `DirectoryLister.extract_from_archive()`,
- testy ZIP i 7z,
- cleanup po preview.

### Issue 2

Tytuł: "Split PreviewPanel into renderer registry and format-specific renderers"

Zakres:

- nowy pakiet `preview/`,
- kontrakt rendererów,
- migracja image/text/html/pdf/archive/sqlite/office,
- utrzymanie kompatybilności API z `FileDialog`.

### Issue 3

Tytuł: "Stabilize pytest temp/cache directories and add CI baseline"

Zakres:

- konfiguracja `addopts`,
- `cache_dir`,
- `.gitignore`,
- GitHub Actions dla 3.10-3.13 i Windows.

### Issue 4

Tytuł: "Introduce linting, typing and coverage gates"

Zakres:

- `ruff`,
- `mypy`,
- coverage dla modułów non-GUI,
- stopniowe podnoszenie quality gates.

## Wniosek

Projekt ma dobrą bazę produktową i rozsądny rdzeń techniczny. Największy problem nie polega na tym, że kod jest zły, tylko na tym, że najbardziej złożone moduły zaczynają przekraczać granicę wygodnej utrzymywalności. Najlepszy zwrot da teraz połączenie trzech rzeczy:

1. domknięcie niespójności bezpieczeństwa i cleanupu wokół archiwów,
2. rozbicie `PreviewPanel` i części `FileDialog`,
3. dodanie procesu jakościowego wokół repo.

To pozwoli rozwijać bibliotekę dalej bez narastania długu technicznego szybciej niż funkcjonalności.
