"""GUI-free DialogLogic navigation tests (local dirs and archive virtual paths)."""

from __future__ import annotations

import os
import zipfile
from unittest.mock import patch

import pytest

from dpg_navigator._filesystem import INDEX_TTL, MAX_SCAN_DEPTH, is_archive_virtual_path
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
        refresh_ui_cb=lambda entries, gen=None: listings.append(list(entries)),
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

    def test_pipe_in_local_name_is_not_archive_route(self, tmp_path):
        missing = tmp_path / "notes|draft"
        logic, listings, errors, path_inputs = _make_logic(str(tmp_path))
        logic.navigate_to(str(missing))

        assert logic.state.current_dir == str(tmp_path)
        assert errors and errors[-1][0] == "Path not found"
        assert "archive" not in errors[-1][1].lower()
        assert path_inputs[-1] == str(tmp_path)
        assert listings == []

    @pytest.mark.skipif(os.name == "nt", reason="| is not a legal Windows filename")
    def test_pipe_in_dirname_lists_as_local(self, tmp_path):
        folder = tmp_path / "has|pipe"
        folder.mkdir()
        (folder / "a.txt").write_text("x")
        logic, listings, errors, _ = _make_logic(str(tmp_path))
        logic.navigate_to(str(folder))
        assert errors == []
        assert logic.state.current_dir == os.path.normpath(str(folder))
        assert any(e.name == "a.txt" for e in listings[-1])


class TestArchiveVirtualPathHelper:
    def test_requires_zip_or_7z_extension(self):
        assert not is_archive_virtual_path(r"C:\data\notes|v1")
        assert is_archive_virtual_path(r"C:\data\pack.zip|/inner")
        assert is_archive_virtual_path("/tmp/pack.7z|/docs")
        assert not is_archive_virtual_path("/tmp/pack.zip")


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

    def test_relative_sibling_archive_from_inside_archive(self, tmp_path):
        first = _zip_with_nested_docs(tmp_path)
        other = tmp_path / "other.zip"
        with zipfile.ZipFile(other, "w") as zf:
            zf.writestr("only.txt", "x")
        logic, listings, errors, _ = _make_logic(str(tmp_path))
        logic.navigate_to(f"{first}|/docs")
        logic.navigate_to("other.zip|/")

        assert errors == []
        assert logic.state.current_dir.endswith("other.zip|/")
        assert any(e.name == "only.txt" for e in listings[-1])

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


def _run_now(fn, *args, **kwargs):
    fn(*args, **kwargs)


class TestDeepSearchAfterIndexBuild:
    """A query typed while the index builds is replayed once it is ready."""

    def _tree(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "needle.txt").write_text("x")
        return tmp_path

    def test_pending_query_runs_deep_search_when_build_finishes(self, tmp_path):
        root = str(self._tree(tmp_path))
        logic, listings, _errors, _ = _make_logic(root)
        logic.config.search_subfolders = True
        logic.state.search_query = "needle"

        with patch("dpg_navigator.dialog._logic.JobManager.submit", side_effect=_run_now):
            logic.start_index_build()

        assert listings, "deep search did not refresh the UI"
        names = [entry.name for entry in listings[-1]]
        assert "\0deep_sep" in names
        assert "needle.txt" in names

    def test_no_replay_without_query(self, tmp_path):
        root = str(self._tree(tmp_path))
        logic, listings, _errors, _ = _make_logic(root)
        logic.config.search_subfolders = True

        with patch("dpg_navigator.dialog._logic.JobManager.submit", side_effect=_run_now):
            logic.start_index_build()

        assert listings == []
        assert logic._dir_index.ready

    def test_no_replay_after_navigating_elsewhere(self, tmp_path):
        root = str(self._tree(tmp_path))
        logic, listings, _errors, _ = _make_logic(root)
        logic.config.search_subfolders = True
        logic.state.search_query = "needle"
        queued = []

        with patch("dpg_navigator.dialog._logic.JobManager.submit", side_effect=queued.append):
            logic.start_index_build()
        logic.state.current_dir = str(tmp_path / "sub")
        queued[0]()

        assert listings == []

    def test_no_replay_when_generation_changed(self, tmp_path):
        root = str(self._tree(tmp_path))
        logic, listings, _errors, _ = _make_logic(root)
        logic.config.search_subfolders = True
        logic.state.search_query = "needle"
        queued = []

        with patch("dpg_navigator.dialog._logic.JobManager.submit", side_effect=queued.append):
            logic.start_index_build()
        logic.state.index_generation += 1
        queued[0]()

        assert listings == []


