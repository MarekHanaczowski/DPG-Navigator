"""Tests for text-preview encoding detection (no DearPyGui)."""

from __future__ import annotations

from dpg_navigator._preview import decode_preview_bytes


class TestDecodePreviewBytes:
    def test_empty_is_not_binary(self):
        text, is_bin, encoding = decode_preview_bytes(b"")
        assert text == ""
        assert is_bin is False
        assert encoding is None

    def test_utf8(self):
        text, is_bin, encoding = decode_preview_bytes("Zażółć".encode())
        assert is_bin is False
        assert text == "Zażółć"
        assert encoding == "utf-8-sig"

    def test_utf8_bom(self):
        raw = b"\xef\xbb\xbfhello"
        text, is_bin, encoding = decode_preview_bytes(raw)
        assert is_bin is False
        assert text == "hello"
        assert encoding == "utf-8-sig"

    def test_utf32_be_bom(self):
        raw = b"\x00\x00\xfe\xff" + "ab".encode("utf-32-be")
        text, is_bin, encoding = decode_preview_bytes(raw)
        assert is_bin is False
        assert text == "ab"
        assert encoding == "utf-32-be"

    def test_utf16_le_bom(self):
        raw = "ab".encode("utf-16")
        text, is_bin, encoding = decode_preview_bytes(raw)
        assert is_bin is False
        assert text == "ab"
        assert encoding == "utf-16"

    def test_nul_bytes_are_binary(self):
        raw = b"\x00\x01\x02\x03\xff\xfe\x00\x00"
        text, is_bin, encoding = decode_preview_bytes(raw)
        assert is_bin is True
        assert text is None
        assert encoding is None

    def test_known_encoding_skips_detection(self):
        raw = "ab".encode("utf-16")
        text, is_bin, encoding = decode_preview_bytes(
            raw,
            known_encoding="utf-16",
        )
        assert is_bin is False
        assert text == "ab"
        assert encoding == "utf-16"

    def test_cp1250_polish(self):
        raw = "łąka".encode("cp1250")
        text, is_bin, encoding = decode_preview_bytes(raw)
        assert is_bin is False
        assert text == "łąka"
        assert encoding == "cp1250"
