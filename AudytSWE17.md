# DPG Navigator — Raport audytu kodu

**Przeglądana wersja:** `1.0.0b3` (`dpg_navigator/__init__.py`)  
**Zakres:** statyczny przegląd modułów `dpg_navigator/`, testów, CI, konfiguracji pakowania i dokumentacji. Nie uruchamiano testów runtime ani skanów CVE zależności.

---

## Podsumowanie dla kierownictwa

Projekt to funkcjonalna biblioteka okienka wyboru plików oparta na DearPyGui z rozbudowanym panelem podglądu. Ostatnie poprawki w `1.0.0b3` zamknęły kilka konkretnych błędów (routowanie Word/mammoth, limit wielkości wypakowywania archiwów, timeout Chrome, limity indeksu). Pozostałe ryzyka dotyczą głównie **bezpieczeństwa podglądu w Chrome Headless**, **higieny cyklu życia wątków/procesów** oraz **rozmiaru i złożoności dwóch monolitów GUI**: `_dialog.py` i `_preview.py`.

| Obszar | Ocena | Kluczowa obserwacja |
|---|---:|---|
| Architektura | 3/5 | Czyste loadery czysto-danych, ale `FileDialog` i `PreviewPanel` są zbyt duże. |
| Jakość kodu | 3/5 | Dobra dokumentacja, ale nadużywanie `Any`, szerokie `except Exception` i duplikacja. |
| Bezpieczeństwo | 3/5 | Zabezpieczenia ZipSlip/SQLite/ścieżek obecne, ale Chrome Headless uruchamia dowolny JS/sieć. |
| Niezawodność | 3/5 | Liczniki generacji anulują przestarzałe wątki, ale brak `join`/timeoutu i możliwe osierocone procesy. |
| Wydajność | 3/5 | Tekst/SQLite ograniczone, ale bufory renderowania HTML/Office mogą być bardzo duże. |
| Testy | 3/5 | ~500 funkcji testowych, głównie czysto-danych; GUI/HTML/Chrome pokryte słabo. |
| DevOps / CI | 3/5 | Dobre trusted publishing, ale pływające tagi akcji i brak SBOM/lockfile. |
| Dokumentacja | 4/5 | README jest czytelny; drobne niezgodności z `pyproject.toml` i przykładami. |

---

## Co zostało już naprawione w `1.0.0b3`

- **Routowanie Word/mammoth** — teraz wybiera `_render_word_html_preview` gdy `capabilities.mammoth` jest prawdziwe (`dpg_navigator/_preview.py:726-730`), zgodnie z dokumentacją.
- **Wykrywanie Chrome** — sprawdzane w runtime (`dpg_navigator/_html.py:45-63`); brak przeglądarki powoduje fallback do surowego tekstu.
- **Timeout podprocesu Chrome** — wstrzyknięty do `html2image` (`dpg_navigator/_html.py:302-305`), by zabić zawieszony proces.
- **Wypakowywanie elementów archiwów** — scentralizowane w `DirectoryLister.extract_from_archive()` z limitem `max_size` (`dpg_navigator/_preview.py:778-780`) i zabezpieczeniem ZipSlip.
- **Rekurencyjny indeks katalogów** — ograniczony do 50 000 wpisów (`dpg_navigator/_filesystem.py:47`) i uwzględnia `show_hidden`/dowiązania symboliczne.
- **Workflow publikacji** — teraz zależy od pełnego CI (`publish.yml:12-15` poprzez `uses: ./.github/workflows/ci.yml`).

---

## Pozostałe ustalenia i rekomendacje

### 1. Podgląd w Chrome Headless stanowi ryzyko sandbox — **Wysokie**
`dpg_navigator/_html.py` oraz ścieżki podglądu Word/Markdown/kodu przekazują dowolny HTML/Office/Markdown do Chrome Headless. Używane flagi (`--hide-scrollbars`, `--force-device-scale-factor=1`, `--disable-gpu`) **nie wyłączają** JavaScriptu, żądań sieciowych, zdalnych czcionek ani dostępu do plików lokalnych.

