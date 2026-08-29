"""Tests for shared preview resource limits."""

from __future__ import annotations

import base64
import struct
import zipfile
from unittest.mock import patch

import pytest

from dpg_navigator._preview_limits import (
    HTML_DATA_IMAGE_MAX_BYTES,
    IMAGE_PREVIEW_MAX_DIMENSION,
    IMAGE_PREVIEW_MAX_PIXELS,
    PREVIEW_TEXT_CHUNK_BYTES,
    PreviewLimitError,
    assert_image_within_limits,
    capped_thumbnail_size,
    check_ooxml_package,
    decode_preview_rgba_bytes,
    exceeds_bytes,
    file_size,
    font_magic_ok,
    is_safe_data_image,
    load_preview_rgba,
    ooxml_exceeds_preview_limit,
    probe_image_size,
    read_image_header,
    read_image_header_bytes,
)


def _png(width: int, height: int) -> bytes:
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + ihdr + b"\x00\x00\x00\x00"


def _gif(width: int, height: int) -> bytes:
    return b"GIF89a" + struct.pack("<HH", width, height) + b"\x00" * 14


def _bmp(width: int, height: int) -> bytes:
    data = bytearray(26)
    data[0:2] = b"BM"
    struct.pack_into("<ii", data, 18, width, height)
    return bytes(data)


def _jpeg(width: int, height: int) -> bytes:
    sof = b"\xff\xc0\x00\x0b\x08" + struct.pack(">HH", height, width) + b"\x01\x11\x00"
    return (b"\xff\xd8" + sof).ljust(24, b"\x00")


def _webp_vp8x(width: int, height: int) -> bytes:
    data = bytearray(30)
    data[0:4] = b"RIFF"
    data[8:12] = b"WEBP"
    data[12:16] = b"VP8X"
    data[24:27] = (width - 1).to_bytes(3, "little")
    data[27:30] = (height - 1).to_bytes(3, "little")
    return bytes(data)


def _webp_vp8(width: int, height: int) -> bytes:
    data = bytearray(30)
    data[0:4] = b"RIFF"
    data[8:12] = b"WEBP"
    data[12:16] = b"VP8 "
    data[26:28] = (width & 0x3FFF).to_bytes(2, "little")
    data[28:30] = (height & 0x3FFF).to_bytes(2, "little")
    return bytes(data)


def _webp_vp8l(width: int, height: int) -> bytes:
    data = bytearray(25)
    data[0:4] = b"RIFF"
    data[8:12] = b"WEBP"
    data[12:16] = b"VP8L"
    bits = (width - 1) | ((height - 1) << 14)
    data[21:25] = bits.to_bytes(4, "little")
    return bytes(data).ljust(30, b"\x00")


class TestImageLimits:
    def test_png_header_dimensions(self):
        assert read_image_header_bytes(_png(30, 40)) == (30, 40)

    def test_gif_bmp_jpeg_webp_headers(self):
        assert read_image_header_bytes(_gif(12, 34)) == (12, 34)
        assert read_image_header_bytes(_bmp(16, -20)) == (16, 20)
        assert read_image_header_bytes(_jpeg(64, 48)) == (64, 48)
        assert read_image_header_bytes(_webp_vp8x(80, 60)) == (80, 60)
        assert read_image_header_bytes(_webp_vp8(40, 30)) == (40, 30)
        assert read_image_header_bytes(_webp_vp8l(11, 9)) == (11, 9)

    def test_unknown_header_is_none(self):
        assert read_image_header_bytes(b"not-an-image-header!!!!!!") is None
        assert read_image_header_bytes(b"short") is None

    def test_read_image_header_from_path(self, tmp_path):
        path = tmp_path / "tiny.png"
        path.write_bytes(_png(8, 9))
        assert read_image_header(str(path)) == (8, 9)
        assert probe_image_size(str(path)) == (8, 9)
        assert read_image_header(str(tmp_path / "missing.png")) is None

    def test_oversized_pixels_rejected(self):
        with pytest.raises(PreviewLimitError, match="pixel"):
            assert_image_within_limits(100, 100, max_dim=200, max_pixels=50)
        with pytest.raises(PreviewLimitError, match="dimensions"):
            assert_image_within_limits(30000, 30000)

    def test_invalid_and_oversize_dimensions(self):
        with pytest.raises(PreviewLimitError, match="invalid"):
            assert_image_within_limits(0, 10)
        with pytest.raises(PreviewLimitError, match="dimensions"):
            assert_image_within_limits(IMAGE_PREVIEW_MAX_DIMENSION + 1, 10)

    def test_pixel_cap_matches_8192_square(self):
        assert IMAGE_PREVIEW_MAX_PIXELS == 8192 * 8192

    def test_thumbnail_scale_and_invalid(self):
        assert capped_thumbnail_size(0, 10) == (1, 1)
        assert capped_thumbnail_size(100, 50, max_dim=50) == (50, 25)
        assert capped_thumbnail_size(10, 10, max_dim=50) == (10, 10)

    def test_file_size_helpers(self, tmp_path):
        path = tmp_path / "blob.bin"
        path.write_bytes(b"abcdef")
        assert file_size(str(path)) == 6
        assert file_size(str(tmp_path / "missing.bin")) is None
        assert exceeds_bytes(str(path), 3) is True
        assert exceeds_bytes(str(path), 10) is False

    def test_load_and_decode_rgba(self, tmp_path):
        image = pytest.importorskip("PIL.Image")
        path = tmp_path / "ok.png"
        image.new("RGB", (4, 3), (255, 0, 0)).save(path)
        width, height, data = load_preview_rgba(str(path))
        assert (width, height) == (4, 3)
        assert len(data) == 4 * 3 * 4
        blob = path.read_bytes()
        dec_w, dec_h, _dec = decode_preview_rgba_bytes(blob)
        assert (dec_w, dec_h) == (4, 3)

    def test_decode_rejects_header_bomb(self):
        with pytest.raises(PreviewLimitError):
            decode_preview_rgba_bytes(_png(30000, 30000))


