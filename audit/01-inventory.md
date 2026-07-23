# 01 — Inwentaryzacja repozytorium

Data: 2026-07-19
Commit audytowany: `b0372f6` (lokalny `main`; patrz `audit/00-scope.md` §2 —
`origin/main` zawiera 8 dodatkowych commitów nieobecnych lokalnie).

> Ten dokument jest wyłącznie inwentaryzacją stanu repozytorium — nie zawiera
> ocen, ryzyk ani rekomendacji (to zadanie kolejnych etapów audytu). Nie
> modyfikowano kodu produkcyjnego; artefakt zapisany wyłącznie w `audit/`.

---

## 1. Moduły i odpowiedzialności

Pakiet: `dpg_navigator/` (63 pliki `.py` śledzone w git, ~7 556 linii kodu
źródłowego bez testów, wg `wc -l`). Architektura po refaktorze MVC: ścisły
rozdział logiki bez-GUI (`dialog/_state.py`, `dialog/_logic.py`, `vfs/`,
`_filesystem.py`, `_preview_registry.py`, loadery danych `_preview_*.py`) od
warstwy renderującej DPG (`_dialog.py`, `dialog/_ui.py`, `renderers/`,
`_preview.py`, `_pdf.py`, `_html.py`, `_icons.py`, `_styles.py`,
`_keyboard.py`).

### 1.1 Rdzeń / orkiestracja

| Moduł | Linie | Odpowiedzialność |
|---|---:|---|
| `__init__.py` | 59 | Publiczny re-export API (`FileDialog`, `DialogConfig`, `DialogMode`, `StyleVariant`, `FileEntry`, `DEFAULT_FILTER_LIST`, predykaty `*_available()`); `__version__` (jedyne miejsce bumpowania wersji, czytane przez hatchling). |
| `_dialog.py` | 687 | `FileDialog(KeyboardMixin)` — orkiestrator: `__init__` (budowa configu, unikalizacja tagu DPG, inicjalizacja `DialogState`/`DialogLogic`/`PreviewPanel`/`IconRegistry`/sidebar/`DialogUIBuilder`), `show/hide/destroy/change_callback`, adaptery kompatybilności właściwości (`_size_cache`, `_dir_index`, `_selected_files` itd. delegujące do `state`/`logic`), obsługa kliknięć (`_on_entry_click` — pojedynczy/wielokrotny wybór, podwójny klik nawigacja/otwarcie, ekstrakcja z archiwum przy podwójnym kliku), sortowanie kolumn (`_on_sort`), zwracanie wyboru (`_return_selection`), wyszukiwanie/filtr, przełącznik podglądu, tworzenie nowego folderu, komunikaty błędów (modal/status label). |
| `dialog/_state.py` | 64 | `DialogState` (dataclass) — cały mutowalny stan: nawigacja/historia, zaznaczenie, listing (`row_entries`, filtr, sort), wyszukiwanie (query, `index_generation`, debounce timer, separator wierszy deep-search), podgląd (`is_preview_open`), async (`size_cache`, `pending_size_cells`, `bg_generation`). Metoda `navigate()` zarządza stosem historii. |
| `dialog/_logic.py` | 277 | `DialogLogic` — logika bez DPG: `go_back/go_up/navigate_to` (w tym rozwiązywanie ścieżek wirtualnych archiwum `archiwum.zip\|/wewnątrz`, walidacja `os.path.isdir`/`PermissionError`), `_create_new_folder` (z `validate_folder_name`), `refresh_listing`/`_run_search`/`_perform_deep_search` (debounce 0.3 s przez `JobManager`), `start_index_build`/`start_size_computation` (zadania w tle), `cancel_background_tasks` (inkrementacja generacji + anulowanie timera). |
| `dialog/_ui.py` | 430 | `DialogUIBuilder` — budowa drzewa widgetów DPG: `_build_ui` (root window, motywy, sidebar, explorer, toolbar, pasek wyszukiwania, pasek nowego folderu, tabela explorer, dolny pasek), `_render_entry`/`_render_entries_list` (renderowanie wierszy tabeli z ikonami, formatowaniem rozmiaru/daty, drag-and-drop payload). |
| `_types.py` | 142 | Modele danych: `DialogMode`, `StyleVariant` (Enum), `FileEntry` (frozen dataclass), `DialogConfig` (dataclass, ~20 pól konfiguracyjnych z docstringami), `DEFAULT_FILTER_LIST` (tuple, ~180 rozszerzeń). |
| `_availability.py` | 129 | Sondowanie opcjonalnych backendów przy imporcie (`try/except Exception` wokół importów pypdfium2/numpy/Pillow/html2image/python-docx/mammoth/python-pptx/openpyxl/markdown/Pygments/py7zr) i funkcje `*_available()` konsumowane w całym pakiecie. |
| `_job_manager.py` | 145 | `JobManager` (statyczny) — `submit()` uruchamia krótkożyjący wątek daemon per zadanie (`concurrent.futures.Future`); dedykowana pętla timera oparta o kopiec (`heapq`) zamiast wątku na każdy debounce (`schedule_timer`/`cancel_timer`); `shutdown(wait, timeout)` zamyka pętlę timera i czeka na wątki robocze. |
| `_platform.py` | 147 | Abstrakcje cross-platform: `get_drives()` (psutil + `/Volumes` na macOS), `get_special_dirs()` (Windows: `winreg` odczyt `User Shell Folders`; Linux: `xdg-user-dir` przez `subprocess.run` z timeout=2 s; macOS: mapowanie nazw), `is_mod_key_down()`, `is_hidden()` (Windows: `ctypes.windll.kernel32.GetFileAttributesW`), `get_file_time()`. |
| `_icons.py` | 163 | `IconRegistry` — ładowanie 41 nazwanych ikon PNG z `images/` do tekstur DPG w pętli, mapa rozszerzenie→ikona (`EXTENSION_MAP`/`_EXT_LOOKUP`, O(1)), `get_for_file`/`get_for_dir`, `destroy()` (zwolnienie tekstur). |
| `_styles.py` | 270 | `SidebarRenderer` (ABC) + `LabeledSidebar` (drzewo katalogów z etykietami, `_MAX_TREE_DEPTH=10`, ~200 px, resizable) i `CompactSidebar` (tylko ikony, ~40 px, tooltips); `STYLE_REGISTRY: dict[StyleVariant, type[SidebarRenderer]]`. |
| `_keyboard.py` | 253 | `KeyboardMixin` — globalne handlery klawiatury DPG (ESC, F5, Ctrl+A, Strzałki, Enter) z guardem `_is_dialog_active()`; nawigacja klawiaturą po wierszach tabeli (`_move_focus`, `_select_row_by_index`, `_activate_focused_row`); `mouse_wheel_handler` deleguje do PDF/HTML scroll. |

