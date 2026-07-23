# A7 — `platform-os-integration` — Runda 1

Data: 2026-07-19
Commit audytowany: `b0372f6` (lokalny `main`; patrz `audit/00-scope.md` §2 —
`origin/main` ma 8 dodatkowych commitów niedostępnych lokalnie).

> Artefakt audytu. Nie modyfikowano kodu produkcyjnego — wyłącznie odczyt i
> analiza. Zakres zgodny z `audit/03-plan.md` §6 (A7): `dpg_navigator/_platform.py`
> (`get_drives`, `get_special_dirs`/`_get_xdg_dir`, `is_hidden`, `is_mod_key_down`,
> `get_file_time`), `demo.py` (DPI awareness, font polski), `dpg_navigator/_icons.py`
> (ładowanie tekstur), rozszerzone o `examples/example.py`, `examples/example_folders.py`
> i `README.md` (ta sama gałąź kodu HiDPI co w `demo.py`) — w ramach „całego
> repozytorium" wskazanego w poleceniu.

Metodologia: pełne prześledzenie ścieżek wywołania (`_platform.py` →
`dialog/_ui.py` / `_dialog.py` / `_filesystem.py` / `vfs/_local.py` / `_styles.py`),
próba obalenia każdego ustalenia (sprawdzenie miejsc wywołania pod kątem
istniejącego try/except, sprawdzenie testów pod kątem czy przypadek jest już
pokryty, weryfikacja zewnętrzna specyfikacji `xdg-user-dir` i znanego zachowania
`psutil`/Windows dla niedostępnych dysków sieciowych). Sprawdzono
`docs/audits/*.md` — żadne z poniższych ustaleń nie jest tam wzmiankowane.

---

## Ustalenia

### platform-os-integration-01 — `_get_xdg_dir` woła `xdg-user-dir DOWNLOADS` (liczba mnoga), tool akceptuje tylko `DOWNLOAD`

- **Plik:** `dpg_navigator/_platform.py:65,103-116` (funkcja `_get_xdg_dir`,
  wywoływana z `get_special_dirs()` dla `_SYSTEM == "Linux"`)
