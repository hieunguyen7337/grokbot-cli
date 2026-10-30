"""A cancellable browser step, completed by a caller-owned status check."""

import webbrowser
from collections.abc import Callable
from threading import Event
from typing import ClassVar

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

from gbot.output import terminal_safe
from gbot.service.handoff import HandoffResult, wait_until

WAITING = "Waiting… (o open again · c copy link · esc cancel)"


class HandoffScreen(ModalScreen[HandoffResult]):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", priority=True),
        Binding("o", "open", "Open again", priority=True),
        Binding("c", "copy", "Copy link", priority=True),
    ]
    DEFAULT_CSS = """
    HandoffScreen { align: center middle; background: $background 80%; }
    HandoffScreen > Vertical { width: 70; height: auto; max-height: 95%;
        border: round $accent; padding: 1 2; overflow-y: auto; }
    HandoffScreen Static { height: auto; margin-bottom: 1; }
    """

    def __init__(
        self,
        title: str,
        url: str,
        check: Callable[[], object],
        instruction: str = "Finish in your browser, then come back here.",
        timeout_s: float = 600.0,
        opener: Callable[[str], object] = webbrowser.open,
    ) -> None:
        super().__init__()
        self.heading, self.url, self.check = title, url, check
        self.instruction, self.timeout_s, self.opener = instruction, timeout_s, opener
        self.cancel = Event()
        self.wake = Event()
        self._waiting = False

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(Text(terminal_safe(self.heading)))
            yield Static(Text(terminal_safe(self.instruction)))
            yield Static(Text(terminal_safe(self.url), overflow="fold"))
            yield Static(WAITING, id="handoff-status", markup=False)

    def on_mount(self) -> None:
        self.action_open()

    def action_open(self) -> None:
        self._status(WAITING)
        try:
            opened = self.opener(self.url)
        except Exception:  # noqa: BLE001 - browser launch boundary
            opened = False
        if opened is False:
            self._status("Could not open a browser; copy the link instead.")
        if not self._waiting:
            self._waiting = True
            self._wait()

    def action_copy(self) -> None:
        self.app.copy_to_clipboard(self.url)
        self.app.notify("Link copied", markup=False)

    def action_cancel(self) -> None:
        self.cancel.set()
        self.wake.set()
        self.dismiss(HandoffResult("cancelled"))

    def on_unmount(self) -> None:
        self.cancel.set()
        self.wake.set()

    def poke(self) -> None:
        self.wake.set()

    def _status(self, text: str) -> None:
        self.query_one("#handoff-status", Static).update(Text(terminal_safe(text)))

    @work(thread=True, exit_on_error=False)
    def _wait(self) -> None:
        app = self.app
        try:
            result = wait_until(
                self.check,
                cancel=self.cancel,
                wake=self.wake,
                timeout_s=self.timeout_s,
            )
        except Exception as error:  # noqa: BLE001 - caller check boundary
            result = None
            message = terminal_safe(str(error))
        else:
            message = ""
        if not self.cancel.is_set():
            app.call_from_thread(self._finished, result, message)

    def _finished(self, result: HandoffResult | None, message: str) -> None:
        self._waiting = False
        if self.cancel.is_set() or not self.is_mounted:
            return
        if result is None:
            self._status(message)
        elif result.status == "timeout":
            self._status("Timed out waiting; press o to try again or esc to close.")
        else:
            self.dismiss(result)