### 1.2 Filesystem i wirtualny filesystem (VFS)

| Moduł | Linie | Odpowiedzialność |
|---|---:|---|
| `_filesystem.py` | 447 | `DirectoryLister` (fasada delegująca do `VFSRegistry`: `list_directory`, `compute_dir_size`, `format_size`/`format_time`, `extract_from_archive`, zarządzanie katalogiem tymczasowym sesji `_get_session_temp_dir`/`cleanup_temp_files`); `validate_folder_name()` i `build_selection_list()` (ochrona przed path traversal — patrz §4); `DirectoryIndex` — indeks w pamięci budowany w tle (`INDEX_SCAN_DEPTH=8`, `INDEX_TTL=60s`, `INDEX_MAX_ENTRIES=50 000`, `INDEX_MAX_RESULTS=500`), thread-safe (`threading.Lock`), rekurencyjny `os.scandir` z licznikiem generacji do anulowania (`_Cancelled`) i twardym limitem wpisów (`_IndexFull`); nie podąża za dowiązaniami symbolicznymi katalogów. |
| `vfs/_base.py` | 49 | `VFSProvider` (ABC): `is_valid_path`, `list_dir`, `get_size`, `extract_file`. |
| `vfs/_local.py` | 114 | `LocalVFSProvider` — fizyczny filesystem przez `os.scandir`/`os.walk` (rozmiar katalogu ograniczony `MAX_SCAN_DEPTH=3`), filtrowanie `fnmatch`, ukryte pliki via `_platform.is_hidden`. |
| `vfs/_archive.py` | 241 | `ArchiveVFSProvider` — listing/ekstrakcja z ZIP (`zipfile`) i 7z (`py7zr`, opcjonalny) po konwencji `archiwum\|/wewnątrz`; ochrona ZipSlip (`os.path.realpath` + sprawdzenie prefiksu przed `zf.extract`), odmowa rozpakowania zaszyfrowanych archiwów, limit rozmiaru rozpakowanego pliku (`max_size`/`allow_large_extensions`), katalog tymczasowy per-archiwum nazwany hashem MD5 ścieżki (`_short_md5`, `usedforsecurity=False` z fallbackiem dla starszych Pythonów). |
| `vfs/_registry.py` | 42 | `VFSRegistry` — routing ścieżki do providera (`ArchiveVFSProvider` przed `LocalVFSProvider`; local jako fallback). |
| `vfs/__init__.py` | 6 | Re-export `VFSProvider`, `VFSRegistry`. |

### 1.3 Podgląd (preview) — routing, loadery danych i renderery DPG

