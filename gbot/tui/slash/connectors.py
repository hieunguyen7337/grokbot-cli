"""Confirmed account connector and tool controls."""

from collections.abc import Callable, Sequence

from textual import events
from textual.message import Message

from gbot.output import terminal_safe
from gbot.service import connectors as service
from gbot.service.events import Other
from gbot.service.handoff import HandoffResult
from gbot.tui.app import ServiceEvent
from gbot.tui.panels.kit import (
    Detail,
    FormField,
    FormPanel,
    ListPanel,
    PanelAction,
    PanelRow,
)
from gbot.tui.screens.confirm import ConfirmScreen
from gbot.tui.screens.handoff import HandoffScreen
from gbot.tui.slash import SlashCommand, SlashContext
from gbot.tui.slash.avatar_voice import _Detail
from gbot.tui.slash.rooms import _writable

CHOICES = ("Auto review", "Always allow", "Needs approval", "Blocked")


def _worker(ctx: SlashContext, work: Callable[[], object]) -> None:
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


def _confirm(
    ctx: SlashContext,
    title: str,
    work: Callable[[], object],
    done: Callable[[], object],
) -> None:
    if not _writable(ctx):
        return

    def confirmed(ok: bool | None) -> None:
        if not ok or not _writable(ctx):
            return

        def run() -> None:
            if ctx.app.read_only:
                raise ValueError("Read-only mode")
            work()
            ctx.app.call_from_thread(done)

        _worker(ctx, run)

    ctx.app.push_screen(ConfirmScreen(terminal_safe(title), "", "Confirm"), confirmed)


class _Form(FormPanel):
    def __init__(
        self,
        ctx: SlashContext,
        title: str,
        fields: Sequence[FormField],
        work: Callable[[dict[str, str | bool]], object],
        done: Callable[[], object],
    ) -> None:
        self.ctx, self.done = ctx, done

        def save(values: dict[str, str | bool]) -> None:
            if ctx.app.read_only:
                raise ValueError("Read-only mode")
            work(values)

        super().__init__(title, fields, save, confirm=title)

    def action_submit(self) -> None:
        if _writable(self.ctx):
            super().action_submit()

    def _submit_done(self, message: str) -> None:
        super()._submit_done(message)
        self.done()

    def _submit_error(self, message: str) -> None:
        super()._submit_error(message)
        self.ctx.app.notify(terminal_safe(message), severity="error", markup=False)


class _Handoff(HandoffScreen):
    def _finished(self, result: HandoffResult | None, message: str) -> None:
        if self.cancel.is_set() or not self.is_mounted:
            return
        if result and result.status == "timeout":
            self._waiting = False
            self._status(service.TIMEOUT)
        else:
            super()._finished(result, message)


class ConnectorsPanel(ListPanel):
    def __init__(self, ctx: SlashContext) -> None:
        self.ctx = ctx
        self.servers: list[service.Server] = []
        super().__init__(
            "Connectors",
            self.load_rows,
            on_select=self.open_connector,
            actions=(
                PanelAction("A", "Forget always allow", self.clear),
                PanelAction("r", "Reload", lambda *_: self.reload()),
            ),
        )

    def load_rows(self) -> list[PanelRow]:
        self.servers = service.servers(self.ctx.service.transport)
        return [
            PanelRow(
                s.id,
                s.plugin_name or s.name,
                f"{s.account_key or '-'} · {service.status_sentence(s)} · {s.tool_count} tools",
            )
            for s in self.servers
        ]

    def open_connector(self, row: PanelRow) -> None:
        self.ctx.app.push_screen(
            ConnectorPanel(self.ctx, service.find(self.servers, row.key))
        )

    def clear(self, *_: object) -> None:
        _confirm(
            self.ctx,
            'Forget every "always allow" answer for connector tools?',
            lambda: service.clear_always_allow(self.ctx.service.transport),
            self.reload,
        )

    def on_key(self, event: events.Key) -> None:
        if event.key == "A" and not self.visible_rows:
            self.clear()
            event.stop()
            event.prevent_default()
        else:
            super().on_key(event)


