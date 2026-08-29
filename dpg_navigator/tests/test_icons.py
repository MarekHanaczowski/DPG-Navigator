"""Tests for dpg_navigator._icons — extension mapping and icon lookup.

Only tests pure data structures and lookup logic; DPG texture loading
is NOT tested (requires DPG context).
"""

from __future__ import annotations

import os

import pytest

from dpg_navigator._icons import (
    _EXT_LOOKUP,
    EXTENSION_MAP,
    ICON_NAMES,
    IconRegistry,
)

# ── ICON_NAMES ──────────────────────────────────────────────────


class TestIconNames:
    def test_is_list(self):
        assert isinstance(ICON_NAMES, list)

    def test_not_empty(self):
        assert len(ICON_NAMES) > 0

    def test_count(self):
        assert len(ICON_NAMES) == 40

    def test_all_strings(self):
        for name in ICON_NAMES:
            assert isinstance(name, str)
            assert len(name) > 0

    def test_no_duplicates(self):
        assert len(ICON_NAMES) == len(set(ICON_NAMES))

    def test_icon_files_exist(self):
        images = os.path.join(os.path.dirname(os.path.dirname(__file__)), "images")
        for name in ICON_NAMES:
            assert os.path.isfile(os.path.join(images, f"{name}.png")), name

    def test_no_unreferenced_icon_files(self):
        images = os.path.join(os.path.dirname(os.path.dirname(__file__)), "images")
        on_disk = {name[:-4] for name in os.listdir(images) if name.lower().endswith(".png")}
        assert on_disk == set(ICON_NAMES)

    @pytest.mark.parametrize(
        "name",
        [
            "folder",
            "mini_folder",
            "mini_document",
            "python",
            "script",
            "home",
            "desktop",
            "downloads",
            "documents",
            "hd",
            "pdf",
            "spreadsheet",
            "presentation",
            "web",
            "database",
            "word",
            "text",
            "config",
            "markdown",
        ],
    )
    def test_essential_icons_present(self, name):
        assert name in ICON_NAMES


# ── EXTENSION_MAP ───────────────────────────────────────────────


class TestExtensionMap:
    def test_is_dict(self):
        assert isinstance(EXTENSION_MAP, dict)

    def test_not_empty(self):
        assert len(EXTENSION_MAP) > 0

    def test_keys_are_tuples_of_strings(self):
        for key in EXTENSION_MAP:
            assert isinstance(key, tuple)
            for ext in key:
                assert isinstance(ext, str)
                assert ext.startswith(".")

    def test_values_are_valid_icon_names(self):
        for icon_name in EXTENSION_MAP.values():
            assert icon_name in ICON_NAMES, f"Icon {icon_name!r} not in ICON_NAMES"

    def test_all_extensions_lowercase(self):
        for exts in EXTENSION_MAP:
            for ext in exts:
                assert ext == ext.lower(), f"Extension {ext!r} is not lowercase"

    @pytest.mark.parametrize(
        "ext,expected_icon",
        [
            (".py", "python"),
            (".exe", "app"),
            (".zip", "zip"),
            (".png", "picture"),
            (".mp3", "music_note"),
            (".mp4", "video"),
            (".txt", "text"),
            (".c", "script"),
            (".iso", "iso"),
            (".url", "url"),
            (".lnk", "link"),
            (".svg", "vector"),
            (".obj", "object"),
            (".dll", "gears"),
            (".pdf", "pdf"),
            (".xlsx", "spreadsheet"),
            (".pptx", "presentation"),
            (".html", "web"),
            (".sql", "database"),
            (".docx", "word"),
            (".json", "config"),
            (".md", "markdown"),
        ],
    )
    def test_specific_extension_mapping(self, ext, expected_icon):
        found_icon = None
        for exts, icon in EXTENSION_MAP.items():
            if ext in exts:
                found_icon = icon
                break
        assert found_icon == expected_icon, f"{ext} → {found_icon}, expected {expected_icon}"


# ── _EXT_LOOKUP (flat reverse index) ───────────────────────────