| Moduł | Linie | Odpowiedzialność |
|---|---:|---|
| `_preview_registry.py` | 158 | Routing bez DPG: grupy rozszerzeń (`STB_IMAGE_EXTS`, `PILLOW_EXTRA_EXTS`, `PDF_EXTS`, `WORD_EXTS`, `PPTX_EXTS`, `MD_EXTS`, `HTML_EXTS`, `CSV_EXTS`, `EXCEL_EXTS`, `XML_EXTS`, `ZIP_EXTS`, `SEVEN_Z_EXTS`, `FONT_EXTS`, `DB_EXTS`, `CODE_EXTS`, `TEXT_PREVIEW_EXTS`), `PreviewKind` (Enum), `PreviewCapabilities` (frozen dataclass — flagi dostępności backendów), `resolve_preview_kind()` — **kolejność sprawdzeń jest istotna** (ma dedykowane testy w `test_preview_registry.py`). |
| `_preview.py` | 261 | `PreviewPanel` — delegat spinający `PreviewKind` → renderer (`self._renderers: dict[PreviewKind, BaseRenderer]`), `_preview_capabilities()` (duplikuje sondowanie z `_availability.py` lokalnymi importami — do zweryfikowania w kolejnym etapie), `update()` (routing wejścia), `_load_text_content()` (wykrywanie kodowania: `utf-8-sig` → heurystyka UTF-16 (BOM/gęstość zer) → `cp1250` fallback z `errors="replace"`; limit `_TEXT_PREVIEW_MAX_SIZE=100 KB`), `build_handlers` (item_resize_handler), `shutdown()`. |
| `renderers/_base.py` | 44 | `PreviewContext` (stan współdzielony między rendererami: `panel_id`, `table_wrapper`, `config_tag`, `capabilities`, callbacki `on_clear`/`on_show_error`, `image_cache`, `temp_font`, `pptx_texture_tags`); `BaseRenderer` (Protocol: `render`, `clear`). |
| `renderers/image.py` | 89 | `ImageRenderer` — `dpg.load_image` dla formatów stb_image; fallback Pillow (`load_image_pillow`, downscale do 8192×8192, konwersja RGBA→`array('f', ...)` znormalizowany 0–1) dla WebP/TIFF/ICO/HEIC/AVIF/SVG/DDS/PCX/EPS; drugi fallback: kopiowanie do pliku tymczasowego (`tempfile.NamedTemporaryFile(delete=False)`) gdy `dpg.load_image` zawiedzie na ścieżce oryginalnej (np. znaki spoza ASCII w ścieżce). |
| `renderers/text.py` | 121 | `TextRenderer` — podgląd tekstu/kodu z paginacją (`_render_text_navigation`, `_on_text_page_change`), ostrzeżenie o pliku binarnym. |
| `renderers/data.py` | 349 | `DataRenderer` — CSV/TSV, Excel, SQLite, XML jako natywna `dpg.table()` (`_render_table_widget`, `freeze_rows=1`, scrollX/Y); przełączanie arkuszy Excel i tabel SQLite na żądanie. |
| `renderers/archive.py` | 162 | `ArchiveRenderer` — listing ZIP/7z jako tabela (nazwa, rozmiar, ratio kompresji), podgląd zawartości wybranego wpisu archiwum przez rekurencyjne wywołanie `request_update_cb`. |
| `renderers/document.py` | 792 | `DocumentRenderer` — największy renderer: HTML (`_render_html_preview` przez `HTMLRenderer`), Markdown (`markdown` lib → HTML → `bleach.clean()` z białą listą tagów → `HTMLRenderer.open_string`), Word (`_render_word_html_preview` mammoth+Chrome pixel-perfect, `_render_word_preview` fallback python-docx tekst+tabele), PPTX (`_render_pptx_preview` — tekst, formatowanie, tabele, notatki, obrazy inline via PIL→static_texture), PDF (`_render_pdf_preview` przez `PDFRenderer`), obsługa scroll/resize delegowana do aktywnego renderera dokumentu (PDF stronicowanie / HTML scroll viewport). |
| `renderers/font.py` | 159 | `FontRenderer` — live podgląd glifów `.ttf`/`.otf`; `load_font_with_unicode()` rejestruje zakresy Latin-1 + Latin Extended-A (`add_font_range`/`add_font_chars`) dla polskich znaków diakrytycznych; `polish_sample_text()` (pangram „Zazółć gęślą jaźń”). |
| `_preview_word.py` | 109 | Czysty loader (bez DPG): `load_word_document()` przez `python-docx` — `WordDocument`/`WordParagraph`/`WordRun`/`WordTable`. |
| `_preview_presentation.py` | 149 | Czysty loader: `load_presentation()` przez `python-pptx` — `PresentationDocument`/`Slide`/`Shape`/`Table`/notatki. |
| `_preview_archive.py` | 139 | Czysty loader: `load_zip_table()`/`load_7z_table()` — metadane archiwum (lista plików, rozmiar, ratio) do tabeli. |
| `_preview_spreadsheet.py` | 113 | Czysty loader: `load_excel_table()` przez `openpyxl` (`read_only=True, data_only=True`). |
| `_preview_sqlite.py` | 103 | Czysty loader: `load_sqlite_table()` — otwarcie **tylko do odczytu** przez URI `?mode=ro`, `PRAGMA table_info`, identyfikatory cudzysłowione (`_quote_identifier`), limit skanu `COUNT(*)` (`MAX_COUNT_SCAN=100 000`). |
| `_preview_table.py` | 84 | Czysty loader: `parse_csv_table()` — stdlib `csv` + `csv.Sniffer` do wykrywania separatora, `utf-8-sig`. |
| `_pdf.py` | 321 | `PDFRenderer` — `pypdfium2` rendering stron do `raw_texture` (via `ctypes.memmove`), LRU cache stron (`OrderedDict`, 10 pozycji), prefetch sąsiednich stron w tle (`_start_prefetch`/`_prefetch_worker`), `_doc_lock` (wątkowe bezpieczeństwo dokumentu pdfium). |
| `_html.py` | 738 | `HTMLRenderer` — renderowanie HTML/Markdown/Word-HTML/kodu przez **Chrome Headless** (`html2image`): dedykowany profil Chrome w katalogu tymczasowym (`dpg_nav_chrome_profile`), timeout subprocesu (`_CHROME_TIMEOUT=30s` wstrzykiwany do `browser._subprocess_run_kwargs`), zrzut ekranu do PNG w `tempfile.gettempdir()`, auto-trim (numpy), detekcja przepełnienia szerokości przez wstrzyknięty JS (`_OVERFLOW_MARKER` koduje `scrollWidth` w pikselu (3,3) RGB), skalowanie LANCZOS, przewijalny viewport (`raw_texture`+`mvBuffer`+`memmove`), debounce resize (`threading.Timer`, 0.4 s), limit wejścia `_MAX_HTML_BYTES=2 MB` przed uruchomieniem Chrome, limit szerokości re-renderu `_MAX_RENDER_W=4000` (ochrona przed `PIL.DecompressionBombError`/wyczerpaniem pamięci kafli GPU), `--disable-gpu`/`--log-level=3` flagi Chrome, `disable_logging=True` (subprocess stdout→DEVNULL); współdzielona instancja klasy `Html2Image` (double-checked locking), `shutdown_shared()`. |

### 1.4 Zewnętrzne pliki niekodowe

- `dpg_navigator/images/` — 44 pliki `.png` (ikony 3D Fluency, Icons8) ładowane przez `_icons.py`.

