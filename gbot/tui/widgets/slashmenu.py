"""Completion menu for slash commands."""

from rich.text import Text
from textual.widgets import Static

from gbot.output import terminal_safe
from gbot.tui.slash import Scope, SlashCommand, complete


class SlashMenu(Static):
    DEFAULT_CSS = """
    SlashMenu { height: auto; max-height: 8; display: none; border-left: solid $accent; }
    """

    def __init__(self, scope: Scope) -> None:
        super().__init__()
        self.slash_scope: Scope = scope
        self.matches: tuple[SlashCommand, ...] = ()
        self.index = 0

    def update_input(self, value: str) -> None:
        self.display = (
            value.startswith("/")
            and not value.startswith("//")
            and not any(c.isspace() for c in value)
        )
        self.matches = complete(value[1:], self.slash_scope) if self.display else ()
        # An unknown name leaves nothing to pick, so the menu would only be an empty border.
        self.display = bool(self.matches)
        self.index = 0
        self._draw()

    def _draw(self) -> None:
        start = max(0, self.index - 7)
        lines = []
        for i, command in enumerate(self.matches[start : start + 8], start):
            marker = ">" if i == self.index else " "
            usage = f"/{command.name} {command.args}".rstrip()
            lines.append(terminal_safe(f"{marker} {usage}   {command.summary}"))
        self.update(Text("\n".join(lines)))

    def move(self, delta: int) -> None:
        if self.matches:
            self.index = (self.index + delta) % len(self.matches)
            self._draw()

    @property
    def selected(self) -> SlashCommand | None:
        return self.matches[self.index] if self.matches else None
