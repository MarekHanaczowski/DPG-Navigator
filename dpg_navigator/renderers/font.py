"""Font preview renderer — live glyph sample via DPG with Unicode ranges.

Loads .ttf/.otf into DearPyGui with Latin + Latin Extended-A (Polish diacritics)
and common punctuation so pangrams render with real glyphs, not tofu boxes.
"""

from __future__ import annotations

from typing import Any

import dearpygui.dearpygui as dpg  # type: ignore[import-untyped]

from .._preview_limits import FONT_PREVIEW_MAX_BYTES, exceeds_bytes, font_magic_ok
from .._types import FileEntry
from ._base import BaseRenderer, PreviewContext

# Built with \u escapes so the file encoding cannot corrupt Polish samples.
_PANGRAMS = (
    "The quick brown fox jumps over the lazy dog.",
    "0123456789 !@#$%&*()[]{}.,;:?'\"",
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "abcdefghijklmnopqrstuvwxyz",
    # Zazółć gęślą jaźń — ĄĆĘŁŃÓŚŹŻ ąćęłńóśźż
    (
        "Zaz\u00f3\u0142\u0107 g\u0119\u015bl\u0105 ja\u017a\u0144"
        " \u2014 \u0104\u0106\u0118\u0141\u0143\u00d3\u015a\u0179\u017b"
        " \u0105\u0107\u0119\u0142\u0144\u00f3\u015b\u017a\u017c"
    ),
    # Euro €  •  en–dash  — em—dash  … ellipsis
    "Euro \u20ac  \u2022  en\u2013dash  \u2014 em\u2014dash  \u2026 ellipsis",
)

_FONT_SIZES = (16, 24, 36, 48)

_LATIN_EXTENDED_A = (0x0100, 0x017F)
_LATIN_1_SUPPLEMENT = (0x00A0, 0x00FF)

# Explicit Polish letters + punctuation (DPG 1.x needs these in the atlas).
_POLISH_AND_PUNCT_CHARS: tuple[int, ...] = (
    0x00F3,
    0x0105,
    0x0107,
    0x0119,
    0x0142,
    0x0144,
    0x015B,
    0x017A,
    0x017C,
    0x00D3,
    0x0104,
    0x0106,
    0x0118,
    0x0141,
    0x0143,
    0x015A,
    0x0179,
    0x017B,
    0x20AC,
    0x2013,
    0x2014,
    0x2018,
    0x2019,
    0x201C,
    0x201D,
    0x2026,
    0x2022,
)
# Back-compat alias for tests that imported _EXTRA_CHARS.
_EXTRA_CHARS = _POLISH_AND_PUNCT_CHARS


def _dpg_needs_manual_glyph_ranges() -> bool:
    """True when DPG still requires explicit glyph ranges (pre-2.3).

    DearPyGui 2.3+ builds the font atlas on demand; ``add_font_range*`` /
    ``add_font_chars`` are deprecated no-ops and emit DeprecationWarning.

    Uses the installed package version (not ``get_major_version()``), which
    can crash outside an active DPG context on some builds.
    """
    try:
        from importlib.metadata import version as pkg_version

        parts = pkg_version("dearpygui").split(".")
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 0
        return (major, minor) < (2, 3)
    except Exception:
        # Unknown install: prefer registering ranges (harmless if no-op).
        return True


def _register_unicode_ranges() -> None:
    """Bake glyph ranges into the font currently being defined (dpg.font context).

    Only runs on DPG < 2.3, where Basic Latin is the default atlas and Polish
    diacritics would otherwise render as mojibake/tofu. On 2.3+ this is a no-op
    (auto atlas) so we skip the deprecated APIs entirely.
    """
    if not _dpg_needs_manual_glyph_ranges():
        return
    dpg.add_font_range_hint(dpg.mvFontRangeHint_Default)
    dpg.add_font_range(_LATIN_1_SUPPLEMENT[0], _LATIN_1_SUPPLEMENT[1])
    dpg.add_font_range(_LATIN_EXTENDED_A[0], _LATIN_EXTENDED_A[1])
    dpg.add_font_chars(list(_POLISH_AND_PUNCT_CHARS))


def polish_sample_text() -> str:
    """Return the Polish pangram used in the preview (for tests)."""
    return _PANGRAMS[4]


def load_font_with_unicode(path: str, size: float | int) -> Any:
    """Create one DPG font; registers Polish ranges only when required by DPG."""
    with dpg.font(path, size) as font_id:
        _register_unicode_ranges()
    return font_id


class FontRenderer(BaseRenderer):
    """Preview a .ttf/.otf by loading it into DPG and drawing sample text."""

    def __init__(self) -> None:
        self._font_ids: list[Any] = []

    def render(self, entry: FileEntry, ctx: PreviewContext) -> None:
        """Load the selected font at several sizes and render Unicode samples."""
        self.clear()
        if not ctx.panel_id:
            return

        dpg.delete_item(ctx.panel_id, children_only=True)
        dpg.add_text(
            entry.name,
            color=[180, 180, 255],
            parent=ctx.panel_id,
        )
        dpg.add_separator(parent=ctx.panel_id)

        if exceeds_bytes(entry.full_path, FONT_PREVIEW_MAX_BYTES):
            ctx.show_error("Font preview failed", "File too large for preview")
            return
        if not font_magic_ok(entry.full_path):
            ctx.show_error("Font preview failed", "Unrecognized font format")
            return

        try:
            with dpg.font_registry():
                for size in _FONT_SIZES:
                    self._font_ids.append(load_font_with_unicode(entry.full_path, size))
        except Exception as exc:
            ctx.show_error("Font preview failed", str(exc))
            self.clear()
            return

        if not self._font_ids:
            ctx.show_error("Font preview failed", "No font sizes loaded.")
            return

        if ctx.temp_font is not None and dpg.does_item_exist(ctx.temp_font):
            try:
                dpg.delete_item(ctx.temp_font)
            except Exception:
                pass
        ctx.temp_font = self._font_ids[0]

        with dpg.child_window(parent=ctx.panel_id, height=-1, width=-1):
            for font_id, size in zip(self._font_ids, _FONT_SIZES):
                # Bind the whole block so every line uses the preview face
                # (per-item bind is flaky when the default atlas lacks glyphs).
                with dpg.group() as block:
                    dpg.add_text(f"-- {size}px --", color=[128, 128, 128])
                    for line in _PANGRAMS:
                        dpg.add_text(line, wrap=0)
                    dpg.add_spacer(height=8)
                try:
                    dpg.bind_item_font(block, font_id)
                except Exception:
                    for child in dpg.get_item_children(block, 1) or []:
                        try:
                            dpg.bind_item_font(child, font_id)
                        except Exception:
                            pass

    def clear(self) -> None:
        """Delete fonts created for the current font preview."""
        for font_id in self._font_ids:
            if dpg.does_item_exist(font_id):
                try:
                    dpg.delete_item(font_id)
                except Exception:
                    pass
        self._font_ids.clear()
