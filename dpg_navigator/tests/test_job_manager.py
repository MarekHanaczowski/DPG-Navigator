"""Tests for the bounded JobManager worker pool."""

from __future__ import annotations

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

    def test_submit_works_after_shutdown(self):
        JobManager.submit(lambda: None).result(timeout=2)
        JobManager.shutdown(wait=True, timeout=2.0)
        assert JobManager.submit(lambda: "ok").result(timeout=2) == "ok"
