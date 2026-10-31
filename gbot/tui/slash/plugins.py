"""Browse catalog plugins and confirm per-bot changes."""

from collections.abc import Callable
from typing import ClassVar

from rich.text import Text
from textual import events
from textual.widgets import Input, Select, Static

from gbot.commands.catalog import field_text
from gbot.commands.plugins import plugin_text
from gbot.output import terminal_safe
from gbot.service import plugins as service
from gbot.tui.panels.kit import (
    Detail,
    FormField,
    FormPanel,
    ListPanel,
    PanelAction,
    PanelRow,
)
from gbot.tui.screens.confirm import ConfirmScreen
from gbot.tui.slash import SlashCommand, SlashContext
from gbot.tui.slash.avatar_voice import _Detail
from gbot.tui.slash.rooms import _writable


def _worker(ctx: SlashContext, work: Callable[[], None]) -> None:
    def run() -> None:
        try:
            work()
        except Exception as error:  # noqa: BLE001 - worker boundary
            ctx.app.call_from_thread(
                ctx.app.notify,
                terminal_safe(str(error)),
                severity="error",
                markup=False,
            )

    ctx.app.run_worker(run, thread=True, exit_on_error=False)


def _confirm(ctx: SlashContext, title: str, work: Callable[[], None]) -> None:
    if not _writable(ctx):
        return

    def confirmed(ok: bool | None) -> None:
        if ok and _writable(ctx):

            def run() -> None:
                if ctx.app.read_only:
                    raise ValueError("Read-only mode")
                work()

            _worker(ctx, run)

    ctx.app.push_screen(ConfirmScreen(terminal_safe(title), "", "Save"), confirmed)


class _List(ListPanel):
    AUTO_FOCUS: ClassVar[str | None] = ""

    def __init__(self, ctx: SlashContext, *args, **kwargs) -> None:
        self.ctx = ctx
        super().__init__(*args, **kwargs)

    def on_mount(self) -> None:
        super().on_mount()
        self.set_focus(None)

    def _loaded(self, rows: list[PanelRow], error: str) -> None:
        super()._loaded(rows, error)
        if error:
            self.ctx.app.notify(terminal_safe(error), severity="error", markup=False)


class _SettingsForm(FormPanel):
    def __init__(
        self,
        ctx: SlashContext,
        plugin: service.Plugin,
        fields: list[service.Field],
        done: Callable[[], None],
    ) -> None:
        self.ctx, self.plugin, self.done = ctx, plugin, done
        self.options = {
            f.key: dict(f.options) for f in fields if f.options and not f.secret
        }
        super().__init__(
            f"{plugin.display_name} settings",
            tuple(
                FormField(
                    f.key,
                    f.label,
                    "password" if f.secret else "choice" if f.options else "text",
                    choices=tuple(label for label, _ in f.options),
                    hint=f.hint + (" · required" if f.required else ""),
                )
                for f in fields
            ),
            self.save,
        )

    def clear(self) -> None:
        for i, field in enumerate(self.fields):
            widget = self.query_one(f"#form-{i}")
            if isinstance(widget, Input):
                widget.value = ""
            elif isinstance(widget, Select):
                widget.value = Select.BLANK

    def action_submit(self) -> None:
        if not _writable(self.ctx):
            return

        def confirmed(ok: bool | None) -> None:
            if ok and _writable(self.ctx):
                super(_SettingsForm, self).action_submit()
            self.clear()

        self.ctx.app.push_screen(
            ConfirmScreen(
                terminal_safe(f"Save settings for {self.plugin.display_name}?"),
                "",
                "Save",
            ),
            confirmed,
        )

    def save(self, values: dict[str, str | bool]) -> None:
        try:
            if self.ctx.app.read_only:
                raise ValueError("Read-only mode")
            service.set_variables(
                self.ctx.service.transport,
                self.ctx.bot_id or "",
                self.plugin.plugin_id,
                {
                    key: self.options.get(key, {}).get(str(value), value)
                    for key, value in values.items()
                },
            )
        finally:
            values.clear()

    def _submit_done(self, message: str) -> None:
        self.clear()
        super()._submit_done(message)
        self.done()

    def _submit_error(self, message: str) -> None:
        self.clear()
        super()._submit_error(terminal_safe(message))
        self.ctx.app.notify(terminal_safe(message), severity="error", markup=False)

    def action_back(self) -> None:
        self.clear()
        super().action_back()


def _settings(
    ctx: SlashContext,
    plugin: service.Plugin,
    entry: service.CatalogEntry | None,
    done: Callable[[], None],
) -> None:
    if not _writable(ctx):
        return
    fields = service.variable_fields(plugin, entry)
    if not fields:
        ctx.app.notify("No settings for this plugin", markup=False)
        return
    ctx.app.push_screen(_SettingsForm(ctx, plugin, fields, done))


