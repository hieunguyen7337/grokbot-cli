"""Confirmed Teams setup and human account linking."""

from collections.abc import Callable
from datetime import UTC, datetime

from textual import events
from textual.widgets import Static

from gbot.output import terminal_safe
from gbot.service import teams as service
from gbot.service.handoff import HandoffResult
from gbot.tui.panels.kit import Detail, FormField, ListPanel, PanelAction, PanelRow
from gbot.tui.screens.confirm import ConfirmScreen
from gbot.tui.screens.handoff import HandoffScreen
from gbot.tui.slash import SlashCommand, SlashContext
from gbot.tui.slash.avatar_voice import _Detail, _Form
from gbot.tui.slash.rooms import _writable


def _worker(
    ctx: SlashContext, work: Callable[[], object], done: Callable[[object], object]
) -> None:
    def run() -> None:
        try:
            result = work()
        except Exception as error:  # noqa: BLE001 - worker boundary
            ctx.app.call_from_thread(
                ctx.app.notify,
                terminal_safe(str(error)),
                severity="error",
                markup=False,
            )
        else:
            ctx.app.call_from_thread(done, result)

    ctx.app.run_worker(run, thread=True, exit_on_error=False)


def _mutate(
    ctx: SlashContext,
    title: str,
    work: Callable[[], object],
    done: Callable[[object], object],
) -> None:
    if not _writable(ctx):
        return

    def confirmed(ok: bool | None) -> None:
        if not ok or not _writable(ctx):
            return

        def run() -> object:
            if ctx.app.read_only:
                raise ValueError("Read-only mode")
            return work()

        _worker(ctx, run, done)

    ctx.app.push_screen(ConfirmScreen(terminal_safe(title), "", "Continue"), confirmed)


