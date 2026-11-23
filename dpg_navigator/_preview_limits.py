"""Shared preview resource limits (GUI-free).

Byte, pixel, and decompressed-package gates used by image, Office, font,
HTML, and archive preview paths. Renderers import constants and helpers
from here so limits stay consistent.
"""

from __future__ import annotations

import base64
import io
import os
import struct
import zipfile
from typing import Any, NamedTuple

from ._optional import OptionalModule, as_optional

PREVIEW_TEXT_CHUNK_BYTES: int = 256 * 1024
IMAGE_PREVIEW_MAX_BYTES: int = 32 * 1024 * 1024
IMAGE_PREVIEW_MAX_DIMENSION: int = 8192
IMAGE_PREVIEW_MAX_PIXELS: int = IMAGE_PREVIEW_MAX_DIMENSION * IMAGE_PREVIEW_MAX_DIMENSION
IMAGE_PREVIEW_TEXTURE_MAX_DIMENSION: int = 2048
"""Long-edge cap for the image preview texture (decoded size stays the source size).

DearPyGui uploads static textures as float RGBA, 16 bytes per pixel, on its
own thread: a 12 MP photo is a 192 MB buffer and held the dialog for
0.23-0.33 s (24 MP: 0.45-0.63 s). At 2048 px the texture is at most 3.1 MP
(50 MB) and the upload takes about 50-60 ms whatever the source size. Every GPU
DearPyGui runs on supports a 2048 px texture (most allow 8192-16384), and in
a pane about 700 px wide the picture stays sharp up to roughly 3x zoom.
"""
OOXML_PREVIEW_MAX_COMPRESSED_BYTES: int = 32 * 1024 * 1024
OOXML_PREVIEW_MAX_DECOMPRESSED_BYTES: int = 128 * 1024 * 1024
OOXML_PREVIEW_MAX_ENTRIES: int = 4096
OOXML_PREVIEW_MAX_MEMBER_BYTES: int = 32 * 1024 * 1024
PDF_PREVIEW_MAX_BYTES: int = 50 * 1024 * 1024
FONT_PREVIEW_MAX_BYTES: int = 16 * 1024 * 1024
HTML_DATA_IMAGE_MAX_BYTES: int = 512 * 1024
ARCHIVE_PREVIEW_MEMBER_MAX_BYTES: int = PREVIEW_TEXT_CHUNK_BYTES
ARCHIVE_EXTRACT_MAX_BYTES: int = 512 * 1024 * 1024

_SAFE_DATA_IMAGE_PREFIXES = (
    "data:image/gif;base64,",
    "data:image/jpeg;base64,",
    "data:image/png;base64,",
    "data:image/webp;base64,",
)

_FONT_MAGICS = (b"\x00\x01\x00\x00", b"OTTO", b"ttcf", b"wOFF", b"wOF2")

_PILImage: OptionalModule | None
try:
    from PIL import Image as _PILImage_mod

    _PILImage = as_optional(_PILImage_mod)
except Exception:
    _PILImage = None

_np: Any
try:
    import numpy as _np
except Exception:
    _np = None


class PreviewLimitError(Exception):
    """A preview input exceeded a documented resource limit."""


def file_size(path: str) -> int | None:
    """Return ``os.path.getsize`` or ``None`` when the path cannot be stat'd."""
    try:
        return os.path.getsize(path)
    except OSError:
        return None


def exceeds_bytes(path: str, limit: int) -> bool:
    """True when *path* exists and is larger than *limit*."""
    size = file_size(path)
    return size is not None and size > limit


def assert_image_within_limits(
    width: int,
    height: int,
    *,
    max_dim: int = IMAGE_PREVIEW_MAX_DIMENSION,
    max_pixels: int = IMAGE_PREVIEW_MAX_PIXELS,
) -> None:
    """Raise :class:`PreviewLimitError` when decoded dimensions are unsafe."""
    if width <= 0 or height <= 0:
        raise PreviewLimitError("Image has invalid dimensions")
    if width > max_dim or height > max_dim:
        raise PreviewLimitError("Image dimensions too large for preview")
    if width * height > max_pixels:
        raise PreviewLimitError("Image pixel count too large for preview")


def capped_thumbnail_size(
    width: int,
    height: int,
    max_dim: int = IMAGE_PREVIEW_MAX_DIMENSION,
) -> tuple[int, int]:
    """Return ``(width, height)`` scaled to fit inside *max_dim*."""
    if width <= 0 or height <= 0:
        return 1, 1
    scale = min(max_dim / width, max_dim / height, 1.0)
    return max(1, int(width * scale)), max(1, int(height * scale))


