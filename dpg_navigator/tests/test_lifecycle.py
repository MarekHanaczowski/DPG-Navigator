"""Lifecycle and concurrency tests exercising real background machinery.

These drive the actual thread-spawning and cancellation paths (DirectoryIndex
build, FileDialog background index) against a real temp filesystem, with
DearPyGui mocked only at the call boundary. They establish the thread-lifecycle
baseline for the JobManager work in docs/ROADMAP.md (P1 #1).
"""

import threading
import time
from unittest.mock import MagicMock, patch

from dpg_navigator._dialog import FileDialog
from dpg_navigator._filesystem import DirectoryIndex


def _wait(predicate, timeout=5.0, interval=0.02):
    """Poll *predicate* until true or *timeout* elapses; return its final value."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


class TestDirectoryIndexCancellation:
    """The generation counter must abort an in-flight build."""

    def test_build_cancels_when_generation_changes(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "f.txt").write_text("x")

        idx = DirectoryIndex()
        # get_generation() != generation → _walk aborts immediately.
        idx.build(str(tmp_path), generation=0, get_generation=lambda: 1)

        assert not idx.ready
        assert idx.search("f") == []

    def test_build_completes_when_generation_matches(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "needle.txt").write_text("x")

        idx = DirectoryIndex()
        idx.build(str(tmp_path), generation=3, get_generation=lambda: 3)

        assert idx.ready
        assert [e.name for e in idx.search("needle")] == ["needle.txt"]


class TestBackgroundIndexLifecycle:
    """FileDialog's background index thread starts, settles, and cancels."""

    @staticmethod
    def _dialog(current_dir):
        dlg = FileDialog.__new__(FileDialog)
        dlg._current_dir = current_dir
        dlg._dir_index = DirectoryIndex()
        dlg._index_generation = 0
        dlg._bg_generation = 0
        dlg._search_debounce_timer = None
        dlg._config = MagicMock(show_hidden=False)
        return dlg

    def test_index_thread_settles_then_invalidates(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "report.txt").write_text("x")

        dlg = self._dialog(str(tmp_path))
        before = set(threading.enumerate())

        with patch("dpg_navigator._dialog.dpg"):
            dlg._start_index_build()

            assert _wait(lambda: dlg._dir_index.ready), "index never became ready"
            # The daemon build thread must terminate — no leak.
            leaked = _wait(
                lambda: not [
                    t for t in threading.enumerate()
                    if t not in before and t.is_alive()
                ]
            )
            assert leaked, "background index thread did not terminate"

            search_hit = [e.name for e in dlg._dir_index.search("report")]
            assert search_hit == ["report.txt"]

            # Teardown-style cancellation invalidates the index and bumps
            # both generation counters so any late worker is ignored.
            dlg._cancel_background_tasks()

        assert not dlg._dir_index.ready
        # _start_index_build bumped index gen 0->1, _cancel bumped 1->2.
        assert dlg._index_generation == 2
        assert dlg._bg_generation == 1

    def test_restart_supersedes_previous_generation(self, tmp_path):
        (tmp_path / "a.txt").write_text("x")

        dlg = self._dialog(str(tmp_path))
        with patch("dpg_navigator._dialog.dpg"):
            dlg._start_index_build()
            gen_after_first = dlg._index_generation
            dlg._start_index_build()

        assert dlg._index_generation == gen_after_first + 1
        assert _wait(lambda: dlg._dir_index.ready)
