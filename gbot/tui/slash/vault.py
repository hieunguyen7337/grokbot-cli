"""Account vault, passkeys and 1Password metadata panels."""

from collections.abc import Callable
from datetime import UTC, datetime

from textual.widgets import Input, Static

from gbot.output import terminal_safe
from gbot.service import vault as service
from gbot.tui.panels.kit import (
    Detail,
    FormField,
    FormPanel,
    ListPanel,
    PanelAction,
    PanelRow,
)
from gbot.tui.slash import SlashCommand, SlashContext
from gbot.tui.slash.avatar_voice import _confirm, _Detail, _worker
from gbot.tui.slash.rooms import _writable


def _date(ms: int) -> str:
    return (
        datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%d") if ms else "never"
    )


def _card(card: service.Card | service.PaymentMethod) -> str:
    return (
        f"{card.brand} ··{card.last4} · {card.exp_month:02d}/{card.exp_year % 100:02d}"
    )


class _LoginForm(FormPanel):
    def __init__(
        self,
        ctx: SlashContext,
        done: Callable[[], object],
        item: service.VaultItem | None = None,
    ) -> None:
        self.ctx, self.done, self.item = ctx, done, item
        super().__init__(
            "Update login" if item else "Add login",
            (
                FormField("title", "Title", value=item.title if item else ""),
                FormField("username", "Username", value=item.username if item else ""),
                FormField(
                    "password",
                    "Password",
                    "password",
                    required=True,
                    hint="Enter the password again to update this login."
                    if item
                    else "",
                ),
                FormField(
                    "sites",
                    "Sites (comma separated)",
                    value=", ".join(item.sites) if item else "",
                ),
                FormField("notes", "Notes", value=item.notes if item else ""),
            ),
            self.save,
            confirm="Save login",
        )

    def action_submit(self) -> None:
        if not _writable(self.ctx):
            return
        title = (
            self.query_one("#form-0", Input).value.strip()
            or self.query_one("#form-1", Input).value.strip()
        )
        self.heading = terminal_safe(
            f"{'Update' if self.item else 'Save'} login {title}?"
        )
        self.confirm = self.heading
        super().action_submit()

    def save(self, values: dict[str, str | bool]) -> None:
        try:
            if self.ctx.app.read_only:
                raise ValueError("Read-only mode")
            service.put_login(
                self.ctx.service.transport,
                id=self.item.id if self.item else None,
                title=str(values["title"]),
                username=str(values["username"]),
                password=str(values["password"]),
                sites=str(values["sites"]).split(","),
                notes=str(values["notes"]),
            )
        finally:
            values.clear()

    def _submit_error(self, message: str) -> None:
        super()._submit_error(message)
        self.ctx.app.notify(terminal_safe(message), severity="error", markup=False)

    def _submit_done(self, message: str) -> None:
        super()._submit_done(message)
        self.done()


def vault(ctx: SlashContext, args: str) -> None:
    items: dict[str, service.VaultItem] = {}

    def load() -> list[PanelRow]:
        current = service.list_items(ctx.service.transport)
        items.clear()
        items.update((r.id, r) for r in current)
        rows = []
        for kind, label in (
            ("login", "Logins"),
            ("card", "Cards"),
            ("contact", "Contacts"),
            ("unknown", "Other"),
        ):
            selected = [r for r in current if r.kind == kind]
            if kind == "unknown" and not selected:
                continue
            rows.append(PanelRow("section:" + kind, label, tone="muted"))
            rows.extend(
                PanelRow(
                    r.id,
                    r.title or r.username or r.id,
                    _card(r.card)
                    if r.card
                    else " · ".join(
                        filter(None, (r.username, next(iter(r.sites), "")))
                    ),
                )
                for r in selected
            )
        rows.append(PanelRow("section:payments", "Payment methods"))
        outcome, methods, _ = service.payment_methods(ctx.service.transport)
        if outcome == "ok":
            rows.extend(
                PanelRow("payment:" + r.id, r.name or r.id, _card(r)) for r in methods
            )
        else:
            rows.append(PanelRow("payment:status", "", detail=outcome))
        return rows

    def add(row: PanelRow) -> None:
        if _writable(ctx):
            ctx.app.push_screen(_LoginForm(ctx, panel.reload))

    def edit(row: PanelRow) -> None:
        if not _writable(ctx):
            return
        item = items.get(row.key)
        if (item and item.kind == "card") or row.key.startswith("payment:"):
            ctx.app.notify("Add or edit cards in the Grok Bot app", markup=False)
        elif item and item.kind == "login":
            ctx.app.push_screen(_LoginForm(ctx, panel.reload, item))

    def delete(row: PanelRow) -> None:
        if not _writable(ctx):
            return
        if item := items.get(row.key):
            _confirm(
                ctx,
                f"Delete {item.title or item.username} from the vault?",
                lambda: service.delete_item(ctx.service.transport, item.id),
                panel.reload,
            )

    panel = ListPanel(
        "Vault",
        load,
        filterable=False,
        actions=(
            PanelAction("a", "Add login", add),
            PanelAction("e", "Edit login", edit),
            PanelAction("d", "Delete", delete),
        ),
    )
    ctx.app.push_screen(panel)


