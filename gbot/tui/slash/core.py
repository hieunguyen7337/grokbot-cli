"""Built-in, service-free commands."""

from gbot.tui.panels import Detail, DetailPanel, ListPanel, PanelRow
from gbot.tui.slash import SlashCommand, SlashContext, available, complete


def help_command(ctx: SlashContext, args: str) -> None:
    from gbot.tui.screens.home import HomeScreen

    scope = "home" if isinstance(ctx.screen, HomeScreen) else "session"
    commands = available(scope)

    def show(name: str) -> None:
        matches = complete(name.removeprefix("/"), scope)
        exact = [c for c in matches if c.name == name.removeprefix("/").casefold()]
        if exact:
            matches = tuple(exact)
        if len(matches) != 1:
            raise ValueError(f"Unknown command /{name} · /help lists commands")
        command = matches[0]
        ctx.app.push_screen(
            DetailPanel(
                f"/{command.name}",
                lambda: Detail(
                    (
                        ("Usage", f"/{command.name} {command.args}".rstrip()),
                        ("Summary", command.summary),
                    )
                ),
            )
        )

    if args:
        show(args)
    else:
        ctx.app.push_screen(
            ListPanel(
                "Slash commands",
                lambda: [
                    PanelRow(c.name, f"/{c.name} {c.args}".rstrip(), c.summary)
                    for c in commands
                ],
                on_select=lambda row: show(row.key),
            )
        )


def keys_command(ctx: SlashContext, args: str) -> None:
    ctx.app.action_help()


COMMANDS = (
    SlashCommand(
        "help", "List commands or show command help", help_command, args="[name]"
    ),
    SlashCommand("keys", "Show keyboard shortcuts", keys_command),
)
