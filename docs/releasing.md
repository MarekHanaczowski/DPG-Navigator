# Release Checklist

Publishing is automated by `.github/workflows/publish.yml`:

- `release` (`published`, pre-releases included) publishes to **PyPI**.
- `workflow_dispatch` publishes to **TestPyPI** (dry run).

Before building, the workflow runs the full CI workflow (`ci.yml`) as a
quality gate, then checks that the release tag equals `v{__version__}` from
`dpg_navigator/__init__.py`. Both publish jobs use trusted publishing (OIDC),
so no API token secret is needed.

## Versions

Versions follow [PEP 440](https://peps.python.org/pep-0440/) and, from 1.0.0,
[Semantic Versioning](https://semver.org/) for the public API defined in the
README ("Public API and Versioning").

| Stage | `__version__` | Tag | GitHub Release |
|-------|---------------|-----|----------------|
| Beta | `1.0.0b9` | `v1.0.0b9` | pre-release |
| Release candidate | `1.0.0rc1` | `v1.0.0rc1` | pre-release |
| Stable | `1.0.0` | `v1.0.0` | latest release |

`pip install dpg-navigator` ignores pre-releases unless `--pre` or an exact
version is given.

A release candidate is the code intended to ship as the stable version. After
an rc, only fixes for bugs found in that rc go in; each fix produces the next
rc (`rc2`, ...). When an rc has been in use for the soak period with no new
blocking bug, the same code is released as the stable version with only the
version number and the changelog heading changed.

## 0. Configure trusted publishing once

The PyPI project already exists, so the trusted publisher is configured in the
**project's** settings on PyPI (not as a pending publisher):

1. GitHub environment `pypi` -> PyPI trusted publisher for `publish.yml`.
2. GitHub environment `testpypi` -> TestPyPI trusted publisher for
   `publish.yml`.

## 1. Prepare the release PR

Work on a branch, never directly on `main`:

```bash
git switch main
git pull
git switch -c release/<version>
```

1. Set `__version__` in `dpg_navigator/__init__.py`.
2. In `CHANGELOG.md`, rename `## [Unreleased]` to `## [<version>] - YYYY-MM-DD`
   and add an empty `## [Unreleased]` above it.
3. For the stable 1.0.0 only: change the `Development Status` classifier in
   `pyproject.toml` from `4 - Beta` to `5 - Production/Stable`.
4. Commit, push, and open a PR to `main`.

## 2. Run quality checks

CI runs on the PR. Every job must pass, including:

- the Python matrix (Linux 3.10-3.14, Windows 3.10 and 3.13);
- **Lowest dependencies (Python 3.10)**, which installs every direct
  dependency at its declared minimum;
- **DearPyGui smoke (xvfb)**, which runs the real-DearPyGui integration tests
  with Chrome (`chrome-headless-shell`, `DPG_CHROME_NO_SANDBOX=1`).

The macOS job, `pip-audit` (informational, `continue-on-error`) and the
CycloneDX SBOM (`sbom-cyclonedx` artifact) run after the merge to `main`.
Before a stable release, check that the post-merge run on `main` is green too.

To run the same checks locally:

```bash
python -m pip install -e ".[dev]"
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m pytest -q --cov=dpg_navigator --cov-report=term-missing
DPG_INTEGRATION=1 python -m pytest -m integration   # needs a display
```

When adding a runtime or extra dependency, update `pyproject.toml` only (not
`requirements.txt`) and add a row to `THIRD_PARTY_NOTICES.md`. Keep the
Icons8 credit if you add or replace files under `dpg_navigator/images/`.
Third-party Actions stay pinned to commit SHAs.

## 3. Optional local build and smoke test

The publish workflow builds and checks the distributions itself. A local build
is still a useful pre-release check:

```bash
python -m pip install "build==1.2.2" "twine==7.0.0"
python -m build
python -m twine check dist/*
```

Smoke-test the wheel in a clean virtual environment (on Windows use
`.smoke_venv\Scripts\python`):

```bash
python -m venv .smoke_venv
.smoke_venv/bin/python -m pip install "dist/dpg_navigator-<version>-py3-none-any.whl"
.smoke_venv/bin/python -c "import dpg_navigator; from dpg_navigator import FileDialog, DialogConfig; print(dpg_navigator.__version__, FileDialog.__name__, DialogConfig().title)"
```

## 4. Merge, then tag

1. Merge the release PR (merge commit).
2. Update the local `main` and check that the version on it is the one you are
   about to tag:

   ```bash
   git switch main
   git pull
   git show main:dpg_navigator/__init__.py | grep __version__
   ```

3. Create and push an annotated tag on that commit:

   ```bash
   git tag -a v<version> -m "Release v<version>"
   git push origin v<version>
   ```

4. Check that the tag points at the release commit:

   ```bash
   git show v<version>:dpg_navigator/__init__.py | grep __version__
   ```

## 5. Publish

Write the release notes to a file (for example the changelog section of this
version), then create the GitHub Release from the tag. Use `--notes-file`
rather than an inline string, which breaks on quotes and newlines in
PowerShell.

Beta or release candidate:

```bash
gh release create v<version> --title "v<version>" --notes-file release-notes.md --prerelease
```

Stable:

```bash
gh release create v<version> --title "v<version>" --notes-file release-notes.md --latest
```

Publishing the release starts the `Publish` workflow: CI gate, tag/version
check, build, then upload to PyPI. Afterwards check:

- the workflow run is green;
- `https://pypi.org/project/dpg-navigator/<version>/` exists;
- `pip install dpg-navigator==<version>` works in a clean environment.

For a dry run against TestPyPI, start **Actions -> Publish -> Run workflow**
(`workflow_dispatch`) on the branch to test.

## If something goes wrong

- **Tag/version mismatch** (the build job fails): delete the GitHub Release
  and the tag (`git push origin :refs/tags/v<version>`), fix the version in a
  PR, then tag again.
- **A broken version reached PyPI**: PyPI files cannot be replaced. Yank the
  version on PyPI (Manage -> Release -> Options -> Yank) and release a fixed
  version with the next number (`rc2`, or `1.0.1`).
