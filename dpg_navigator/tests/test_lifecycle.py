"""Lifecycle and concurrency tests exercising real background machinery.

These drive the actual thread-spawning and cancellation paths (DirectoryIndex
build, FileDialog background index) against a real temp filesystem, with
DearPyGui mocked only at the call boundary. They establish the thread-lifecycle
baseline for the JobManager work in docs/ROADMAP.md (P1 #1).
"""

from __future__ import annotations

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


from dpg_navigator.dialog._state import DialogState
from dpg_navigator.dialog._logic import DialogLogic

