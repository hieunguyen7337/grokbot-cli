"""Confirmed bot creation, identity and runtime settings."""

from collections.abc import Callable
from typing import Literal
from uuid import uuid4

from rich.text import Text
from textual.widgets import Input, Select, Static, Switch, TextArea

from gbot.output import terminal_safe
from gbot.service import bots
from gbot.service.avatar_voice import check_png
from gbot.service.models import Bot
from gbot.tui.panels.kit import FormField, FormPanel, ListPanel, PanelAction, PanelRow
from gbot.tui.screens.confirm import ConfirmScreen
from gbot.tui.slash import SlashCommand, SlashContext
from gbot.tui.slash.attachments import file_path
from gbot.tui.slash.rooms import _refresh, _writable


def _notice(
    ctx: SlashContext,
    message: str,
    severity: Literal["information", "warning", "error"] = "information",
) -> None:
    ctx.app.notify(terminal_safe(message), severity=severity, markup=False)


def _home(ctx: SlashContext) -> None:
    while ctx.app.screen is not ctx.app.home:
        ctx.app.pop_screen()


def _change(
    ctx: SlashContext,
    question: str,
    action: Callable[[], None],
    done: Callable[[], None],
) -> None:
    if not _writable(ctx):
        return

    def confirmed(ok: bool | None) -> None:
        if not ok or not _writable(ctx):
            return

        def worker() -> None:
            try:
                if ctx.app.read_only:
                    raise ValueError("Read-only mode")
                action()
            except Exception as error:  # noqa: BLE001 - worker boundary
                ctx.app.call_from_thread(_notice, ctx, str(error), "error")
            else:
                ctx.app.call_from_thread(_refresh, ctx, done)

        ctx.app.run_worker(worker, thread=True, exit_on_error=False)

    ctx.app.push_screen(
        ConfirmScreen(terminal_safe(question), "", "Confirm"), confirmed
    )


