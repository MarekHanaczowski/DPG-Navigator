# Release Checklist

Publishing is automated via `.github/workflows/publish.yml`:

- `workflow_dispatch` publishes to TestPyPI.
- `release` (`published`) publishes to PyPI.

Both jobs use trusted publishing (OIDC), so no API token secret is required.

## 0. Configure trusted publishing once

Before the first automated publish, configure trusted publishers for this
repository on both package indexes:

1. `testpypi` environment in GitHub -> TestPyPI trusted publisher entry.
2. `pypi` environment in GitHub -> PyPI trusted publisher entry.

Use the `publish.yml` workflow name and the repository default branch settings
expected by the package index.

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
python -m ruff format --check .
python -m mypy
python -m pytest -q
```

Push the release commit and confirm that every GitHub Actions matrix job passes.

CI also generates a CycloneDX SBOM (`sbom.cdx.json`) as the `sbom-cyclonedx`
artifact. Third-party Actions are pinned to commit SHAs in
`.github/workflows/ci.yml` and `publish.yml` (not floating tags).

When adding a runtime or extra dependency, update `pyproject.toml` only (not
`requirements.txt` pins) and add a row to `THIRD_PARTY_NOTICES.md`. Keep the
Icons8 credit if you add or replace files under `dpg_navigator/images/`.

## 3. Optional local build and smoke test

The publish workflow builds and validates distributions automatically. Local
builds are still useful for pre-release checks:

```bash
python -m pip install build twine
python -m build
python -m twine check dist/*
```

Then run the wheel smoke test:

```bash
python -m venv .smoke_venv
python -m pip --python .smoke_venv install --no-deps dist/dpg_navigator-<version>-py3-none-any.whl
python -m pip --python .smoke_venv install "dearpygui>=1.9.1" "psutil>=5.9.0" "bleach>=6.0" "defusedxml>=0.7.1"
python -m pip --python .smoke_venv show dpg-navigator
python -c "import dpg_navigator; from dpg_navigator import FileDialog, DialogConfig; print(dpg_navigator.__version__); print(FileDialog.__name__); print(DialogConfig().title)"
```

## 4. Publish flow

For a dry run against TestPyPI:

```bash
# Run Actions -> Publish -> Run workflow (workflow_dispatch)
```

For production release:

1. Create and push an annotated version tag:

```bash
git tag -a v<version> -m "Release v<version>"
git push origin main
git push origin v<version>
```

2. Publish a GitHub Release from that tag.
3. The `Publish` workflow runs automatically on `release.published` and uploads
   the already-built distributions to PyPI.
