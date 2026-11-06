"""Run a function on the Qt (main) thread from a worker thread.

Used on macOS, where keyboard-layout (TIS) calls are only allowed on the main thread.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

from PySide6.QtCore import QObject, Qt, Signal


class MainThreadRunner(QObject):
    """Create on the main thread. ``call`` waits for the result; ``post`` does not."""

    _request = Signal(object)

    def __init__(self, timeout_s: float = 3.0):
        super().__init__()
        self.timeout_s = timeout_s
        self._request.connect(self._run, Qt.ConnectionType.QueuedConnection)

    def _run(self, job) -> None:
        fn, box, done = job
        try:
            box["result"] = fn()
        except BaseException as e:  # noqa: BLE001 - handed to the waiting thread
            box["error"] = e
        finally:
            if done is not None:
                done.set()

    def call(self, fn: Callable[[], Any]) -> Any:
        if threading.current_thread() is threading.main_thread():
            return fn()
        box: dict = {}
        done = threading.Event()
        self._request.emit((fn, box, done))
        if not done.wait(self.timeout_s):
            raise TimeoutError("the main thread did not respond")
        if "error" in box:
            raise box["error"]
        return box.get("result")

    def post(self, fn: Callable[[], Any]) -> None:
        if threading.current_thread() is threading.main_thread():
            fn()
        else:
            self._request.emit((fn, {}, None))
