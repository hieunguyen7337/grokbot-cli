from collections.abc import Callable
from time import monotonic
from typing import ClassVar

from textual import work
from textual.app import App
from textual.binding import Binding, BindingType
from textual.command import Provider
from textual.message import Message

from gbot.output import terminal_safe
from gbot.service import bots as bot_service
from gbot.service import events, trays
from gbot.service.api import Service
from gbot.service.models import Bot, Card, ConnectionStatus
from gbot.tui.glyphs import glyphs
from gbot.tui.notifications import Notifier
from gbot.tui.palette import GbotCommands
from gbot.tui.screens.help import HelpScreen
from gbot.tui.screens.home import HOME_BINDINGS, HomeScreen
from gbot.tui.screens.session import SessionScreen
from gbot.tui.state import AppState
from gbot.tui.theme import GBOT_THEME, STYLES
from groken.client import ConnectError

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
    COMMANDS: ClassVar[set[type[Provider] | Callable[[], type[Provider]]]] = {
        GbotCommands
    }
    bell_enabled = True

    def __init__(
        self,
        service: Service,
        *,
        ascii_only: bool = False,
        bot: str | None = None,
        animate: bool = True,
        read_only: bool = False,
    ) -> None:
        super().__init__()
        self.service = service
        self.read_only = read_only
        self.ascii_only = ascii_only
        self.symbols = glyphs(ascii_only)
        self.initial_bot = bot
        self.animations_enabled = animate
        self.state = AppState()
        self.bots: list[Bot] = []
        self.trays: list[trays.Tray] = []
        self.main_bot_id: str | None = None
        self.notifier = Notifier()
        self.home = HomeScreen()
        self._source: events.EventSource | None = None
        self._followed: set[tuple[str, str | None]] = set()
        self._service_closing = False
        self._loaded = False
        self._sweep_finished = False
        self._cards_refreshed: set[str] = set()
        self._queued: list[events.Event] = []
        self._exit_requested_at: float | None = None
        self.register_theme(GBOT_THEME)
        self.theme = "gbot"
        if not animate:
            self.animation_level = "none"

    @property
    def loaded(self) -> bool:
        return self._loaded

    @property
    def settled(self) -> bool:
        return self.loaded and self._sweep_finished

    async def on_mount(self) -> None:
        await self.push_screen(self.home)
        self.load_service()

    def service_error(self, error: Exception) -> None:
        self.notify(terminal_safe(str(error)), severity="error", markup=False)

    def bot_error(
        self, bot_id: str, error: Exception | None = None, *, notify: bool = True
    ) -> None:
        if error is None:
            self.state.errors.pop(bot_id, None)
        else:
            self.state.errors[bot_id] = terminal_safe(str(error)).partition("\n")[0][
                :160
            ]
            if notify:
                self.service_error(error)
        self.refresh_home()

    def user_acted(self) -> None:
        if self._source is not None and self.state.status in {
            ConnectionStatus.ASLEEP,
            ConnectionStatus.SIGNED_OUT,
        }:
            self._source.nudge()

    def notify_roster(self) -> None:
        open_bot_id = next(
            (
                screen.bot_id
                for screen in reversed(self.screen_stack)
                if isinstance(screen, SessionScreen)
            ),
            None,
        )
        notices = self.notifier.update(
            self.state.bots.values(), open_bot_id=open_bot_id
        )
        for notice in notices:
            self.notify(terminal_safe(notice.text), markup=False)
        if self.bell_enabled and any(notice.bell for notice in notices):
            self.bell()

    def _receive_event(self, event: events.Event) -> None:
        self.post_message(ServiceEvent(event))

    def follow(self, bot_id: str, session_id: str | None = None) -> None:
        self._followed.add((bot_id, session_id))
        if self._source is not None:
            try:
                self._source.follow(bot_id, session_id)
            except Exception as error:  # noqa: BLE001 - event-source boundary
                self.service_error(error)

    def unfollow(self, bot_id: str, session_id: str | None = None) -> None:
        self._followed.discard((bot_id, session_id))
        if self._source is not None:
            try:
                self._source.unfollow(bot_id, session_id)
            except Exception as error:  # noqa: BLE001 - event-source boundary
                self.service_error(error)

    @work(thread=True, exit_on_error=False)
    def load_service(self) -> None:
        try:
            source = self.service.event_source()
            self._source = source
            if self._service_closing:
                source.close()
                return
            source.start(self._receive_event)
            self.call_from_thread(self._follow_source)
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

    def _follow_source(self) -> None:
        for bot_id, session_id in self._followed.copy():
            self.follow(bot_id, session_id)

    def _install(self, bots: list[Bot], cards: list[Card], warnings: list[str]) -> None:
        self._cards_refreshed.clear()
        self.state.apply(events.RosterReplaced(tuple(bots)))
        self.state.cards = {
            bot.id: [c for c in cards if c.bot_id == bot.id] for bot in bots
        }
        self.home.initialize_preferences(bots)
        self.notify_roster()
        self._loaded = True
        self.refresh_main()
        self.refresh_trays()
        for event in self._queued:
            self.on_service_event(ServiceEvent(event))
        self._queued.clear()
        self.sweep_cards([bot.id for bot in bots if bot.awaiting is None])
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

    @work(thread=True, exit_on_error=False, group="card-sweep")
    def sweep_cards(self, bot_ids: list[str]) -> None:
        try:
            for bot_id in bot_ids:
                if self._service_closing:
                    break
                if bot_id in self._cards_refreshed:
                    continue
                try:
                    cards, warnings = self.service.pending([bot_id])
                    if not self._service_closing:
                        self.call_from_thread(
                            self._install_sweep_cards, bot_id, cards, warnings
                        )
                except Exception as error:  # noqa: BLE001 - service/worker boundary
                    if self._service_closing:
                        break
                    if isinstance(error, ConnectError) and error.status == 401:
                        self.call_from_thread(self.service_error, error)
                        break
                    self.call_from_thread(self.bot_error, bot_id, error, notify=False)
        finally:
            self._sweep_finished = True

    def _install_sweep_cards(
        self, bot_id: str, cards: list[Card], warnings: list[str]
    ) -> None:
        if bot_id not in self._cards_refreshed:
            self._install_cards(bot_id, cards, warnings)

    def on_service_event(self, message: ServiceEvent) -> None:
        from gbot.tui.screens.handoff import HandoffScreen

        if not self._loaded:
            self._queued.append(message.event)
            for screen in self.screen_stack:
                if isinstance(screen, HandoffScreen):
                    screen.poke()
            return
        previous_status = self.state.status
        if isinstance(message.event, events.Other) and message.event.channel == "tray":
            self.refresh_trays()
        changes = self.state.apply(message.event)
        if (
            self.state.status == ConnectionStatus.SIGNED_OUT
            and previous_status != ConnectionStatus.SIGNED_OUT
        ):
            self.notify("Signed out. Run: gbot login", severity="error", markup=False)
        if "roster" in changes:
            self.notify_roster()
        for change in changes:
            if change.startswith("cards:"):
                self._cards_refreshed.add(change[6:])
                self.refresh_cards(change[6:])
        if isinstance(message.event, (events.RosterResync, events.Resynced)):
            self.refresh_roster()
        if changes:
            self.refresh_home()
        if isinstance(
            message.event,
            (
                events.EntryAdded,
                events.EntryChanged,
                events.EntryRemoved,
                events.TranscriptReset,
                events.BoxChanged,
            ),
        ):
            for screen in self.screen_stack:
                if isinstance(screen, SessionScreen):
                    screen.apply_event(message.event)
        for screen in self.screen_stack:
            if isinstance(screen, HandoffScreen):
                screen.poke()

    def refresh_home(self) -> None:
        self.bots = list(self.state.bots.values())
        self.home.refresh_state()
        for screen in self.screen_stack:
            if isinstance(screen, SessionScreen):
                screen.refresh_state()

    def on_resize(self) -> None:
        self.call_after_refresh(self.home.refresh_state)

    @work(thread=True, exit_on_error=False, group="main", exclusive=True)
    def refresh_main(self) -> None:
        try:
            main_id = bot_service.main_agent(self.service.transport)
        except Exception:  # noqa: BLE001 - optional user settings
            return
        if not self._service_closing:
            self.call_from_thread(self._install_main, main_id)

    def _install_main(self, main_id: str | None) -> None:
        self.main_bot_id = main_id
        self.refresh_home()

    @work(thread=True, exit_on_error=False, group="trays", exclusive=True)
    def refresh_trays(self) -> None:
        try:
            loaded = trays.trays(self.service.transport)
        except Exception:  # noqa: BLE001 - optional gateway capability
            return
        if not self._service_closing:
            self.call_from_thread(self._install_trays, loaded)

    def _install_trays(self, loaded: list[trays.Tray]) -> None:
        self.trays = loaded
        self.refresh_home()

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
            self.call_from_thread(self.bot_error, bot_id, error)

    def _install_cards(
        self, bot_id: str, cards: list[Card], warnings: list[str]
    ) -> None:
        self.state.errors.pop(bot_id, None)
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
            self.action_palette_quit()
        else:
            self._exit_requested_at = now
            self.notify("Press Ctrl+C again to exit", timeout=2)

    def action_palette_quit(self) -> None:
        self._close_source()
        self.exit()
