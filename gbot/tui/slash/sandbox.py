"""Cloud computer state, confirmed recreate and upgrade schedule, and runtime settings."""

from collections.abc import Callable
from typing import Literal

from textual.widgets import Static

from gbot.output import terminal_safe
from gbot.service import sandbox as service
from gbot.service.errors import refusal
from gbot.tui.panels.kit import Detail, FormField, PanelAction
from gbot.tui.screens.confirm import ConfirmScreen
from gbot.tui.slash import SlashCommand, SlashContext
from gbot.tui.slash.avatar_voice import _Detail, _Form
from gbot.tui.slash.rooms import _writable
from groken.client import ConnectError

Severity = Literal["information", "warning", "error"]


def _notify(
    ctx: SlashContext, message: str, severity: Severity = "information"
) -> None:
    ctx.app.notify(terminal_safe(message), severity=severity, markup=False)


def _failure(error: Exception) -> tuple[str, Severity]:
    found = refusal(error)
    if found is not None:
        return found.message, "warning"
    return str(error).split("\n", 1)[0], "error"


def _worker(
    ctx: SlashContext, work: Callable[[], object], done: Callable[[object], object]
) -> None:
    def run() -> None:
        try:
            result = work()
        except Exception as error:  # noqa: BLE001 - worker boundary
            message, severity = _failure(error)
            ctx.app.call_from_thread(_notify, ctx, message, severity)
        else:
            ctx.app.call_from_thread(done, result)

    ctx.app.run_worker(run, thread=True, exit_on_error=False)


