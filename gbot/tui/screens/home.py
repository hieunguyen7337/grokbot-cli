from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Static

from gbot.service.models import Bot
from gbot.tui.glyphs import Glyphs


class HomeScreen(Screen):
    """Small roster placeholder, replaced by the home-list unit."""

    def __init__(self, bots: list[Bot], symbols: Glyphs) -> None:
        super().__init__()
        self.bots = bots
        self.symbols = symbols

    def compose(self) -> ComposeResult:
        sep = self.symbols.separator
        with Horizontal(id="header"):
            yield Static(f"Grok Bot {sep} {len(self.bots)} bots", id="heading")
            yield Static(f"{self.symbols.dot} live", id="connection")
        yield Static("\n".join(bot.name for bot in self.bots), id="body", markup=False)
        yield Static(
            f"{self.symbols.arrow} Inbox  {self.symbols.user} message {sep} @bot {sep} /command "
            f"{sep} s: n: t: filters\n"
            f"space peek {sep} enter open {sep} / commands {sep} ctrl+p palette {sep} ? help",
            id="footer",
            markup=False,
        )