def read_image_header_bytes(data: bytes) -> tuple[int, int] | None:
    """Parse width/height from a PNG, JPEG, GIF, BMP, or WebP header prefix."""
    if len(data) < 24:
        return None
    if data.startswith(b"\x89PNG\r\n\x1a\n") and data[12:16] == b"IHDR":
        width, height = struct.unpack(">II", data[16:24])
        return int(width), int(height)
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        width, height = struct.unpack("<HH", data[6:10])
        return int(width), int(height)
    if data.startswith(b"BM") and len(data) >= 26:
        width, height = struct.unpack("<ii", data[18:26])
        return int(width), abs(int(height))
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP" and len(data) >= 30:
        return _webp_size(data)
    if data[:2] == b"\xff\xd8":
        return _jpeg_size(data)
    return None


def read_image_header(path: str) -> tuple[int, int] | None:
    """Read a small prefix of *path* and parse image dimensions if possible."""
    try:
        with open(path, "rb") as handle:
            data = handle.read(65536)
    except OSError:
        return None
    return read_image_header_bytes(data)


def probe_image_size(path: str) -> tuple[int, int] | None:
    """Return ``(width, height)`` from a header parse or lazy Pillow open."""
    parsed = read_image_header(path)
    if parsed is not None:
        return parsed
    if _PILImage is None:
        return None
    try:
        with _PILImage.open(path) as image:
            return int(image.size[0]), int(image.size[1])
    except Exception:
        return None


class PreviewRaster(NamedTuple):
    """A decoded preview picture: the source size and the (smaller) texture."""

    width: int
    """Width of the source image in pixels."""
    height: int
    """Height of the source image in pixels."""
    texture_width: int
    texture_height: int
    data: Any
    """Float RGBA pixels, ``texture_width * texture_height * 4`` values."""


def load_preview_rgba(path: str, *, max_dim: int = IMAGE_PREVIEW_MAX_DIMENSION) -> tuple[int, int, Any]:
    """Load an image for preview, thumbnailing before the RGBA conversion.

    Returns the decoded ``(width, height, data)``; the image is shrunk to fit
    a *max_dim* square (at most ``IMAGE_PREVIEW_MAX_DIMENSION``).
    """
    raster = load_preview_raster(path, max_dim=max_dim)
    return raster.texture_width, raster.texture_height, raster.data


def load_preview_raster(path: str, *, max_dim: int = IMAGE_PREVIEW_TEXTURE_MAX_DIMENSION) -> PreviewRaster:
    """Decode *path* for an on-screen preview, shrunk to fit a *max_dim* square.

    The result keeps the source size next to the texture size, so a caller
    can lay the picture out (and report it) at its true size while uploading
    a smaller texture. Shrinking happens before the float conversion, so a
    large photo never exists as a full-size float buffer.
    """
    if _PILImage is None:
        raise RuntimeError("Pillow is not installed or unavailable.")
    box = max(1, min(max_dim, IMAGE_PREVIEW_MAX_DIMENSION))
    with _PILImage.open(path) as image:
        src_w, src_h = int(image.size[0]), int(image.size[1])
        tex_w, tex_h, data = _shrunk_rgba_float(image, box, box)
    return PreviewRaster(src_w, src_h, tex_w, tex_h, data)


def decode_preview_rgba_bytes(blob: bytes, *, max_width: int | None = None) -> tuple[int, int, Any]:
    """Decode an embedded image blob with the same pixel gate as file images.

    *max_width* additionally shrinks a wider image (aspect ratio kept), so a
    caller that shows it at a known width does not upload a full-size texture.
    """
    header = read_image_header_bytes(blob)
    if header is not None:
        assert_image_within_limits(*header)
    if _PILImage is None:
        raise PreviewLimitError("Pillow is required to preview this image")
    with _PILImage.open(io.BytesIO(blob)) as image:
        if header is None:
            assert_image_within_limits(int(image.size[0]), int(image.size[1]))
        box_w = (
            IMAGE_PREVIEW_MAX_DIMENSION if max_width is None else max(1, min(max_width, IMAGE_PREVIEW_MAX_DIMENSION))
        )
        return _shrunk_rgba_float(image, box_w, IMAGE_PREVIEW_MAX_DIMENSION)


