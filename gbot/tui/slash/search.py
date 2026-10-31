"""Search messages, media and the current conversation."""

import time

from textual.widgets import Static

from gbot.output import terminal_safe
from gbot.service import search
from gbot.tui.model import age_text
from gbot.tui.panels.kit import ListPanel, PanelRow
from gbot.tui.slash import SlashCommand, SlashContext
from gbot.tui.widgets.transcript import Transcript


def _age(timestamp: int) -> str:
    # Rows without a time (the demo data) show no age.
    return age_text(int(time.time() * 1000) - timestamp) if timestamp > 0 else ""


def _detail(*parts: str) -> str:
    return " · ".join(part for part in parts if part)


def _name(ctx: SlashContext, bot_id: str) -> str:
    bot = ctx.app.state.bots.get(bot_id)
    return terminal_safe(bot.name if bot else bot_id)


def _open(ctx: SlashContext, row: PanelRow) -> None:
    from gbot.tui.screens.home import HomeScreen

    bot = ctx.app.state.bots.get(row.key)
    if bot:
        ctx.app.pop_screen()
        if not isinstance(ctx.app.screen, HomeScreen):
            ctx.app.pop_screen()
        ctx.app.open_bot(bot)


def messages(ctx: SlashContext, args: str) -> None:
    if not args.strip():
        ctx.app.notify("Type something to search", markup=False)
        return

    def load() -> list[PanelRow]:
        try:
            return [
                PanelRow(
                    m.agent_id,
                    f"{_name(ctx, m.agent_id)}  {terminal_safe(m.snippet)}",
                    _detail(terminal_safe(m.role), _age(m.timestamp_ms)),
                )
                for m in search.messages(ctx.service.transport, args)
            ]
        except Exception as error:  # noqa: BLE001 - worker boundary
            ctx.app.call_from_thread(
                ctx.app.notify,
                terminal_safe(str(error)),
                severity="warning",
                markup=False,
            )
            return []

    ctx.app.push_screen(
        ListPanel("Search messages", load, on_select=lambda row: _open(ctx, row))
    )


def media(ctx: SlashContext, args: str) -> None:
    def load() -> list[PanelRow]:
        try:
            return [
                PanelRow(
                    m.agent_id,
                    terminal_safe(m.file_name),
                    _detail(
                        terminal_safe(m.kind),
                        _name(ctx, m.agent_id),
                        _age(m.timestamp_ms),
                    ),
                )
                for m in search.media(ctx.service.transport, args)
            ]
        except Exception as error:  # noqa: BLE001 - worker boundary
            ctx.app.call_from_thread(
                ctx.app.notify,
                terminal_safe(str(error)),
                severity="warning",
                markup=False,
            )
            return []

    ctx.app.push_screen(
        ListPanel("Search media", load, on_select=lambda row: _open(ctx, row))
    )


def find(ctx: SlashContext, args: str) -> None:
    if not args.strip():
        ctx.app.notify("Type something to search", markup=False)
        return
    history = ctx.screen.query_one(Transcript)

    def selected(row: PanelRow) -> None:
        ctx.app.pop_screen()
        widget = history.entries.get(row.key)
        if widget:
            history.scroll_to_widget(widget, animate=False)
        else:
            ctx.app.notify(
                "Earlier in the chat · press pgup to load more", markup=False
            )

    def hint() -> None:
        panel.empty = "More matches exist"
        panel.query_one(".panel-footer", Static).update("More matches exist · esc back")

    def load() -> list[PanelRow]:
        try:
            result = search.conversation(ctx.service.transport, ctx.bot_id or "", args)
            if not result.complete:
                ctx.app.call_from_thread(hint)
            return [
                PanelRow(
                    m.entry_id,
                    terminal_safe(m.snippet),
                    _detail(terminal_safe(m.role), _age(m.timestamp_ms)),
                )
                for m in result.matches
            ]
        except Exception as error:  # noqa: BLE001 - worker boundary
            ctx.app.call_from_thread(
                ctx.app.notify,
                terminal_safe(str(error)),
                severity="warning",
                markup=False,
            )
            return []

    panel = ListPanel("Find in conversation", load, on_select=selected)
    ctx.app.push_screen(panel)


COMMANDS = (
    SlashCommand("search", "Search messages", messages, args="<query>"),
    SlashCommand("media", "Search media", media, args="[query]"),
    SlashCommand(
        "find",
        "Search this conversation",
        find,
        scope="session",
        args="<query>",
        needs_bot=True,
    ),
)
