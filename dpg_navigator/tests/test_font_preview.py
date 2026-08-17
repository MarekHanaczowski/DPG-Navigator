"""Tests for font preview Unicode range helpers (no DPG context required)."""

from __future__ import annotations

from dpg_navigator.renderers import font as fontmod


class TestFontUnicodeRanges:
    def test_polish_pangram_contains_diacritics(self):
        text = fontmod.polish_sample_text()
        for ch in "ąćęłńóśźżĄĆĘŁŃÓŚŹŻ":
            assert ch in text, f"missing {ch!r} in {text!r}"

    def test_latin_extended_a_covers_polish_codepoints(self):
        lo, hi = fontmod._LATIN_EXTENDED_A
        # ą U+0105, ć U+0107, ę U+0119, ł U+0142, ń U+0144, ó U+00F3 is Latin-1
        for cp in (0x0105, 0x0107, 0x0119, 0x0142, 0x0144, 0x015B, 0x017A, 0x017C, 0x0179, 0x017B):
            assert lo <= cp <= hi

    def test_latin1_covers_o_acute(self):
        lo, hi = fontmod._LATIN_1_SUPPLEMENT
        assert lo <= 0x00F3 <= hi  # ó
        assert lo <= 0x00D3 <= hi  # Ó

    def test_extra_chars_include_euro_and_dashes(self):
        assert 0x20AC in fontmod._EXTRA_CHARS
        assert 0x2013 in fontmod._EXTRA_CHARS
        assert 0x2014 in fontmod._EXTRA_CHARS

    def test_polish_chars_list_covers_all_diacritics(self):
        needed = {ord(c) for c in "ąćęłńóśźżĄĆĘŁŃÓŚŹŻ"}
        assert needed.issubset(set(fontmod._POLISH_AND_PUNCT_CHARS))

    def test_pangrams_include_euro_line(self):
        joined = "\n".join(fontmod._PANGRAMS)
        assert "€" in joined
        assert "\u0142" in joined  # ł
        assert "\u0105" in joined  # ą

    def test_manual_ranges_gate_is_bool(self):
        assert isinstance(fontmod._dpg_needs_manual_glyph_ranges(), bool)
