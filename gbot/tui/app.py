from time import monotonic
from typing import ClassVar

from textual import work
from textual.app import App
from textual.binding import Binding, BindingType
from textual.message import Message

from gbot.output import terminal_safe
from gbot.service import events
from gbot.service.api import Service
from gbot.service.models import Bot, Card
from gbot.tui.glyphs import glyphs
from gbot.tui.screens.help import HelpScreen
from gbot.tui.screens.home import HOME_BINDINGS, HomeScreen
from gbot.tui.screens.session import SessionScreen
from gbot.tui.state import AppState
from gbot.tui.theme import GBOT_THEME, STYLES

SHELL_BINDINGS = [
    Binding("ctrl+p", "command_palette", "Command palette", priority=True),
    Binding("escape", "escape", "Close or clear"),
    Binding(
        "ctrl+c", "request_exit", "Press twice within 2 seconds to exit", priority=True
    ),
]


class ServiceEvent(Message):
    def __init__(self, event: events.Event) -> None:
        super().__init__()
        self.event = event


class GbotApp(App[None]):
    TITLE = "gbot"
    CSS = STYLES
    BINDINGS: ClassVar[list[BindingType]] = [*SHELL_BINDINGS]
    COMMAND_PALETTE_BINDING = "ctrl+p"
    ENABLE_COMMAND_PALETTE = True

    def __init__(
        self,
        service: Service,
        *,
        ascii_only: bool = False,
        bot: str | None = None,
        animate: bool = True,
    ) -> None:
        super().__init__()
        self.service = service
        self.ascii_only = ascii_only
        self.symbols = glyphs(ascii_only)
        self.initial_bot = bot
        self.animations_enabled = animate
        self.state = AppState()
        self.bots: list[Bot] = []
        self.home = HomeScreen()
        self._source: events.EventSource | None = None
        self._service_closing = False
        self._loaded = False
        self._queued: list[events.Event] = []
        self._exit_requested_at: float | None = None
        self.register_theme(GBOT_THEME)
        self.theme = "gbot"
        if not animate:
            self.animation_level = "none"

    async def on_mount(self) -> None:
        await self.push_screen(self.home)
        self.load_service()

    def service_error(self, error: Exception) -> None:
        self.notify(terminal_safe(str(error)), severity="error", markup=False)

    def _receive_event(self, event: events.Event) -> None:
        self.post_message(ServiceEvent(event))

    @work(thread=True, exit_on_error=False)
    def load_service(self) -> None:
        try:
            source = self.service.event_source()
            self._source = source
            if self._service_closing:
                source.close()
                return
            source.start(self._receive_event)
        except Exception as error:  # noqa: BLE001 - service/worker boundary must notify
            self.call_from_thread(self.service_error, error)
        bots: list[Bot] = []
        cards: list[Card] = []
        warnings: list[str] = []
        try:
            bots = self.service.roster()
        except Exception as error:  # noqa: BLE001 - service/worker boundary must notify
            self.call_from_thread(self.service_error, error)
        try:
            cards, warnings = self.service.pending()
        except Exception as error:  # noqa: BLE001 - service/worker boundary must notify
            self.call_from_thread(self.service_error, error)
        if not self._service_closing:
            self.call_from_thread(self._install, bots, cards, warnings)

    def _install(self, bots: list[Bot], cards: list[Card], warnings: list[str]) -> None:
        self.state.apply(events.RosterReplaced(tuple(bots)))
        self.state.cards = {
            bot.id: [c for c in cards if c.bot_id == bot.id] for bot in bots
        }
        self.home.initialize_preferences(bots)
        self._loaded = True
        for event in self._queued:
            self.on_service_event(ServiceEvent(event))
        self._queued.clear()
        self.refresh_home()
        for warning in warnings:
            self.notify(terminal_safe(warning), markup=False)
        if self.initial_bot:
            matches = [
                bot
                for bot in self.bots
                if bot.id == self.initial_bot
                or bot.name.casefold() == self.initial_bot.casefold()
            ]
            if len(matches) == 1:
                self.open_bot(matches[0])
            else:
                self.notify(
                    f"Bot selector is unknown or ambiguous: {terminal_safe(self.initial_bot)}",
                    markup=False,
                )

    def on_service_event(self, message: ServiceEvent) -> None:
        if not self._loaded:
            self._queued.append(message.event)
            return
        changes = self.state.apply(message.event)
        for change in changes:
            if change.startswith("cards:"):
                self.refresh_cards(change[6:])
        if isinstance(message.event, (events.RosterResync, events.Resynced)):
            self.refresh_roster()
        if changes:
            self.refresh_home()

    def refresh_home(self) -> None:
        self.bots = list(self.state.bots.values())
        self.home.refresh_state()

    @work(thread=True, exit_on_error=False)
    def refresh_roster(self) -> None:
        try:
            bots = self.service.roster()
            self.post_message(ServiceEvent(events.RosterReplaced(tuple(bots))))
        except Exception as error:  # noqa: BLE001 - service/worker boundary must notify
            self.call_from_thread(self.service_error, error)

    @work(thread=True, exit_on_error=False)
    def refresh_cards(self, bot_id: str) -> None:
        try:
            cards, warnings = self.service.pending([bot_id])
            self.call_from_thread(self._install_cards, bot_id, cards, warnings)
        except Exception as error:  # noqa: BLE001 - service/worker boundary must notify
            self.call_from_thread(self.service_error, error)

    def _install_cards(
        self, bot_id: str, cards: list[Card], warnings: list[str]
    ) -> None:
        if bot_id in self.state.bots:
            self.state.cards[bot_id] = cards
            self.refresh_home()
        for warning in warnings:
            self.notify(terminal_safe(warning), markup=False)

    def _close_source(self) -> None:
        self._service_closing = True
        if self._source is not None:
            source, self._source = self._source, None
            try:
                source.close()
            except Exception as error:  # noqa: BLE001 - service/worker boundary must notify
                self.service_error(error)

    def on_unmount(self) -> None:
        self._close_source()

    def open_bot(self, bot: Bot) -> None:
        if isinstance(self.screen, HomeScreen):
            self.push_screen(SessionScreen(bot.id, bot_name=bot.name))

    def action_help(self) -> None:
        if not isinstance(self.screen, HelpScreen):
            self.push_screen(HelpScreen([*HOME_BINDINGS, *SHELL_BINDINGS]))

    def action_escape(self) -> None:
        if not isinstance(self.screen, HomeScreen):
            self.pop_screen()

    def action_request_exit(self) -> None:
        now = monotonic()
        if self._exit_requested_at is not None and now - self._exit_requested_at <= 2:
            self._close_source()
            self.exit()
        else:
            self._exit_requested_at = now
            self.notify("Press Ctrl+C again to exit", timeout=2)
