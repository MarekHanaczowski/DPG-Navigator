"""Tests for the shared frame pump (``arm_frame_callback``).

DearPyGui keeps one callback per frame number and fires it only when that
frame starts. The fake below models both facts: a later registration for the
same frame replaces the earlier one, and a registration for a frame that has
already started is lost.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from dpg_navigator import _frame_callback
from dpg_navigator._dialog import FileDialog
from dpg_navigator._frame_callback import _LEADS, arm_frame_callback, reset_frame_callbacks
from dpg_navigator._html import HTMLRenderer


class _FakeDpg:
    """One callback slot per frame, like DearPyGui.

    ``jumps[i]`` frames pass during the i-th registration, the way the render
    thread keeps drawing while the callback thread registers.
    """

    def __init__(self, start: int = 10, jumps: list[int] | None = None) -> None:
        self.frame = start
        self._jumps = list(jumps or [])
        self.slots: dict[int, object] = {}
        self.registered: list[int] = []

    def get_frame_count(self) -> int:
        return self.frame

    def set_frame_callback(self, frame: int, callback: object) -> None:
        self.registered.append(frame)
        self.slots[frame] = callback
        if self._jumps:
            self.frame += self._jumps.pop(0)

    def render_frame(self) -> None:
        """Start the next frame and fire the callback registered for it."""
        self.frame += 1
        callback = self.slots.pop(self.frame, None)
        if callback is not None:
            callback()  # type: ignore[operator]


class TestRegistration:
    def test_registers_the_next_frame(self):
        dpg = _FakeDpg(start=10)

        assert arm_frame_callback(dpg, lambda: None) is True
        assert dpg.registered == [11]

    def test_retries_when_the_target_frame_already_started(self):
        """The render thread began frame 11 before the callback for 11 was
        registered, so that registration can never fire."""
        dpg = _FakeDpg(start=10, jumps=[1])

        assert arm_frame_callback(dpg, lambda: None) is True
        assert dpg.registered == [11, 12]

    def test_later_attempts_reach_further_ahead(self):
        dpg = _FakeDpg(start=0, jumps=[1, 1])

        assert arm_frame_callback(dpg, lambda: None) is True
        # Third attempt: frame is 2, lead is 2.
        assert dpg.registered == [1, 2, 4]

    def test_reports_failure_when_every_target_was_overtaken(self):
        dpg = _FakeDpg(start=0, jumps=[100] * len(_LEADS))

        assert arm_frame_callback(dpg, lambda: None) is False
        assert len(dpg.registered) == len(_LEADS)

    def test_a_failed_arming_is_retried_by_the_next_request(self):
        dpg = _FakeDpg(start=0, jumps=[100] * len(_LEADS))
        calls: list[str] = []
        arm_frame_callback(dpg, lambda: calls.append("first"))

        assert arm_frame_callback(dpg, lambda: calls.append("second")) is True
        dpg.render_frame()

        assert calls == ["first", "second"]


class TestSharedFrame:
    def test_two_polls_share_one_registration(self):
        """Registered separately, the second would replace the first in
        DearPyGui's single slot for that frame."""
        dpg = _FakeDpg()
        calls: list[str] = []

        arm_frame_callback(dpg, lambda: calls.append("dialog"))
        arm_frame_callback(dpg, lambda: calls.append("html"))
        dpg.render_frame()

        assert dpg.registered == [11]
        assert calls == ["dialog", "html"]

    def test_two_self_rearming_polls_both_keep_running(self):
        dpg = _FakeDpg()
        runs = {"dialog": 0, "html": 0}

        def dialog_poll() -> None:
            runs["dialog"] += 1
            arm_frame_callback(dpg, dialog_poll)

        def html_poll() -> None:
            runs["html"] += 1
            arm_frame_callback(dpg, html_poll)

        arm_frame_callback(dpg, dialog_poll)
        arm_frame_callback(dpg, html_poll)
        for _ in range(5):
            dpg.render_frame()

        assert runs == {"dialog": 5, "html": 5}

    def test_same_callback_requested_twice_runs_once(self):
        dpg = _FakeDpg()
        calls: list[int] = []

        def poll() -> None:
            calls.append(1)

        arm_frame_callback(dpg, poll)
        arm_frame_callback(dpg, poll)
        dpg.render_frame()

        assert calls == [1]

    def test_a_callback_runs_once_per_request(self):
        dpg = _FakeDpg()
        calls: list[int] = []
        arm_frame_callback(dpg, lambda: calls.append(1))

        for _ in range(3):
            dpg.render_frame()

        assert calls == [1]

    def test_a_failing_callback_does_not_stop_the_others(self):
        dpg = _FakeDpg()
        calls: list[str] = []

        def broken() -> None:
            raise RuntimeError("boom")

        arm_frame_callback(dpg, broken)
        arm_frame_callback(dpg, lambda: calls.append("ok"))
        dpg.render_frame()

        assert calls == ["ok"]

    def test_bound_classmethods_are_recognised_as_the_same_callback(self):
        """``cls.method`` builds a new bound-method object on every access."""
        dpg = _FakeDpg()

        arm_frame_callback(dpg, FileDialog._poll_sidebar_drives)
        arm_frame_callback(dpg, FileDialog._poll_sidebar_drives)

        assert len(_frame_callback._pending) == 1