class _CatalogPanel(_List):
    def __init__(
        self, ctx: SlashContext, done: Callable[[], None] = lambda: None
    ) -> None:
        self.entries: dict[str, service.CatalogEntry] = {}
        self.done = done
        super().__init__(
            ctx,
            "Connector catalog",
            self.load_catalog,
            on_select=self.open_entry,
            filterable=True,
            actions=(PanelAction("a", "Add to bot", self.add),) if ctx.bot_id else (),
        )

    def load_catalog(self) -> list[PanelRow]:
        entries = service.catalog(self.ctx.service.transport)
        self.entries = {e.id: e for e in entries}
        rows = []
        for category in dict.fromkeys(e.category or "Other" for e in entries):
            rows.append(PanelRow(f"heading:{category}", category))
            rows.extend(
                PanelRow(
                    e.id,
                    e.display_name,
                    f"{e.publisher} · {len(e.connector_names)} connectors",
                )
                for e in entries
                if (e.category or "Other") == category
            )
        return rows

    @property
    def visible_rows(self) -> list[PanelRow]:
        if not self.is_mounted:
            return self.rows
        value = self.query_one("#panel-filter", Input).value.casefold()
        rows, heading, added = [], None, False
        for row in self.rows:
            if row.key.startswith("heading:"):
                heading, added = row, False
            elif value in row.label.casefold() or (
                heading and value in heading.label.casefold()
            ):
                if heading and not added:
                    rows.append(heading)
                    added = True
                rows.append(row)
        return rows

    def _draw(self) -> None:
        super()._draw()
        widget = self.query_one("#panel-rows", Static)
        if isinstance(widget.content, Text):
            text = widget.content.copy()
            offset = 0
            for line in text.plain.splitlines(keepends=True):
                if any(
                    r.key.startswith("heading:") and line[2:].rstrip() == r.label
                    for r in self.visible_rows
                ):
                    text.stylize("dim", offset, offset + len(line))
                offset += len(line)
            widget.update(text)

    def open_entry(self, row: PanelRow) -> None:
        entry = self.entries.get(row.key)
        if entry is None:
            return
        self.ctx.app.push_screen(
            _Detail(
                entry.display_name,
                lambda: Detail(
                    (
                        ("Description", entry.description),
                        ("Publisher", entry.publisher),
                        ("Connectors", ", ".join(entry.connector_names)),
                        (
                            "Setup fields",
                            "\n".join(field_text(f) for f in entry.fields) or "None",
                        ),
                    ),
                    actions=(PanelAction("a", "Add to bot", lambda: self.add(row)),)
                    if self.ctx.bot_id
                    else (),
                ),
            )
        )

    def add(self, row: PanelRow) -> None:
        entry = self.entries.get(row.key)
        bot = self.ctx.app.state.bots.get(self.ctx.bot_id or "")
        if entry is None or bot is None:
            return

        def run() -> None:
            result = service.add_plugin(self.ctx.service.transport, bot.id, entry)
            plugin = next((p for p in result if str(p.plugin_id) == entry.id), None)

            def done() -> None:
                self.done()
                if (
                    plugin
                    and not plugin.has_configured_variables
                    and service.variable_fields(plugin, entry)
                ):
                    _settings(self.ctx, plugin, entry, self.done)

            self.ctx.app.call_from_thread(done)

        _confirm(self.ctx, f"Add {entry.display_name} to {bot.name}?", run)


class _PluginsPanel(_List):
    def __init__(self, ctx: SlashContext) -> None:
        self.plugins: dict[str, service.Plugin] = {}
        self.bot = ctx.app.state.bots[ctx.bot_id or ""]
        super().__init__(
            ctx,
            f"{self.bot.name} plugins",
            self.load_plugins,
            on_select=self.open_plugin,
            empty="No plugins",
            filterable=True,
            actions=(
                PanelAction("a", "Add", self.add),
                PanelAction("x", "Remove", self.remove_plugin),
                PanelAction("v", "Settings", self.settings),
            ),
        )

    def load_plugins(self) -> list[PanelRow]:
        self.plugins = {
            str(p.plugin_id): p
            for p in service.bot_plugins(self.ctx.service.transport, self.bot.id)
            if not p.is_bot_skills
        }
        return [
            PanelRow(key, p.display_name, plugin_text(p))
            for key, p in self.plugins.items()
        ]

    def on_key(self, event: events.Key) -> None:
        if isinstance(self.focused, Input):
            super().on_key(event)
            return
        if event.key == "a":
            self.add()
            event.stop()
            event.prevent_default()
        elif event.key in {"x", "v"} and not _writable(self.ctx):
            event.stop()
            event.prevent_default()
        else:
            super().on_key(event)

    def add(self, row: PanelRow | None = None) -> None:
        if _writable(self.ctx):
            self.ctx.app.push_screen(_CatalogPanel(self.ctx, self.reload))

    def open_plugin(self, row: PanelRow) -> None:
        plugin = self.plugins[row.key]
        self.ctx.app.push_screen(
            _Detail(
                plugin.display_name,
                lambda: Detail(
                    (
                        ("Description", plugin.description),
                        ("Skills", ", ".join(plugin.skill_names)),
                        ("Servers", ", ".join(plugin.server_names)),
                        ("Install mode", plugin.install_mode),
                        ("Credential source", plugin.credential_source),
                    )
                ),
            )
        )

    def remove_plugin(self, row: PanelRow) -> None:
        plugin = self.plugins[row.key]

        def run() -> None:
            service.remove_plugin(
                self.ctx.service.transport, self.bot.id, plugin.plugin_id
            )
            self.ctx.app.call_from_thread(self.reload)

        _confirm(self.ctx, f"Remove {plugin.display_name} from {self.bot.name}?", run)

    def settings(self, row: PanelRow) -> None:
        if not _writable(self.ctx):
            return
        plugin = self.plugins[row.key]

        def load() -> None:
            entry = next(
                (
                    e
                    for e in service.catalog(self.ctx.service.transport)
                    if e.id == str(plugin.plugin_id)
                ),
                None,
            )
            self.ctx.app.call_from_thread(
                _settings, self.ctx, plugin, entry, self.reload
            )

        _worker(self.ctx, load)


def catalog(ctx: SlashContext, args: str) -> None:
    ctx.app.push_screen(_CatalogPanel(ctx))


def plugins(ctx: SlashContext, args: str) -> None:
    ctx.app.push_screen(_PluginsPanel(ctx))


COMMANDS = (
    SlashCommand("catalog", "Browse connector catalog", catalog),
    SlashCommand(
        "plugins", "Manage bot plugins", plugins, scope="session", needs_bot=True
    ),
)