def check_ooxml_package(path: str) -> None:
    """Reject Office packages that exceed compressed or decompressed limits."""
    if not os.path.isfile(path):
        return
    if exceeds_bytes(path, OOXML_PREVIEW_MAX_COMPRESSED_BYTES):
        raise PreviewLimitError("File too large for preview")
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > OOXML_PREVIEW_MAX_ENTRIES:
                raise PreviewLimitError("File too large for preview")
            total = 0
            for info in infos:
                size = int(info.file_size)
                if size > OOXML_PREVIEW_MAX_MEMBER_BYTES:
                    raise PreviewLimitError("File too large for preview")
                total += size
                if total > OOXML_PREVIEW_MAX_DECOMPRESSED_BYTES:
                    raise PreviewLimitError("File too large for preview")
    except zipfile.BadZipFile:
        return


def ooxml_exceeds_preview_limit(path: str) -> bool:
    """True when *path* fails the Office compressed/decompressed preview gate."""
    try:
        check_ooxml_package(path)
    except PreviewLimitError:
        return True
    except OSError:
        return False
    return False


def font_magic_ok(path: str) -> bool:
    """True when *path* starts with a TrueType/OpenType/WOFF magic number."""
    try:
        with open(path, "rb") as handle:
            return handle.read(4) in _FONT_MAGICS
    except OSError:
        return False


def is_safe_data_image(value: str) -> bool:
    """True for an allow-listed raster ``data:image`` small enough to decode."""
    stripped = value.strip()
    lowered = stripped.lower()
    if not lowered.startswith(_SAFE_DATA_IMAGE_PREFIXES):
        return False
    comma = stripped.find(",")
    if comma < 0:
        return False
    payload = "".join(stripped[comma + 1 :].split())
    max_b64 = HTML_DATA_IMAGE_MAX_BYTES * 4 // 3 + 64
    if len(payload) > max_b64:
        return False
    try:
        raw = base64.b64decode(payload, validate=False)
    except Exception:
        return False
    if not raw or len(raw) > HTML_DATA_IMAGE_MAX_BYTES:
        return False
    header = read_image_header_bytes(raw)
    if header is None:
        return True
    try:
        assert_image_within_limits(*header)
    except PreviewLimitError:
        return False
    return True


def fast_rgba_conversion() -> bool:
    """True when NumPy converts decoded pixels; without it, conversion is a slow Python loop."""
    return _np is not None


def _shrunk_rgba_float(image: Any, box_w: int, box_h: int) -> tuple[int, int, Any]:
    """Shrink an open Pillow *image* to fit ``box_w`` x ``box_h``, then convert to float RGBA."""
    if image.size[0] > box_w or image.size[1] > box_h:
        if image.mode in ("1", "P"):
            # Pillow resizes palette and bilevel images with nearest-neighbour
            # only; convert first so the shrunk preview is not aliased.
            image = image.convert("RGBA")
        image.thumbnail((box_w, box_h))
    rgba = image.convert("RGBA") if image.mode != "RGBA" else image
    return _rgba_to_float(rgba)


def _rgba_to_float(rgba: Any) -> tuple[int, int, Any]:
    import array

    width, height = rgba.size
    raw = rgba.tobytes()
    if _np is not None:
        data = _np.frombuffer(raw, dtype=_np.uint8).astype(_np.float32) / _np.float32(255)
    else:
        data = array.array("f", (byte / 255.0 for byte in raw))
    return int(width), int(height), data


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    offset = 2
    length = len(data)
    while offset + 9 < length:
        if data[offset] != 0xFF:
            offset += 1
            continue
        marker = data[offset + 1]
        offset += 2
        if marker in {0xD8, 0xD9} or marker == 0x01:
            continue
        if offset + 2 > length:
            return None
        block = int.from_bytes(data[offset : offset + 2], "big")
        if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
            if offset + 7 > length:
                return None
            height, width = struct.unpack(">HH", data[offset + 3 : offset + 7])
            return int(width), int(height)
        if block < 2:
            return None
        offset += block
    return None


def _webp_size(data: bytes) -> tuple[int, int] | None:
    kind = data[12:16]
    if kind == b"VP8X" and len(data) >= 30:
        width = 1 + int.from_bytes(data[24:27], "little")
        height = 1 + int.from_bytes(data[27:30], "little")
        return width, height
    if kind == b"VP8 " and len(data) >= 30:
        width = int.from_bytes(data[26:28], "little") & 0x3FFF
        height = int.from_bytes(data[28:30], "little") & 0x3FFF
        return width, height
    if kind == b"VP8L" and len(data) >= 25:
        bits = int.from_bytes(data[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    return None
