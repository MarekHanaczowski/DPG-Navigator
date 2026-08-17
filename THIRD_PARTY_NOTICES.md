# Third-party notices

This file covers **this repository's own license**, **assets bundled in the
package**, and the **Python packages declared** in `pyproject.toml`.

Installed versions and *transitive* dependencies are not frozen here — they
change with each environment. CI publishes a CycloneDX SBOM (`sbom.cdx.json`,
artifact `sbom-cyclonedx`) for a full graph of a given build.

Chrome / Chromium is **not** shipped with this package. HTML, Markdown, and
Word-HTML previews launch a browser binary the user already has on `PATH`.

## This project

`dpg-navigator` is licensed under the MIT License. See [LICENSE](LICENSE).

## Bundled icons (Icons8 3D Fluency)

The PNG files under `dpg_navigator/images/` are [Icons8 3D Fluency](https://icons8.com/icons/3d-fluency)
graphics, used under Icons8's **free** terms: keep a visible credit with a
link to [https://icons8.com](https://icons8.com) (this file, the README Credits
section, and any host-app About screen that redistributes the dialog). Do **not**
extract these files and redistribute them as a standalone icon pack.

Bundled files:

- `add_file.png`
- `add_folder.png`
- `app.png`
- `back.png`
- `big_picture.png`
- `c.png`
- `config.png`
- `database.png`
- `desktop.png`
- `document.png`
- `documents.png`
- `downloads.png`
- `folder.png`
- `gears.png`
- `hd.png`
- `home.png`
- `iso.png`
- `link.png`
- `markdown.png`
- `mini_document.png`
- `mini_error.png`
- `mini_folder.png`
- `music.png`
- `music_note.png`
- `note.png`
- `object.png`
- `pdf.png`
- `picture.png`
- `picture_folder.png`
- `presentation.png`
- `python.png`
- `refresh.png`
- `script.png`
- `search.png`
- `spreadsheet.png`
- `text.png`
- `up.png`
- `url.png`
- `vector.png`
- `video.png`
- `videos.png`
- `web.png`
- `word.png`
- `zip.png`

## Declared Python dependencies

SPDX identifiers below come from each project's published metadata. They are
**not** a substitute for the license text that ships with an installed
distribution. Optional extras are pulled in only when the matching extra is
installed (`pip install dpg-navigator[pdf]`, `[archive]`, `[all]`, …).

### Runtime (always installed)

| Package | SPDX / license | Project |
| --- | --- | --- |
| [dearpygui](https://github.com/hoffstadt/DearPyGui) | MIT | GUI toolkit |
| [psutil](https://github.com/giampaolo/psutil) | BSD-3-Clause | process helpers (Chrome child teardown) |
| [bleach](https://github.com/mozilla/bleach) | Apache-2.0 | HTML sanitization |
| [defusedxml](https://github.com/tiran/defusedxml) | PSF-2.0 | safe XML parsing |

### Optional extras

| Extra | Package | SPDX / license | Notes |
| --- | --- | --- | --- |
| `preview`, `pdf`, `word`, `pptx`, `html`, `markdown` | [Pillow](https://python-pillow.org/) | MIT-CMU | image decode / screenshot PNG |
| `pdf` | [pypdfium2](https://github.com/pypdfium2-team/pypdfium2) | BSD-3-Clause (bindings); Apache-2.0 and other licenses in bundled PDFium | ships a native PDFium binary |
| `pdf`, `word`, `html`, `markdown` | [numpy](https://numpy.org/) | BSD-3-Clause | pixel buffers |
| `word` | [python-docx](https://github.com/python-openxml/python-docx) | MIT | `.docx` text fallback |
| `word` | [mammoth](https://github.com/mwilliamson/python-mammoth) | BSD-2-Clause | `.docx` → HTML |
| `word`, `html`, `markdown` | [html2image](https://github.com/vgalin/html2image) | MIT | Chrome/Chromium screenshot driver |
| `pptx` | [python-pptx](https://github.com/scanny/python-pptx) | MIT | `.pptx` preview |
| `markdown` | [Markdown](https://python-markdown.github.io/) | BSD-3-Clause | Markdown → HTML |
| `excel` | [openpyxl](https://openpyxl.readthedocs.io/) | MIT | `.xlsx` preview |
| `archive` | [py7zr](https://github.com/miurahr/py7zr) | **LGPL-2.1-or-later** | 7z listing/extract; **not vendored** — installed from PyPI with the extra |
| `code` | [Pygments](https://pygments.org/) | BSD-2-Clause | optional; source files already preview as text |

`py7zr` is the only declared extra under a copyleft license. This project does
not copy its sources into the sdist/wheel. Applications that **bundle** py7zr
into a frozen binary must follow LGPL-2.1-or-later (typically: dynamic link, or
provide the objects needed to relink).

### Development extra (`[dev]`)

Test and lint tools (`pytest`, `ruff`, `mypy`, and type stubs) are not required
at runtime. Their licenses apply only when you install `[dev]`.

## Build backend

Source builds use [hatchling](https://github.com/pypa/hatch) (MIT), declared
under `[build-system]` in `pyproject.toml`.