class TeamsPanel(_Detail):
    def __init__(self, ctx: SlashContext) -> None:
        self.ctx = ctx
        self.bot = ctx.app.state.bots[ctx.bot_id or ""]
        self.state = service.TeamsState("unknown")
        self.nonce: str | None = None
        super().__init__(
            f"{terminal_safe(self.bot.name)} on Microsoft Teams", self.content
        )

    def on_mount(self) -> None:
        super().on_mount()
        self.reload()

    def content(self) -> Detail:
        state = self.state
        actions = []
        if state.state in {"not_connected", "removed", "removed_in_teams", "connected"}:
            actions.append(PanelAction("c", "Connect", self.connect))
        if state.state in {"connected", "app_created", "removed", "removed_in_teams"}:
            actions.append(PanelAction("i", "Install", self.install))
        if state.state in {"installed", "update_pending"}:
            actions.extend(
                (
                    PanelAction("a", "Add to a team", self.add),
                    PanelAction("r", "Reinstall", self.reinstall),
                    PanelAction("x", "Uninstall", self.uninstall),
                )
            )
        if state.tenant_id:
            actions.append(PanelAction("d", "Disconnect tenant", self.disconnect))
        actions.append(PanelAction("g", "Reload", self.reload))
        return Detail(
            (
                ("State", state.state),
                ("Tenant", state.tenant_name or state.tenant_id or "none"),
                ("Tenant ID", state.tenant_id or "none"),
                (
                    "Installed teams",
                    ", ".join(
                        str(team.get("displayName") or team.get("teamId"))
                        for team in state.installed_teams
                    )
                    or "none",
                ),
            ),
            body="\n".join(
                (
                    *state.messages,
                    "The manager is a Teams admin."
                    if state.manager_is_admin
                    else "The manager is not a Teams admin.",
                    state.rejection_note,
                )
            ),
            actions=tuple(actions),
        )

    def loaded(self, value: object) -> None:
        if isinstance(value, service.TeamsState):
            self.state = value
        self.detail = self.content()
        self.index = 0
        self._draw()
        self.query_one(".panel-footer", Static).update(
            " · ".join(f"{a.key} {a.label}" for a in self.detail.actions)
            + " · esc back"
        )

    def reload(self) -> None:
        _worker(
            self.ctx,
            lambda: service.install_state(self.ctx.service.transport, self.bot.id),
            self.loaded,
        )

    def completed(self, value: object) -> None:
        if isinstance(value, service.TeamsState) and value.failure_reason:
            self.ctx.app.notify(
                terminal_safe(service.sentence(value.failure_reason)),
                severity="error",
                markup=False,
            )
        self.reload()

    def connect(self) -> None:
        if not _writable(self.ctx):
            return

        def prepare(values: dict[str, str | bool]) -> None:
            admin = values["consent"] == "Admin"

            def review() -> None:
                self.ctx.app.pop_screen()

                def start() -> object:
                    return service.start_connect(
                        self.ctx.service.transport, self.bot.id, admin=admin
                    )

                def opened(value: object) -> None:
                    assert isinstance(value, tuple)
                    url, admin_url, nonce = value
                    self.nonce = str(nonce)
                    self.ctx.app.push_screen(
                        HandoffScreen(
                            "Connect to Teams",
                            admin_url if admin else url,
                            service.connect_check(
                                self.ctx.service.transport, self.bot.id, str(nonce)
                            ),
                        ),
                        self.connected,
                    )

                _mutate(
                    self.ctx,
                    f"Connect {self.bot.name} to Teams? Your browser opens.",
                    start,
                    opened,
                )

            self.ctx.app.call_from_thread(review)

        self.ctx.app.push_screen(
            _Form(
                self.ctx,
                "Teams consent",
                (
                    FormField(
                        "consent", "Consent", "choice", "Normal", ("Normal", "Admin")
                    ),
                ),
                prepare,
            )
        )

    def connected(self, result: HandoffResult | None) -> None:
        if result and result.status == "done":
            self.loaded(result.value)
            if (
                isinstance(result.value, service.TeamsState)
                and (
                    result.value.connected_account is not None
                    or result.value.state in {"connected", "app_created"}
                )
                and result.value.consent_result
                not in {"access_denied", "grant_conflict", "other"}
            ):
                self.install()

    def install(self) -> None:
        self._teams_form(False)

    def add(self) -> None:
        self._teams_form(True)

    def _teams_form(self, add: bool) -> None:
        if not _writable(self.ctx):
            return

        def loaded(value: object) -> None:
            assert isinstance(value, tuple)
            rows = value
            if add and not rows:
                self.ctx.app.notify("No joined teams available", markup=False)
                return
            labels = {
                str(row.get("displayName") or row.get("teamId"))
                + " ("
                + str(row.get("teamId"))
                + ")": str(row.get("teamId"))
                for row in rows
            }
            fields = (
                (
                    FormField(
                        "team",
                        "Team",
                        "choice",
                        next(iter(labels), ""),
                        tuple(labels),
                        required=True,
                    ),
                )
                if add
                else (
                    FormField("personal", "Install personally", "toggle", True),
                    *(
                        FormField("team:" + team_id, label, "toggle")
                        for label, team_id in labels.items()
                    ),
                )
            )

            def prepare(values: dict[str, str | bool]) -> None:
                ids = [
                    key.removeprefix("team:")
                    for key, selected in values.items()
                    if key.startswith("team:") and selected
                ]
                if not add and not values["personal"] and not ids:
                    raise ValueError(
                        "Select personal installation or at least one team"
                    )

                def review() -> None:
                    self.ctx.app.pop_screen()

                    def work() -> object:
                        if add:
                            row = service.add_to_team(
                                self.ctx.service.transport,
                                self.bot.id,
                                labels[str(values["team"])],
                                nonce=self.nonce,
                            )
                            if row.get("failureReason"):
                                raise ValueError(
                                    service.sentence(str(row["failureReason"]))
                                )
                            return service.install_state(
                                self.ctx.service.transport, self.bot.id
                            )
                        return service.install(
                            self.ctx.service.transport,
                            self.bot.id,
                            tenant_id=self.state.tenant_id,
                            team_ids=ids,
                            personal=bool(values["personal"]),
                            nonce=self.nonce,
                        )

                    _mutate(
                        self.ctx,
                        f"{'Add' if add else 'Install'} {self.bot.name}'s Teams app?",
                        work,
                        self.loaded if add else self.completed,
                    )

                self.ctx.app.call_from_thread(review)

            self.ctx.app.push_screen(
                _Form(
                    self.ctx,
                    "Add to a team" if add else "Install Teams app",
                    fields,
                    prepare,
                )
            )

        _worker(
            self.ctx,
            lambda: service.joined_teams(self.ctx.service.transport, self.bot.id),
            loaded,
        )

    def reinstall(self) -> None:
        _mutate(
            self.ctx,
            f"Reinstall {self.bot.name}'s Teams app?",
            lambda: service.reinstall(
                self.ctx.service.transport, self.bot.id, nonce=self.nonce
            ),
            self.completed,
        )

    def uninstall(self) -> None:
        _mutate(
            self.ctx,
            f"Remove {self.bot.name}'s Teams app?",
            lambda: service.uninstall(self.ctx.service.transport, self.bot.id),
            self.completed,
        )

    def disconnect(self) -> None:
        if not _writable(self.ctx):
            return
        tenant = self.state.tenant_id
        if not tenant:
            return

        def done(value: object) -> None:
            assert isinstance(value, tuple)
            self.ctx.app.notify(
                terminal_safe(
                    "Bots still installed: " + (", ".join(value[2]) or "none")
                ),
                markup=False,
            )
            self.reload()

        _mutate(
            self.ctx,
            f"Disconnect Teams tenant {self.state.tenant_name or tenant}?",
            lambda: service.disconnect(self.ctx.service.transport, self.bot.id, tenant),
            done,
        )