---

## 2. Punkty wejścia

| Punkt wejścia | Opis |
|---|---|
| `from dpg_navigator import FileDialog` | Główne API biblioteczne. Konstruktor `FileDialog(config: DialogConfig \| Callable \| None = None, callback: Callable \| None = None, **kwargs)` (wspiera stare i nowe sygnatury). Metody publiczne: `show()`, `hide()`, `destroy()`, `change_callback()`. Context manager (`__enter__`/`__exit__` → `destroy()`). |
| `dpg_navigator/__init__.py` | Publiczny re-export: `FileDialog`, `DialogConfig`, `DialogMode`, `StyleVariant`, `FileEntry`, `DEFAULT_FILTER_LIST`, predykaty dostępności (`word_available`, `mammoth_available`, `pptx_available`, `markdown_available`, `pdf_available`, `html_available`, `chrome_available`, `excel_available`, `py7zr_available`, `pygments_available`). |
| `demo.py` (root) | Interaktywna aplikacja demonstracyjna (wymaga wyświetlacza) — tworzy kontekst DPG, ustawia DPI awareness na Windows (`ctypes.windll.shcore.SetProcessDpiAwareness`), ładuje font systemowy z fallbackiem Polski (`_bind_ui_font_with_polish`, czyta `WINDIR` z `os.environ`), uruchamia `FileDialog` z `show_preview=True`. |
| `examples/example.py` | Minimalny przykład użycia z callbackiem, `show_dir_size=True`, `show_preview=True`. |
| `examples/example_folders.py` | Przykład `DialogMode.OPEN_DIRS` (wybór folderów). |
| `benchmarks/benchmark_heavy_paths.py` | CLI (`argparse`) do pomiaru czasu "ciężkich" ścieżek podglądu bez uruchamiania DPG (indeks katalogów, CSV, Excel, SQLite, ZIP) — profile `quick`/`default` (i inne), opcja `--json`. |
| `dpg_navigator/tests/` | 34 pliki testowe jednostkowe (bez GUI, kolekcjonowane domyślnie). |
| `dpg_navigator/tests/integration/` | Testy integracyjne z prawdziwym DPG — **opt-in**, wymagają zmiennej `DPG_INTEGRATION=1` (patrz §8) i wyświetlacza/GPU; domyślnie ignorowane przez `collect_ignore_glob` w `tests/integration/conftest.py`. |

Brak CLI / `console_scripts` w `pyproject.toml` — to czysto biblioteka do embedowania w aplikacji-hoście DPG, nie samodzielna aplikacja ani serwer.

---

## 3. Modele danych

Wszystkie modele danych to `dataclass` (część `frozen`), zdefiniowane bez zależności od DPG — testowalne w izolacji.

| Model | Plik | Charakterystyka |
|---|---|---|
| `DialogConfig` | `_types.py` | Konfiguracja dialogu (~20 pól: `title`, `tag`, `width/height`, `min_size`, `mode`, `default_path`, `filter_list`, `file_filter`, `show_dir_size`, `allow_drag`, `multi_selection`, `show_shortcuts`, `no_resize`, `modal`, `show_hidden`, `show_preview`, `preview_width`, `search_subfolders`, `style`, `custom_dirs`). Mutowalna (nie frozen) — `FileDialog.__init__` kopiuje ją (`copy(config)`) by nie mutować instancji współdzielonej między dialogami. |
| `FileEntry` | `_types.py` | `frozen=True` — `name`, `full_path`, `is_dir`, `size_bytes: int \| None`, `modified_time: float`, `is_hidden`; property `ext`. Brak `slots=True` (wymóg wsparcia Python 3.8, gdzie `frozen` + `slots` razem nie działają identycznie — patrz `docs/python38-support` w pamięci projektu). |
| `DialogMode`, `StyleVariant`, `PreviewKind` | `_types.py`, `_preview_registry.py` | `Enum` z `auto()`. |
| `DialogState` | `dialog/_state.py` | Mutowalny stan sesji dialogu (nawigacja, zaznaczenie, listing, wyszukiwanie, async) — patrz §1.1. |
| `PreviewCapabilities` | `_preview_registry.py` | `frozen=True` — flagi dostępności backendów podglądu (markdown/excel/pygments/pdf/seven_z/word/mammoth/pptx). |
| `WordDocument`/`WordParagraph`/`WordRun`/`WordTable` | `_preview_word.py` | Reprezentacja dokumentu Word po parsowaniu python-docx. |
| `PresentationDocument`/`PresentationSlide`/`PresentationShape`/`PresentationTable` | `_preview_presentation.py` | Reprezentacja prezentacji po parsowaniu python-pptx. |
| `ArchiveTable` | `_preview_archive.py` | Metadane archiwum ZIP/7z gotowe do tabeli. |
| `SpreadsheetTable` | `_preview_spreadsheet.py` | Dane arkusza Excel gotowe do tabeli. |
| `SQLiteTable` | `_preview_sqlite.py` | `frozen=True` — `headers`, `rows`, `status`, `tables`, `table_name`. |
| `TableData` | `_preview_table.py` | Dane CSV/TSV gotowe do tabeli. |
| `TimerTask` | `_job_manager.py` | Zadanie zaplanowane w kopcu czasowym JobManager. |
| `Workload`, `BenchmarkResult` | `benchmarks/benchmark_heavy_paths.py` | `frozen=True, slots=True` — modele wejścia/wyjścia benchmarków (używają `slots=True`, bo benchmark nie deklaruje wsparcia 3.8 w ten sam sposób co pakiet główny — do zweryfikowania). |

