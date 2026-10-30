from typing import TYPE_CHECKING, ClassVar, cast

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.screen import Screen
from textual.widgets import Input, Static

from gbot.output import terminal_safe
from gbot.service.models import TranscriptPage
from gbot.tui.widgets.transcript import Transcript, entry_widget

if TYPE_CHECKING:
    from gbot.tui.app import GbotApp


class _SessionInput(Input):
    def check_consume_key(self, key: str, character: str | None) -> bool:
        # Retry must remain reachable while the empty composer has focus.
        if key == "r" and not self.value and cast("SessionScreen", self.screen).failed:
            return False
        return super().check_consume_key(key, character)


class SessionScreen(Screen):
    DEFAULT_CSS = """
    SessionScreen { layout: vertical; }
    SessionScreen #session-status { height: 1; }
    SessionScreen #session-history { height: 1fr; margin-top: 1; }
    SessionScreen #session-input { height: 3; border: round $secondary; }
    SessionScreen #session-notice { height: auto; color: $text-muted; }
    SessionScreen #session-footer { height: 1; color: $text-muted; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "app.pop_screen", "Home"),
        Binding("pageup", "earlier", "Earlier", priority=True),
        Binding("home", "history_top", "Top", priority=True),
        Binding("pagedown", "later", "Later", priority=True),
        Binding("r", "retry", "Retry", priority=True),
        Binding("left", "back_if_empty", "Home", priority=True),
    ]

    def __init__(
        self,
        bot_id: str,
        *,
        bot_name: str | None = None,
        session_id: str | None = None,
    ) -> None:
        super().__init__()
        self.bot_id = bot_id
        self.bot_name = bot_name or bot_id
        self.session_id = session_id
        self.next_before_seq: int | None = None
        self._loading_page = False
        self.loaded = False
        self.failed = False

    @property
    def gbot(self) -> "GbotApp":
        return cast("GbotApp", self.app)

    def compose(self) -> ComposeResult:
        yield Static(terminal_safe(self.bot_name), id="session-status", markup=False)
        yield Transcript(id="session-history")
        yield Static("", id="session-notice", markup=False)
        yield _SessionInput(placeholder="message", id="session-input")
        yield Static("esc home · pgup earlier", id="session-footer", markup=False)

    def on_mount(self) -> None:
        self.query_one(Input).focus()
        self.query_one("#session-footer", Static).update(
            f"esc home {self.gbot.symbols.separator} pgup earlier"
        )
        self._start_load()
        self.load_box()

    def _status(self, box: str | None) -> None:
        bot = next((b for b in self.gbot.bots if b.id == self.bot_id), None)
        parts = [terminal_safe(self.bot_name)]
        if bot is not None:
            parts.append(
                "needs input"
                if bot.awaiting
                else "working"
                if bot.busy
                else "new reply"
                if bot.unread
                else "idle"
            )
        computer = {
            "hibernated": "computer asleep",
            "running": "computer running",
            "absent": "no computer",
        }.get(box or "")
        if computer:
            parts.append(computer)
        self.query_one("#session-status", Static).update(
            f" {self.gbot.symbols.separator} ".join(parts)
        )

    @work(thread=True, exit_on_error=False)
    def load_box(self) -> None:
        try:
            box = self.gbot.service.box_state(self.bot_id)
        except Exception:  # noqa: BLE001 — optional status must not hide the transcript
            box = None
        self.app.call_from_thread(self._status, box)

    def _start_load(self) -> None:
        if self._loading_page or (self.loaded and self.next_before_seq is None):
            return
        self._loading_page = True
        self.failed = False
        self.query_one(Transcript).marker.update("Loading…")
        self.load_page(self.next_before_seq if self.loaded else None)

    @work(thread=True, exit_on_error=False)
    def load_page(self, before: int | None) -> None:
        try:
            if before is None:
                page = self.gbot.service.open(
                    self.bot_id, session_id=self.session_id, limit=200
                )
            else:
                page = self.gbot.service.transcript(
                    self.bot_id,
                    before_seq=before,
                    limit=50,
                    session_id=self.session_id,
                )
        except Exception as exc:  # noqa: BLE001 — worker errors become inline retry notices
            self.app.call_from_thread(self._load_error, str(exc))
        else:
            self.app.call_from_thread(self._show_page, page)

    def _load_error(self, error: str) -> None:
        self._loading_page = False
        self.failed = True
        self.query_one(Transcript).marker.update(
            f"{terminal_safe(error)} — press r to retry"
        )

    async def _show_page(self, page: TranscriptPage) -> None:
        history = self.query_one(Transcript)
        await history.prepend_entries(
            [entry_widget(e, self.gbot.symbols) for e in page.entries],
            initial=not self.loaded,
        )
        self.next_before_seq = page.next_before_seq
        self.loaded = True
        history.marker.update(
            "Beginning of conversation"
            if self.next_before_seq is None
            else "pgup earlier"
        )
        self.call_after_refresh(self._load_finished)

    def _load_finished(self) -> None:
        self._loading_page = False

    def on_transcript_top_reached(self) -> None:
        if self.loaded and not self.failed:
            self._start_load()

    def action_earlier(self) -> None:
        history = self.query_one(Transcript)
        if history.scroll_y == 0:
            self._start_load()
        else:
            history.scroll_page_up(animate=False)

    def action_history_top(self) -> None:
        history = self.query_one(Transcript)
        if history.scroll_y == 0:
            self._start_load()
        else:
            history.scroll_home(animate=False)

    def action_later(self) -> None:
        self.query_one(Transcript).scroll_page_down(animate=False)

    def action_retry(self) -> None:
        if self.failed:
            self._start_load()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        # Printable and editing keys belong to the composer once it holds text.
        empty = not self.query_one(Input).value
        if action == "retry":
            return self.failed and empty
        if action in {"back_if_empty", "history_top"}:
            return empty
        return super().check_action(action, parameters)

    def action_back_if_empty(self) -> None:
        self.app.pop_screen()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.query_one("#session-notice", Static).update(
            "Sending arrives with live mode"
        )
