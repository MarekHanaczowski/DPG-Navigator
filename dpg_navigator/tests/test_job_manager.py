"""Tests for the bounded JobManager worker pool."""

from __future__ import annotations

import logging
import threading
import time
from unittest.mock import patch

import pytest

import dpg_navigator._job_manager as jobmod
from dpg_navigator._job_manager import JobManager


@pytest.fixture(autouse=True)
def _reset_pool():
    JobManager.shutdown(wait=True, timeout=2.0)
    yield
    JobManager.shutdown(wait=True, timeout=2.0)


def _join_workers(timeout: float = 2.0) -> None:
    deadline = time.time() + timeout
    for thread in list(threading.enumerate()):
        if thread.name.startswith("dpg_nav_worker") and thread.is_alive():
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            thread.join(remaining)


class TestJobManagerPool:
    def test_submit_returns_result(self):
        future = JobManager.submit(lambda value: value + 1, 3)
        assert future.result(timeout=2) == 4

    def test_submit_propagates_exception(self):
        future = JobManager.submit(lambda: 1 / 0)
        with pytest.raises(ZeroDivisionError):
            future.result(timeout=2)

    def test_worker_count_is_capped(self):
        current: set[int] = set()
        lock = threading.Lock()
        max_seen = [0]
        release = threading.Event()

        def work() -> None:
            ident = threading.get_ident()
            with lock:
                current.add(ident)
                max_seen[0] = max(max_seen[0], len(current))
            release.wait(timeout=2)
            with lock:
                current.discard(ident)

        with patch.object(jobmod, "_MAX_WORKERS", 2):
            JobManager.shutdown(wait=True, timeout=2.0)
            futures = [JobManager.submit(work) for _ in range(6)]
            deadline = time.time() + 1.0
            while time.time() < deadline and max_seen[0] < 2:
                time.sleep(0.01)
            assert 1 <= max_seen[0] <= 2
            release.set()
            for future in futures:
                future.result(timeout=2)

    def test_submit_is_rejected_during_shutdown(self):
        started = threading.Event()
        release = threading.Event()

        def blocker() -> None:
            started.set()
            release.wait(timeout=2)

        with patch.object(jobmod, "_MAX_WORKERS", 1):
            JobManager.shutdown(wait=True, timeout=2.0)
            JobManager.submit(blocker)
            assert started.wait(timeout=2)
            JobManager._shutting_down = True
            rejected = JobManager.submit(lambda: "no")
            assert rejected.cancelled()
            JobManager._shutting_down = False
            release.set()
            _join_workers()

    def test_submit_works_after_shutdown(self):
        JobManager.submit(lambda: None).result(timeout=2)
        JobManager.shutdown(wait=True, timeout=2.0)
        assert JobManager.submit(lambda: "ok").result(timeout=2) == "ok"

    def test_cancelled_queued_job_does_not_run(self):
        started = threading.Event()
        release = threading.Event()
        ran_second = threading.Event()

        def blocker() -> None:
            started.set()
            release.wait(timeout=2)

        def second() -> None:
            ran_second.set()

        with patch.object(jobmod, "_MAX_WORKERS", 1):
            JobManager.shutdown(wait=True, timeout=2.0)
            JobManager.submit(blocker)
            assert started.wait(timeout=2)
            queued = JobManager.submit(second)
            assert queued.cancel()
            release.set()
            deadline = time.time() + 1.0
            while time.time() < deadline and not ran_second.is_set():
                time.sleep(0.01)
            assert queued.cancelled()
            assert not ran_second.is_set()
            _join_workers()

    def test_shutdown_cancels_queued_work(self):
        started = threading.Event()
        release = threading.Event()
        ran_second = threading.Event()

        def blocker() -> None:
            started.set()
            release.wait(timeout=2)

        def second() -> None:
            ran_second.set()

        with patch.object(jobmod, "_MAX_WORKERS", 1):
            JobManager.shutdown(wait=True, timeout=2.0)
            JobManager.submit(blocker)
            assert started.wait(timeout=2)
            queued = JobManager.submit(second)
            JobManager.shutdown(wait=False)
            assert queued.cancelled()
            assert not ran_second.is_set()
            release.set()
            _join_workers()

    def test_shutdown_logs_when_join_times_out(self, caplog):
        started = threading.Event()
        release = threading.Event()

        def blocker() -> None:
            started.set()
            release.wait(timeout=5)

        with patch.object(jobmod, "_MAX_WORKERS", 1):
            JobManager.shutdown(wait=True, timeout=2.0)
            JobManager.submit(blocker)
            assert started.wait(timeout=2)
            with caplog.at_level(logging.WARNING, logger="dpg_navigator._job_manager"):
                JobManager.shutdown(wait=True, timeout=0.05)
            assert any("timed out" in rec.message for rec in caplog.records)
            release.set()
            _join_workers()