Brak ORM, brak modeli persystencji własnej — biblioteka nie posiada własnej bazy danych; SQLite jest wyłącznie **czytany** jako format podglądu plików użytkownika.

---

## 4. Miejsca zapisu (write locations)

Biblioteka nie ma własnej trwałej bazy danych ani plików konfiguracyjnych zapisywanych na dysku poza tym, co użytkownik jawnie robi przez UI dialogu. Wszystkie miejsca zapisu:

| Operacja | Lokalizacja | Moduł | Uwagi |
|---|---|---|---|
| Tworzenie nowego folderu | katalog docelowy wybrany przez użytkownika w UI | `dialog/_logic.py::_create_new_folder` (`os.makedirs(new_path, exist_ok=False)`) | Poprzedzone `validate_folder_name()` (`_filesystem.py`) — odrzuca `.`/`..`, separatory ścieżek, nazwy rozwiązujące się (przez `os.path.realpath`, więc też przez symlinki) poza bieżący katalog. |
| Ekstrakcja pliku z archiwum (podgląd/wybór) | katalog tymczasowy sesji: `tempfile.gettempdir()/dpg_navigator_extracted_<md5(pid+time)>/<md5(archive_path)>/...` | `_filesystem.py::DirectoryLister._get_session_temp_dir`, `vfs/_archive.py::ArchiveVFSProvider.extract_file` | Chronione przed ZipSlip (`os.path.realpath` + sprawdzenie prefiksu przed `zf.extract`/`z.extract`); limit rozmiaru (`max_size`, domyślnie `_MAX_ARCHIVE_EXTRACT_SIZE=512 MB` w `_dialog.py` dla podwójnego kliku); katalog czyszczony w `cleanup_temp_files()` (`shutil.rmtree(ignore_errors=True)`) dopiero gdy ostatnia instancja `FileDialog` zostaje zniszczona (`_instance_count <= 0`), by nie usuwać plików używanych przez inną otwartą instancję. |
| Zrzuty ekranu Chrome Headless (podgląd HTML/MD/Word/kod) | `tempfile.gettempdir()/<uuid>.png` oraz profil `tempfile.gettempdir()/dpg_nav_chrome_profile/` | `_html.py::HTMLRenderer._hti_screenshot`, `_get_hti` | Plik PNG usuwany po odczycie (`os.remove(target_path)`); profil Chrome trwały między renderami w obrębie procesu (przyspiesza kolejne odpalenia). |
| Kopia pliku obrazu do pliku tymczasowego (fallback ładowania obrazu) | `tempfile.NamedTemporaryFile(delete=False, suffix=ext)` w domyślnym katalogu tymczasowym systemu | `renderers/image.py::ImageRenderer.render` | Usuwany w bloku `finally` (`os.unlink(tmp_path)`), tylko gdy `dpg.load_image` na ścieżce oryginalnej zawiedzie. |
| Zapis wybranego pliku/folderu | **brak** — biblioteka nie zapisuje danych użytkownika; zwraca listę ścieżek przez `callback` (`_return_selection`). Zapis/otwarcie pliku wskazanego przez użytkownika leży po stronie aplikacji-hosta. |

Brak logów zapisywanych na dysk przez bibliotekę (używany jest `logging` standardowy — konsument aplikacji decyduje o handlerach); brak plików konfiguracyjnych `.ini`/`.json`/rejestru zapisywanych przez bibliotekę (odczyt rejestru Windows w `_platform.py` jest tylko do odczytu, patrz §5).

---

## 5. Integracje zewnętrzne

| Integracja | Typ | Moduł | Szczegóły |
|---|---|---|---|
| Chrome / Chromium (binarka systemowa) | Proces zewnętrzny (subprocess, przez `html2image`) | `_html.py`, `_availability.py::chrome_available` | Renderuje HTML/Markdown/Word(mammoth)/kod (Pygments) do PNG w trybie headless. **Wykonuje JavaScript dokumentu i może wykonywać żądania sieciowe** — udokumentowane wprost w README §"Security and Reliability" jako ostrzeżenie ("preview only content you trust"). Timeout 30 s wstrzyknięty w `_subprocess_run_kwargs`; flagi `--disable-gpu`, `--log-level=3`. Wykrywanie binarki przez `html2image`/`Html2Image().browser.executable` — brak konfiguracji ścieżki Chrome przez zmienną środowiskową w kodzie pakietu (poleganie na wykrywaniu html2image). |
| `xdg-user-dir` (binarka systemowa, Linux) | Proces zewnętrzny (subprocess) | `_platform.py::_get_xdg_dir` | Odpytywana o lokalizację katalogów specjalnych (Desktop/Downloads/...) w lokalizacjach nie-angielskich; `timeout=2s`, `FileNotFoundError`/`TimeoutExpired`/`OSError` łapane — brak binarki degraduje się do ścieżki domyślnej `home/name`. |
| Rejestr Windows (`winreg`) | Odczyt systemowy (nie proces) | `_platform.py::get_special_dirs` | Odczyt `HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders` dla lokalizacji Desktop/Downloads/Pictures/Documents/Music/Videos. Tylko odczyt (`winreg.OpenKey`/`QueryValueEx`), brak zapisu do rejestru. |
| `psutil` | Biblioteka (nie proces) | `_platform.py::get_drives` | `psutil.disk_partitions()` do enumeracji dysków/wolumenów. |
| pypdfium2, numpy, Pillow, python-docx, mammoth, html2image, python-pptx, markdown, openpyxl, py7zr, Pygments, bleach | Biblioteki opcjonalne (extras) | zależne od funkcji podglądu | Wszystkie sondowane przez `try/except Exception` w `_availability.py` — brak twardej zależności; degradacja funkcjonalna udokumentowana (`README.md` §"Optional Dependencies"). Brak żadnej biblioteki sieciowej (`requests`/`urllib`/`socket`/`aiohttp`) używanej bezpośrednio przez kod pakietu — jedyna droga do sieci to pośrednio przez proces Chrome (patrz wyżej). |
| GitHub Actions (CI) | Integracja zewnętrzna dev/release | `.github/workflows/*.yml` | `actions/checkout`, `actions/setup-python`, `actions/upload-artifact`/`download-artifact`, `pypa/gh-action-pypi-publish` — wszystkie pinowane do SHA commitów. PyPI trusted publishing (OIDC `id-token: write`, bez sekretów API w repo). |
| PyPI / TestPyPI | Publikacja pakietu | `.github/workflows/publish.yml` | `publish-pypi` (trigger: `release: published`), `publish-testpypi` (trigger: `workflow_dispatch`), oba environment-gated (`pypi`/`testpypi`). |

