"""Gate for the real-DearPyGui integration tests.

Importing dearpygui requires a working display/GPU, so these modules are NOT
collected during a normal ``pytest`` run (which would otherwise import a real
Chrome/OpenGL stack and can crash in headless/sandboxed environments). They are
collected only when ``DPG_INTEGRATION=1`` is set.

Run them with a display, e.g.::

    DPG_INTEGRATION=1 pytest -m integration
    # headless Linux:
    xvfb-run -a env DPG_INTEGRATION=1 pytest -m integration
"""

from __future__ import annotations

import os

import pytest

if os.environ.get("DPG_INTEGRATION") != "1":
    collect_ignore_glob = ["test_*.py"]


@pytest.fixture
def dpg_viewport():
    """A DPG context + viewport, torn down after the test.

    dearpygui is imported inside the fixture so collecting this module without
    ``DPG_INTEGRATION=1`` cannot pull in OpenGL.
    """
    import dearpygui.dearpygui as dpg

    dpg.create_context()
    dpg.create_viewport(title="dpg-navigator-integration", width=1000, height=700)
    dpg.setup_dearpygui()
    dpg.show_viewport()
    try:
        yield
    finally:
        dpg.destroy_context()
