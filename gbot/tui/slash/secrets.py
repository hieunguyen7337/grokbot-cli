"""Confirmed, write-only secret management for the selected bot."""

from rich.text import Text
from textual import events
from textual.widgets import Input, Static, Switch

from gbot.output import terminal_safe
from gbot.service import secrets as service
from gbot.tui.panels.kit import FormField, FormPanel, ListPanel, PanelAction, PanelRow
from gbot.tui.screens.confirm import ConfirmScreen
from gbot.tui.slash import SlashCommand, SlashContext
from gbot.tui.slash.avatar_voice import _confirm
from gbot.tui.slash.rooms import _refresh, _writable
from gbot.tui.slash.search import _age


class _SecretForm(FormPanel):
    def __init__(self, panel: "_SecretsPanel", *, copy: bool = False) -> None:
        self.panel, self.ctx, self.copy = panel, panel.ctx, copy
        self.outcomes: list[tuple[str, str]] = []
        fields = (
            tuple(FormField(name, name, "toggle") for name in panel.box.keys)
            if copy
            else (
                FormField("name", "Name"),
                FormField("description", "Description"),
                FormField("value", "Value", "password"),
            )
        )
        super().__init__(
            "Copy computer secrets" if copy else "Save secret", fields, self.save
        )

    def action_submit(self) -> None:
        if not _writable(self.ctx):
            return
        if self.copy:
            count = sum(
                self.query_one(f"#form-{i}", Switch).value
                for i in range(len(self.fields))
            )
            if not count:
                self._submit_error("Select at least one computer secret")
                return
            title = f"Copy {count} computer secrets to {self.panel.bot_label}?"
        else:
            try:
                name = service.normalize_name(self.query_one("#form-0", Input).value)
                service.check_value(self.query_one("#form-2", Input).value)
            except ValueError as error:
                self._submit_error(str(error))
                return
            self.query_one("#form-0", Input).value = name
            title = (
                f"Replace secret {name} on {self.panel.bot_label}?"
                if name in {row.key for row in self.panel.rows}
                else f"Save secret {name} to {self.panel.bot_label}?"
            )

        def confirmed(ok: bool | None) -> None:
            if ok and _writable(self.ctx):
                super(_SecretForm, self).action_submit()
            elif not self.copy:
                self.query_one("#form-2", Input).value = ""

        self.ctx.app.push_screen(ConfirmScreen(title, "", "Save"), confirmed)

    def save(self, values: dict[str, str | bool]) -> None:
        try:
            if self.ctx.app.read_only:
                raise ValueError("Read-only mode")
            if self.copy:
                self.outcomes = service.carry_to_bot(
                    self.ctx.service.transport,
                    self.panel.bot_id,
                    [name for name, enabled in values.items() if enabled is True],
                )
            else:
                service.put_secret(
                    self.ctx.service.transport,
                    self.panel.bot_id,
                    str(values["name"]),
                    str(values["value"]),
                    str(values["description"]),
                )
        finally:
            values.clear()

    def action_back(self) -> None:
        if not self.copy:
            self.query_one("#form-2", Input).value = ""
        super().action_back()

    def _submit_done(self, message: str) -> None:
        self.ctx.app.pop_screen()
        if self.copy:
            self.ctx.app.notify(
                terminal_safe(
                    "\n".join(f"{name}: {outcome}" for name, outcome in self.outcomes)
                ),
                markup=False,
            )
        _refresh(self.ctx, self.panel.reload)

    def _submit_error(self, message: str) -> None:
        super()._submit_error(terminal_safe(message))
        self.ctx.app.notify(terminal_safe(message), severity="error", markup=False)


class _SecretsPanel(ListPanel):
    def __init__(self, ctx: SlashContext) -> None:
        self.ctx = ctx
        self.bot_id = ctx.bot_id or ""
        self.bot_label = terminal_safe(ctx.app.state.bots[self.bot_id].name)
        self.box = service.BoxSecrets((), (), False, None)
        super().__init__(
            f"{self.bot_label} secrets",
            self.load_secrets,
            empty="No secrets",
            actions=(
                PanelAction("a", "Add", self.add),
                PanelAction("d", "Delete", self.delete),
                PanelAction("c", "Copy from computer", self.copy),
            ),
        )

    def load_secrets(self) -> list[PanelRow]:
        rows = service.list_secrets(self.ctx.service.transport, self.bot_id)
        self.box = service.box_secrets(self.ctx.service.transport)
        return [
            PanelRow(
                row.name,
                row.name,
                " · ".join(
                    part
                    for part in (
                        row.description,
                        f"updated {_age(row.updated_at_ms)}"
                        if row.updated_at_ms
                        else "updated unknown",
                    )
                    if part
                ),
            )
            for row in rows
        ]

    def _loaded(self, rows: list[PanelRow], error: str) -> None:
        super()._loaded(rows, error)
        if error:
            self.ctx.app.notify(terminal_safe(error), severity="error", markup=False)

    def _draw(self) -> None:
        super()._draw()
        widget = self.query_one("#panel-rows", Static)
        content = widget.content
        text = content.copy() if isinstance(content, Text) else Text(str(content))
        applied = "applied" if self.box.is_applied else "not applied"
        footer = f"\nComputer: {len(self.box.keys)} secret names ({applied})"
        text.append(footer, style="dim")
        widget.update(text)

    def on_key(self, event: events.Key) -> None:
        if event.key in {"a", "c", "d"}:
            if not _writable(self.ctx):
                pass
            elif event.key == "a":
                self.add()
            elif event.key == "c":
                self.copy()
            elif self.visible_rows:
                self.delete(self.visible_rows[self.index])
            event.stop()
            event.prevent_default()
        else:
            super().on_key(event)

    def add(self) -> None:
        if _writable(self.ctx):
            self.ctx.app.push_screen(_SecretForm(self))

    def copy(self) -> None:
        if _writable(self.ctx):
            self.ctx.app.push_screen(_SecretForm(self, copy=True))

    def delete(self, row: PanelRow) -> None:
        _confirm(
            self.ctx,
            f"Delete secret {terminal_safe(row.key)} from {self.bot_label}?",
            lambda: service.delete_secret(
                self.ctx.service.transport, self.bot_id, row.key
            ),
            self.reload,
        )


def secrets(ctx: SlashContext, args: str) -> None:
    ctx.app.push_screen(_SecretsPanel(ctx))


COMMANDS = (
    SlashCommand(
        "secrets", "Manage bot secrets", secrets, scope="session", needs_bot=True
    ),
)