Brak: bazy danych zewnętrznej, message queue, API zewnętrznego (REST/gRPC), usług chmurowych, telemetrii/analytics, integracji z systemami autentykacji/autoryzacji.

---

## 6. Kolejki / zadania asynchroniczne

Cała współbieżność w tle jest realizowana przez własny, statyczny `JobManager` (`_job_manager.py`) — bez `asyncio`, bez zewnętrznej kolejki (Celery/RQ/itp.), bez puli wątków wielokrotnego użytku (`ThreadPoolExecutor`).

| Mechanizm | Opis |
|---|---|
| `JobManager.submit(fn, *args, **kwargs)` | Tworzy krótkożyjący wątek daemon (`threading.Thread(daemon=True)`) na zadanie, zwraca `concurrent.futures.Future`; wątek usuwa się z rejestru `_threads` po zakończeniu. |
| `JobManager.schedule_timer(interval, fn, args, kwargs)` / `cancel_timer(timer)` | Jedna dedykowana pętla-wątek (`_timer_worker`) obsługuje wszystkie zaplanowane opóźnione wywołania przez kopiec czasowy (`heapq`) zamiast wątku na debounce — redukcja "thread churn" przy częstym debounce (np. wyszukiwanie). |
| `JobManager.shutdown(wait=True, timeout=2.0)` | Anuluje kolejkę timerów, czeka (z limitem czasu) na zakończenie aktywnych wątków roboczych; wywoływane w `FileDialog.destroy()` gdy `_instance_count` spada do zera. |

**Konsumenci `JobManager`:**

- `DialogLogic.start_index_build()` — budowa `DirectoryIndex` w tle (`JobManager.submit`).
- `DialogLogic.start_size_computation()` — obliczanie rozmiarów katalogów w tle, cache z TTL 60 s (`DialogState.size_cache`).
- `DialogLogic.trigger_search()`/`_run_search`/`_perform_deep_search` — debounce 0.3 s (`JobManager.schedule_timer`) przed wyszukiwaniem płytkim i głębokim (rekurencyjnym, przez `DirectoryIndex`).
- `_pdf.py::PDFRenderer._start_prefetch`/`_prefetch_worker` — prefetch stron sąsiednich (N±1) w tle po zmianie strony PDF.
- `_html.py::HTMLRenderer` — renderowanie Chrome w tle (`_start_render`/`_render_worker`, `JobManager.submit`), debounce resize przez `threading.Timer` (0.4 s, **nie** `JobManager.schedule_timer` — osobny mechanizm timera w tym module).

**Wzorzec anulowania nieaktualnych wyników:** liczniki generacji (`DialogState.bg_generation`, `DialogState.index_generation`, `HTMLRenderer._prefetch_generation`/`_render_generation` odpowiedniki) sprawdzane przed zapisaniem wyniku z wątku w tle — zapobiega wyścigom po nawigacji/zamknięciu.

**Marshaling do wątku głównego DPG:** DPG jest single-threaded; wywołania z wątków w tle muszą wracać na wątek główny wewnątrz `dpg.mutex()` — widoczne w `FileDialog._safe_refresh_ui`, `_safe_update_path_input`, `_safe_update_size_cell` (`_dialog.py`).

Brak: Celery, RQ, Redis, RabbitMQ, `asyncio`, `multiprocessing`, `ProcessPoolExecutor`, harmonogramu cron w kodzie pakietu.

---

## 7. Procesy uprzywilejowane

Biblioteka **nie uruchamia się z podwyższonymi uprawnieniami** i nie zawiera własnego mechanizmu eskalacji uprawnień (brak `sudo`/`runas`/UAC manifest/setuid). Elementy zbliżone do "procesów uprzywilejowanych" w kontekście tego repozytorium:

