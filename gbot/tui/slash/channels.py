"""Confirmed Slack, texting and listener panels."""

from collections.abc import Callable

from textual.widgets import Static

from gbot.output import terminal_safe
from gbot.service import channels as service
from gbot.service.handoff import HandoffResult
from gbot.tui.panels.kit import Detail, ListPanel, PanelAction, PanelRow
from gbot.tui.screens.confirm import ConfirmScreen
from gbot.tui.screens.handoff import HandoffScreen
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

    ctx.app.push_screen(ConfirmScreen(terminal_safe(title), "", "Continue"), confirmed)


class _ListenerHandoff(HandoffScreen):
    def _finished(self, result: HandoffResult | None, message: str) -> None:
        super()._finished(result, message)
        if result and result.status == "timeout" and self.is_mounted:
            self._status(service.CALLBACK_HINT)
            self.app.notify(service.CALLBACK_HINT, markup=False)


class SlackPanel(_Detail):
    def __init__(self, ctx: SlashContext) -> None:
        self.ctx = ctx
        self.bot = ctx.app.state.bots[ctx.bot_id or ""]
        self.state: service.SlackState | None = None
        super().__init__(f"{terminal_safe(self.bot.name)} on Slack", self.content)

    def on_mount(self) -> None:
        super().on_mount()
        self.reload()

    def content(self) -> Detail:
        state = self.state
        if state is None:
            return Detail((), "Loading…")
        actions = []
        if state.status in {"not_connected", "app_created", "connected"}:
            actions.append(PanelAction("c", "Connect", lambda: self.mutate("connect")))
            if (
                state.workspaces
                and state.status != "connected"
                or state.removed_in_slack
            ):
                actions.append(PanelAction("i", "Install", self.install))
            if state.status in {"app_created", "connected"}:
                actions.extend(
                    (
                        PanelAction("r", "Reinstall", lambda: self.mutate("reinstall")),
                        PanelAction("x", "Uninstall", lambda: self.mutate("uninstall")),
                    )
                )
        actions.append(PanelAction("g", "Reload", self.reload))
        body = "\n".join(
            text
            for flag, text in (
                (state.needs_manifest_update, "The Slack app needs a manifest update."),
                (
                    state.pending_reinstall_approval,
                    "Waiting for a Slack admin to approve the reinstall.",
                ),
                (state.app_unreachable, "The Slack app is unreachable."),
                (state.removed_in_slack, "The app was removed in Slack."),
            )
            if flag
        )
        return Detail(
            (
                ("Status", state.status),
                ("Workspace", state.workspace_name or "none"),
                ("Workspaces", str(len(state.workspaces))),
            ),
            body,
            tuple(actions),
        )

    def loaded(self, state: service.SlackState) -> None:
        if not self.is_mounted:
            return
        self.state = state
        self.detail = self.content()
        self.index = min(self.index, max(0, len(self.detail.actions) - 1))
        self._draw()
        self.query_one(".panel-footer", Static).update(
            " · ".join(f"{a.key} {a.label}" for a in self.detail.actions)
            + " · esc back"
        )

    def reload(self) -> None:
        def load() -> None:
            state = service.slack_state(self.ctx.service.transport, self.bot.id)
            self.ctx.app.call_from_thread(self.loaded, state)

        _worker(self.ctx, load)

    def install(self) -> None:
        if not _writable(self.ctx) or self.state is None:
            return
        workspaces = self.state.workspaces
        if len(workspaces) <= 1:
            self.mutate(
                "install", str(workspaces[0]["slackTeamId"]) if workspaces else None
            )
            return

        def choose(row: PanelRow) -> None:
            self.ctx.app.pop_screen()
            # The confirmation result must belong to this persistent panel,
            # rather than the chooser whose message queue is closing.
            self.call_later(self.mutate, "install", row.key)

        self.ctx.app.push_screen(
            ListPanel(
                "Choose a workspace",
                lambda: [
                    PanelRow(
                        str(w["slackTeamId"]),
                        str(w.get("slackTeamName") or w["slackTeamId"]),
                    )
                    for w in workspaces
                ],
                on_select=choose,
            )
        )

    def mutate(self, verb: str, workspace: str | None = None) -> None:
        before = self.state
        if before is None:
            return
        title = (
            f"Remove {self.bot.name}'s Slack app from {before.workspace_name or 'Slack'}?"
            if verb == "uninstall"
            else f"Connect {self.bot.name} to Slack? Your browser opens."
        )

        def work() -> None:
            transport = self.ctx.service.transport
            if verb == "install":
                result = service.install_slack(transport, self.bot.id, workspace)
            else:
                action = {
                    "connect": service.start_slack_connect,
                    "reinstall": service.reinstall_slack,
                    "uninstall": service.uninstall_slack,
                }[verb]
                result = action(transport, self.bot.id)
            _, url, message = result
            if message:
                self.ctx.app.call_from_thread(
                    self.ctx.app.notify, terminal_safe(message), markup=False
                )
            if url:

                def finished(result: HandoffResult | None) -> None:
                    if (
                        result
                        and result.status == "done"
                        and isinstance(result.value, service.SlackState)
                    ):
                        self.loaded(result.value)

                self.ctx.app.call_from_thread(
                    self.ctx.app.push_screen,
                    HandoffScreen(
                        "Slack",
                        url,
                        service.slack_check(transport, self.bot.id, before),
                    ),
                    finished,
                )
            else:
                state = service.slack_state(transport, self.bot.id)
                self.ctx.app.call_from_thread(self.loaded, state)

        _confirm(self.ctx, title, work)


