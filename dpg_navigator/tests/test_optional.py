"""Tests for optional-backend typing helpers."""

from __future__ import annotations

import pytest

from dpg_navigator._optional import as_optional, require_optional


def test_as_optional_returns_the_same_object() -> None:
    sentinel = object()
    assert as_optional(sentinel) is sentinel


def test_require_optional_returns_installed_backend() -> None:
    sentinel = object()
    assert require_optional(sentinel, "numpy") is sentinel


def test_require_optional_raises_when_missing() -> None:
    with pytest.raises(RuntimeError, match="numpy is not installed"):
        require_optional(None, "numpy")