- **Ryzyko:** podgląd niezaufanego pliku HTML może wyciec lokalne pliki, pobrać zasoby z sieci lub wykonać złośliwe skrypty w rendererze.
- **Dowód:** własne flagi ustawiane są w `_Html2Image(...)` (`_html.py:287-295`); README ostrzega użytkownika, ale kod nie wymusza bezpiecznego trybu.
- **Rekomendacja:** wprowadź politykę `trusted`/`untrusted`; dla niezaufanych plików użyj osobnego profilu Chrome, `--user-data-dir`, `--block-new-web-contents`, `--disable-features=IsolateOrigins,site-per-process`, a najlepiej uruchamiaj Chrome w osobnej przestrzeni procesów lub VM. Minimalnie udostępnij `browser_available()` i wyłącz renderowany podgląd dla niezaufanych plików.

### 2. Cykl życia wątków i procesów jest niewystarczająco kontrolowany — **Wysokie**
Praca w tle jest uruchamiana jako `threading.Thread(daemon=True, ...)` w `_html.py:483-487`, `_pdf.py` i `_dialog.py`. Metoda `destroy()` tylko zwiększa licznik generacji; **nie wykonuje** `join()`, nie zabija procesu Chrome ani nie czeka na cleanup.

- **Ryzyko:** zamknięcie okna w trakcie renderowania może pozostawić zombie proces Chrome, otwarty `PdfDocument` lub częściowo zapisany tymczasowy PNG.
- **Dowód:** `HTMLRenderer.close()` anuluje timer i usuwa elementy DPG, ale nigdy nie zatrzymuje podprocesu Chrome utworzonego przez `html2image`; `PDFRenderer.close()` działa podobnie.
- **Rekomendacja:** dodaj mały `JobManager` oparty na `ThreadPoolExecutor`/`ProcessPoolExecutor` lub śledź aktywne wątki i wywołuj `join(timeout=...)`. Owijaj wywołania Chrome tak, by można je było zabić przy teardown.

### 3. `FileDialog` i `PreviewPanel` są zbyt duże — **Średnie**
- `dpg_navigator/_dialog.py` ma około 1200+ linii; `dpg_navigator/_preview.py` ma 2023 linie i miesza routing, cykl życia widgetów DPG, cache obrazów, stronicowanie tekstu, renderowanie tabel, zarządzanie delegatami PDF/HTML, podglądy Office i archiwów.
- **Ryzyko:** wysoki koszt utrzymania, trudność w testowaniu jednostkowym, łatwość o regresje przy dodawaniu formatów.
- **Rekomendacja:** podziel `_preview.py` na `preview/renderers/{image,text,html,pdf,table,office,archive,sqlite,font}.py` i zostaw `PreviewPanel` jako cienki router/koordynator cleanupu. Podziel `_dialog.py` na `DialogState`, `DialogController` i `FileDialog`.

### 4. Budżety zasobów dla renderowanych podglądów są hojne — **Średnie**
`HTMLRenderer` robi zrzuty ekranu o wysokości 8000 px i szerokości do 4000 px (`_html.py:68-75`), a następnie trzyma kilka pełnowymiarowych kopii NumPy/Pillow. Nie ma limitu wielkości wejściowego HTML.

- **Ryzyko:** spreparowany plik HTML/Office może spowodować alokacje w setki MB lub długie działanie Chrome.
- **Rekomendacja:** dodaj `max_html_bytes`, `max_render_pixels`, `max_render_time` oraz twarde limity `max_pages`/`max_slides` dla podglądów Office. Awaryjnie wyświetlaj komunikat „plik zbyt duży do podglądu”.

### 5. Raportowanie błędów w panelu podglądu jest zbyt ciche — **Średnie**
Wiele ścieżek podglądu łapie `Exception` i wywołuje `self.clear()`, co pokazuje tylko ogólny tekst **„Preview”** (`_preview.py:490-502`). Użytkownik nie wie, dlaczego plik się nie wyświetlił.

- **Dowód:** `_render_image_preview`, `_handle_virtual_archive_preview`, `_render_pptx_preview` itp. pochłaniają błędy.
- **Rekomendacja:** dodaj `_show_preview_error(message, detail)`, który zapisuje pełny traceback w logu i wyświetla bezpieczny komunikat dla użytkownika.

### 6. Pokrycie testami jest nierówne — **Średnie**
Jest około 497 funkcji `def test_` w 18 plikach, ale ciężkie ścieżki GUI/Chrome są słabo pokryte:

