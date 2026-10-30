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

    def slash_commands(self) -> list[tuple[str, Callable[[], None]]]:
        from gbot.tui.screens.session import SessionScreen
        from gbot.tui.slash import SlashContext, available, run

        app = cast("GbotApp", self.app)
        commands: list[tuple[str, Callable[[], None]]] = []
        if isinstance(self.screen, (HomeScreen, SessionScreen)):
            screen = self.screen
            scope = "home" if isinstance(screen, HomeScreen) else "session"
            bot_id = (
                screen.bot_list.selected_id
                if isinstance(screen, HomeScreen)
                else screen.bot_id
            )
            session_id = (
                screen.session_id if isinstance(screen, SessionScreen) else None
            )
            ctx = SlashContext(app, screen, bot_id, session_id)

            def dispatch(name: str) -> None:
                error = run(ctx, f"/{name}")
                if error:
                    app.notify(error, severity="warning", markup=False)

            commands.extend(
                (f"/{c.name}  {c.summary}", partial(dispatch, c.name))
                for c in available(scope)
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
        for label, command in [*self.commands(), *self.slash_commands()]:
            score = matcher.match(label)
            if score > 0:
                yield Hit(score, Text(label), command, text=label)

    async def discover(self) -> Hits:
        for label, command in [*self.commands(), *self.slash_commands()]:
            yield DiscoveryHit(Text(label), command, text=label)