class TestOoxmlLimits:
    def test_decompressed_zip_bomb_is_rejected(self, tmp_path):
        path = tmp_path / "bomb.docx"
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("word/document.xml", "x" * 64)
        with patch("dpg_navigator._preview_limits.OOXML_PREVIEW_MAX_DECOMPRESSED_BYTES", 8):
            assert ooxml_exceeds_preview_limit(str(path)) is True

    def test_small_non_zip_is_not_oversized(self, tmp_path):
        path = tmp_path / "small.docx"
        path.write_bytes(b"x")
        assert ooxml_exceeds_preview_limit(str(path)) is False

    def test_missing_path_is_not_oversized(self, tmp_path):
        assert ooxml_exceeds_preview_limit(str(tmp_path / "nope.docx")) is False

    def test_entry_and_member_caps(self, tmp_path):
        path = tmp_path / "many.docx"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("a.xml", "hello")
            archive.writestr("b.xml", "world")
        with (
            patch("dpg_navigator._preview_limits.OOXML_PREVIEW_MAX_ENTRIES", 1),
            pytest.raises(PreviewLimitError),
        ):
            check_ooxml_package(str(path))
        with (
            patch("dpg_navigator._preview_limits.OOXML_PREVIEW_MAX_MEMBER_BYTES", 2),
            pytest.raises(PreviewLimitError),
        ):
            check_ooxml_package(str(path))
        with (
            patch("dpg_navigator._preview_limits.OOXML_PREVIEW_MAX_COMPRESSED_BYTES", 1),
            pytest.raises(PreviewLimitError),
        ):
            check_ooxml_package(str(path))
        check_ooxml_package(str(path))

    def test_oserror_during_zip_is_not_oversized(self, tmp_path):
        path = tmp_path / "locked.docx"
        path.write_bytes(b"PK\x03\x04")
        with patch("dpg_navigator._preview_limits.zipfile.ZipFile", side_effect=OSError("locked")):
            assert ooxml_exceeds_preview_limit(str(path)) is False


class TestDataImage:
    def test_short_png_prefix_is_allowed(self):
        assert is_safe_data_image("data:image/png;base64,iVBORw0KGgo=") is True

    def test_svg_data_uri_is_rejected(self):
        assert is_safe_data_image("data:image/svg+xml;base64,PHN2Zz4=") is False

    def test_oversized_payload_is_rejected(self):
        payload = "A" * (HTML_DATA_IMAGE_MAX_BYTES * 4)
        assert is_safe_data_image(f"data:image/png;base64,{payload}") is False

    def test_empty_and_header_bomb_payloads(self):
        assert is_safe_data_image("data:image/png;base64,") is False
        bomb = base64.b64encode(_png(30000, 30000)).decode("ascii")
        assert is_safe_data_image(f"data:image/png;base64,{bomb}") is False


class TestFontMagic:
    def test_otto_magic_ok(self, tmp_path):
        path = tmp_path / "font.otf"
        path.write_bytes(b"OTTO" + b"\x00" * 8)
        assert font_magic_ok(str(path)) is True
        path.write_bytes(b"XXXX")
        assert font_magic_ok(str(path)) is False
        assert font_magic_ok(str(tmp_path / "missing.ttf")) is False


class TestTextChunk:
    def test_text_chunk_is_256_kib(self):
        assert PREVIEW_TEXT_CHUNK_BYTES == 256 * 1024
