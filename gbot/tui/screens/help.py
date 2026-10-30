from collections.abc import Sequence
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static


class HelpScreen(ModalScreen[None]):
    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape", "dismiss", "Close")]

    def __init__(self, bindings: Sequence[Binding]) -> None:
        super().__init__()
        self.bindings = bindings

    def compose(self) -> ComposeResult:
        with Vertical(id="help"):
            yield Static("Keyboard help (escape closes)", id="help-title")
            with VerticalScroll(id="help-bindings"):
                for binding in self.bindings:
                    yield Static(
                        f"{binding.key:24} {binding.description}", markup=False
                    )
