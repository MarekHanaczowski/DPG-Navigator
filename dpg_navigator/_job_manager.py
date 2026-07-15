"""JobManager for handling background threads and timers.

Provides a centralized manager for background tasks, using short-lived
daemon threads that terminate after a single task. This avoids long-lived
worker threads that outlive the work they perform, while still giving a
convenient `submit`/`Future` API.

Also provides a dedicated Timer loop that avoids spawning OS threads for
every scheduled timer, heavily reducing thread-churn during debouncing.
"""

from __future__ import annotations
import threading
import time
import heapq
from concurrent.futures import Future

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

class JobManager:
    """Centralized manager for background threads and timers."""

    _threads: set[threading.Thread] = set()
    _lock: threading.Lock = threading.Lock()

    # Timer Loop state
    _timer_queue: list[TimerTask] = []
    _timer_cond: threading.Condition = threading.Condition()
    _timer_thread: threading.Thread | None = None
    _shutdown_flag: bool = False

    @classmethod
    def submit(cls, fn, *args, **kwargs):
        """Submit a task to run in a background daemon thread."""
        future = Future()

        def _run():
            # If the future was cancelled before the thread started, bail out.
            if not future.set_running_or_notify_cancel():
                return
            try:
                result = fn(*args, **kwargs)
                future.set_result(result)
            except Exception as exc:
                future.set_exception(exc)
            finally:
                with cls._lock:
                    cls._threads.discard(t)

        t = threading.Thread(target=_run, name="dpg_nav_worker", daemon=True)
        with cls._lock:
            cls._threads.add(t)
        t.start()
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
                cls._timer_thread = threading.Thread(target=cls._timer_worker, name="dpg_nav_timer", daemon=True)
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
    def shutdown(cls, wait: bool = True, timeout: float = 2.0) -> None:
        """Cancel all pending timers and optionally wait for running threads."""
        # Stop the timer loop
        with cls._timer_cond:
            for task in cls._timer_queue:
                task.cancel()
            cls._timer_queue.clear()
            cls._shutdown_flag = True
            cls._timer_cond.notify_all()

        if cls._timer_thread is not None and cls._timer_thread.is_alive():
            # Wait a tiny bit for timer thread to die
            cls._timer_thread.join(timeout=0.2)

        # Handle active worker threads
        with cls._lock:
            threads = list(cls._threads)

        if wait:
            deadline = time.time() + timeout
            for t in threads:
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                t.join(remaining)
