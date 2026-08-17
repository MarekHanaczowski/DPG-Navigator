"""Guards for supply-chain docs: notices file and non-duplicated requirements."""

from __future__ import annotations

from pathlib import Path

import dpg_navigator

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PKG_DIR = Path(dpg_navigator.__file__).resolve().parent


def _notices_path() -> Path:
    for candidate in (
        _REPO_ROOT / "THIRD_PARTY_NOTICES.md",
        _PKG_DIR / "THIRD_PARTY_NOTICES.md",
    ):
        if candidate.is_file():
            return candidate
    raise AssertionError("THIRD_PARTY_NOTICES.md missing (repo root or installed package dir)")


class TestThirdPartyNotices:
    def test_notices_file_exists(self):
        path = _notices_path()
        assert path.is_file()

    def test_notices_cover_icons8_and_copyleft_extra(self):
        text = _notices_path().read_text(encoding="utf-8")
        assert "Icons8" in text
        assert "https://icons8.com" in text
        assert "py7zr" in text
        assert "LGPL-2.1-or-later" in text
        assert "dearpygui" in text
        assert "dpg_navigator/images/" in text


class TestRequirementsPointer:
    def test_requirements_txt_does_not_pin_packages(self):
        path = _REPO_ROOT / "requirements.txt"
        assert path.is_file(), "keep requirements.txt as a pyproject.toml pointer"
        pins = []
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            pins.append(line)
        assert pins == ["."], pins
