"""Commands available from the TUI's Ctrl+P palette."""

from collections.abc import Callable
from functools import partial
from typing import TYPE_CHECKING, cast

from rich.text import Text
from textual.command import DiscoveryHit, Hit, Hits, Provider

from gbot.output import terminal_safe
from gbot.tui.screens.home import HomeScreen

if TYPE_CHECKING:
    from gbot.tui.app import GbotApp


class GbotCommands(Provider):
    def commands(self) -> list[tuple[str, Callable[[], None]]]:
        app = cast("GbotApp", self.app)
        commands = [
            ("Keyboard help", app.action_help),
            ("Quit", app.action_palette_quit),
        ]
        if isinstance(self.screen, HomeScreen):
            home = self.screen
            commands = [
                (f"Open {terminal_safe(bot.name)}", partial(app.open_bot, bot))
                for bot in app.bots
            ] + commands
            selected = app.state.bots.get(home.bot_list.selected_id or "")
            if selected and home.bot_list.header_key is None:
                commands.append(
                    (f"Pin or unpin {terminal_safe(selected.name)}", home.action_pin)
                )
            commands.extend(
                (
                    ("Group by state", partial(self.group_by, "state")),
                    ("Group by team", partial(self.group_by, "team")),
                    ("Filter bots", home.action_find),
                )
            )
        return commands

    def group_by(self, mode: str) -> None:
        if (
            isinstance(self.screen, HomeScreen)
            and self.screen.preferences.group_by != mode
        ):
            self.screen.action_group_by()

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        for label, command in self.commands():
            score = matcher.match(label)
            if score > 0:
                yield Hit(score, Text(label), command, text=label)

    async def discover(self) -> Hits:
        for label, command in self.commands():
            yield DiscoveryHit(Text(label), command, text=label)