- tylko `6` funkcji testowych w `test_html.py` i `2` w `test_pdf.py`;
- `test_dpg_smoke.py` wymaga `DPG_INTEGRATION=1`, więc integracja jest domyślnie wyłączona;
- `test_dialog.py` mocno mockuje DPG, więc ścieżki cyklu życia/destroy nie są testowane z prawdziwym runtime.
- **Rekomendacja:** dodaj testy integracyjne dla create/destroy z aktywnymi workerami, brakiem Chrome, przekroczonymi rozmiarami archiwów oraz uszkodzonymi plikami Office. Rozważ `pytest-cov` z niskim progiem dla modułów czysto-danych.

### 7. Wzmocnienie CI i łańcucha dostaw — **Średnie**
- GitHub Actions używają pływających tagów (`actions/checkout@v6`, `actions/upload-artifact@v4`, `pypa/gh-action-pypi-publish@release/v1`). Skompromitowany tag może wstrzyknąć kod do pipeline’u wydawniczego.
- Job `pip-audit` ma `continue-on-error: true` (tylko informacyjny).
- Brak CodeQL, Bandit, skanowania sekretów, lockfile’a ani SBOM.
- **Rekomendacja:** przypnij SHA akcji, włącz Dependabot/Renovate, dodaj `pip-audit` do wymaganego quality gate i generuj SBOM/`THIRD_PARTY_NOTICES.md` dla bundlowanych zasobów/ikon.

### 8. Rozbieżności w dokumentacji — **Niskie**
- `README.md:173` podaje **„Python >= 3.10”**, podczas gdy `pyproject.toml:11` deklaruje `requires-python = ">=3.8"`.
- `examples/example.py` ma na sztywno wpisaną ścieżkę `C:/Windows/Fonts/segoeui.ttf`, co psuje przykład na innych platformach.
- `REKOMENDACJE_REPO.md` jest prawidłowo oznaczone jako historyczne, ale `audyt1.md` zawiera twierdzenia już nieaktualne (np. zepsute routowanie Word, brak zależności publikacji od CI) i powinno zostać odświeżone.
- **Rekomendacja:** ujednolicić README z `pyproject.toml`; uczynić przykład czcionki międzyplatformowym; zaktualizować lub zarchiwizować stare dokumenty audytowe.

### 9. Type safety i linting — **Niskie**
- `pyproject.toml:100` włącza tylko kilka reguł Ruff (`E9`, `F63`, `F7`, `F82`). Style, porządek importów i złożoność nie są wymuszane.
- Opcjonalne backendy są typowane jako `Any` i `cast(Any, None)` w `_preview.py`, `_html.py`, `_pdf.py`.
- **Rekomendacja:** rozszerz Ruff o sortowanie importów i reguły `I`; wprowadź małe klasy `Protocol` dla opcjonalnych backendów (`HtmlBackend`, `PdfBackend`, `OfficeBackend`) zamiast `Any`.

---

## Sugerowana kolejność priorytetów

### P0 — przed wydaniem stabilnym
1. Zatwardzić podgląd Chrome w trybie niezaufanego contentu i zapewnić cleanup procesów.
2. Dodać `join` i gwarancje teardown w `destroy()` dla wątków/procesów.
3. Wprowadzić limity wielkości/pikseli dla HTML/Office.
4. Zastąpić ciche `clear()` widocznymi stanami błędu.

### P1 — w ciągu 1–2 tygodni
1. Refaktoryzacja `PreviewPanel` do klas rendererów per format.
2. Refaktoryzacja `FileDialog` na warstwy state/controller/UI.
3. Rozszerzenie testów integracyjnych dla cyklu życia DPG i brakujących backendów.
4. Przypięcie SHA akcji CI i dodanie skanu SBOM/licencji.

### P2 — jakość użytkową
1. Zwiększenie pokrycia Ruff/mypy i dodanie `pytest-cov`.
2. Dodanie testów właściwości dla parsowania ścieżek, wypakowywania archiwów i wykrywania CSV.
3. Odświeżenie i wersjonowanie dokumentów audytowych/rekomendacyjnych.

---

## Wnioski

`dpg-navigator` to dojrzała biblioteka beta. Wersja `1.0.0b3` naprawiła najpilniejsze błędy funkcjonalne z wcześniejszych audytów. Aby osiągnąć poziom produkcyjny, należy skupić się na **sandboxowaniu/bezpieczeństwie Chrome**, **cyklu życia zadań w tle** oraz **podziale dużych modułów GUI na mniejsze, testowalne komponenty**. Po ich zaadresowaniu projekt będzie gotowy do stabilnego `1.0.0`.