class BotForm(FormPanel):
    def __init__(
        self,
        ctx: SlashContext,
        *,
        name: str = "",
        bot: Bot | None = None,
        settings: bool = False,
        server: bots.ServerBot | None = None,
    ) -> None:
        self.ctx, self.bot, self.settings, self.server = ctx, bot, settings, server
        self.nonce = str(uuid4())
        self.previous: dict[str, str | bool] | None = None
        self.png: bytes | None = None
        self.created: Bot | None = None
        if settings and bot:
            fields = [
                FormField("sidebar", "Show in sidebar", "toggle", not bot.hidden),
                FormField("notify", "Notify on updates", "toggle", bot.notifications),
            ]
            if server and not bot.is_group and not server.is_group:
                fields.append(
                    FormField(
                        "drafting", "Drafting", "toggle", not server.drafting_disabled
                    )
                )
            fields.append(
                FormField("main", "Main bot", "toggle", ctx.app.main_bot_id == bot.id)
            )
            heading = f"{bot.name} settings"
        else:
            fields = [
                FormField(
                    "name", "Name", value=bot.name if bot else name, required=True
                )
            ]
            if bot:
                fields.append(FormField("title", "Title", value=bot.title))
            fields.append(
                FormField(
                    "description",
                    "Description",
                    "multiline",
                    bot.description if bot else "",
                    hint="The bot's instructions",
                )
            )
            if not bot:
                fields.extend(
                    [
                        FormField("shape", "Shape", "choice", "blob", bots.SHAPES),
                        FormField("color", "Color", "choice", "blue", bots.COLORS),
                        FormField("avatar", "Avatar"),
                    ]
                )
            heading = f"Edit {bot.name}" if bot else "New bot"
        super().__init__(terminal_safe(heading), fields, self.save)
        self.initial = {f.name: f.value for f in fields}

    def on_mount(self) -> None:
        super().on_mount()
        if self.settings:
            info = (
                f"Owner: {'you' if self.server.owner else 'someone else'} · Harness: {self.server.harness}"
                if self.server
                else "Server details unavailable"
            )
            self.query_one("#form-notice", Static).update(
                Text(terminal_safe(info), style="dim")
            )

    def values(self) -> dict[str, str | bool]:
        result: dict[str, str | bool] = {}
        for i, field in enumerate(self.fields):
            widget = self.query_one(f"#form-{i}")
            if isinstance(widget, Input):
                value = widget.value
            elif isinstance(widget, TextArea):
                value = widget.text
            elif isinstance(widget, Switch):
                value = widget.value
            else:
                selected = self.query_one(f"#form-{i}", Select).value
                value = selected if isinstance(selected, str) else ""
            result[field.name] = value
        return result

    def changes(self, values: dict[str, str | bool]) -> list[str]:
        return [key for key in values if values[key] != self.initial[key]]

    def labels(self, values: dict[str, str | bool]) -> list[str]:
        labels = {
            "sidebar": ("Hide from sidebar", "Show in sidebar"),
            "notify": ("Turn off update notifications", "Turn on update notifications"),
            "drafting": ("Turn off drafting", "Turn on drafting"),
            "main": ("", "Make main bot"),
        }
        return [labels[key][bool(values[key])] for key in self.changes(values)]

    def action_submit(self) -> None:
        if not _writable(self.ctx):
            return
        values = self.values()
        if self.bot and not self.changes(values):
            _notice(self.ctx, "Nothing to change")
            return
        if self.settings:
            if self.server and not self.server.owner:
                self._submit_error(
                    "Only the bot's owner can change this in gbot; use the app"
                )
                return
            if self.initial["main"] and not values["main"]:
                self._submit_error("Choose another main bot instead")
                return
            self.confirm = "\n".join(self.labels(values))
        elif self.bot:
            self.confirm = f"Save changes to {terminal_safe(self.bot.name)}?"
        else:
            try:
                self.png = (
                    file_path(str(values["avatar"])).read_bytes()
                    if values["avatar"]
                    else None
                )
                if self.png is not None:
                    check_png(self.png)
            except (OSError, ValueError) as error:
                self._submit_error(terminal_safe(str(error)))
                return
            if self.previous is not None and values != self.previous:
                self.nonce = str(uuid4())
            self.previous = values.copy()
            self.confirm = f"Create bot {terminal_safe(str(values['name']).strip())}?"
        super().action_submit()

    def save(self, values: dict[str, str | bool]) -> str | None:
        if self.ctx.app.read_only:
            raise ValueError("Read-only mode")
        transport = self.ctx.service.transport
        if not self.bot:
            self.created = bots.create(
                transport,
                str(values["name"]),
                description=str(values["description"]),
                shape=str(values["shape"]),
                color=str(values["color"]),
                png=self.png,
                nonce=self.nonce,
            )
            return f"Created {values['name']}"
        if not self.settings:
            edits = {key: str(values[key]) for key in self.changes(values)}
            bots.update(transport, self.bot, **edits)
            return None
        applied = []
        for key, label in zip(self.changes(values), self.labels(values)):
            try:
                if self.ctx.app.read_only:
                    raise ValueError("Read-only mode")
                if key == "sidebar":
                    bots.set_hidden(transport, self.bot.id, not values[key])
                elif key == "notify":
                    bots.set_notify_on_updates(
                        transport, self.bot.id, bool(values[key])
                    )
                elif key == "drafting":
                    bots.set_drafting_disabled(transport, self.bot.id, not values[key])
                else:
                    bots.set_main(transport, self.bot.id)
                    self.ctx.app.call_from_thread(self.ctx.app.refresh_main)
            except Exception as error:  # partial mutation boundary
                self.ctx.app.call_from_thread(_refresh, self.ctx, lambda: None)
                raise ValueError(
                    f"{label} failed: {error}. Applied: {', '.join(applied) or 'none'}"
                ) from error
            applied.append(label)
            self.initial[key] = values[key]
        return None

    def _submit_error(self, message: str) -> None:
        super()._submit_error(message)
        _notice(self.ctx, message, "error")

    def _submit_done(self, message: str) -> None:
        super()._submit_done(message)

        def done() -> None:
            if self.created:
                _home(self.ctx)
                self.ctx.app.open_bot(
                    self.ctx.app.state.bots.get(self.created.id, self.created)
                )

        _refresh(self.ctx, done)


