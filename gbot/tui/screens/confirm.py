"""Explicit, cancel-first confirmation for card answers."""

from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from gbot.output import terminal_safe


class ConfirmScreen(ModalScreen[bool]):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", priority=True)
    ]
    DEFAULT_CSS = """
    ConfirmScreen { align: center middle; background: $background 80%; }
    ConfirmScreen > Vertical { width: 70; height: auto; max-height: 95%;
        border: round $accent; padding: 1 2; }
    ConfirmScreen Static { height: auto; margin-bottom: 1; }
    ConfirmScreen Horizontal { height: auto; align-horizontal: right; }
    ConfirmScreen Button { margin-left: 1; }
    """

    def __init__(self, title: str, details: str, confirm_label: str) -> None:
        super().__init__()
        self.heading = title
        self.details = details
        self.confirm_label = confirm_label

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(Text(terminal_safe(self.heading)))
            yield Static(Text(terminal_safe(self.details)))
            with Horizontal():
                yield Button("Cancel", id="cancel")
                yield Button(Text(terminal_safe(self.confirm_label)), id="confirm")

    def on_mount(self) -> None:
        self.query_one("#cancel", Button).focus()

    def action_cancel(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(event.button.id == "confirm")