class TestSearchSubfoldersStaleIndex:
    def test_stale_ready_index_is_rebuilt(self, tmp_path):
        logic, _listings, _errors, _ = _make_logic(str(tmp_path))
        with patch("dpg_navigator.dialog._logic.JobManager.submit", side_effect=_run_now):
            logic.start_index_build()
        assert logic._dir_index.ready
        logic._dir_index._built_at -= INDEX_TTL + 1

        with patch.object(logic, "start_index_build") as build:
            logic.set_search_subfolders(True)

        build.assert_called_once()

    def test_fresh_index_for_current_dir_is_reused(self, tmp_path):
        logic, _listings, _errors, _ = _make_logic(str(tmp_path))
        with patch("dpg_navigator.dialog._logic.JobManager.submit", side_effect=_run_now):
            logic.start_index_build()

        with patch.object(logic, "start_index_build") as build:
            logic.set_search_subfolders(True)

        build.assert_not_called()


class TestSizeComputationLowerBound:
    def test_truncated_scan_shows_lower_bound(self, tmp_path):
        deep = tmp_path / "deep"
        path = deep
        for level in range(MAX_SCAN_DEPTH + 1):
            path = path / f"l{level}"
            path.mkdir(parents=True)
            (path / "f.bin").write_bytes(b"x" * 1024)
        cells: list[tuple[str, str]] = []
        logic, _listings, _errors, _ = _make_logic(str(tmp_path))
        logic.update_size_cell = lambda p, text: cells.append((p, text))

        with patch("dpg_navigator.dialog._logic.JobManager.submit", side_effect=_run_now):
            logic.start_size_computation([str(deep)])

        assert cells == [(str(deep), ">= 2 KB")]
        assert str(deep) in logic.state.size_truncated
        assert logic.state.size_cache[str(deep)][0] == 2048

    def test_complete_scan_shows_plain_size(self, tmp_path):
        small = tmp_path / "small"
        small.mkdir()
        (small / "f.bin").write_bytes(b"x" * 1024)
        cells: list[tuple[str, str]] = []
        logic, _listings, _errors, _ = _make_logic(str(tmp_path))
        logic.update_size_cell = lambda p, text: cells.append((p, text))
        logic.state.size_truncated.add(str(small))

        with patch("dpg_navigator.dialog._logic.JobManager.submit", side_effect=_run_now):
            logic.start_size_computation([str(small)])

        assert cells == [(str(small), "1 KB")]
        assert str(small) not in logic.state.size_truncated


@pytest.mark.skipif(os.name == "nt", reason="'|' is not allowed in Windows file names")
class TestPipeInFolderBeforeArchive:
    def test_navigates_into_archive_below_pipe_folder(self, tmp_path):
        folder = tmp_path / "notes|v1"
        folder.mkdir()
        archive_path = _zip_with_nested_docs(folder)
        logic, listings, errors, _ = _make_logic(str(tmp_path))

        logic.navigate_to(f"{archive_path}|/docs")

        assert errors == []
        assert logic.state.current_dir == f"{archive_path}|/docs"
        assert {e.name for e in listings[-1]} == {"nested", "readme.txt"}

        logic.go_up()
        assert logic.state.current_dir == f"{archive_path}|/"