class TestExtLookup:
    def test_is_dict(self):
        assert isinstance(_EXT_LOOKUP, dict)

    def test_not_empty(self):
        assert len(_EXT_LOOKUP) > 0

    def test_all_keys_start_with_dot(self):
        for ext in _EXT_LOOKUP:
            assert ext.startswith("."), f"Key {ext!r} doesn't start with '.'"

    def test_all_values_in_icon_names(self):
        for icon_name in _EXT_LOOKUP.values():
            assert icon_name in ICON_NAMES, f"Value {icon_name!r} not in ICON_NAMES"

    def test_covers_all_extension_map_entries(self):
        """Every extension from EXTENSION_MAP should be in _EXT_LOOKUP."""
        for exts in EXTENSION_MAP:
            for ext in exts:
                assert ext in _EXT_LOOKUP, f"{ext} missing from _EXT_LOOKUP"

    def test_total_count_matches_extension_map(self):
        total = sum(len(exts) for exts in EXTENSION_MAP)
        assert len(_EXT_LOOKUP) == total

    @pytest.mark.parametrize(
        "ext,expected",
        [
            (".py", "python"),
            (".txt", "text"),
            (".mp3", "music_note"),
            (".exe", "app"),
            (".tar.gz", "zip"),
            (".jpg", "picture"),
            (".js", "script"),
            (".pdf", "pdf"),
            (".html", "web"),
            (".sql", "database"),
            (".json", "config"),
            (".md", "markdown"),
        ],
    )
    def test_direct_lookup(self, ext, expected):
        assert _EXT_LOOKUP[ext] == expected

    def test_unknown_extension_not_present(self):
        assert ".xyz123" not in _EXT_LOOKUP


# ── IconRegistry (lookup logic only, no DPG) ───────────────────


