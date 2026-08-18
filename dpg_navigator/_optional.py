"""Typing helpers for optional third-party backends.

Failed imports are ``None`` (no ``cast(Any, None)``). Import the package
under a temporary name, then assign: that avoids mypy ``no-redef`` on
``X: OptionalModule | None`` followed by ``import pkg as X``. After a
``None`` check, attribute access and calls are untyped.
"""

from __future__ import annotations

from typing import Any, Protocol, TypeVar

_T = TypeVar("_T")


class OptionalModule(Protocol):
    """Imported third-party module, class, or factory.

    ``__getattr__`` covers module/class attributes; ``__call__`` covers
    constructors such as ``Document`` / ``Html2Image`` / ``load_workbook``.
    """

    def __getattr__(self, name: str) -> Any: ...

    def __call__(self, *args: Any, **kwargs: Any) -> Any: ...


OptionalCallable = OptionalModule


def as_optional(module: object) -> OptionalModule:
    """Treat a successful import as ``OptionalModule``.

    Real stdlib ``ModuleType`` / typed factories are not structural matches
    for this protocol; the None branch stays a plain ``None``.
    """
    return module  # type: ignore[return-value]


def require_optional(module: _T | None, name: str) -> _T:
    """Narrow a successful optional import. Callers are gated on ``*_available()``."""
    if module is None:
        raise RuntimeError(f"{name} is not installed")
    return module
