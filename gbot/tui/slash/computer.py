"""Desktop state, confirmed actions and private browser opening."""

import webbrowser

from textual.message import Message
from textual.widgets import Static

from gbot.output import terminal_safe
from gbot.service import computer as service
from gbot.service.events import BoxChanged
from gbot.service.models import Bot
from gbot.tui.app import ServiceEvent
from gbot.tui.panels.kit import Detail, PanelAction
from gbot.tui.slash import SlashCommand, SlashContext
from gbot.tui.slash.avatar_voice import _confirm, _Detail, _worker


class _Computer(_Detail):
    def __init__(self, ctx: SlashContext, bot: Bot) -> None:
        self.ctx, self.bot = ctx, bot
        self.value = service.ComputerStatus()
        super().__init__(f"{terminal_safe(bot.name)} computer", self.content)

    def on_mount(self) -> None:
        super().on_mount()
        self.ctx.app.message_signal.subscribe(self, self.changed)
        self.reload()

    def on_unmount(self) -> None:
        self.ctx.app.message_signal.unsubscribe(self)

    def changed(self, message: Message) -> None:
        if (
            isinstance(message, ServiceEvent)
            and isinstance(message.event, BoxChanged)
            and message.event.bot_id == self.bot.id
        ):
            self.reload()

    def content(self) -> Detail:
        value = self.value
        actions = [PanelAction("w", "Wake", self.wake)]
        if value.host_update_available or value.image_update_available:
            actions.append(PanelAction("u", "Update", self.update))
        if value.handoff_request_id:
            actions.append(PanelAction("h", "Hand back", self.hand_back))
        if value.vnc_url:
            actions.append(PanelAction("o", "Open live view", self.open))
        actions.append(PanelAction("r", "Reload", self.reload))
        return Detail(
            service.fields(value),
            body=value.handoff_instruction if value.handoff_request_id else "",
            actions=actions,
        )

    def reload(self) -> None:
        def load() -> None:
            value = service.status(self.ctx.service.transport, self.bot.id)
            self.ctx.app.call_from_thread(self.loaded, value)

        _worker(self.ctx, load)

    def loaded(self, value: service.ComputerStatus) -> None:
        self.value = value
        self.detail = self.content()
        self.index = min(self.index, len(self.detail.actions) - 1)
        self._draw()
        self.query_one(".panel-footer", Static).update(
            " · ".join(f"{a.key} {a.label}" for a in self.detail.actions)
            + " · esc back"
        )

    def wake(self) -> None:
        _confirm(
            self.ctx,
            f"Wake {terminal_safe(self.bot.name)}'s computer?",
            lambda: service.wake(self.ctx.service.transport, self.bot.id),
            self.reload,
        )

    def update(self) -> None:
        _confirm(
            self.ctx,
            f"Update {terminal_safe(self.bot.name)}'s computer? It restarts.",
            lambda: service.update(self.ctx.service.transport, self.bot.id),
            self.reload,
        )

    def hand_back(self) -> None:
        request_id = self.value.handoff_request_id
        _confirm(
            self.ctx,
            f"Hand the computer back to {terminal_safe(self.bot.name)}?",
            lambda: service.hand_back(self.ctx.service.transport, self.bot, request_id),
            self.reload,
        )

    def open(self) -> None:
        url = self.value.vnc_url
        if not url:
            return

        def opened() -> None:
            try:
                launched = webbrowser.open(url)
            except Exception:  # noqa: BLE001 - browser errors may contain access tokens
                # Browser errors may embed the access URL.
                launched = False
            if not launched:
                raise ValueError("Could not open a browser for the live view.")
            self.ctx.app.call_from_thread(
                self.ctx.app.notify, "Opened the live view.", markup=False
            )

        _worker(self.ctx, opened)


def computer(ctx: SlashContext, args: str) -> None:
    bot = ctx.app.state.bots[ctx.bot_id or ""]
    ctx.app.push_screen(_Computer(ctx, bot))


COMMANDS = (
    SlashCommand(
        "computer",
        "Manage the desktop computer",
        computer,
        scope="session",
        needs_bot=True,
    ),
)