- **Ryzyko:** P2
- **Kategoria:** correctness / cross-platform
- **Impact:** Na Linuksie klucz katalogu przekazywany do zewnętrznego narzędzia
  `xdg-user-dir` powstaje przez `name.upper()` z krotki
  `names = ("Desktop", "Downloads", "Pictures", "Documents", "Music", "Videos")`.
  Dla `"Downloads"` daje to `"DOWNLOADS"` — ale oficjalny, udokumentowany zestaw
  kluczy `xdg-user-dir` to `DESKTOP, DOWNLOAD, TEMPLATES, PUBLICSHARE, DOCUMENTS,
  MUSIC, PICTURES, VIDEOS` — **`DOWNLOAD` w liczbie pojedynczej**. Wywołanie z
  nierozpoznanym kluczem nie zwraca poprawnej ścieżki (potwierdzone zewnętrznie:
  man page Arch/Ubuntu/ManKier wymienia dokładnie te 8 kluczy, `DOWNLOAD` bez „S").
  Efekt: `_get_xdg_dir("Downloads")` zwraca `None` (lub, w gorszym przypadku,
  cokolwiek narzędzie zwraca dla nieznanego klucza — patrz test
  `test_nonzero_return_code_returns_none`, które developerzy sami przewidzieli
  jako możliwy wynik), a `get_special_dirs()` spada do twardo zakodowanego
  `os.path.join(home, "Downloads")` — nazwy angielskiej. Na zlokalizowanych
  środowiskach Linux (np. polskie „Pobrane" po `xdg-user-dirs-update` z lokalizacją
  `pl_PL`) katalog `~/Downloads` fizycznie nie istnieje, więc końcowy filtr
  `os.path.isdir(v)` w `get_special_dirs()` usuwa wpis „Downloads" z paska
  bocznego — mimo że poprawne wywołanie (`xdg-user-dir DOWNLOAD`) zwróciłoby
  właściwą ścieżkę. Pozostałych 5 kluczy (Desktop, Pictures, Documents, Music,
  Videos) jest już w liczbie pojedynczej w `names`, więc `.upper()` daje dla nich
  poprawne dopasowanie — problem dotyczy wyłącznie „Downloads".
- **Repro:** Na systemie Linux z `xdg-user-dirs` i `user-dirs.dirs` ustawiającym
  `XDG_DOWNLOAD_DIR="$HOME/Pobrane"`: `subprocess.run(["xdg-user-dir","DOWNLOAD"])`
  zwraca poprawną ścieżkę, `subprocess.run(["xdg-user-dir","DOWNLOADS"])` (dokładnie
  to, co woła kod) — nie. Bez GUI/DPG, czysto na `_platform._get_xdg_dir`.
- **Fix (sugestia, nie wdrożona):** mapowanie nazwa→klucz XDG analogiczne do
  istniejącego `_SHELL_FOLDER_MAP` (Windows) / `macos_mapping` (Darwin), np.
  `{"Downloads": "DOWNLOAD"}` z fallbackiem `name.upper()` dla pozostałych.
- **Confidence:** High — zweryfikowano zewnętrznie specyfikację `xdg-user-dir`
  (WebSearch/WebFetch, man page Arch Linux: klucze `DESKTOP DOWNLOAD TEMPLATES
  PUBLICSHARE DOCUMENTS MUSIC PICTURES VIDEOS`). Mechanizm niesporny — literalne
  porównanie `"Downloads".upper() == "DOWNLOADS" != "DOWNLOAD"`.
- **Counterargument:** Błąd jest niewidoczny na systemach, gdzie fizyczny folder
  i tak nazywa się dosłownie „Downloads" (częste, bo wiele dystrybucji domyślnie
  zostaje przy angielskich nazwach, dopóki użytkownik nie uruchomi
  `xdg-user-dirs-update` z inną lokalizacją) — wtedy fallback `os.path.join(home,
  "Downloads")` przypadkiem trafia. Nie testowano na żywym Linuksie (środowisko
  audytu to Windows) — ustalenie oparte o dokumentację `xdg-user-dirs`, nie o
  bezpośrednie uruchomienie.

---

### platform-os-integration-02 — `get_drives()`/`get_special_dirs()` wywoływane synchronicznie bez timeoutu; nieosiągalny dysk sieciowy może zamrozić cały (jednowątkowy) proces DPG

- **Plik:** `dpg_navigator/_platform.py:36-54` (`get_drives`, przez
  `psutil.disk_partitions()`), `:57-100` (`get_special_dirs`, końcowy filtr
  `os.path.isdir(v)` dla każdego katalogu); wywoływane z
  `dpg_navigator/dialog/_ui.py:174-175` (`_build_sidebar`), które jest wywoływane
  synchronicznie z `FileDialog.__init__` → `self.ui._build_ui()`
  (`dpg_navigator/_dialog.py:189`)