def new(ctx: SlashContext, args: str) -> None:
    ctx.app.push_screen(BotForm(ctx, name=args))


def edit(ctx: SlashContext, args: str) -> None:
    ctx.app.push_screen(BotForm(ctx, bot=ctx.app.state.bots[ctx.bot_id or ""]))


def delete(ctx: SlashContext, args: str) -> None:
    bot = ctx.app.state.bots[ctx.bot_id or ""]

    def action() -> None:
        result = bots.delete(ctx.service.transport, [bot.id])
        if result.refused_ids or result.failed_ids:
            ctx.app.call_from_thread(
                _notice, ctx, f"Deletion refused or failed for {bot.name}", "warning"
            )
            return
        ctx.app.call_from_thread(_notice, ctx, f"Deleted {bot.name}")
        ctx.app.call_from_thread(_home, ctx)

    _change(
        ctx,
        f"Delete {bot.name}? Its conversation history is removed.",
        action,
        lambda: None,
    )


def settings(ctx: SlashContext, args: str) -> None:
    bot = ctx.app.state.bots[ctx.bot_id or ""]

    def worker() -> None:
        try:
            server = bots.server_bots(ctx.service.transport).get(bot.id)
        except Exception:  # noqa: BLE001 - optional server details
            server = None
        ctx.app.call_from_thread(
            ctx.app.push_screen, BotForm(ctx, bot=bot, settings=True, server=server)
        )

    ctx.app.run_worker(worker, thread=True, exit_on_error=False)


def refresh_main(ctx: SlashContext) -> None:
    ctx.app.refresh_main()


def main(ctx: SlashContext, args: str) -> None:
    if not args:
        bot = ctx.app.state.bots.get(ctx.app.main_bot_id or "")
        _notice(
            ctx,
            f"Main bot: {bot.name if bot else ctx.app.main_bot_id}"
            if ctx.app.main_bot_id
            else "No main bot set",
        )
        return
    matches = [
        b
        for b in ctx.app.state.bots.values()
        if b.id == args or b.name.casefold() == args.casefold()
    ]
    if len(matches) != 1:
        raise ValueError(f"Bot selector is unknown or ambiguous: {args}")
    bot = matches[0]
    _change(
        ctx,
        f"Make {bot.name} your main bot?",
        lambda: bots.set_main(ctx.service.transport, bot.id),
        lambda: refresh_main(ctx),
    )


def hidden(ctx: SlashContext, args: str) -> None:
    def show(row: PanelRow) -> None:
        _change(
            ctx,
            f"Show {row.label} in the sidebar?",
            lambda: bots.set_hidden(ctx.service.transport, row.key, False),
            panel.reload,
        )

    def opened(row: PanelRow) -> None:
        bot = ctx.app.state.bots[row.key]
        _home(ctx)
        ctx.app.open_bot(bot)

    panel = ListPanel(
        "Hidden bots",
        lambda: [
            PanelRow(b.id, terminal_safe(b.name), terminal_safe(b.description))
            for b in ctx.app.state.bots.values()
            if b.hidden
        ],
        on_select=opened,
        empty="No hidden bots",
        actions=(PanelAction("u", "Show", show),),
    )
    ctx.app.push_screen(panel)


COMMANDS = (
    SlashCommand("new", "Create a bot", new, args="[name]"),
    SlashCommand("edit", "Edit bot identity", edit, scope="session", needs_bot=True),
    SlashCommand("delete", "Delete a bot", delete, scope="session", needs_bot=True),
    SlashCommand("bot", "Bot settings", settings, scope="session", needs_bot=True),
    SlashCommand("main", "Show or set the main bot", main, args="[bot]"),
    SlashCommand("hidden", "List hidden bots", hidden),
)
