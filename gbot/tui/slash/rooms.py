"""Confirmed group membership management."""

from collections.abc import Callable
from uuid import uuid4

from rich.text import Text
from textual.widgets import Static, Switch

from gbot.output import terminal_safe
from gbot.service import rooms
from gbot.service.models import Bot
from gbot.tui.panels.kit import FormField, FormPanel, ListPanel, PanelAction, PanelRow
from gbot.tui.screens.confirm import ConfirmScreen
from gbot.tui.slash import SlashCommand, SlashContext


def _writable(ctx: SlashContext) -> bool:
    if ctx.app.read_only:
        ctx.app.notify("Read-only mode", severity="warning", markup=False)
        return False
    return True


def _refresh(ctx: SlashContext, done: Callable[[], None]) -> None:
    async def refresh() -> None:
        await ctx.app.refresh_roster().wait()
        ctx.app.call_later(done)

    ctx.app.run_worker(refresh(), exit_on_error=False)


class _BotsForm(FormPanel):
    def __init__(
        self,
        ctx: SlashContext,
        bots: list[Bot],
        *,
        group: Bot | None = None,
        done: Callable[[], None],
    ) -> None:
        self.ctx, self.bots, self.group, self.done = ctx, bots, group, done
        self.created: Bot | None = None
        self.created_name = ""
        self._nonces: dict[tuple[str, tuple[str, ...], str], str] = {}
        fields = (
            []
            if group
            else [
                FormField("name", "Name", required=True),
                FormField("description", "Description"),
            ]
        )
        fields.extend(
            FormField(f"bot:{b.id}", terminal_safe(b.name), "toggle") for b in bots
        )
        super().__init__("Add bots" if group else "New group", fields, self.save)

    def action_submit(self) -> None:
        if not _writable(self.ctx):
            return
        count = sum(
            self.query_one(f"#form-{i}", Switch).value
            for i, field in enumerate(self.fields)
            if field.kind == "toggle"
        )
        if count < (1 if self.group else 2):
            self.query_one("#form-notice", Static).update(
                Text(
                    "Select at least one bot"
                    if self.group
                    else "Select at least two bots"
                )
            )
            return
        self.confirm = (
            f"Add {count} bots to {terminal_safe(self.group.name)}?"
            if self.group
            else f"Create the group with {count} bots?"
        )
        super().action_submit()

    def save(self, values: dict[str, str | bool]) -> str | None:
        if self.ctx.app.read_only:
            raise ValueError("Read-only mode")
        ids = [b.id for b in self.bots if values.get(f"bot:{b.id}") is True]
        if self.group:
            rooms.set_members(
                self.ctx.service.transport, self.group, [*self.group.member_ids, *ids]
            )
        else:
            self.created_name = str(values["name"]).strip()
            # Each distinct request keeps one nonce for the life of the form, so a retry
            # (even after editing and changing back) reuses it and a changed request never does.
            request = (self.created_name, tuple(ids), str(values["description"]))
            nonce = self._nonces.setdefault(request, str(uuid4()))
            self.created = rooms.create_group(
                self.ctx.service.transport,
                self.created_name,
                ids,
                description=str(values["description"]),
                nonce=nonce,
            )
        return None

    def _submit_error(self, message: str) -> None:
        super()._submit_error(message)
        self.ctx.app.notify(message, severity="warning", markup=False)

    def _submit_done(self, message: str) -> None:
        super()._submit_done(message)
        _refresh(self.ctx, self.done)


def newgroup(ctx: SlashContext, args: str) -> None:
    if not _writable(ctx):
        return

    def opened() -> None:
        bot = ctx.app.state.bots.get(form.created.id) if form.created else None
        if bot:
            ctx.app.open_bot(bot)
        else:
            ctx.app.notify(
                f"Created {terminal_safe(form.created_name)}",
                markup=False,
            )

    form = _BotsForm(
        ctx, [b for b in ctx.app.state.bots.values() if not b.is_group], done=opened
    )
    ctx.app.push_screen(form)


def members(ctx: SlashContext, args: str) -> None:
    group = ctx.app.state.bots.get(ctx.bot_id or "")
    if not group or not group.is_group:
        ctx.app.notify("/members works on a group", severity="warning", markup=False)
        return

    def current() -> Bot:
        return ctx.app.state.bots.get(group.id, group)

    def load() -> list[PanelRow]:
        bot = current()
        return [
            PanelRow(
                f"bot:{member}",
                terminal_safe(
                    ctx.app.state.bots[member].name
                    if member in ctx.app.state.bots
                    else member
                ),
                status="bot",
            )
            for member in bot.member_ids
        ] + [
            PanelRow(
                f"person:{i}",
                terminal_safe(person.display_name),
                status="you" if person.is_viewer else "person",
            )
            for i, person in enumerate(rooms.people(bot))
        ]

    def add(row: PanelRow) -> None:
        if not _writable(ctx):
            return
        bot = current()
        ctx.app.push_screen(
            _BotsForm(
                ctx,
                [
                    b
                    for b in ctx.app.state.bots.values()
                    if not b.is_group and b.id not in bot.member_ids
                ],
                group=bot,
                done=panel.reload,
            )
        )

    def remove(row: PanelRow) -> None:
        if not _writable(ctx):
            return
        bot = current()
        person = None
        if row.key.startswith("bot:"):
            if len(bot.member_ids) <= 1:
                ctx.app.notify(
                    "A group needs at least one bot", severity="warning", markup=False
                )
                return
        else:
            person = rooms.people(bot)[int(row.key.split(":", 1)[1])]
            if person.is_viewer or person.user_id is None:
                ctx.app.notify(
                    "Cannot remove yourself"
                    if person.is_viewer
                    else "This person has no user id",
                    severity="warning",
                    markup=False,
                )
                return

        def confirmed(ok: bool | None) -> None:
            if not ok or not _writable(ctx):
                return

            def worker() -> None:
                try:
                    if ctx.app.read_only:
                        raise ValueError("Read-only mode")
                    if person is not None and person.user_id is not None:
                        rooms.remove_people(
                            ctx.service.transport, bot.id, [person.user_id]
                        )
                    else:
                        rooms.set_members(
                            ctx.service.transport,
                            bot,
                            [
                                m
                                for m in bot.member_ids
                                if m != row.key.removeprefix("bot:")
                            ],
                        )
                    ctx.app.call_from_thread(_refresh, ctx, panel.reload)
                except Exception as error:  # noqa: BLE001 - worker boundary
                    ctx.app.call_from_thread(ctx.app.bot_error, bot.id, error)

            ctx.app.run_worker(worker, thread=True, exit_on_error=False)

        ctx.app.push_screen(
            ConfirmScreen(
                f"Remove {terminal_safe(row.label)} from {terminal_safe(bot.name)}?",
                "Update group membership",
                "Remove",
            ),
            confirmed,
        )

    panel = ListPanel(
        f"Members of {terminal_safe(group.name)}",
        load,
        actions=(PanelAction("a", "Add bots", add), PanelAction("x", "Remove", remove)),
    )
    ctx.app.push_screen(panel)


COMMANDS = (
    SlashCommand("newgroup", "Create a group", newgroup, scope="home"),
    SlashCommand("members", "Manage group members", members, needs_bot=True),
)