class _PasskeysPanel(ListPanel):
    def compose(self):
        yield from super().compose()
        yield Static(
            "Add passkeys in the Grok Bot app", classes="panel-footer", markup=False
        )


def passkeys(ctx: SlashContext, args: str) -> None:
    keys: dict[str, service.Passkey] = {}

    def load() -> list[PanelRow]:
        current = service.list_passkeys(ctx.service.transport)
        keys.clear()
        keys.update((r.credential_id, r) for r in current)
        return [
            PanelRow(
                r.credential_id,
                r.name or r.credential_id,
                f"{r.device_type} · backed up: {'yes' if r.backed_up else 'no'} · last used {_date(r.last_used_at_ms)}",
            )
            for r in current
        ]

    def revoke(row: PanelRow) -> None:
        if not _writable(ctx):
            return
        key = keys[row.key]
        _confirm(
            ctx,
            f"Revoke passkey {key.name}? Sign-ins with it stop working.",
            lambda: service.revoke_passkey(ctx.service.transport, key.credential_id),
            panel.reload,
        )

    panel = _PasskeysPanel(
        "Passkeys",
        load,
        filterable=False,
        actions=(PanelAction("x", "Revoke", revoke),),
    )
    ctx.app.push_screen(panel)


def onepassword(ctx: SlashContext, args: str) -> None:
    def load() -> None:
        state = service.onepassword_state(ctx.service.transport)

        def show() -> None:
            if not state.connections:
                ctx.app.push_screen(
                    _Detail(
                        "1Password",
                        lambda: Detail(
                            (), body="Connect 1Password in the Grok Bot app"
                        ),
                    )
                )
                return
            # Each connection gets its own detail screen. Escape reveals the preceding one.
            for connection in state.connections:
                ctx.app.push_screen(_OnePasswordPanel(ctx, connection))

        ctx.app.call_from_thread(show)

    _worker(ctx, load)


class _OnePasswordPanel(_Detail):
    def __init__(
        self, ctx: SlashContext, connection: service.OnePasswordConnection
    ) -> None:
        self.ctx, self.connection = ctx, connection
        super().__init__("1Password", self.content)

    def content(self) -> Detail:
        c = self.connection
        return Detail(
            (
                ("Account", c.account_email),
                ("Vault", c.vault_name),
                ("Items", str(c.item_count)),
                ("Last sync", _date(c.last_successful_sync_at_ms)),
                ("Last error", c.last_sync_error_code or "none"),
                ("Lifecycle", c.lifecycle_state),
                ("Expiry", _date(c.expires_at_ms)),
            ),
            actions=(
                PanelAction("s", "Sync", self.sync),
                PanelAction("x", "Disconnect", self.disconnect),
            ),
        )

    def sync(self) -> None:
        def work() -> None:
            state = service.sync_onepassword(self.ctx.service.transport)
            connection = next(
                (
                    c
                    for c in state.connections
                    if c.connection_id == self.connection.connection_id
                ),
                None,
            )

            def update() -> None:
                if connection:
                    self.connection = connection
                    self.detail = self.content()
                    self._draw()
                else:
                    self.detail = Detail(
                        (), body="Connect 1Password in the Grok Bot app"
                    )
                    self._draw()

            self.ctx.app.call_from_thread(update)

        _confirm(self.ctx, "Sync 1Password connections?", work, lambda: None)

    def disconnect(self) -> None:
        _confirm(
            self.ctx,
            f"Disconnect 1Password vault {self.connection.vault_name}?",
            lambda: service.delete_onepassword(
                self.ctx.service.transport, self.connection.connection_id
            ),
            lambda: self.ctx.app.pop_screen(),
        )


COMMANDS = (
    SlashCommand("vault", "Manage account vault", vault),
    SlashCommand("passkeys", "Manage passkeys", passkeys),
)
