"""UI-free completion checks for browser handoffs."""

import time
from collections.abc import Callable
from dataclasses import dataclass
from threading import Event
from typing import Literal

# Each Event.wait is this short, so cancellation is seen without helper threads.
_WAIT_CAP_S = 0.05


@dataclass(frozen=True)
class HandoffResult:
    status: Literal["done", "cancelled", "timeout"]
    value: object = None


def wait_until(
    check: Callable[[], object],
    *,
    cancel: Event,
    wake: Event | None,
    timeout_s: float = 600.0,
    intervals: tuple[float, ...] = (1.0, 2.0, 3.0, 5.0),
    clock: Callable[[], float] = time.monotonic,
) -> HandoffResult:
    if not intervals or any(interval <= 0 for interval in intervals):
        raise ValueError("Intervals must be nonempty and positive")
    deadline = clock() + timeout_s
    index = 0
    while True:
        if cancel.is_set():
            return HandoffResult("cancelled")
        if index and clock() >= deadline:
            return HandoffResult("timeout")
        value = check()
        if cancel.is_set():
            return HandoffResult("cancelled")
        if value is not None:
            return HandoffResult("done", value)
        next_check = min(deadline, clock() + intervals[min(index, len(intervals) - 1)])
        index += 1
        while not cancel.is_set() and clock() < next_check:
            remaining = min(_WAIT_CAP_S, next_check - clock())
            if wake is None:
                cancel.wait(remaining)
            # Event has no wait-any operation, so callers that pass `wake` set it
            # whenever they set `cancel` (HandoffScreen does).
            elif wake.wait(remaining):
                wake.clear()
                break
