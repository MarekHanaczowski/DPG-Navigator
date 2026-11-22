"""Arm a DearPyGui frame callback so that it cannot be silently missed."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

_LEADS = (1, 1, 2, 4, 16)
"""Frames to look ahead on each attempt; later attempts reach further."""


def arm_frame_callback(dpg: Any, callback: Callable[..., Any]) -> bool:
    """Schedule *callback* for an upcoming frame; False if none could be secured.

    ``dpg.set_frame_callback(n, ...)`` fires only at the moment frame *n*
    starts. The polls in this package re-arm themselves with
    ``get_frame_count() + 1`` from DearPyGui's callback thread while the
    render thread keeps drawing, so frame *n* can start between reading the
    count and registering the callback. A callback registered for a frame
    that has already started never fires, and a self-re-arming poll that
    misses once is dead for good.

    So the count is read again after registering. If it is still below the
    target, the registration got in first. Otherwise the callback may have
    been missed and a later frame is tried. A callback that did fire for the
    earlier target merely runs once more.

    *dpg* is the ``dearpygui.dearpygui`` module, passed in so the caller's
    own (possibly mocked) reference is the one used.
    """
    for lead in _LEADS:
        target = int(dpg.get_frame_count()) + lead
        dpg.set_frame_callback(target, callback)
        if int(dpg.get_frame_count()) < target:
            return True
    return False