class ConnectorPanel(_Detail):
    def __init__(self, ctx: SlashContext, server: service.Server) -> None:
        self.ctx, self.server = ctx, server
        self.shared = False
        self.auth_events: list[dict[str, object]] = []
        super().__init__(terminal_safe(server.plugin_name or server.name), self.content)

    def on_mount(self) -> None:
        super().on_mount()
        self.ctx.app.message_signal.subscribe(self, self.changed)
        self.reload()

    def on_unmount(self) -> None:
        self.ctx.app.message_signal.unsubscribe(self)

    def changed(self, message: Message) -> None:
        if (
            isinstance(message, ServiceEvent)
            and isinstance(message.event, Other)
            and message.event.channel == "mcp-auth"
            and isinstance(message.event.payload, dict)
        ):
            self.auth_events.append(message.event.payload)
            for screen in self.ctx.app.screen_stack:
                if isinstance(screen, _Handoff):
                    screen.poke()

    def content(self) -> Detail:
        s = self.server
        actions = [
            PanelAction("t", "Tools", self.open_tools),
            PanelAction("i", "Instructions", self.instructions),
            PanelAction("s", "Sign in", self.sign_in),
        ]
        if s.account_key:
            actions.extend(
                (
                    PanelAction("n", "Rename account", self.rename),
                    PanelAction("x", "Remove account", self.remove_account),
                )
            )
        if not s.is_team:
            actions.append(PanelAction("X", "Remove connector", self.remove_connector))
        actions.extend(
            (
                PanelAction(
                    "g",
                    "Stop allowing in group chats"
                    if self.shared
                    else "Allow in group chats",
                    self.group,
                ),
                PanelAction("r", "Reload", self.reload),
            )
        )
        return Detail(
            (
                ("Status", service.status_sentence(s)),
                ("Account", s.account_key or "-"),
                ("Transport", s.transport or "-"),
                ("Tools", str(s.tool_count)),
                ("Group chats", "allowed" if self.shared else "not allowed"),
                ("Instructions", s.custom_instructions or "-"),
            ),
            actions=actions,
        )

    def reload(self) -> None:
        def load() -> None:
            server = service.find(
                service.servers(self.ctx.service.transport), self.server.id
            )
            shared = server.id in service.shared_spaces(self.ctx.service.transport)

            def loaded() -> None:
                self.server, self.shared = server, shared
                self.detail = self.content()
                self.index = min(self.index, len(self.detail.actions) - 1)
                self._draw()

            self.ctx.app.call_from_thread(loaded)

        _worker(self.ctx, load)

    def open_tools(self) -> None:
        self.ctx.app.push_screen(ConnectorToolsPanel(self.ctx, self.server))

    def form(
        self,
        title: str,
        fields: Sequence[FormField],
        work: Callable[[dict[str, str | bool]], object],
    ) -> None:
        if _writable(self.ctx):
            self.ctx.app.push_screen(_Form(self.ctx, title, fields, work, self.reload))

    def instructions(self) -> None:
        self.form(
            f"Save instructions for {self.heading}?",
            (
                FormField(
                    "text", "Instructions", "multiline", self.server.custom_instructions
                ),
            ),
            lambda v: service.set_instructions(
                self.ctx.service.transport, self.server.id, str(v["text"])
            ),
        )

    def rename(self) -> None:
        self.form(
            f"Rename account {self.server.account_key} for {self.heading}?",
            (
                FormField(
                    "key", "Account name", value=self.server.account_key, required=True
                ),
            ),
            lambda v: service.rename_account(
                self.ctx.service.transport,
                self.server.id,
                self.server.account_key,
                str(v["key"]).strip(),
            ),
        )

    def remove_account(self) -> None:
        _confirm(
            self.ctx,
            f"Remove account {self.server.account_key} from {self.heading}?",
            lambda: service.remove_account(
                self.ctx.service.transport, self.server.id, self.server.account_key
            ),
            self.reload,
        )

    def remove_connector(self) -> None:
        if self.server.is_team:
            return

        def removed() -> None:
            self.ctx.app.pop_screen()
            if isinstance(self.ctx.app.screen, ConnectorsPanel):
                self.ctx.app.screen.reload()

        _confirm(
            self.ctx,
            f"Remove {self.heading}? Its tools stop working for every bot.",
            lambda: service.remove_server(self.ctx.service.transport, self.server.id),
            removed,
        )

    def group(self) -> None:
        _confirm(
            self.ctx,
            f"{'Stop allowing' if self.shared else 'Allow'} {self.heading} in group chats?",
            lambda: service.set_shared_space(
                self.ctx.service.transport, self.server.id, not self.shared
            ),
            self.reload,
        )

    def sign_in(self) -> None:
        def start() -> None:
            self.auth_events.clear()
            before = service.find(
                service.servers(self.ctx.service.transport), self.server.id
            )
            outcome, url, sentence = service.start_sign_in(
                self.ctx.service.transport,
                before.id,
                account_key=before.account_key or None,
                reauth=before.status_kind
                not in {"authentication_required", "sign_in_pending"},
            )

            def show() -> None:
                if outcome == "started" and url:
                    self.ctx.app.push_screen(
                        _Handoff(
                            f"Sign in to {self.heading}",
                            url,
                            service.sign_in_check(
                                self.ctx.service.transport, before, self.auth_events
                            ),
                            instruction=service.TIMEOUT,
                        ),
                        self.signed_in,
                    )
                else:
                    self.ctx.app.notify(sentence, markup=False)

            self.ctx.app.call_from_thread(show)

        _confirm(
            self.ctx,
            f"Sign in to {self.heading}? Your browser opens.",
            start,
            lambda: None,
        )

    def signed_in(self, result: HandoffResult | None) -> None:
        if result and result.status == "done":
            if isinstance(result.value, str):
                self.ctx.app.notify(
                    terminal_safe(result.value), severity="error", markup=False
                )
            else:
                self.reload()