class TestIconRegistryLookup:
    """Test get_for_file() and get_for_dir() with mocked _tags dict.

    We manually populate _tags to avoid needing DPG for texture loading.
    """

    @pytest.fixture
    def registry(self):
        """Create an IconRegistry with pre-populated _tags (no DPG load)."""
        reg = IconRegistry.__new__(IconRegistry)
        reg._tags = {
            "python": "tag_python",
            "script": "tag_script",
            "note": "tag_note",
            "picture": "tag_picture",
            "music_note": "tag_music",
            "video": "tag_video",
            "zip": "tag_zip",
            "app": "tag_app",
            "mini_document": "tag_mini_doc",
            "mini_folder": "tag_mini_folder",
            "object": "tag_object",
            "vector": "tag_vector",
            "gears": "tag_gears",
            "c": "tag_c",
            "iso": "tag_iso",
            "url": "tag_url",
            "link": "tag_link",
            "pdf": "tag_pdf",
            "spreadsheet": "tag_spreadsheet",
            "presentation": "tag_presentation",
            "web": "tag_web",
            "database": "tag_database",
            "word": "tag_word",
            "text": "tag_text",
            "config": "tag_config",
            "markdown": "tag_markdown",
        }
        return reg

    # ── get_for_file ────────────────────────────────────────

    def test_python_file(self, registry):
        assert registry.get_for_file("main.py") == "tag_python"

    def test_javascript_file(self, registry):
        assert registry.get_for_file("app.js") == "tag_script"

    def test_text_file(self, registry):
        assert registry.get_for_file("readme.txt") == "tag_text"

    def test_image_file(self, registry):
        assert registry.get_for_file("photo.jpg") == "tag_picture"

    def test_music_file(self, registry):
        assert registry.get_for_file("song.mp3") == "tag_music"

    def test_video_file(self, registry):
        assert registry.get_for_file("clip.mp4") == "tag_video"

    def test_archive_file(self, registry):
        assert registry.get_for_file("backup.zip") == "tag_zip"

    def test_executable_file(self, registry):
        assert registry.get_for_file("setup.exe") == "tag_app"

    def test_c_source(self, registry):
        assert registry.get_for_file("main.c") == "tag_script"

    def test_iso_file(self, registry):
        assert registry.get_for_file("ubuntu.iso") == "tag_iso"

    def test_case_insensitive(self, registry):
        assert registry.get_for_file("Photo.JPG") == "tag_picture"
        assert registry.get_for_file("ARCHIVE.ZIP") == "tag_zip"

    def test_double_extension_tar_gz(self, registry):
        result = registry.get_for_file("archive.tar.gz")
        assert result == "tag_zip"

    def test_unknown_extension_fallback(self, registry):
        result = registry.get_for_file("data.xyz123")
        assert result == "tag_mini_doc"

    def test_no_extension_fallback(self, registry):
        result = registry.get_for_file("Makefile")
        assert result == "tag_mini_doc"

    def test_dotfile_without_known_ext(self, registry):
        result = registry.get_for_file(".gitignore")
        assert result == "tag_mini_doc"

    def test_multiple_dots(self, registry):
        result = registry.get_for_file("app.test.py")
        assert result == "tag_python"

    def test_bare_extension_file(self, registry):
        """A filename that IS just an extension (e.g., '.gz') should
        fall back to mini_document since there's no stem for double-ext check."""
        result = registry.get_for_file(".gz")
        assert result == "tag_mini_doc"

    def test_double_ext_tag_not_loaded_fallback(self):
        """If double-extension resolves to an icon name not in _tags,
        should fall through to mini_document."""
        reg = IconRegistry.__new__(IconRegistry)
        # zip is in _EXT_LOOKUP for .tar.gz but NOT in _tags
        reg._tags = {"mini_document": "tag_fallback"}
        result = reg.get_for_file("archive.tar.gz")
        assert result == "tag_fallback"

    # ── get_for_dir ─────────────────────────────────────────

    def test_get_for_dir(self, registry):
        assert registry.get_for_dir() == "tag_mini_folder"

    # ── get (simple tag lookup) ─────────────────────────────

    def test_get_existing(self, registry):
        assert registry.get("python") == "tag_python"

    def test_get_missing(self, registry):
        assert registry.get("nonexistent") is None

    # ── Edge case: missing tags in registry ─────────────────

    def test_missing_icon_tag_falls_through(self):
        """If the icon name exists in _EXT_LOOKUP but not in _tags,
        get_for_file should fall through to mini_document."""
        reg = IconRegistry.__new__(IconRegistry)
        reg._tags = {"mini_document": "tag_fallback"}
        result = reg.get_for_file("script.py")
        assert result == "tag_fallback"

    def test_completely_empty_tags(self):
        """If _tags is completely empty, get_for_file returns ''."""
        reg = IconRegistry.__new__(IconRegistry)
        reg._tags = {}
        result = reg.get_for_file("test.py")
        assert result == ""

    # ── Missing category coverage ───────────────────────────

    def test_html_file(self, registry):
        assert registry.get_for_file("index.html") == "tag_web"

    def test_css_file(self, registry):
        assert registry.get_for_file("style.css") == "tag_web"

    def test_sql_file(self, registry):
        assert registry.get_for_file("dump.sql") == "tag_database"

    def test_sqlite_file(self, registry):
        assert registry.get_for_file("data.sqlite") == "tag_database"

    def test_pdf_file(self, registry):
        assert registry.get_for_file("report.pdf") == "tag_pdf"

    def test_epub_file(self, registry):
        assert registry.get_for_file("book.epub") == "tag_pdf"

    def test_docx_file(self, registry):
        assert registry.get_for_file("letter.docx") == "tag_word"

    def test_xlsx_file(self, registry):
        assert registry.get_for_file("data.xlsx") == "tag_spreadsheet"

    def test_ods_file(self, registry):
        assert registry.get_for_file("budget.ods") == "tag_spreadsheet"

    def test_pptx_file(self, registry):
        assert registry.get_for_file("slides.pptx") == "tag_presentation"

    def test_odp_file(self, registry):
        assert registry.get_for_file("talk.odp") == "tag_presentation"

    def test_kotlin_file(self, registry):
        assert registry.get_for_file("Main.kt") == "tag_script"

    def test_vue_file(self, registry):
        assert registry.get_for_file("App.vue") == "tag_script"

    def test_toml_file(self, registry):
        assert registry.get_for_file("pyproject.toml") == "tag_config"

    def test_vob_video(self, registry):
        assert registry.get_for_file("movie.vob") == "tag_video"

    def test_heic_image(self, registry):
        assert registry.get_for_file("photo.heic") == "tag_picture"

    def test_dwg_cad(self, registry):
        assert registry.get_for_file("plan.dwg") == "tag_object"

    def test_svg_file(self, registry):
        assert registry.get_for_file("logo.svg") == "tag_vector"

    def test_blend_file(self, registry):
        assert registry.get_for_file("model.blend") == "tag_object"

    def test_dll_file(self, registry):
        assert registry.get_for_file("lib.dll") == "tag_gears"

    def test_url_file(self, registry):
        assert registry.get_for_file("bookmark.url") == "tag_url"

    def test_lnk_file(self, registry):
        assert registry.get_for_file("shortcut.lnk") == "tag_link"

    def test_tar_without_gz(self, registry):
        """Plain .tar should also map to zip."""
        assert registry.get_for_file("backup.tar") == "tag_zip"

    def test_uppercase_tar_gz(self, registry):
        """Case-insensitive double extension."""
        assert registry.get_for_file("BACKUP.TAR.GZ") == "tag_zip"

    # ── get_for_dir fallback ────────────────────────────────

    def test_get_for_dir_missing_tag(self):
        """If mini_folder not in _tags, get_for_dir returns ''."""
        reg = IconRegistry.__new__(IconRegistry)
        reg._tags = {}
        assert reg.get_for_dir() == ""


# ── Duplicate extension detection ──────────────────────────────


class TestExtensionMapIntegrity:
    def test_no_duplicate_extensions_across_tuples(self):
        """Each extension should appear in at most one tuple."""
        seen: dict[str, str] = {}
        for exts, icon in EXTENSION_MAP.items():
            for ext in exts:
                if ext in seen:
                    pytest.fail(f"Duplicate extension {ext!r}: in both {seen[ext]!r} and {icon!r}")
                seen[ext] = icon

    def test_all_extension_map_icons_match_icon_names(self):
        """Every icon referenced in EXTENSION_MAP must exist in ICON_NAMES."""
        icon_set = set(ICON_NAMES)
        for exts, icon in EXTENSION_MAP.items():
            assert icon in icon_set, f"Icon {icon!r} for {exts} not in ICON_NAMES"