- **Ryzyko:** P2
- **Kategoria:** availability / cross-platform robustness
- **Impact:** DPG jest jednowątkowe (zasada architektoniczna repo — patrz
  `CLAUDE.md`/pamięć projektu). `get_drives()` i `get_special_dirs()` są wołane
  bezpośrednio na wątku budującym UI, bez żadnego timeoutu ani wątku roboczego
  (w przeciwieństwie do np. obliczania rozmiaru katalogu, które jawnie idzie
  przez `JobManager` w tle). Na Windows to udokumentowane, dobrze znane
  zachowanie systemowe: gdy zmapowany dysk sieciowy (litera dysku wskazująca na
  niedostępny serwer SMB) jest odpięty/niedostępny, zapytania o jego właściwości
  (co dokładnie robi enumeracja partycji i sprawdzanie istnienia katalogu)
  blokują się na czas timeoutu sieciowego Windows — to samo zjawisko, które
  powoduje znane „zawieszenia" Eksploratora Windows przy dyskach sieciowych
  (potwierdzone zewnętrznie: Microsoft Q&A „File explorer slow/hangs when mapped
  drive not available"). Analogicznie: jeśli specjalny folder (Desktop/Documents)
  jest przekierowany polityką domenową na niedostępny udział sieciowy (typowe w
  środowiskach korporacyjnych z Folder Redirection), końcowy
  `os.path.isdir(v)` w `get_special_dirs()` zawiesza się na tym samym mechanizmie.
  Skutek: **cały proces-host** (nie tylko dialog) zamraża się na czas
  otwierania/tworzenia `FileDialog` — bez paska postępu, bez możliwości
  anulowania, na czas nieznany (zależny od konfiguracji sieci/timeoutu SMB).
- **Repro (opisowe, nie uruchomione w tym audycie — wymaga środowiska Windows z
  faktycznie zmapowanym, ale niedostępnym dyskiem sieciowym):** zmapować literę
  dysku na `\\adres-nieosiagalny\share`, odłączyć serwer/sieć, następnie
  utworzyć `FileDialog(...)` — oczekiwane: proces zawiesza się w
  `get_drives()`/`get_special_dirs()` na czas timeoutu SMB (typowo dziesiątki
  sekund).
- **Fix (sugestia, nie wdrożona):** przenieść `get_drives()`/`get_special_dirs()`
  do `JobManager` (analogicznie do istniejącego wzorca dla rozmiaru katalogu /
  indeksu wyszukiwania) z placeholderem w UI do czasu ukończenia, albo dodać
  twardy timeout wykonania w osobnym wątku z fallbackiem do samego „Home".
- **Confidence:** Medium — mechanizm sieciowy jest dobrze udokumentowanym
  zjawiskiem systemowym (Windows/SMB timeout), a kod rzeczywiście nie ma tu
  żadnego timeoutu/wątku roboczego (weryfikowalne czytaniem kodu). Nie
  zweryfikowano eksperymentalnie w tej sesji (brak środowiska z odpiętym
  dyskiem sieciowym).
- **Counterargument:** To ustalenie **przekracza ściśle wąski zakres A7** i
  zachodzi na obszar A3 (`concurrency-lifecycle` — JobManager, marshaling do
  DPG), bo właściwa naprawa (przeniesienie do wątku roboczego) to zmiana wzorca
  współbieżności, nie samej logiki `_platform.py`. Odnotowuję to tu, bo
  *źródłem* problemu są funkcje `_platform.py` będące ślepe na to, że mogą się
  zablokować — ale ocena priorytetu/fix-u prawdopodobnie należy do A3.
  Częstotliwość w praktyce: ograniczona do środowisk z dyskami
  sieciowymi/folder redirection (typowe korporacyjne domeny Windows), rzadka na
  komputerach domowych.

---

### platform-os-integration-03 — Snippet `SetProcessDpiAwareness` w `README.md` i w `examples/*.py` bez try/except, mimo że `demo.py` właśnie to naprawiono (ten sam commit)

- **Plik:** `README.md:160-169` (sekcja „HiDPI / 4K Displays (Windows)"),
  `examples/example.py:5-7`, `examples/example_folders.py:12-14`
  — kontrast z już naprawionym `demo.py:4-9`
- **Ryzyko:** P3
- **Kategoria:** robustness / documentation-code consistency
- **Impact:** Commit `b0372f6` („Harden previews and CI...") owinął wywołanie
  `ctypes.windll.shcore.SetProcessDpiAwareness(2)` w `demo.py` w
  `try/except Exception: pass`, właśnie dlatego, że to wywołanie może rzucić
  wyjątek — `shcore.dll`/`SetProcessDpiAwareness` istnieje dopiero od Windows
  8.1 (funkcja API `Shcore.dll`); na starszych Windows albo w środowiskach bez
  tej biblioteki (np. niektóre sandboxy/Wine) dostęp do
  `ctypes.windll.shcore` rzuca `OSError` przy ładowaniu DLL, a
  `.SetProcessDpiAwareness` mogłoby rzucić `AttributeError`, gdyby DLL się
  załadowało bez tej funkcji. Dokładnie ten sam jednowierszowy fragment w
  `README.md` (oficjalny, kopiuj-wklej snippet polecany integratorom) oraz w obu
  plikach `examples/` **nie ma** tego zabezpieczenia — pozostał nienaprawiony w
  tym samym commicie, który naprawił `demo.py`. Efekt: integrator kopiujący
  dosłownie snippet z README, uruchamiający `examples/example.py` lub
  `examples/example_folders.py` na niewspieranym Windows, dostanie
  nieobsłużony wyjątek **przed** `dpg.create_context()` — twardy crash zamiast
  granicznej degradacji.
- **Repro:** statyczna analiza / brak środowiska Windows <8.1 w tej sesji do
  faktycznego uruchomienia; potwierdzone przez `git show b0372f6 -- demo.py`
  (diff pokazuje dodanie `try/except Exception: pass` tylko w `demo.py`) oraz
  brak analogicznej zmiany w `README.md`/`examples/*.py` w tym samym i
  późniejszych lokalnych commitach.
- **Fix (sugestia, nie wdrożona):** ujednolicić snippet w README i obu
  `examples/*.py` z wersją z `demo.py` (owinąć w `try/except Exception: pass`).
- **Confidence:** High co do niespójności (weryfikowalne bezpośrednio w plikach
  + diff gita); Medium co do realnego wpływu — zależy od udziału niewspieranych
  środowisk Windows wśród użytkowników biblioteki (nieznany, ale niezerowy —
  README nie deklaruje minimalnej wersji Windows).
- **Counterargument:** To kod przykładowy/dokumentacyjny, nie ścieżka
  wykonania biblioteki (`dpg_navigator/` samo w sobie nigdy nie woła
  `SetProcessDpiAwareness`) — więc nie zagraża integralności samej biblioteki,
  tylko doświadczeniu integratora kopiującego snippet. Możliwe, że pozostawienie
  README/examples „prostymi" (bez try/except) jest świadomym wyborem
  dydaktycznym (krótszy, czytelniejszy snippet) — ale brak o tym wzmianki, a
  fakt, że dokładnie ten sam wiersz w `demo.py` dostał zabezpieczenie w tym samym
  commicie, sugeruje raczej niedopatrzenie niż świadomą decyzję.

---

### platform-os-integration-04 — `_get_xdg_dir` nie łapie `UnicodeDecodeError` z `subprocess.run(text=True)`; brak zabezpieczenia w łańcuchu wywołań aż do konstruktora `FileDialog`

- **Plik:** `dpg_navigator/_platform.py:103-116` (`_get_xdg_dir`), wywoływane
  bez własnego try/except z `get_special_dirs()` (`:67-69`), które z kolei jest
  wywoływane bez try/except z `dpg_navigator/dialog/_ui.py:174`
  (`_build_sidebar`), wywoływanego bez try/except z `_build_ui()` →
  `dpg_navigator/_dialog.py:189` (`FileDialog.__init__`)
- **Ryzyko:** P3
- **Kategoria:** error-handling / cross-platform
- **Impact:** `subprocess.run(["xdg-user-dir", ...], capture_output=True,
  text=True, timeout=2)` z `text=True` dekoduje stdout/stderr subprocesu
  używając `locale.getpreferredencoding(False)` w trybie `errors="strict"`.
  Jeśli bajty wyjścia narzędzia nie są poprawne w tym kodowaniu (np. środowisko
  z niespójną/minimalna lokalizacją, ścieżka domowa ze znakami spoza ASCII na
  systemie bez wymuszonego UTF-8), `subprocess.run` rzuca `UnicodeDecodeError`
  — który **jest podklasą `ValueError`, nie `OSError`**, więc nie jest łapany
  przez istniejący `except (FileNotFoundError, subprocess.TimeoutExpired,
  OSError)`. Wyjątek propaguje się w górę przez `get_special_dirs()` →
  `_build_sidebar()` → `_build_ui()` aż do konstruktora `FileDialog.__init__`,
  gdzie nie ma żadnego try/except — cała budowa dialogu (już częściowo wykonana:
  ikony załadowane, część drzewa widgetów DPG utworzona) kończy się
  nieobsłużonym wyjątkiem zamiast degradacji pojedynczego skrótu.
- **Repro:** Nie uruchomiono na żywo (wymaga Linuksa z kontrolowaną
  lokalizacją). Mechanizm potwierdzalny czysto przez inspekcję: `text=True`
  bez jawnego `encoding=`/`errors=` używa strict decode; typ wyjątku
  (`UnicodeDecodeError << ValueError`) nie jest podtypem `OSError`.
- **Fix (sugestia, nie wdrożona):** rozszerzyć except w `_get_xdg_dir` o
  `UnicodeDecodeError` (lub użyć `errors="replace"`/`errors="surrogateescape"`
  w `subprocess.run`), względnie owinąć całe `get_special_dirs()` w
  try/except na poziomie wywołania w `_build_sidebar`.
- **Confidence:** Medium — mechanizm techniczny pewny, ale prawdopodobieństwo
  trafienia w praktyce ograniczone przez PEP 538 (koercja lokalizacji C→C.UTF-8
  w CPython 3.7+ na większości dystrybucji), więc realny trigger wymaga
  dość nietypowego środowiska (np. minimalny obraz kontenera bez `C.UTF-8`).
- **Counterargument:** Wąski edge case; gdyby aplikacja-host owijała
  konstruktor `FileDialog(...)` we własny try/except (rozsądna praktyka dla
  bibliotek GUI), skutek ograniczałby się do nieudanego otwarcia dialogu, a nie
  crashu całej aplikacji — ale biblioteka nigdzie nie dokumentuje, że
  konstruktor może rzucać, więc to zaskakujące zachowanie dla integratora.

---

### platform-os-integration-05 — `get_special_dirs()` zakłada Windows w gałęzi `else` zamiast jawnie sprawdzać `_SYSTEM == "Windows"`; na nieobsługiwanej platformie `winreg` jest `None`, co daje nieobsłużony `AttributeError`

- **Plik:** `dpg_navigator/_platform.py:18-25` (`winreg = None` chyba że
  `os.name == "nt"`), `:67-97` (`if _SYSTEM == "Linux": ... elif _SYSTEM ==
  "Darwin": ... else: # Windows ...`)
- **Ryzyko:** P3
- **Kategoria:** defensive-programming / cross-platform
- **Impact:** Gałąź Windows jest wybierana przez domyślne `else`, nie przez
  jawne `elif _SYSTEM == "Windows"`. `winreg` jest ustawiane na `None` na
  starcie modułu, chyba że `os.name == "nt"` (czyli faktyczny Windows). Na
  jakiejkolwiek platformie, dla której `platform.system()` **nie** zwraca
  `"Linux"` ani `"Darwin"` (projekt deklaruje wsparcie tylko dla
  Windows/Linux/macOS — patrz `audit/00-scope.md` §1 — więc to dotyczy
  wyłącznie platform poza zadeklarowaną macierzą wsparcia, np. BSD/Solaris/AIX,
  albo nietypowych buildów Pythona), kod wpada w gałąź „Windows" i próbuje
  `winreg.OpenKey(...)`, gdzie `winreg is None` — daje to
  `AttributeError: 'NoneType' object has no attribute 'OpenKey'`. Ten wyjątek
  **nie jest łapany** przez istniejący `except (OSError, FileNotFoundError)`
  (AttributeError nie jest podklasą OSError), więc propaguje się aż do
  konstruktora `FileDialog`, zamiast degradować się łagodnie jak w gałęziach
  Linux/Darwin (`dirs[name] = os.path.join(home, name)`).
- **Repro:** Nie uruchomiono (wymaga platformy poza Windows/Linux/macOS, np.
  FreeBSD, gdzie `platform.system() == "FreeBSD"`). Mechanizm weryfikowalny
  bezpośrednio czytaniem kodu: `if/elif/else` bez trzeciego jawnego warunku +
  `winreg` inicjalizowane tylko pod `os.name == "nt"`.
- **Fix (sugestia, nie wdrożona):** zmienić `else: # Windows` na
  `elif _SYSTEM == "Windows":` i dodać jawną gałąź fallbackową (jak dla
  Linux/Darwin) dla wszystkich innych/nieznanych wartości `_SYSTEM`.
- **Confidence:** High co do mechanizmu (bezpośrednia lektura kodu), Low co do
  realnego wystąpienia w praktyce — projekt jawnie nie deklaruje wsparcia dla
  innych platform.
- **Counterargument:** Ponieważ projekt oficjalnie wspiera tylko
  Windows/Linux/macOS (deklaracja w `pyproject.toml`/README), można argumentować,
  że to **nie jest błąd w zakresie wspieranych platform** — raczej brak
  „defensywnej" obsługi dla platform jawnie niewspieranych, gdzie każde
  zachowanie (w tym crash) jest formalnie dopuszczalne. Zgłaszam mimo to, bo
  koszt naprawy jest trywialny, a obecne zachowanie (nieinformacyjny
  `AttributeError` zamiast łagodnej degradacji) jest gorsze niż to, co kod już
  robi dla Linux/Darwin.

---

## Ustalenia odrzucone (obalone w trakcie audytu)

Dla przejrzystości — kandydaci, które przeanalizowano i **nie** zgłoszono:

- **`is_hidden()` na Windows dla ścieżek >260 znaków (MAX_PATH):**
  `GetFileAttributesW` może zwrócić `INVALID_FILE_ATTRIBUTES` dla długich
  ścieżek bez prefiksu `\\?\`, co skutkuje cichym `is_hidden() == False`
  zamiast crasha. Odrzucone jako osobne ustalenie — to nie jest błąd
  specyficzny dla tej funkcji, tylko ogólne, dobrze znane ograniczenie API
  Windows dotyczące całego repo (enumeracja katalogów przez `os.scandir` też by
  ucierpiała), więc lepiej pasuje jako przekrojowa uwaga dla całego projektu niż
  punktowe ustalenie w `_platform.py`.
- **`get_file_time()` — martwy kod:** funkcja jest zdefiniowana, przetestowana
  (`tests/test_platform.py`), ale nigdzie nie wywoływana w kodzie produkcyjnym
  (`_filesystem.py`/`vfs/_local.py` liczą `st_mtime` bezpośrednio, nie przez
  ten wrapper) ani nie eksportowana w `__init__.py`. Odrzucone jako ustalenie —
  to nieużywany kod, nie błąd behawioralny; nie powoduje nieprawidłowego
  działania.
- **Wielokrotne otwieranie tego samego klucza rejestru w pętli
  (`get_special_dirs()`, gałąź Windows):** `winreg.OpenKey(...)` jest wołane
  osobno dla każdej z 5 nazw zamiast raz przed pętlą. Odrzucone — to
  nieefektywność (5 dodatkowych wywołań syscalli), nie błąd poprawności ani
  bezpieczeństwa; pomijalny wpływ na wydajność.
- **`get_drives()` — brak filtra `os.path.isdir()` na zwróconych punktach
  montowania** (w przeciwieństwie do `get_special_dirs()`, które filtruje).
  Odrzucone — to świadoma architektura: nawigacja do nieistniejącego/odłączonego
  dysku jest już obsłużona downstream przez istniejące `except (OSError,
  PermissionError)` w `list_dir()`/`DirectoryLister`, więc dodatkowy filtr
  tutaj byłby tylko kosmetyczny.

---

## Podsumowanie

| ID | Ryzyko | Plik | Confidence |
|---|---|---|---|
| platform-os-integration-01 | P2 | `_platform.py` (`_get_xdg_dir`) | High |
| platform-os-integration-02 | P2 | `_platform.py` (`get_drives`/`get_special_dirs`) | Medium |
| platform-os-integration-03 | P3 | `README.md`, `examples/*.py` | High (niespójność) / Medium (impact) |
| platform-os-integration-04 | P3 | `_platform.py` (`_get_xdg_dir`) | Medium |
| platform-os-integration-05 | P3 | `_platform.py` (`get_special_dirs`) | High (mechanizm) / Low (wystąpienie) |

5 ustalań zgłoszonych, 4 kandydatów obalonych/odrzuconych (sekcja powyżej).
Żadne nie duplikuje ustaleń z `docs/audits/*.md` (sprawdzono grepem po słowach
kluczowych: xdg, winreg, shcore, dpi, is_hidden, get_drives, get_special_dirs,
_platform — trafienia tylko w spisach plików/rekomendacjach ogólnych, nie w
konkretnych ustaleniach).