class TeamsAccountPanel(ListPanel):
    def __init__(self, ctx: SlashContext) -> None:
        self.ctx = ctx
        super().__init__(
            "Teams account",
            self.links,
            empty="No Teams account linked",
            actions=(
                PanelAction("l", "Link", self.link),
                PanelAction("x", "Unlink", self.unlink),
            ),
        )

    def links(self) -> list[PanelRow]:
        return [
            PanelRow(
                link.tenant_id,
                link.tenant_id,
                datetime.fromtimestamp(link.linked_at_ms / 1000, UTC).strftime(
                    "%Y-%m-%d"
                ),
            )
            for link in service.account_links(self.ctx.service.transport)
        ]

    def on_key(self, event: events.Key) -> None:
        if event.key == "l":
            self.link()
            event.stop()
            event.prevent_default()
        else:
            super().on_key(event)

    def link(self, row: PanelRow | None = None) -> None:
        def start() -> object:
            before = service.account_links(self.ctx.service.transport)
            return service.start_account_link(self.ctx.service.transport), before

        def opened(value: object) -> None:
            assert isinstance(value, tuple)
            url, before = value

            def finished(result: HandoffResult | None) -> None:
                if result and result.status == "done":
                    self.reload()

            self.ctx.app.push_screen(
                HandoffScreen(
                    "Link your Teams account",
                    url,
                    service.account_link_check(self.ctx.service.transport, before),
                    timeout_s=120,
                ),
                finished,
            )

        _mutate(self.ctx, "Link your Teams account? Your browser opens.", start, opened)

    def unlink(self, row: PanelRow) -> None:
        _mutate(
            self.ctx,
            f"Unlink your Teams account in {row.label}?",
            lambda: service.unlink_account(self.ctx.service.transport, row.key),
            lambda _: self.reload(),
        )


def teams(ctx: SlashContext, args: str) -> None:
    ctx.app.push_screen(TeamsPanel(ctx))


def teams_account(ctx: SlashContext, args: str) -> None:
    ctx.app.push_screen(TeamsAccountPanel(ctx))


COMMANDS = (
    SlashCommand(
        "teams", "Manage Microsoft Teams", teams, scope="session", needs_bot=True
    ),
    SlashCommand("teams-account", "Link your Teams account", teams_account),
)
