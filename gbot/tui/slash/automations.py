"""Automation lists, details and confirmed prompt editing."""

from collections.abc import Callable
from threading import Event
from time import time

from textual import events
from textual.message import Message
from textual.widgets import Static

from gbot.output import terminal_safe
from gbot.service import automations as service
from gbot.service.events import Other
from gbot.service.models import Bot, _record
from gbot.tui.app import ServiceEvent
from gbot.tui.model import age_text
from gbot.tui.panels.kit import Detail, FormField, ListPanel, PanelAction, PanelRow
from gbot.tui.screens.confirm import ConfirmScreen
from gbot.tui.slash import SlashCommand, SlashContext
from gbot.tui.slash.avatar_voice import _Detail, _Form
from gbot.tui.slash.rooms import _writable


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


def _when(value: int | None) -> str:
    if value is None:
        return "—"
    delta = value - int(time() * 1000)
    return f"in {age_text(delta)}" if delta > 0 else f"{age_text(-delta)} ago"


def _changed(message: Message, ids: set[str]) -> bool:
    return (
        isinstance(message, ServiceEvent)
        and isinstance(message.event, Other)
        and message.event.channel in {"automations", "agent-automations-changed"}
        and _record(message.event.payload).get("agentId") in ids
    )


def _form(
    ctx: SlashContext,
    bot: Bot,
    done: Callable[[], object],
    automation: service.Automation | None = None,
) -> None:
    if not _writable(ctx):
        return
    fields = [
        FormField(
            "name", "Name", value=automation.name if automation else "", required=True
        ),
        FormField(
            "prompt",
            "Prompt",
            "multiline",
            automation.prompt if automation else "",
            required=True,
        ),
    ]
    cron = automation is None or automation.trigger.get("type") == "cron"
    if cron:
        fields.append(
            FormField(
                "schedule",
                "Schedule",
                value=str(automation.trigger.get("schedule", "")) if automation else "",
                required=True,
                hint="e.g. 0 9 * * 1-5 or @daily",
            )
        )

    def prepare(values: dict[str, str | bool]) -> None:
        name, prompt = str(values["name"]), str(values["prompt"])
        if not name.strip() or not prompt.strip():
            raise ValueError("Name and prompt must not be blank.")
        schedule = service.check_schedule(str(values["schedule"])) if cron else None

        def save() -> object:
            if automation:
                return service.update(
                    ctx.service.transport,
                    bot,
                    automation,
                    name=name,
                    prompt=prompt,
                    schedule=schedule,
                )
            return service.create(
                ctx.service.transport,
                bot,
                name=name,
                prompt=prompt,
                schedule=schedule or "",
            )

        def finished() -> None:
            ctx.app.pop_screen()
            done()

        ctx.app.call_from_thread(_confirm, ctx, f"Save {name}?", save, finished)

    ctx.app.push_screen(
        _Form(
            ctx, "Edit automation" if automation else "New automation", fields, prepare
        )
    )


class AutomationsPanel(ListPanel):
    def __init__(self, ctx: SlashContext) -> None:
        self.ctx = ctx
        self.all_bots = ctx.bot_id is None
        self.found: dict[str, service.Automation] = {}
        super().__init__(
            "Automations",
            self.load_rows,
            on_select=self.open,
            empty="No automations",
            actions=(
                PanelAction("b", "All bots", self.toggle_bots),
                PanelAction("n", "New", self.new),
                PanelAction("r", "Reload", self.reload),
            ),
        )

    def shown_ids(self) -> set[str]:
        return (
            set(self.ctx.app.state.bots) if self.all_bots else {self.ctx.bot_id or ""}
        )

    def load_rows(self) -> list[PanelRow]:
        bots = self.ctx.app.state.bots
        items = (
            service.list_for_account(self.ctx.service.transport, list(bots.values()))
            if self.all_bots
            else service.list_for_bot(
                self.ctx.service.transport, bots[self.ctx.bot_id or ""]
            )
        )
        self.found = {f"{a.bot_id}:{a.id}": a for a in items}
        return [
            PanelRow(
                key,
                a.name,
                " · ".join(
                    [
                        "on" if a.is_enabled else "off",
                        service.describe_trigger(a.trigger),
                        _when(a.next_run_at_ms),
                        *([bots[a.bot_id].name] if self.all_bots else []),
                    ]
                ),
            )
            for key, a in self.found.items()
        ]

    def on_mount(self) -> None:
        self.ctx.app.message_signal.subscribe(self, self.changed)
        super().on_mount()

    def on_unmount(self) -> None:
        self.ctx.app.message_signal.unsubscribe(self)

    def changed(self, message: Message) -> None:
        if _changed(message, self.shown_ids()):
            self.reload()

    def toggle_bots(self) -> None:
        if self.ctx.bot_id:
            self.all_bots = not self.all_bots
        self.reload()

    def open(self, row: PanelRow) -> None:
        item = self.found[row.key]
        if not item.permits("OPEN"):
            self.ctx.app.notify(
                "Automation permission denied: open.", severity="error", markup=False
            )
            return
        self.ctx.app.push_screen(
            AutomationPanel(
                self.ctx, self.ctx.app.state.bots[item.bot_id], item, self.reload
            )
        )

    def new(self) -> None:
        if not _writable(self.ctx):
            return
        bot_id = self.ctx.bot_id
        if not bot_id and self.visible_rows:
            bot_id = self.found[self.visible_rows[self.index].key].bot_id
        if bot_id:
            _form(self.ctx, self.ctx.app.state.bots[bot_id], self.reload)
        else:
            self.ctx.app.notify("Select a bot first", markup=False)

    def on_key(self, event: events.Key) -> None:
        # List-level actions must also work when there are no records.
        action = next((a for a in self.actions if a.key == event.key), None)
        if action:
            action.run()
            event.stop()
            event.prevent_default()
        else:
            super().on_key(event)


