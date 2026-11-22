"""One shared DearPyGui frame callback for every poll in the package.

DearPyGui keeps a single callback per frame number: a second
``dpg.set_frame_callback(n, ...)`` replaces the first. Two polls that each
re-arm themselves for "the next frame" therefore cannot coexist. Whichever
registers last wins the frame, and the other one, which only re-arms from
inside its own callback, is never called again.

Polls ask for a frame through :func:`arm_frame_callback` instead. All
requests for the same frame share one registration, owned by this module.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

_log = logging.getLogger(__name__)

_LEADS = (1, 1, 2, 4, 16)
"""Frames to look ahead on each attempt; later attempts reach further."""

_lock = threading.Lock()
_pending: list[Callable[[], Any]] = []
_target: int | None = None
"""Frame the shared dispatch is registered for; ``None`` when not armed."""


def arm_frame_callback(dpg: Any, callback: Callable[[], Any]) -> bool:
    """Call *callback* once on an upcoming frame; False if none was secured.

    Must run on a DearPyGui thread. Asking again for a callback that is
    already waiting changes nothing. When False is returned the callback
    stays queued and the next request, from any poll, arms the dispatch.

    *dpg* is the ``dearpygui.dearpygui`` module, passed in so the caller's
    own (possibly mocked) reference is the one used.
    """
    global _target
    with _lock:
        if callback not in _pending:
            _pending.append(callback)
        frame = int(dpg.get_frame_count())
        # A registration is trusted only while its frame is still ahead and
        # near: a passed frame has been dispatched (or lost), and a far one
        # belongs to a DearPyGui context that no longer exists.
        if _target is not None and frame < _target <= frame + max(_LEADS):
            return True
        _target = _register(dpg)
        return _target is not None


def _register(dpg: Any) -> int | None:
    """Register the shared dispatch for an upcoming frame and return it.

    ``set_frame_callback(n, ...)`` fires only at the moment frame *n* starts.
    This runs on DearPyGui's callback thread while the render thread keeps
    drawing, so frame *n* can start between reading the count and
    registering, and a callback registered for a started frame never fires.

    So the count is read again after registering. Still below the target
    means the registration got in first; otherwise a later frame is tried,
    further ahead each time. A dispatch that did fire for the earlier target
    merely runs once more.
    """
    for lead in _LEADS:
        target = int(dpg.get_frame_count()) + lead
        dpg.set_frame_callback(target, _dispatch)
        if int(dpg.get_frame_count()) < target:
            return target
    return None


def _dispatch(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Run every waiting callback; called by DearPyGui for the armed frame."""
    del sender, app_data, user_data
    with _lock:
        callbacks = list(_pending)
        _pending.clear()
    for callback in callbacks:
        try:
            callback()
        except Exception:
            _log.exception("Frame callback failed: %r", callback)


def reset_frame_callbacks() -> None:
    """Forget waiting callbacks and the armed frame (last dialog destroyed)."""
    global _target
    with _lock:
        _pending.clear()
        _target = None
