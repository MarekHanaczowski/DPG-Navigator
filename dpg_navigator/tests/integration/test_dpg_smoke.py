"""Real-DearPyGui smoke tests (opt-in; see conftest for how to run).

These construct a genuine DPG context and viewport and drive the full
FileDialog lifecycle — construction, a few rendered frames, and teardown — to
verify the widget/texture/theme wiring the mocked unit tests cannot reach.

Not collected unless ``DPG_INTEGRATION=1`` because ``import dearpygui`` needs a
display/GPU.
"""

from __future__ import annotations

import threading
import time

import dearpygui.dearpygui as dpg
import pytest

from dpg_navigator import FileDialog

from .dpg_harness import pump

pytestmark = pytest.mark.integration


class TestDialogSmoke:
    def test_construct_render_destroy(self, dpg_viewport, tmp_path):
        (tmp_path / "a.txt").write_text("hello")
        (tmp_path / "sub").mkdir()

        before = set(threading.enumerate())

        dialog = FileDialog(default_path=str(tmp_path))
        dialog.show()
        pump()

        assert dpg.does_item_exist(dialog._config.tag)

        dialog.destroy()
        pump()

        assert not dpg.does_item_exist(dialog._config.tag)

        # Background workers spawned by the dialog should settle after destroy.
        deadline = time.time() + 5
        leaked = [t for t in threading.enumerate() if t not in before and t.is_alive()]
        while leaked and time.time() < deadline:
            time.sleep(0.1)
            leaked = [t for t in threading.enumerate() if t not in before and t.is_alive()]
        assert not leaked, f"leaked threads after destroy: {leaked}"

    def test_two_default_dialogs_get_distinct_tags(self, dpg_viewport, tmp_path):
        first = FileDialog(default_path=str(tmp_path))
        second = FileDialog(default_path=str(tmp_path))
        try:
            pump()
            assert first._config.tag != second._config.tag
        finally:
            first.destroy()
            second.destroy()