| Element | Charakter | Moduł |
|---|---|---|
| Proces Chrome Headless | Zewnętrzny proces potomny uruchamiany z uprawnieniami użytkownika hosta; wykonuje JavaScript dokumentu i może wykonać żądania sieciowe (patrz §5) — z perspektywy modelu zagrożeń jest to najbardziej "uprzywilejowany" (w sensie zdolności działania) komponent w repo, mimo że nie działa z podniesionymi uprawnieniami OS. | `_html.py` |
| `subprocess.run(["xdg-user-dir", ...])` | Zewnętrzny proces potomny, tylko odczyt ścieżki, timeout 2 s, brak przekazywania danych użytkownika jako argumentów poza stałą nazwą katalogu. | `_platform.py` |
| Odczyt rejestru Windows (`winreg.OpenKey` na `HKEY_CURRENT_USER`) | Operacja systemowa w przestrzeni użytkownika bieżącego procesu (nie wymaga podniesionych uprawnień; `HKCU`, nie `HKLM`). | `_platform.py` |
| `ctypes.windll.kernel32.GetFileAttributesW` | Wywołanie WinAPI (odczyt atrybutów pliku) w przestrzeni użytkownika. | `_platform.py::is_hidden` |
| `ctypes.windll.shcore.SetProcessDpiAwareness(2)` | Wywołanie WinAPI (ustawienie DPI-awareness procesu) — tylko w `demo.py`, nie w kodzie biblioteki. | `demo.py` |
| GitHub Actions `publish.yml` — `id-token: write` | Uprawnienie OIDC (trusted publishing) do wystawienia tokenu tożsamości dla PyPI/TestPyPI podczas release — jedyne miejsce w repo z podwyższonym `permissions:` (poza domyślnym `contents: read`). | `.github/workflows/publish.yml` |

Brak: serwera nasłuchującego na porcie, brak operacji wymagających uprawnień administratora/roota, brak zapisu do lokalizacji systemowych (poza katalogiem tymczasowym użytkownika).

---

## 8. Konfiguracja środowisk

### 8.1 Zmienne środowiskowe

| Zmienna | Gdzie czytana | Cel |
|---|---|---|
| `DPG_INTEGRATION` | `dpg_navigator/tests/integration/conftest.py` | Gate dla testów integracyjnych z prawdziwym DPG (`== "1"` odblokowuje kolekcję `test_*.py` w `tests/integration/`); domyślnie testy te są ignorowane (`collect_ignore_glob`), bo import `dearpygui` wymaga wyświetlacza/GPU. |
| `WINDIR` | `demo.py::_bind_ui_font_with_polish` | Lokalizacja katalogu Windows do wyszukania fontu systemowego (fallback `C:\Windows` gdy nieustawiona). |