class SmsPanel(_Detail):
    def __init__(self, ctx: SlashContext) -> None:
        self.ctx = ctx
        self.link: service.MessagingLink | None = None
        self.phones: tuple[service.LinkedPhone, ...] = ()
        super().__init__("Text your bots", self.content)

    def on_mount(self) -> None:
        super().on_mount()
        self.reload()

    def content(self) -> Detail:
        if self.link is None:
            return Detail((), "Loading…")
        if not self.link.available:
            return Detail((), self.link.unavailable_reason)
        fields = [("Line number", self.link.line_number or "none")]
        fields.extend(
            (
                p.address,
                f"{p.handle_id} · linked {p.linked_at_ms} · last seen {p.last_seen_at_ms}",
            )
            for p in self.phones
        )
        body = "No linked phones" if not self.phones else ""
        if self.link.pending_code:
            code, expires, message, uri = self.link.pending_code
            body += f"\nCode: {code} (expires {expires})\n{message}\n{uri}"
        actions = [PanelAction("l", "Link a phone", self.issue)]
        if self.phones:
            actions.append(PanelAction("x", "Unlink a phone", self.unlink))
        actions.append(PanelAction("g", "Reload", self.reload))
        return Detail(fields, body.strip(), actions)

    def loaded(
        self, link: service.MessagingLink, phones: tuple[service.LinkedPhone, ...]
    ) -> None:
        if not self.is_mounted:
            return
        self.link, self.phones = link, phones
        self.detail = self.content()
        self.index = 0
        self._draw()
        self.query_one(".panel-footer", Static).update(
            " · ".join(f"{a.key} {a.label}" for a in self.detail.actions)
            + " · esc back"
        )

    def reload(self) -> None:
        def load() -> None:
            link = service.messaging_link(self.ctx.service.transport)
            phones = (
                service.linked_phones(self.ctx.service.transport)
                if link.available
                else ()
            )
            self.ctx.app.call_from_thread(self.loaded, link, phones)

        _worker(self.ctx, load)

    def issue(self) -> None:
        def work() -> None:
            link = service.issue_link_code(self.ctx.service.transport)
            self.ctx.app.call_from_thread(self.loaded, link, self.phones)

        _confirm(self.ctx, "Link a phone? Send the code from your phone.", work)

    def unlink(self) -> None:
        if not _writable(self.ctx):
            return

        def choose(row: PanelRow) -> None:
            self.ctx.app.pop_screen()
            self.call_later(self.unlink_selected, row.key, row.label)

        if len(self.phones) == 1:
            self.unlink_selected(self.phones[0].handle_id, self.phones[0].address)
        else:
            self.ctx.app.push_screen(
                ListPanel(
                    "Choose a phone",
                    lambda: [PanelRow(p.handle_id, p.address) for p in self.phones],
                    on_select=choose,
                )
            )

    def unlink_selected(self, handle_id: str, address: str) -> None:
        def work() -> None:
            service.unlink_phone(self.ctx.service.transport, handle_id)
            self.ctx.app.call_from_thread(self.reload)

        _confirm(self.ctx, f"Unlink {address}?", work)


def slack(ctx: SlashContext, args: str) -> None:
    ctx.app.push_screen(SlackPanel(ctx))


def sms(ctx: SlashContext, args: str) -> None:
    ctx.app.push_screen(SmsPanel(ctx))


def listeners(ctx: SlashContext, args: str) -> None:
    def load() -> list[PanelRow]:
        return [
            PanelRow(
                r.platform,
                r.platform,
                f"{r.state} · connected: {r.is_connected} · needed by {r.needed_by_count} automations"
                + (f" · {r.detail}" if r.detail else "")
                + "".join(
                    f" · {s.get('kind')}: {s.get('scope')}" for s in r.scope_issues
                ),
            )
            for r in service.listener_integrations(ctx.service.transport)
        ]

    def connect(row: PanelRow) -> None:
        def work() -> None:
            url = service.listener_connect_url(ctx.service.transport, row.key)

            def finished(result: HandoffResult | None) -> None:
                if result and result.status == "done":
                    panel.reload()

            ctx.app.call_from_thread(
                ctx.app.push_screen,
                _ListenerHandoff(
                    "Connect " + row.label,
                    url,
                    service.listener_check(ctx.service.transport, row.key),
                ),
                finished,
            )

        _confirm(ctx, f"Connect {row.label}? Your browser opens.", work)

    panel = ListPanel(
        "Listeners",
        load,
        actions=(
            PanelAction("c", "Connect", connect),
            PanelAction("g", "Reload", lambda row: panel.reload()),
        ),
    )
    ctx.app.push_screen(panel)


COMMANDS = (
    SlashCommand("slack", "Manage Slack app", slack, scope="session", needs_bot=True),
    SlashCommand("sms", "Text your bots", sms),
    SlashCommand("listeners", "Connect event sources", listeners),
)
