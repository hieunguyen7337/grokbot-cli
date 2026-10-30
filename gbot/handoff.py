"""Browser handoff for CLI callers; callers map cancellation to exit 130."""

import sys
import webbrowser
from collections.abc import Callable
from threading import Event
from typing import TextIO

from gbot.output import terminal_safe
from gbot.service.handoff import HandoffResult, wait_until


def run_handoff(
    url: str,
    check: Callable[[], object],
    *,
    err: TextIO = sys.stderr,
    opener: Callable[[str], object] = webbrowser.open,
    timeout_s: float = 600.0,
    open_browser: bool = True,
) -> HandoffResult:
    cancel = Event()
    try:
        print("Open this link to continue:", file=err)
        print(terminal_safe(url), file=err, flush=True)
        if open_browser:
            try:
                opener(url)
            except Exception:  # noqa: BLE001 - the printed link is the fallback
                print("Could not open a browser; use the link above.", file=err)
        return wait_until(check, cancel=cancel, wake=None, timeout_s=timeout_s)
    except KeyboardInterrupt:
        cancel.set()
        return HandoffResult("cancelled")