def _change(
    ctx: SlashContext,
    title: str,
    label: str,
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

    ctx.app.push_screen(ConfirmScreen(title, "", label), confirmed)


def _started(result: service.RecreateResult) -> str:
    return (
        f"Started: {'yes' if result.started else 'no'} · "
        f"Reason: {result.reason or 'none'} · "
        f"Operation: {result.operation_id or 'none'}"
    )


class _Live(_Detail):
    """A detail panel that redraws its actions and footer after each load or change."""

    def redraw(self) -> None:
        self.detail = self.load()
        self.index = min(self.index, len(self.detail.actions) - 1)
        self._draw()
        self.query_one(".panel-footer", Static).update(
            " · ".join(f"{a.key} {a.label}" for a in self.detail.actions)
            + " · esc back"
        )


class SandboxPanel(_Live):
    def __init__(self, ctx: SlashContext) -> None:
        self.ctx = ctx
        self.value = service.Overview()
        super().__init__("Cloud computer", self.content)

    def on_mount(self) -> None:
        super().on_mount()
        self.reload()

    def content(self) -> Detail:
        value = self.value
        actions = [
            PanelAction("r", "Recreate", self.recreate),
            PanelAction("f", "Force recreate", self.force),
            PanelAction(
                "s",
                "Reschedule upgrade" if value.schedule else "Schedule upgrade",
                self.schedule,
            ),
        ]
        if value.schedule is not None:
            actions.append(PanelAction("c", "Cancel upgrade", self.cancel))
        actions.append(PanelAction("g", "Reload", self.reload))
        return Detail(service.fields(value), body=value.notice, actions=tuple(actions))

    def reload(self) -> None:
        _worker(
            self.ctx,
            lambda: service.overview(self.ctx.service.transport),
            self.loaded,
        )

    def loaded(self, value: object) -> None:
        assert isinstance(value, service.Overview)
        self.value = value
        self.redraw()

    def recreate(self) -> None:
        if not _writable(self.ctx):
            return
        transport = self.ctx.service.transport
        fields = (
            FormField(
                "data",
                "Data",
                "choice",
                "Keep data",
                ("Keep data", "Discard data"),
                required=True,
            ),
            FormField(
                "confirm",
                "Type recreate to discard data",
                hint="Only needed to discard data",
            ),
        )

        def prepare(values: dict[str, str | bool]) -> None:
            keep = values["data"] != "Discard data"
            if not keep and str(values["confirm"]).strip() != "recreate":
                raise ValueError("Type recreate to discard data.")
            title = (
                "Recreate the cloud computer? Your data is kept."
                if keep
                else "Recreate the cloud computer and discard its data?"
            )

            def review() -> None:
                self.ctx.app.pop_screen()
                _change(
                    self.ctx,
                    title,
                    "Recreate",
                    lambda: service.recreate(transport, preserve_data=keep),
                    self.recreated,
                )

            self.ctx.app.call_from_thread(review)

        self.ctx.app.push_screen(
            _Form(self.ctx, "Recreate the cloud computer", fields, prepare)
        )

    def force(self) -> None:
        if not _writable(self.ctx):
            return
        transport = self.ctx.service.transport
        fields = (
            FormField(
                "confirm",
                "Type recreate to confirm",
                hint="This recreates the cloud computer now.",
            ),
        )

        def prepare(values: dict[str, str | bool]) -> None:
            if str(values["confirm"]).strip() != "recreate":
                raise ValueError("Type recreate to confirm.")

            def review() -> None:
                self.ctx.app.pop_screen()
                _change(
                    self.ctx,
                    "Force recreate the cloud computer?",
                    "Force recreate",
                    lambda: service.force_recreate(transport),
                    self.recreated,
                )

            self.ctx.app.call_from_thread(review)

        self.ctx.app.push_screen(_Form(self.ctx, "Force recreate", fields, prepare))

    def recreated(self, value: object) -> None:
        assert isinstance(value, service.RecreateResult)
        _notify(
            self.ctx,
            _started(value),
            "information" if value.started else "warning",
        )
        self.reload()

    def schedule(self) -> None:
        if not _writable(self.ctx):
            return
        transport = self.ctx.service.transport
        current = self.value.schedule
        rescheduling = current is not None
        fields = (
            FormField(
                "local_time",
                "Local time (HH:MM)",
                value=current.local_time if current else "03:30",
                required=True,
                hint="24-hour clock",
            ),
            FormField(
                "timezone",
                "Time zone",
                value=current.timezone if current and current.timezone else "UTC",
                required=True,
                hint="IANA name, such as Europe/Paris",
            ),
            FormField(
                "recurring",
                "Recurring",
                "toggle",
                current.recurring if current else False,
            ),
        )

        def prepare(values: dict[str, str | bool]) -> None:
            local_time = str(values["local_time"]).strip()
            timezone = str(values["timezone"]).strip()
            recurring = bool(values["recurring"])
            service.check_schedule(timezone, local_time)

            def review() -> None:
                self.ctx.app.pop_screen()
                change = (
                    service.reschedule_upgrade
                    if rescheduling
                    else service.schedule_upgrade
                )
                _change(
                    self.ctx,
                    f"{'Reschedule' if rescheduling else 'Schedule'} the cloud "
                    f"computer upgrade for {local_time} {timezone}?",
                    "Save",
                    lambda: change(transport, timezone, local_time, recurring),
                    self.scheduled,
                )

            self.ctx.app.call_from_thread(review)

        title = "Reschedule upgrade" if rescheduling else "Schedule upgrade"
        self.ctx.app.push_screen(_Form(self.ctx, title, fields, prepare))

    def scheduled(self, value: object) -> None:
        assert isinstance(value, service.UpgradeSchedule)
        _notify(self.ctx, "Upgrade schedule saved.")
        self.reload()

    def cancel(self) -> None:
        transport = self.ctx.service.transport
        _change(
            self.ctx,
            "Cancel the scheduled cloud computer upgrade?",
            "Cancel upgrade",
            lambda: service.cancel_upgrade(transport),
            self.cancelled,
        )

    def cancelled(self, value: object) -> None:
        _notify(self.ctx, "Scheduled upgrade cancelled.")
        self.reload()


def _read_settings(ctx: SlashContext) -> tuple[service.RuntimeSettings, str]:
    try:
        return service.runtime_settings(ctx.service.transport), ""
    except ConnectError as error:
        found = refusal(error)
        if found is None:
            raise
        return service.RuntimeSettings(), found.message


class SettingsPanel(_Live):
    def __init__(self, ctx: SlashContext) -> None:
        self.ctx = ctx
        self.value = service.RuntimeSettings()
        self.notice = ""
        super().__init__("Settings", self.content)

    def on_mount(self) -> None:
        super().on_mount()
        self.reload()

    def names(self) -> dict[str, str]:
        return {bot.id: bot.name for bot in self.ctx.app.state.bots.values()}

    def content(self) -> Detail:
        value = self.value
        actions: list[PanelAction] = []
        if self.ctx.bot_id or self.names():
            actions.append(PanelAction("p", "Pin or unpin bot", self.pin))
        actions.append(
            PanelAction(
                "a",
                "Turn auto-review off"
                if value.auto_review_enabled
                else "Turn auto-review on",
                self.auto_review,
            )
        )
        actions.append(PanelAction("g", "Reload", self.reload))
        # A refused read shows its sentence alone, not the defaults as if the server had sent them.
        return Detail(
            () if self.notice else service.settings_fields(value, self.names()),
            body=self.notice,
            actions=tuple(actions),
        )

    def reload(self) -> None:
        _worker(self.ctx, lambda: _read_settings(self.ctx), self.loaded)

    def loaded(self, value: object) -> None:
        assert isinstance(value, tuple)
        settings, notice = value
        self.show(settings, notice)

    def show(self, settings: service.RuntimeSettings, notice: str) -> None:
        self.value, self.notice = settings, notice
        self.redraw()

    def saved(self, value: object) -> None:
        assert isinstance(value, service.RuntimeSettings)
        self.show(value, "")

    def _blocked(self) -> bool:
        # A failed read leaves defaults here; writing them would drop stored instructions.
        if self.notice:
            _notify(self.ctx, self.notice, "warning")
            return True
        return False

    def pin(self) -> None:
        if not _writable(self.ctx) or self._blocked():
            return
        bot = self.ctx.app.state.bots.get(self.ctx.bot_id or "")
        if bot is not None:
            self.toggle(bot.id, bot.name)
        else:
            self.pick()

    def toggle(self, bot_id: str, name: str) -> None:
        current = self.value
        pinned = bot_id in current.pinned_agent_ids
        ids = (
            [item for item in current.pinned_agent_ids if item != bot_id]
            if pinned
            else [*current.pinned_agent_ids, bot_id]
        )
        transport = self.ctx.service.transport
        _change(
            self.ctx,
            f"{'Unpin' if pinned else 'Pin'} {name}?",
            "Unpin" if pinned else "Pin",
            lambda: service.update_runtime_settings(
                transport, current, pinned_agent_ids=ids
            ),
            self.saved,
        )

    def pick(self) -> None:
        names = self.names()
        labels = {f"{name} ({bot_id})": bot_id for bot_id, name in names.items()}
        if not labels:
            return
        fields = (
            FormField(
                "bot",
                "Bot",
                "choice",
                next(iter(labels)),
                tuple(labels),
                required=True,
            ),
        )

        def prepare(values: dict[str, str | bool]) -> None:
            bot_id = labels[str(values["bot"])]

            def review() -> None:
                self.ctx.app.pop_screen()
                self.toggle(bot_id, names[bot_id])

            self.ctx.app.call_from_thread(review)

        self.ctx.app.push_screen(_Form(self.ctx, "Pin a bot", fields, prepare))

    def auto_review(self) -> None:
        if not _writable(self.ctx) or self._blocked():
            return
        current = self.value
        enable = not current.auto_review_enabled
        transport = self.ctx.service.transport
        _change(
            self.ctx,
            "Turn auto-review on?" if enable else "Turn auto-review off?",
            "Turn on" if enable else "Turn off",
            lambda: service.update_runtime_settings(
                transport, current, auto_review_enabled=enable
            ),
            self.saved,
        )


def sandbox(ctx: SlashContext, args: str) -> None:
    ctx.app.push_screen(SandboxPanel(ctx))


def runtime(ctx: SlashContext, args: str) -> None:
    ctx.app.push_screen(SettingsPanel(ctx))


COMMANDS = (
    SlashCommand("sandbox", "Show the cloud computer", sandbox),
    SlashCommand("runtime", "Show runtime settings", runtime),
)