class AutomationPanel(_Detail):
    def __init__(
        self,
        ctx: SlashContext,
        bot: Bot,
        value: service.Automation,
        refresh: Callable[[], object],
    ) -> None:
        self.ctx, self.bot, self.value, self.refresh_list = ctx, bot, value, refresh
        self.cancel, self.wake = Event(), Event()
        self.run_status = ""
        super().__init__(value.name, self.content)

    def content(self) -> Detail:
        a = self.value
        actions = []
        if a.permits("EDIT"):
            actions.append(PanelAction("e", "Edit", self.edit))
        if a.permits("TOGGLE"):
            actions.append(
                PanelAction("t", "Turn off" if a.is_enabled else "Turn on", self.toggle)
            )
        if a.permits("DELETE"):
            actions.append(PanelAction("x", "Delete", self.delete))
        if a.permits("OPEN"):
            actions.append(PanelAction("R", "Run now", self.run_now))
        actions.append(PanelAction("r", "Reload", self.reload))
        runs = "\n".join(
            f"{r.id} · {r.status} · {_when(r.started_at_ms)}" for r in a.runs[:5]
        )
        return Detail(
            (
                ("Trigger", service.describe_trigger(a.trigger)),
                ("State", "on" if a.is_enabled else "off"),
                ("Next run", _when(a.next_run_at_ms)),
                ("Last run", _when(a.last_run_at_ms)),
                ("Created", _when(a.created_at_ms)),
                ("Provenance", str(a.provenance or "—")),
            ),
            body=f"{a.prompt}\n\nLast runs\n{runs or 'No runs'}"
            + (f"\n\n{self.run_status}" if self.run_status else ""),
            actions=actions,
        )

    def on_mount(self) -> None:
        super().on_mount()
        self.ctx.app.message_signal.subscribe(self, self.changed)

    def on_unmount(self) -> None:
        self.cancel.set()
        self.wake.set()
        self.ctx.app.message_signal.unsubscribe(self)

    def changed(self, message: Message) -> None:
        if _changed(message, {self.bot.id}):
            self.wake.set()
            self.reload()

    def loaded(self, value: service.Automation) -> None:
        if not self.is_mounted:
            return
        self.value = value
        self.detail = self.content()
        self.index = min(self.index, len(self.detail.actions) - 1)
        self._draw()
        self.query_one(".panel-footer", Static).update(
            " · ".join(f"{a.key} {a.label}" for a in self.detail.actions)
            + " · esc back"
        )

    def reload(self) -> None:
        def load() -> None:
            value = service.get(self.ctx.service.transport, self.bot, self.value.id)
            self.ctx.app.call_from_thread(self.loaded, value)

        _worker(self.ctx, load)

    def edit(self) -> None:
        _form(self.ctx, self.bot, self.reload, self.value)

    def toggle(self) -> None:
        _confirm(
            self.ctx,
            f"Turn {'off' if self.value.is_enabled else 'on'} {self.value.name}?",
            lambda: service.set_enabled(
                self.ctx.service.transport,
                self.bot,
                self.value,
                not self.value.is_enabled,
            ),
            self.reload,
        )

    def delete(self) -> None:
        def done() -> None:
            self.ctx.app.pop_screen()
            self.refresh_list()

        _confirm(
            self.ctx,
            f"Delete automation {self.value.name}?",
            lambda: service.delete(self.ctx.service.transport, self.bot, self.value),
            done,
        )

    def status(self, text: str) -> None:
        self.run_status = text
        self.loaded(self.value)

    def run_now(self) -> None:
        value = self.value

        def run() -> None:
            service.run_now(self.ctx.service.transport, self.bot, value)
            self.ctx.app.call_from_thread(self.status, "Waiting for run to start…")
            result = service.wait_for_run(
                self.ctx.service.transport,
                self.bot,
                value,
                cancel=self.cancel,
                wake=self.wake,
            )
            if not self.cancel.is_set():
                self.ctx.app.call_from_thread(
                    self.status, result.status if result else "Run start timed out"
                )

        _confirm(self.ctx, f"Run {value.name} now?", run, self.reload)


def automations(ctx: SlashContext, args: str) -> None:
    ctx.app.push_screen(AutomationsPanel(ctx))


COMMANDS = (
    SlashCommand("automations", "Manage scheduled and triggered prompts", automations),
)
