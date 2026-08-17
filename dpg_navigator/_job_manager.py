"""JobManager for handling background threads and timers.

Worker tasks run on a bounded pool of daemon threads so a burst of
index/size/preview jobs cannot spawn one OS thread per task. Timers share
one min-heap loop and dispatch into the same pool.
"""

from __future__ import annotations

import heapq
import logging
import queue
import threading
import time
from typing import Any
from concurrent.futures import Future

_log = logging.getLogger(__name__)

_MAX_WORKERS = 8


class TimerTask:
    """Represents a scheduled timer task."""
    def __init__(self, execute_at: float, fn, args: tuple, kwargs: dict):
        self.execute_at = execute_at
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.cancelled = False

    def cancel(self):
        """Cancel this timer so it won't execute."""
        self.cancelled = True

    def __lt__(self, other):
        # For heapq sorting based on execution time
        return self.execute_at < other.execute_at


class _Stop:
    """Sentinel that tells one worker of a given pool generation to exit."""

    def __init__(self, generation: int) -> None:
        self.generation = generation


class JobManager:
    """Centralized manager for background threads and timers."""

    _lock: threading.Lock = threading.Lock()
    _work_queue: queue.Queue[Any] = queue.Queue()
    _workers: list[threading.Thread] = []
    _pool_generation: int = 0

    # Timer Loop state
    _timer_queue: list[TimerTask] = []
    _timer_cond: threading.Condition = threading.Condition()
    _timer_thread: threading.Thread | None = None
    _shutdown_flag: bool = False

    @classmethod
    def _ensure_pool(cls) -> None:
        """Start idle daemon workers if the pool is empty."""
        with cls._lock:
            cls._workers = [t for t in cls._workers if t.is_alive()]
            if cls._workers:
                return
            generation = cls._pool_generation
            for index in range(_MAX_WORKERS):
                worker = threading.Thread(
                    target=cls._worker,
                    args=(generation,),
                    name=f"dpg_nav_worker-{index}",
                    daemon=True,
                )
                cls._workers.append(worker)
                worker.start()

    @classmethod
    def _worker(cls, generation: int) -> None:
        while True:
            item = cls._work_queue.get()
            if isinstance(item, _Stop):
                if item.generation == generation:
                    return
                continue
            future, fn, args, kwargs = item
            if not future.set_running_or_notify_cancel():
                continue
            try:
                future.set_result(fn(*args, **kwargs))
            except Exception as exc:
                future.set_exception(exc)

    @classmethod
    def submit(cls, fn, *args, **kwargs):
        """Submit a task to the bounded worker pool."""
        future: Future[Any] = Future()
        cls._ensure_pool()
        cls._work_queue.put((future, fn, args, kwargs))
        return future

    @classmethod
    def _timer_worker(cls):
        """Dedicated background loop that processes timers from the min-heap."""
        while True:
            with cls._timer_cond:
                while not cls._timer_queue and not cls._shutdown_flag:
                    cls._timer_cond.wait()

                if cls._shutdown_flag:
                    break

                now = time.time()
                next_task = cls._timer_queue[0]

                if next_task.execute_at <= now:
                    heapq.heappop(cls._timer_queue)
                    if not next_task.cancelled:
                        # Dispatch work to the thread manager rather than blocking timer loop
                        cls.submit(next_task.fn, *next_task.args, **next_task.kwargs)
                else:
                    # Wait until the next timer expires, or a new timer wakes us up
                    cls._timer_cond.wait(next_task.execute_at - now)

    @classmethod
    def schedule_timer(cls, interval: float, fn, args=None, kwargs=None) -> TimerTask:
        """Schedule a function to run after a delay, tracking the timer."""
        task = TimerTask(time.time() + interval, fn, args or (), kwargs or {})

        with cls._timer_cond:
            heapq.heappush(cls._timer_queue, task)

            # Start the loop if not running
            if cls._timer_thread is None or not cls._timer_thread.is_alive():
                cls._shutdown_flag = False
                cls._timer_thread = threading.Thread(
                    target=cls._timer_worker, name="dpg_nav_timer", daemon=True,
                )
                cls._timer_thread.start()

            cls._timer_cond.notify()

        return task

    @classmethod
    def cancel_timer(cls, timer: TimerTask | None) -> None:
        """Cancel a scheduled timer and remove it from tracking."""
        if timer is not None:
            timer.cancel()
            # We don't need to aggressively remove it from the heap;
            # the loop will discard it when its time comes if cancelled is True.

    @classmethod
    def _cancel_queued_work(cls) -> None:
        """Cancel jobs still waiting in the queue so workers never start them.

        Stop sentinels are put back: a leftover worker from a timed-out
        shutdown still needs its matching ``_Stop`` to exit.
        """
        orphaned_stops: list[_Stop] = []
        while True:
            try:
                item = cls._work_queue.get_nowait()
            except queue.Empty:
                break
            if isinstance(item, _Stop):
                orphaned_stops.append(item)
                continue
            future = item[0]
            future.cancel()
        for stop in orphaned_stops:
            cls._work_queue.put(stop)

    @classmethod
    def shutdown(cls, wait: bool = True, timeout: float = 2.0) -> None:
        """Cancel pending timers and stop the worker pool.

        Queued (not yet started) jobs are cancelled so they never run.
        In-flight work is left to finish; ``wait`` joins workers up to
        ``timeout`` and logs a warning if any are still alive.
        """
        with cls._timer_cond:
            for task in cls._timer_queue:
                task.cancel()
            cls._timer_queue.clear()
            cls._shutdown_flag = True
            cls._timer_cond.notify_all()

        if cls._timer_thread is not None and cls._timer_thread.is_alive():
            cls._timer_thread.join(timeout=0.2)

        with cls._lock:
            generation = cls._pool_generation
            cls._pool_generation += 1
            workers = list(cls._workers)
            cls._workers = []

        cls._cancel_queued_work()
        for _ in workers:
            cls._work_queue.put(_Stop(generation))

        if wait:
            deadline = time.time() + timeout
            for worker in workers:
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                worker.join(remaining)
            leftover = sum(1 for worker in workers if worker.is_alive())
            if leftover:
                _log.warning(
                    "JobManager.shutdown timed out with %s worker(s) still running",
                    leftover,
                )
