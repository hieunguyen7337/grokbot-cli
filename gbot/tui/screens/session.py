from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.screen import Screen
from textual.widgets import Static


class SessionScreen(Screen):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "app.pop_screen", "Home")
    ]

    def __init__(self, bot_id: str, *, bot_name: str | None = None) -> None:
        super().__init__()
        self.bot_id = bot_id
        self.bot_name = bot_name or bot_id

    def compose(self) -> ComposeResult:
        yield Static(self.bot_name, id="header", markup=False)
        yield Static("Session view arrives in a later unit", id="body")
        yield Static("escape home", id="footer")