Poza tym pakiet **nie czyta** żadnych zmiennych środowiskowych konfiguracyjnych (brak `os.environ` w `dpg_navigator/*.py` poza `_platform.py`'s subprocess i `demo.py` — potwierdzone przez grep, zero trafień `os.environ` w plikach źródłowych pakietu poza `demo.py`).

### 8.2 Pliki konfiguracyjne repo

| Plik | Rola |
|---|---|
| `pyproject.toml` | Jedyne źródło metadanych pakietu, zależności (rdzeniowe + 10 extras + `all` + `dev`), build backend (`hatchling`), wersjonowanie (`[tool.hatch.version] source = "regex"` czytający `__version__` z `dpg_navigator/__init__.py`), konfiguracja `pytest` (`testpaths`, `addopts = "--basetemp=.pytest_tmp"`, `cache_dir`, marker `integration`), `ruff` (`target-version = "py38"`, `select = ["E9","F63","F7","F82"]` — wyłącznie reguły poprawnościowe), `mypy` (bez pinowanej `python_version` — celowo, by dopasować się do interpretera każdego joba CI). |
| `requirements.txt` | Równoległe (zduplikowane) źródło zależności obok `pyproject.toml` — odnotowane jako dług w `docs/ROADMAP.md`. |
| `.github/workflows/ci.yml` | Macierz 9 kombinacji OS×Python (Ubuntu 3.8–3.13, Windows 3.8/3.13, macOS 3.13); joby `test` (ruff + mypy na jawnej liście "czystych" modułów + pytest), `audit` (`pip-audit`, `continue-on-error: true`), `sbom` (CycloneDX). |
| `.github/workflows/publish.yml` | Release gate przez `uses: ./.github/workflows/ci.yml`; build (`python -m build` + `twine check`); publikacja PyPI/TestPyPI przez trusted publishing (OIDC), oba environment-scoped. |
| `.gitignore` | Standardowy Python (`__pycache__`, `.venv`, `dist/`, `build/`, cache pytest/ruff); `.claude/` ignorowany (konfiguracja lokalna Claude Code, poza zakresem repo). |
| `docs/releasing.md` | Procedura ręczna wydania (bumpowanie `__version__`, tagowanie, publikacja przez trusted publishing). |

### 8.3 Wymagania systemowe poza pip

- **Chrome/Chromium na `PATH`** — wymagany przez `html2image` dla podglądu HTML/Markdown/kodu/Word-HTML; jego brak wykrywany jest przez `chrome_available()` i degraduje podgląd do tekstu (bez twardego błędu).
- **`xdg-user-dir`** (opcjonalnie, Linux) — poprawia lokalizację katalogów specjalnych w środowiskach nie-angielskich; brak binarki nie blokuje działania (fallback na `home/name`).
- **Python 3.8–3.13** — macierz CI testuje pełen zakres; kod źródłowy wymaga `from __future__ import annotations` w każdym nowym pliku dla zgodności z 3.8 (brak `slots=True` w nowych dataclassach z tego samego powodu, poza benchmarkiem).

---

## 9. Struktura testów

### 9.1 Testy jednostkowe (`dpg_navigator/tests/`, zbierane domyślnie)

21 plików (19 `test_*.py` + `conftest.py` + `__init__.py`), ~4 234 linii łącznie. `pytest.ini_options` w `pyproject.toml`: `testpaths = ["dpg_navigator/tests"]`, `addopts = "--basetemp=.pytest_tmp"`.

| Plik testowy | Linie | Moduł(y) pod testem |
|---|---:|---|
| `test_filesystem.py` | 890 | `_filesystem.py` (`DirectoryLister`, `DirectoryIndex`), `vfs` (`VFSRegistry`) |
| `test_dialog.py` | 519 | `_dialog.py` (`FileDialog`), `_filesystem.py`, `_types.py`, `vfs`, `_preview.py` |
| `test_platform.py` | 513 | `_platform.py` (w tym mockowanie `subprocess.run` dla `xdg-user-dir`, `winreg`) |
| `test_pdf.py` | 495 | `_pdf.py` (`PDFRenderer`) |
| `test_icons.py` | 409 | `_icons.py` (`IconRegistry`) |
| `test_types.py` | 201 | `_types.py` |
| `test_styles.py` | 194 | `_styles.py` (`SidebarRenderer`, `LabeledSidebar`, `CompactSidebar`) |
| `test_document_renderer.py` | 140 | `renderers/document.py` (`DocumentRenderer`) |
| `test_preview_registry.py` | 100 | `_preview_registry.py` (`resolve_preview_kind` — kolejność routingu) |
| `test_html.py` | 98 | `_html.py` (logika czysta: dostępność backendu, wstrzykiwanie timeoutu subprocesu) |
| `test_preview_sqlite.py` | 95 | `_preview_sqlite.py` |
| `test_preview_spreadsheet.py` | 90 | `_preview_spreadsheet.py` |
| `test_init.py` | 73 | `dpg_navigator/__init__.py` (re-eksporty, `__version__`) |
| `test_preview_presentation.py` | 77 | `_preview_presentation.py` |
| `test_preview_archive.py` | 65 | `_preview_archive.py` |
| `test_preview_table.py` | 60 | `_preview_table.py` |
| `test_preview_word.py` | 60 | `_preview_word.py` |
| `test_lifecycle.py` | 58 | `_dialog.py` (`FileDialog`), `_filesystem.py` (`DirectoryIndex`), `dialog/_state.py` (`DialogState`), `dialog/_logic.py` (`DialogLogic`) — cykl życia/destroy |
| `test_font_preview.py` | 44 | `renderers/font.py` |
| `conftest.py` | 53 | Fixtures współdzielone: `tmp_tree` (drzewo katalogów testowych), `empty_dir` |

**Moduły bez dedykowanego pliku testowego** (mogą być pokryte pośrednio przez `test_dialog.py`/`test_lifecycle.py`/`test_document_renderer.py`, do zweryfikowania w kolejnym etapie audytu pod kątem faktycznego pokrycia):
`dialog/_ui.py` (`DialogUIBuilder`), `_job_manager.py` (`JobManager`), `_keyboard.py` (`KeyboardMixin`), `vfs/_local.py`/`vfs/_archive.py`/`vfs/_registry.py` bezpośrednio (pośrednio przez `test_filesystem.py`/`test_dialog.py`), `renderers/image.py`, `renderers/text.py`, `renderers/data.py`, `renderers/archive.py`, `_availability.py`, `_preview.py` (bezpośrednio — pośrednio przez `test_dialog.py`).

### 9.2 Testy integracyjne (`dpg_navigator/tests/integration/`, opt-in)

| Plik | Linie | Opis |
|---|---:|---|
| `conftest.py` | 20 | Gate `DPG_INTEGRATION == "1"`; bez tego `collect_ignore_glob = ["test_*.py"]` — pliki nie są nawet importowane (import `dearpygui` wymaga wyświetlacza/GPU i mógłby crashować w środowisku headless/sandboxed). |
| `test_dpg_smoke.py` | 77 | Test dymny z prawdziwym kontekstem DPG (marker `integration`). |

Uruchomienie: `DPG_INTEGRATION=1 pytest -m integration` (lub `xvfb-run -a env DPG_INTEGRATION=1 pytest -m integration` na headless Linux) — nieuruchomione w tej sesji inwentaryzacji.

### 9.3 Narzędzia jakości poza pytest

| Narzędzie | Zakres | Konfiguracja |
|---|---|---|
| `ruff check .` | Cały pakiet | `select = ["E9","F63","F7","F82"]` — wyłącznie reguły poprawnościowe (składnia/undefined names), świadomie wąski zestaw. |
| `mypy` | Jawna lista 18 "czystych" (bez GUI) modułów w `ci.yml` (patrz §8.2) — pominięty dla Python 3.8/3.9 w CI. Nie obejmuje `dialog/`, `vfs/`, `renderers/`, `_job_manager.py`, `_availability.py`. |
| `pip-audit` | Zależności | Job `audit` w CI, `continue-on-error: true` — nie blokuje merge'a. |
| `cyclonedx-bom` | SBOM | Job `sbom` w CI, artefakt `sbom-cyclonedx` (retencja 30 dni). |
| `twine check` | Metadane dystrybucji | Job `build` w `publish.yml`, przed publikacją. |

### 9.4 Benchmarki (poza pytest)

`benchmarks/benchmark_heavy_paths.py` — mierzy ścieżki podglądu bez uruchamiania DPG (indeks katalogów, CSV, Excel, SQLite, ZIP); profile `quick`/`default`, wynik JSON opcjonalny; baseline w `benchmarks/baselines/windows-python-3.13.json`.

---

## 10. Zakres nieobjęty tą inwentaryzacją

Zgodnie z poleceniem, dokument jest czystym opisem stanu — nie zawiera oceny ryzyk, nie uruchomiono w tej sesji: pełnego `pytest -q`, `mypy` na żywo, `pip_audit` na żywo, testów integracyjnych DPG, benchmarków. Wszystkie te kroki są zidentyfikowane (§8, §9) i pozostawione właściwemu etapowi audytu. Rozbieżność `main` lokalny vs `origin/main` opisana w `audit/00-scope.md` §2 pozostaje w mocy — ustalenia tego dokumentu dotyczą wyłącznie stanu lokalnego (`b0372f6`).