class ConnectorToolsPanel(ListPanel):
    def __init__(self, ctx: SlashContext, server: service.Server) -> None:
        self.ctx, self.server = ctx, server
        self.tools: list[service.Tool] = []
        self.policy = service.Policy({})
        super().__init__(
            f"{terminal_safe(server.plugin_name or server.name)} tools",
            self.load_rows,
            actions=(
                PanelAction("space", "Enable/disable", self.toggle),
                PanelAction("p", "Permission", self.permission),
                PanelAction("d", "Defaults", self.defaults),
                PanelAction("r", "Reload", lambda *_: self.reload()),
            ),
        )

    def load_rows(self) -> list[PanelRow]:
        self.tools = service.tools(self.ctx.service.transport, self.server.id)
        self.policy = service.policy(self.ctx.service.transport, self.server.id)
        return [
            PanelRow(
                t.name,
                t.name,
                f"{'read' if t.is_read_only else 'write'} · {t.permission}"
                + (" · disabled" if t.is_disabled else ""),
            )
            for t in self.tools
        ]

    def toggle(self, row: PanelRow) -> None:
        tool = next(t for t in self.tools if t.name == row.key)
        _confirm(
            self.ctx,
            f"{'Enable' if tool.is_disabled else 'Disable'} {tool.name}?",
            lambda: service.set_tool_disabled(
                self.ctx.service.transport,
                self.server.id,
                tool.name,
                not tool.is_disabled,
            ),
            self.reload,
        )

    def permission(self, row: PanelRow) -> None:
        if not _writable(self.ctx):
            return
        tool = next(t for t in self.tools if t.name == row.key)
        self.ctx.app.push_screen(
            _Form(
                self.ctx,
                f"Change permission for {tool.name}?",
                (
                    FormField(
                        "level",
                        "Permission",
                        "choice",
                        CHOICES[service.LABELS.index(tool.permission)],
                        CHOICES,
                    ),
                ),
                lambda v: service.set_permission(
                    self.ctx.service.transport,
                    self.server.id,
                    tool=(tool.name, service.LABELS[CHOICES.index(str(v["level"]))]),
                ),
                self.reload,
            )
        )

    def defaults(self, *_: object) -> None:
        if not _writable(self.ctx):
            return
        self.ctx.app.push_screen(
            _Form(
                self.ctx,
                f"Change defaults for {self.server.plugin_name or self.server.name}?",
                tuple(
                    FormField(
                        key,
                        key.title(),
                        "choice",
                        CHOICES[service.LABELS.index(value or "auto_review")],
                        CHOICES,
                    )
                    for key, value in (
                        ("reads", self.policy.reads),
                        ("writes", self.policy.writes),
                    )
                ),
                lambda v: service.set_permission(
                    self.ctx.service.transport,
                    self.server.id,
                    reads=service.LABELS[CHOICES.index(str(v["reads"]))],
                    writes=service.LABELS[CHOICES.index(str(v["writes"]))],
                ),
                self.reload,
            )
        )

    def on_key(self, event: events.Key) -> None:
        if event.key == "d" and not self.visible_rows:
            self.defaults()
            event.stop()
            event.prevent_default()
        else:
            super().on_key(event)


def connectors(ctx: SlashContext, args: str) -> None:
    ctx.app.push_screen(ConnectorsPanel(ctx))


COMMANDS = (SlashCommand("connectors", "Manage account connectors", connectors),)
