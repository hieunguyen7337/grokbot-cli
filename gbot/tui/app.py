import asyncio
import threading
from collections import deque
from collections.abc import Callable, Sequence
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
from gbot.service.cards import waiting as waiting_row
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

# Card checks in flight at once during the startup sweep. Each check waits on the gateway, so a few overlap.
CARD_SWEEP_PARALLEL = 4
# Transcript pages the home sweep reads per session for a bot that is not waiting (speed); a waiting bot reads in full.
HOME_RECENT_PAGES = 1

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


def _waiting_ids(bots: Sequence[Bot]) -> set[str]:
    # The bots whose cards get a full read, by the same test discover uses.
    return {bot.id for bot in bots if waiting_row(bot.raw)}


class _CardSweep:
    """The checks of one card sweep. Check threads share it; every field is read or written under the lock.

    Every bot gets a quick check of its newest page first. A waiting bot then gets a full check, queued at the end of
    the queue by the thread that finished its quick check once that result is on home.
    """

    def __init__(self, bot_ids: Sequence[str], bots: Sequence[Bot]) -> None:
        self.bots = list(bots)
        self.total = len(bot_ids)
        self.done = 0
        self._waiting = _waiting_ids(self.bots) & set(bot_ids)
        self.full_total = len(self._waiting)
        self.full_done = 0
        # (bot id, is a full check)
        self._queue: deque[tuple[str, bool]] = deque(
            (bot_id, False) for bot_id in bot_ids
        )
        self._stopped = False
        self._running = 0
        # (bot id, warning) already shown: a waiting bot's quick and full reads can report the same warning.
        self._warned: set[tuple[str, str]] = set()
        self._lock = threading.Lock()

    def start(self, threads: int) -> None:
        with self._lock:
            self._running = threads

    def take(self) -> tuple[str, bool] | None:
        with self._lock:
            if self._stopped or not self._queue:
                return None
            return self._queue.popleft()

    def count(self) -> None:
        # One quick check counted.
        with self._lock:
            self.done += 1

    def count_full(self) -> None:
        with self._lock:
            self.full_done += 1

    def plan_full(self, bot_id: str, *, wanted: bool) -> None:
        # Called once a quick check is finished and its result is installed. A waiting bot's full check joins the end
        # of the queue, or, when none is wanted (the quick check failed or the cards were refreshed), counts as done.
        with self._lock:
            if bot_id not in self._waiting:
                return
            if wanted:
                self._queue.append((bot_id, True))
            else:
                self.full_done += 1

    def unseen(self, bot_id: str, warnings: Sequence[str]) -> list[str]:
        with self._lock:
            fresh = [w for w in warnings if (bot_id, w) not in self._warned]
            self._warned.update((bot_id, w) for w in fresh)
            return fresh

    def progress(self) -> tuple[bool, int, int]:
        # (older, done, total): the quick checks until every one is counted, then the full checks of waiting bots.
        with self._lock:
            if self.done >= self.total and self.full_done < self.full_total:
                return True, self.full_done, self.full_total
            return False, self.done, self.total

    def stop_for_auth(self) -> bool:
        # True only for the first caller, which owns the one notice.
        with self._lock:
            first = not self._stopped
            self._stopped = True
            return first

    def leave(self) -> bool:
        # True for the last thread to leave, which tells the sweep that every check has finished.
        with self._lock:
            self._running -= 1
            return self._running == 0

    def abandon(self, threads: int) -> bool:
        # Threads counted by start() that never ran. True when no running thread is left to finish the sweep.
        with self._lock:
            self._running -= threads
            return self._running == 0


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
        self._roster_returned = False
        self._sweep: _CardSweep | None = None
        self._sweep_finished = False
        self._cards_refreshed: set[str] = set()
        self._queued: list[events.Event] = []
        self._exit_requested_at: float | None = None
        self.started_at = monotonic()
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

    @property
    def load_stage(self) -> str | None:
        """What home shows while loading: connecting, loading, sweeping, older (full checks of waiting bots), or None."""
        if self._sweep_finished:
            return None
        if not self._loaded:
            return "loading" if self._roster_returned else "connecting"
        sweep = self._sweep
        if sweep is None or not sweep.total:
            return None
        older, _, _ = sweep.progress()
        return "older" if older else "sweeping"

    @property
    def sweep_progress(self) -> tuple[int, int]:
        # (done, total) of the stage load_stage names.
        sweep = self._sweep
        if sweep is None:
            return (0, 0)
        _, done, total = sweep.progress()
        return (done, total)

    async def on_mount(self) -> None:
        self.started_at = monotonic()
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
        try:
            bots = self.service.roster()
        except Exception as error:  # noqa: BLE001 - service/worker boundary must notify
            self.call_from_thread(self.service_error, error)
        else:
            if not self._service_closing:
                self.call_from_thread(self._roster_arrived)
        # Home lists the roster at once; every bot's cards, waiting bots first, come from the parallel sweep.
        if not self._service_closing:
            self.call_from_thread(self._install, bots)

    def _roster_arrived(self) -> None:
        self._roster_returned = True
        self.home.refresh_progress()

    def _follow_source(self) -> None:
        for bot_id, session_id in self._followed.copy():
            self.follow(bot_id, session_id)

    def _install(self, bots: list[Bot]) -> None:
        self._cards_refreshed.clear()
        self.state.apply(events.RosterReplaced(tuple(bots)))
        self.state.cards = {bot.id: [] for bot in bots}
        self.home.initialize_preferences(bots)
        self.notify_roster()
        self._loaded = True
        self.refresh_main()
        self.refresh_trays()
        for event in self._queued:
            self.on_service_event(ServiceEvent(event))
        self._queued.clear()
        # The home list must hold this roster before the sweep can follow its display order.
        self.refresh_home()
        shown = self._display_order([bot.id for bot in bots])
        waiting = _waiting_ids(bots)
        self._sweep = _CardSweep(
            [
                *(bot_id for bot_id in shown if bot_id in waiting),
                *(bot_id for bot_id in shown if bot_id not in waiting),
            ],
            bots,
        )
        self.sweep_cards(self._sweep)
        self.refresh_home()
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

    def _display_order(self, bot_ids: list[str]) -> list[str]:
        # Bots in the order the home list shows them (pinned first, then by state), then the rest.
        wanted = set(bot_ids)
        shown = [
            bot_id for bot_id in self.home.bot_list.visible_ids if bot_id in wanted
        ]
        listed = set(shown)
        return [*shown, *(bot_id for bot_id in bot_ids if bot_id not in listed)]

    @work(exit_on_error=False, group="card-sweep")
    async def sweep_cards(self, sweep: _CardSweep) -> None:
        if sweep.total:
            loop = asyncio.get_running_loop()
            finished = asyncio.Event()
            threads = min(CARD_SWEEP_PARALLEL, sweep.total)
            sweep.start(threads)
            # Daemon threads, not Textual thread workers: asyncio.run joins the default executor at exit,
            # so a check blocked on the network would hold up quitting. This coroutine only waits.
            started = 0
            try:
                for _ in range(threads):
                    threading.Thread(
                        target=self._run_card_checks,
                        args=(sweep, loop, finished),
                        name="gbot-card-check",
                        daemon=True,
                    ).start()
                    started += 1
            except Exception as error:  # noqa: BLE001 - the OS can refuse a thread
                self.log.error(f"card check thread did not start: {error!r}")
                # The threads that never started cannot leave; the last one out ends the sweep.
                if sweep.abandon(threads - started):
                    finished.set()
                if not started:
                    self.notify(
                        "Could not start the card check.",
                        severity="error",
                        markup=False,
                    )
            await finished.wait()
        self._sweep_finished = True
        self.refresh_home()

    def _run_card_checks(
        self,
        sweep: _CardSweep,
        loop: asyncio.AbstractEventLoop,
        finished: asyncio.Event,
    ) -> None:
        try:
            self._check_bots(sweep)
        except Exception as error:  # noqa: BLE001 - thread boundary: a UI callback can fail while screens close
            self.log.error(f"card check thread stopped: {error!r}")
        finally:
            try:
                if sweep.leave():
                    loop.call_soon_threadsafe(finished.set)
            except RuntimeError:  # the app loop has already closed
                pass

    def _check_bots(self, sweep: _CardSweep) -> None:
        while (item := sweep.take()) is not None:
            if self._service_closing:
                break
            bot_id, full = item
            if full:
                self._full_check(sweep, bot_id)
            else:
                self._quick_check(sweep, bot_id)

    def _quick_check(self, sweep: _CardSweep, bot_id: str) -> None:
        if bot_id in self._cards_refreshed:
            sweep.count()
            sweep.plan_full(bot_id, wanted=False)
            return
        try:
            cards, warnings = self.service.pending(
                [bot_id],
                bots=sweep.bots,
                recent_pages=HOME_RECENT_PAGES,
                waiting_in_full=False,
            )
        except Exception as error:  # noqa: BLE001 - service/worker boundary
            sweep.count()
            self._check_failed(sweep, bot_id, error)
            # A waiting bot still gets its full read, as before the quick pass; a 401 has stopped the sweep.
            auth = isinstance(error, ConnectError) and error.status == 401
            sweep.plan_full(bot_id, wanted=not auth)
            return
        sweep.count()
        if self._service_closing:
            return
        try:
            installed = self.call_from_thread(
                self._install_sweep_cards, bot_id, cards, sweep.unseen(bot_id, warnings)
            )
        except Exception as error:  # noqa: BLE001 - UI install boundary: a failed install is a badge
            installed = False
            self.call_from_thread(self.bot_error, bot_id, error, notify=False)
        # Only now, with the quick result on home, may the full check of a waiting bot join the queue.
        sweep.plan_full(bot_id, wanted=installed)

    def _full_check(self, sweep: _CardSweep, bot_id: str) -> None:
        if bot_id in self._cards_refreshed:
            sweep.count_full()
            return
        try:
            cards, warnings = self.service.pending([bot_id], bots=sweep.bots)
        except Exception as error:  # noqa: BLE001 - service/worker boundary
            sweep.count_full()
            self._check_failed(sweep, bot_id, error)
            return
        sweep.count_full()
        if self._service_closing:
            return
        try:
            self.call_from_thread(
                self._install_sweep_cards, bot_id, cards, sweep.unseen(bot_id, warnings)
            )
        except Exception as error:  # noqa: BLE001 - UI install boundary: a failed install is a badge
            self.call_from_thread(self.bot_error, bot_id, error, notify=False)

    def _check_failed(self, sweep: _CardSweep, bot_id: str, error: Exception) -> None:
        if self._service_closing:
            return
        if isinstance(error, ConnectError) and error.status == 401:
            # One notice for the whole sweep; the other checks in flight end quietly.
            if sweep.stop_for_auth():
                self.call_from_thread(self.service_error, error)
        else:
            self.call_from_thread(self.bot_error, bot_id, error, notify=False)

    def _install_sweep_cards(
        self, bot_id: str, cards: list[Card], warnings: list[str]
    ) -> bool:
        # Refreshed cards already hold a full read, which a sweep result must not replace. Returns whether installed.
        if bot_id in self._cards_refreshed:
            return False
        self._install_cards(bot_id, cards, warnings)
        return True

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
            self.call_from_thread(
                self._install_refreshed_cards, bot_id, cards, warnings
            )
        except Exception as error:  # noqa: BLE001 - service/worker boundary must notify
            self.call_from_thread(self.bot_error, bot_id, error)

    def _install_refreshed_cards(
        self, bot_id: str, cards: list[Card], warnings: list[str]
    ) -> None:
        # A full read: a capped sweep result that lands later must not replace it.
        self._cards_refreshed.add(bot_id)
        self._install_cards(bot_id, cards, warnings)

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
