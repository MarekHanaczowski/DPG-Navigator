"""Gate for the real-DearPyGui integration tests.

Importing dearpygui requires a working display/GPU, so these modules are NOT
collected during a normal ``pytest`` run. They are collected only when
``DPG_INTEGRATION=1`` is set.

CI runs them under xvfb as a required job (``DPG_CHROME_NO_SANDBOX=1``,
``DPG_CHROME_BIN`` = chrome-headless-shell). Locally::

    DPG_INTEGRATION=1 pytest -m integration
    xvfb-run -a env DPG_INTEGRATION=1 pytest -m integration
"""

from __future__ import annotations

import os

import pytest

if os.environ.get("DPG_INTEGRATION") != "1":
    collect_ignore_glob = ["test_*.py"]


@pytest.fixture(scope="session")
def _dpg_context():
    """One DPG context and viewport for the whole integration run.

    Creating a second context in the same process and rendering frames in it
    segfaults under xvfb with software GL (reproduced with bare DearPyGui 2.3.1
    on Linux: one create/destroy cycle is fine, a second one crashes). Each test
    therefore reuses this context and only tears down the dialogs it created.

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


@pytest.fixture
def dpg_viewport(_dpg_context):
    """The session-wide DPG context and viewport (see ``_dpg_context``)."""
    yield
