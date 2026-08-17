"""Tests for preview extension registry and renderer routing."""

from __future__ import annotations

from dpg_navigator._preview_registry import (
    CODE_EXTS,
    HTML_EXTS,
    MD_EXTS,
    STB_IMAGE_EXTS,
    WORD_EXTS,
    PreviewCapabilities,
    PreviewKind,
    html_active_extensions,
    resolve_preview_kind,
)


def _resolve(filename: str, **capabilities: bool) -> PreviewKind:
    return resolve_preview_kind(
        filename,
        capabilities=PreviewCapabilities(**capabilities),
        image_extensions=STB_IMAGE_EXTS,
    )


class TestResolvePreviewKind:
    def test_html_has_builtin_route(self):
        assert _resolve("index.html") is PreviewKind.HTML

    def test_markdown_falls_back_to_text_without_backend(self):
        assert _resolve("README.md") is PreviewKind.TEXT

    def test_markdown_uses_renderer_when_backend_is_available(self):
        assert _resolve("README.md", markdown=True) is PreviewKind.MARKDOWN

    def test_code_falls_back_to_text_without_pygments(self):
        assert _resolve("script.py") is PreviewKind.TEXT

    def test_code_uses_renderer_when_pygments_is_available(self):
        assert _resolve("script.py", pygments=True) is PreviewKind.CODE

    def test_excel_requires_optional_backend(self):
        assert _resolve("book.xlsx") is PreviewKind.NONE
        assert _resolve("book.xlsx", excel=True) is PreviewKind.EXCEL

    def test_pdf_requires_optional_backend(self):
        assert _resolve("report.pdf") is PreviewKind.NONE
        assert _resolve("report.pdf", pdf=True) is PreviewKind.PDF

    def test_zip_has_builtin_route(self):
        assert _resolve("bundle.zip") is PreviewKind.ZIP

    def test_seven_z_requires_optional_backend(self):
        assert _resolve("bundle.7z") is PreviewKind.NONE
        assert _resolve("bundle.7z", seven_z=True) is PreviewKind.SEVEN_Z

    def test_image_route_uses_passed_extensions(self):
        assert _resolve("photo.png") is PreviewKind.IMAGE

    def test_word_requires_optional_backend(self):
        assert _resolve("document.docx") is PreviewKind.NONE
        assert _resolve("document.docx", word=True) is PreviewKind.WORD


class TestHtmlActiveExtensions:
    def test_base_html_extensions_are_always_active(self):
        assert html_active_extensions(PreviewCapabilities()) == HTML_EXTS

    def test_optional_html_renderers_extend_active_extensions(self):
        extensions = html_active_extensions(
            PreviewCapabilities(markdown=True, pygments=True, mammoth=True),
        )

        assert MD_EXTS <= extensions
        assert WORD_EXTS <= extensions
        assert not CODE_EXTS.issubset(extensions)


class TestExtensionlessFilenames:
    """Extensionless files (Makefile/Dockerfile) resolve via their dotted entry."""

    def test_dockerfile_routes_to_text_without_pygments(self):
        assert _resolve("Dockerfile") is PreviewKind.TEXT

    def test_dockerfile_routes_to_code_with_pygments(self):
        assert _resolve("Dockerfile", pygments=True) is PreviewKind.CODE

    def test_makefile_routes_to_text_without_pygments(self):
        assert _resolve("Makefile") is PreviewKind.TEXT

    def test_makefile_routes_to_code_with_pygments(self):
        assert _resolve("Makefile", pygments=True) is PreviewKind.CODE

    def test_dotfile_without_extension_routes_to_text(self):
        # splitext(".gitignore") == (".gitignore", ""), so no extension but the
        # dotted name still matches the registry entry.
        assert _resolve(".gitignore") is PreviewKind.TEXT

    def test_unknown_extensionless_name_has_no_route(self):
        assert _resolve("README") is PreviewKind.NONE
