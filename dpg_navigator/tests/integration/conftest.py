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

if os.environ.get("DPG_INTEGRATION") != "1":
    collect_ignore_glob = ["test_*.py"]
