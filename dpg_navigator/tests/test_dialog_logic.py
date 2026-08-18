"""GUI-free DialogLogic navigation tests (local dirs and archive virtual paths)."""

from __future__ import annotations

import os
import zipfile

from dpg_navigator._types import DialogConfig
from dpg_navigator.dialog._logic import DialogLogic
from dpg_navigator.dialog._state import DialogState


def _make_logic(root: str):
    state = DialogState()
    state.current_dir = root
    config = DialogConfig(search_subfolders=False, show_dir_size=False)
    listings: list[list] = []
    errors: list[tuple[str, str]] = []
    path_inputs: list[str] = []
    logic = DialogLogic(
        state=state,
        config=config,
        refresh_ui_cb=lambda entries: listings.append(list(entries)),
        show_error_cb=lambda title, msg: errors.append((title, msg)),
        update_path_input_cb=lambda path: path_inputs.append(path),
        update_size_cell_cb=lambda *_args: None,
    )
    return logic, listings, errors, path_inputs


def _zip_with_nested_docs(tmp_path):
    archive_path = tmp_path / "sample.zip"
    with zipfile.ZipFile(archive_path, "w") as zf:
        zf.writestr("docs/readme.txt", "hello")
        zf.writestr("docs/nested/inner.txt", "deep")
        zf.writestr("root.txt", "top")
    return str(archive_path)


class TestNavigateLocal:
    def test_enters_subdirectory(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "a.txt").write_text("x")

        logic, listings, errors, _ = _make_logic(str(tmp_path))
        logic.navigate_to(str(sub))

        assert errors == []
        assert logic.state.current_dir == os.path.normpath(str(sub))
        assert any(e.name == "a.txt" for e in listings[-1])

    def test_missing_directory_keeps_current_and_reports(self, tmp_path):
        logic, listings, errors, path_inputs = _make_logic(str(tmp_path))
        logic.navigate_to(str(tmp_path / "missing"))

        assert logic.state.current_dir == str(tmp_path)
        assert errors and errors[-1][0] == "Path not found"
        assert path_inputs[-1] == str(tmp_path)
        assert listings == []

    def test_relative_subdirectory(self, tmp_path):
        sub = tmp_path / "rel"
        sub.mkdir()
        (sub / "b.txt").write_text("y")

        logic, listings, errors, _ = _make_logic(str(tmp_path))
        logic.navigate_to("rel")

        assert errors == []
        assert logic.state.current_dir == os.path.normpath(str(sub))
        assert any(e.name == "b.txt" for e in listings[-1])


class TestNavigateArchive:
    def test_enters_archive_root(self, tmp_path):
        archive = _zip_with_nested_docs(tmp_path)
        logic, listings, errors, _ = _make_logic(str(tmp_path))
        logic.navigate_to(f"{archive}|/")

        assert errors == []
        assert logic.state.current_dir == f"{os.path.normpath(archive)}|/"
        names = {e.name for e in listings[-1]}
        assert "docs" in names
        assert "root.txt" in names

    def test_enters_archive_inner_directory(self, tmp_path):
        archive = _zip_with_nested_docs(tmp_path)
        logic, listings, errors, _ = _make_logic(str(tmp_path))
        logic.navigate_to(f"{archive}|/docs")

        assert errors == []
        assert logic.state.current_dir == f"{os.path.normpath(archive)}|/docs"
        names = {e.name: e for e in listings[-1]}
        assert "readme.txt" in names
        assert "nested" in names
        assert names["nested"].is_dir
        assert not names["readme.txt"].is_dir

    def test_relative_archive_path(self, tmp_path):
        _zip_with_nested_docs(tmp_path)
        logic, listings, errors, _ = _make_logic(str(tmp_path))
        logic.navigate_to("sample.zip|/")

        assert errors == []
        assert logic.state.current_dir.endswith("sample.zip|/")
        assert any(e.name == "docs" for e in listings[-1])

    def test_missing_archive_keeps_current_and_reports(self, tmp_path):
        missing = str(tmp_path / "gone.zip")
        logic, listings, errors, path_inputs = _make_logic(str(tmp_path))
        logic.navigate_to(f"{missing}|/")

        assert logic.state.current_dir == str(tmp_path)
        assert errors and errors[-1][0] == "Path not found"
        assert "gone.zip" in errors[-1][1]
        assert path_inputs[-1] == str(tmp_path)
        assert listings == []


class TestGoUp:
    def test_local_parent(self, tmp_path):
        sub = tmp_path / "child"
        sub.mkdir()
        logic, _listings, errors, _ = _make_logic(str(sub))
        logic.go_up()

        assert errors == []
        assert logic.state.current_dir == os.path.normpath(str(tmp_path))

    def test_from_archive_inner_to_parent_member(self, tmp_path):
        archive = _zip_with_nested_docs(tmp_path)
        logic, listings, errors, _ = _make_logic(str(tmp_path))
        logic.navigate_to(f"{archive}|/docs/nested")
        logic.go_up()

        assert errors == []
        assert logic.state.current_dir == f"{os.path.normpath(archive)}|/docs"
        assert any(e.name == "readme.txt" for e in listings[-1])

    def test_from_archive_subdir_to_archive_root(self, tmp_path):
        archive = _zip_with_nested_docs(tmp_path)
        logic, listings, errors, _ = _make_logic(str(tmp_path))
        logic.navigate_to(f"{archive}|/docs")
        logic.go_up()

        assert errors == []
        assert logic.state.current_dir == f"{os.path.normpath(archive)}|/"
        names = {e.name for e in listings[-1]}
        assert "docs" in names
        assert "root.txt" in names

    def test_from_archive_root_to_containing_folder(self, tmp_path):
        archive = _zip_with_nested_docs(tmp_path)
        logic, listings, errors, _ = _make_logic(str(tmp_path))
        logic.navigate_to(f"{archive}|/")
        logic.go_up()

        assert errors == []
        assert logic.state.current_dir == os.path.normpath(str(tmp_path))
        assert any(e.name == "sample.zip" for e in listings[-1])


class TestGoBack:
    def test_returns_to_previous_local_dir(self, tmp_path):
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.mkdir()
        b.mkdir()

        logic, _listings, errors, _ = _make_logic(str(tmp_path))
        logic.navigate_to(str(a))
        logic.navigate_to(str(b))
        logic.go_back()

        assert errors == []
        assert logic.state.current_dir == os.path.normpath(str(a))

    def test_returns_from_archive_to_folder(self, tmp_path):
        archive = _zip_with_nested_docs(tmp_path)
        logic, _listings, errors, _ = _make_logic(str(tmp_path))
        logic.navigate_to(f"{archive}|/")
        logic.go_back()

        assert errors == []
        assert logic.state.current_dir == os.path.normpath(str(tmp_path))