class TestStaleRegistration:
    def test_a_passed_frame_is_not_trusted(self):
        """Another callback took the slot (the host application's own
        ``set_frame_callback``), so the dispatch never ran."""
        dpg = _FakeDpg(start=10)
        calls: list[int] = []
        arm_frame_callback(dpg, lambda: calls.append(1))
        dpg.slots.clear()  # overwritten by somebody else
        dpg.render_frame()
        dpg.render_frame()
        assert calls == []

        arm_frame_callback(dpg, lambda: calls.append(2))
        dpg.render_frame()

        assert calls == [1, 2]

    def test_a_restarted_frame_counter_is_not_trusted(self):
        """A new DearPyGui context counts frames from zero again."""
        old = _FakeDpg(start=5000)
        arm_frame_callback(old, lambda: None)
        new = _FakeDpg(start=3)

        assert arm_frame_callback(new, lambda: None) is True

        assert new.registered == [4]

    def test_reset_forgets_callbacks_and_the_armed_frame(self):
        dpg = _FakeDpg()
        calls: list[int] = []
        arm_frame_callback(dpg, lambda: calls.append(1))

        reset_frame_callbacks()
        dpg.render_frame()
        arm_frame_callback(dpg, lambda: calls.append(2))

        assert calls == []
        assert dpg.registered == [11, 12]

    def test_dearpygui_is_never_called_under_the_helpers_lock(self):
        """Every DearPyGui call takes DPG's mutex. A frame poll can hold that
        mutex and arm a callback while another thread arms one too, so the
        helper's lock must not be held across a DearPyGui call."""
        held: list[str] = []

        class _CheckingDpg(_FakeDpg):
            def get_frame_count(self) -> int:
                if _frame_callback._lock.locked():
                    held.append("get_frame_count")
                return super().get_frame_count()

            def set_frame_callback(self, frame: int, callback: object) -> None:
                if _frame_callback._lock.locked():
                    held.append("set_frame_callback")
                super().set_frame_callback(frame, callback)

        dpg = _CheckingDpg(jumps=[1])
        assert arm_frame_callback(dpg, lambda: None) is True
        assert arm_frame_callback(dpg, lambda: None) is True
        dpg.render_frame()
        assert held == []

    def test_a_failed_registration_does_not_forget_another_threads(self):
        """Arming outside the lock: a call that secured no frame must not
        clear a target that another call registered in the meantime."""
        dpg = _FakeDpg(start=10)

        def racing_register(fake):
            _frame_callback._target = 11  # another thread registered frame 11
            fake.slots[11] = _frame_callback._dispatch
            return None  # ...while this call's attempts were all overtaken

        with patch.object(_frame_callback, "_register", side_effect=racing_register):
            assert arm_frame_callback(dpg, lambda: None) is False
        assert _frame_callback._target == 11


class TestPollsUseTheSharedPump:
    """The dialog poll and the HTML preview poll must not register frames
    themselves: with one slot per frame, one of them would starve."""

    def teardown_method(self):
        FileDialog._sidebar_poll_armed = False
        FileDialog._sidebar_poll_targets = []
        HTMLRenderer._poll_armed = False
        HTMLRenderer._poll_targets.clear()

    def test_dialog_pump_is_armed_through_the_helper(self):
        FileDialog._sidebar_poll_armed = False
        FileDialog._sidebar_poll_targets = [MagicMock()]

        with (
            patch("dpg_navigator._dialog.dpg") as mock_dpg,
            patch("dpg_navigator._dialog.arm_frame_callback", return_value=True) as arm,
        ):
            FileDialog._ensure_ui_pump()

        arm.assert_called_once_with(mock_dpg, FileDialog._poll_sidebar_drives)
        assert FileDialog._sidebar_poll_armed is True

    def test_dialog_pump_stays_unarmed_when_no_frame_could_be_secured(self):
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

    def test_html_poll_and_dialog_pump_survive_each_other(self):
        """The reported bug: a Markdown preview stayed on "Rendering..."
        because the dialog pump re-registered the frame the HTML poll had
        just claimed."""
        dpg = _FakeDpg()
        dialog = MagicMock()
        dialog._destroyed = False
        dialog._has_pending_ui.return_value = True
        FileDialog._sidebar_poll_targets = [dialog]
        renderer = HTMLRenderer.__new__(HTMLRenderer)
        renderer._apply_pending = MagicMock()  # type: ignore[method-assign]
        renderer._poll_needed = MagicMock(return_value=True)  # type: ignore[method-assign]

        with patch("dpg_navigator._dialog.dpg", dpg), patch("dpg_navigator._html.dpg", dpg):
            dpg.mutex = MagicMock()  # type: ignore[attr-defined]
            FileDialog._ensure_ui_pump()
            renderer._arm_poll()  # the click handler starts a render
            FileDialog._ensure_ui_pump()  # the pump poll runs right after it
            for _ in range(4):
                dpg.render_frame()

        assert renderer._apply_pending.call_count == 4
        assert dialog._apply_pending_listing.call_count == 4
