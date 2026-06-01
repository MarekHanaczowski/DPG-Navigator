# Release Checklist

The repository currently has no automated publishing workflow. Perform releases
from a clean `main` checkout and keep artifact upload manual until repository
secrets and a trusted publishing target are configured.

## 1. Prepare the version

1. Update `__version__` in `dpg_navigator/__init__.py`.
2. Move the relevant entries from `CHANGELOG.md` under a versioned heading with
   the release date.
3. Commit the version and changelog update.

## 2. Run quality checks

Install the development dependencies and run the same checks as CI:

```bash
python -m pip install -e ".[dev]"
python -m ruff check .
python -m mypy dpg_navigator/_types.py dpg_navigator/_filesystem.py dpg_navigator/_preview_registry.py dpg_navigator/_preview_table.py dpg_navigator/_preview_archive.py dpg_navigator/_preview_spreadsheet.py dpg_navigator/_preview_sqlite.py
python -m pytest -q
```

Push the release commit and confirm that every GitHub Actions matrix job passes.

## 3. Build artifacts

Install the build frontend, clear previous artifacts, and create both wheel and
source distribution files:

```bash
python -m pip install build
python -m build
```

Verify the resulting files under `dist/`. Build from an empty `dist/` directory
when preparing files for upload so stale artifacts cannot be published.

## 4. Smoke-test the wheel

Create a fresh virtual environment and install only the built wheel plus the
required runtime dependencies:

```bash
python -m venv .smoke_venv
python -m pip --python .smoke_venv install --no-deps dist/dpg_navigator-<version>-py3-none-any.whl
python -m pip --python .smoke_venv install "dearpygui>=1.9.1" "psutil>=5.9.0"
python -m pip --python .smoke_venv show dpg-navigator
```

On older pip versions without `--python`, invoke the virtual environment's
Python executable directly with `-m pip`. Then import the public API:

```bash
python -c "import dpg_navigator; from dpg_navigator import FileDialog, DialogConfig; print(dpg_navigator.__version__); print(FileDialog.__name__); print(DialogConfig().title)"
```

Run the final import command with the fresh virtual environment's Python
executable.

## 5. Tag and publish

Create an annotated tag only after CI and the wheel smoke test pass:

```bash
git tag -a v<version> -m "Release v<version>"
git push origin main
git push origin v<version>
```

Create a GitHub Release from the tag and attach the wheel and source
distribution from `dist/`. Publish to a Python package index only after the
target account and trusted publishing policy are configured.
