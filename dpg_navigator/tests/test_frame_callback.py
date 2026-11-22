"""Tests for ``arm_frame_callback``: a frame callback must not be lost.

``dpg.set_frame_callback(n, ...)`` only fires when frame *n* starts. The
fake below moves the frame count the way the render thread does while a
poll is re-arming itself on the callback thread.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from dpg_navigator._dialog import FileDialog
from dpg_navigator._frame_callback import _LEADS, arm_frame_callback


class _FakeDpg:
    """Frame counter that jumps by ``jumps[i]`` during the i-th registration."""

    def __init__(self, start: int, jumps: list[int]) -> None:
        self.frame = start
        self._jumps = list(jumps)
        self.registered: list[int] = []

    def get_frame_count(self) -> int:
        return self.frame

    def set_frame_callback(self, frame: int, callback: object) -> None:
        self.registered.append(frame)
        if self._jumps:
            self.frame += self._jumps.pop(0)


def _callback() -> None:
    pass


class TestArmFrameCallback:
    def test_registers_the_next_frame(self):
        dpg = _FakeDpg(start=10, jumps=[0])

        assert arm_frame_callback(dpg, _callback) is True
        assert dpg.registered == [11]

    def test_retries_when_the_target_frame_already_started(self):
        """The render thread began frame 11 before the callback for 11 was
        registered, so that registration can never fire."""
        dpg = _FakeDpg(start=10, jumps=[1, 0])

        assert arm_frame_callback(dpg, _callback) is True
        assert dpg.registered == [11, 12]

    def test_later_attempts_reach_further_ahead(self):
        dpg = _FakeDpg(start=0, jumps=[1, 1, 0])

        assert arm_frame_callback(dpg, _callback) is True
        # Third attempt: frame is 2, lead is 2.
        assert dpg.registered == [1, 2, 4]

    def test_reports_failure_when_every_target_was_overtaken(self):
        dpg = _FakeDpg(start=0, jumps=[100] * len(_LEADS))

        assert arm_frame_callback(dpg, _callback) is False
        assert len(dpg.registered) == len(_LEADS)

    def test_passes_the_callback_through(self):
        calls: list[object] = []

        class _Recorder(_FakeDpg):
            def set_frame_callback(self, frame: int, callback: object) -> None:
                calls.append(callback)
                super().set_frame_callback(frame, callback)

        arm_frame_callback(_Recorder(start=3, jumps=[0]), _callback)

        assert calls == [_callback]


class TestDialogPumpArming:
    """``FileDialog``'s frame poll arms itself through the checked helper."""

    def teardown_method(self):
        FileDialog._sidebar_poll_armed = False
        FileDialog._sidebar_poll_targets = []

    def test_pump_is_armed_through_the_helper(self):
        FileDialog._sidebar_poll_armed = False
        FileDialog._sidebar_poll_targets = [MagicMock()]

        with (
            patch("dpg_navigator._dialog.dpg") as mock_dpg,
            patch("dpg_navigator._dialog.arm_frame_callback", return_value=True) as arm,
        ):
            FileDialog._ensure_ui_pump()

        arm.assert_called_once_with(mock_dpg, FileDialog._poll_sidebar_drives)
        assert FileDialog._sidebar_poll_armed is True

    def test_pump_stays_unarmed_when_no_frame_could_be_secured(self):
        """Otherwise the flag would claim a poll is coming and nobody would
        ever arm it again."""
        FileDialog._sidebar_poll_armed = False
        FileDialog._sidebar_poll_targets = [MagicMock()]

        with (
            patch("dpg_navigator._dialog.dpg"),
            patch("dpg_navigator._dialog.arm_frame_callback", return_value=False) as arm,
        ):
            FileDialog._ensure_ui_pump()

        arm.assert_called_once()
        assert FileDialog._sidebar_poll_armed is False
