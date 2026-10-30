"""Email inbox list and confirmed creation."""

from rich.text import Text
from textual import events
from textual.widgets import Input, Static

from gbot.output import terminal_safe
from gbot.service import inboxes as service
from gbot.tui.panels.kit import FormField, ListPanel, PanelAction, PanelRow
from gbot.tui.slash import SlashCommand, SlashContext
from gbot.tui.slash.avatar_voice import _confirm, _Form
from gbot.tui.slash.rooms import _writable


class _InboxForm(_Form):
    def __init__(self, ctx: SlashContext, panel: "_Inboxes") -> None:
        self.domain = panel.domain

        def prepare(values: dict[str, str | bool]) -> None:
            username = service.normalize_username(str(values["username"]))

            def review() -> None:
                def done() -> None:
                    ctx.app.pop_screen()
                    panel.reload()

                _confirm(
                    ctx,
                    f"Create inbox {terminal_safe(username)}@{terminal_safe(self.domain)}?",
                    lambda: service.create_inbox(ctx.service.transport, username),
                    done,
                )

            ctx.app.call_from_thread(review)

        super().__init__(
            ctx,
            "New inbox",
            (
                FormField(
                    "username",
                    "Username",
                    required=True,
                    hint=f"username@{self.domain}",
                ),
            ),
            prepare,
        )

    def on_input_changed(self, event: Input.Changed) -> None:
        username = event.value.strip().lower() or "username"
        self.query_one("#form-error-0", Static).update(
            Text(terminal_safe(f"{username}@{self.domain}"))
        )


class _Inboxes(ListPanel):
    def __init__(self, ctx: SlashContext) -> None:
        self.ctx = ctx
        self.domain = "mail.grokbot.com"
        super().__init__(
            "Email inboxes",
            self.load_inboxes,
            empty="No inboxes",
            actions=(PanelAction("n", "New", self.new),),
        )

    def load_inboxes(self) -> list[PanelRow]:
        rows = service.list_inboxes(self.ctx.service.transport)
        self.domain = rows[0].domain if rows and rows[0].domain else "mail.grokbot.com"
        return [
            PanelRow(row.email, row.email, "assigned" if row.assigned else "unassigned")
            for row in rows
        ]

    def new(self) -> None:
        if _writable(self.ctx):
            self.ctx.app.push_screen(_InboxForm(self.ctx, self))

    def on_key(self, event: events.Key) -> None:
        if event.key == "n":
            self.new()
            event.stop()
            event.prevent_default()
        elif event.key == "r":
            self.reload()
            event.stop()
            event.prevent_default()
        else:
            super().on_key(event)


def inboxes(ctx: SlashContext, args: str) -> None:
    ctx.app.push_screen(_Inboxes(ctx))


COMMANDS = (SlashCommand("inboxes", "Manage email inboxes", inboxes),)
