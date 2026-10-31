"""A read-only preview with an explicit card answer and reply surface."""

from time import monotonic
from typing import TYPE_CHECKING, cast

from rich.text import Text
from textual import events, work
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.timer import Timer
from textual.widgets import Input, Static

from gbot.output import terminal_safe
from gbot.service.models import Bot, Card, TranscriptPage
from gbot.tui.glyphs import glyphs
from gbot.tui.widgets.prompt import CardPrompt
from gbot.tui.widgets.transcript import entry_widget

if TYPE_CHECKING:
    from gbot.tui.app import GbotApp


class _PeekPrompt(CardPrompt):
    def on_mount(self, event: events.Mount | None = None) -> None:
        # Mounting a preview must leave navigation with the roster.
        if event:
            event.prevent_default()

    def _choice_text(self) -> Text:
        return Text(super()._choice_text().plain.replace("\n", "   "))


class Peek(Vertical):
    DEFAULT_CSS = """
    Peek { display: none; dock: bottom; height: 50%; max-height: 50%; }
    Peek #peek-title { height: 2; border-top: solid $secondary; }
    Peek #peek-entries { height: 1fr; min-height: 2; overflow-x: hidden; }
    Peek #peek-card { height: auto; max-height: 7; }
    Peek CardPrompt { max-height: 7; }
    Peek CardPrompt #prompt-body, Peek CardPrompt #prompt-hint { display: none; }
    Peek CardPrompt #prompt-choices { margin-top: 0; }
    Peek #peek-entries > * { margin: 0; }
    Peek #peek-reply { height: 2; border: none; border-top: solid $secondary; padding: 0; }
    Peek #peek-hints { height: 1; color: $text-muted; }
    """

    def __init__(self) -> None:
        super().__init__(id="peek")
        self.bot_id: str | None = None
        self.card: Card | None = None
        self._generation = 0
        self._activity: int | None = None
        self._loaded_at = 0.0
        self._reload_timer: Timer | None = None

    @property
    def gbot(self) -> "GbotApp":
        return cast("GbotApp", self.app)

    @property
    def reply(self) -> Input:
        return self.query_one("#peek-reply", Input)

    def compose(self) -> ComposeResult:
        yield Static(id="peek-title", markup=False)
        yield VerticalScroll(id="peek-entries")
        yield Vertical(id="peek-card")
        yield Input(id="peek-reply")
        yield Static(
            Text("esc close · 1-9 answer · enter open · tab reply"), id="peek-hints"
        )

    def close(self) -> None:
        self.display = False
        self.bot_id = None
        self._generation += 1
        if self._reload_timer:
            self._reload_timer.stop()
            self._reload_timer = None
        self.reply.value = ""

    def show_bot(self, bot: Bot, state_word: str, card: Card | None) -> None:
        changed = bot.id != self.bot_id
        self.display = True
        self.bot_id = bot.id
        self.query_one("#peek-title", Static).update(
            Text(terminal_safe(f"Peek: {bot.name} · {state_word}"))
        )
        self.reply.placeholder = terminal_safe(f"reply to {bot.name}")
        if changed or (card.entry_id if card else None) != (
            self.card.entry_id if self.card else None
        ):
            self.card = card
            holder = self.query_one("#peek-card", Vertical)
            holder.remove_children()
            if card:
                holder.mount(_PeekPrompt(card, ascii_only=self.gbot.ascii_only))
        if changed:
            self.reply.value = ""
            holder = self.query_one("#peek-entries", VerticalScroll)
            holder.remove_children()
            # The first page for a bot is still loading until it arrives.
            holder.mount(
                Static(
                    f"Loading{glyphs(self.gbot.ascii_only).ellipsis}",
                    classes="peek-loading",
                    markup=False,
                )
            )
            self._activity = bot.last_activity_at
            self.reload_entries()
        elif self._activity != bot.last_activity_at:
            self._activity = bot.last_activity_at
            self.schedule_reload()

    def schedule_reload(self) -> None:
        if self._reload_timer is None:
            delay = max(0, 0.5 - (monotonic() - self._loaded_at))
            if delay:
                self._reload_timer = self.set_timer(delay, self.reload_entries)
            else:
                self.reload_entries()

    def reload_entries(self) -> None:
        if self._reload_timer:
            self._reload_timer.stop()
            self._reload_timer = None
        if self.bot_id:
            self._generation += 1
            self._loaded_at = monotonic()
            self.load_entries(self.bot_id, self._generation)

    @work(thread=True, exit_on_error=False, exclusive=True, group="peek-transcript")
    def load_entries(self, bot_id: str, generation: int) -> None:
        try:
            page = self.gbot.service.transcript(bot_id, limit=8)
            self.app.call_from_thread(self._install_entries, bot_id, generation, page)
        except Exception as error:  # noqa: BLE001 - service boundary
            if generation == self._generation:
                self.app.call_from_thread(self._load_failed, error)

    def _load_failed(self, error: Exception) -> None:
        # A failed first page ends the loading line; the error notice stays as before.
        for line in self.query(".peek-loading"):
            line.remove()
        self.gbot.service_error(error)

    async def _install_entries(
        self, bot_id: str, generation: int, page: TranscriptPage
    ) -> None:
        if bot_id != self.bot_id or generation != self._generation:
            return
        holder = self.query_one("#peek-entries", VerticalScroll)
        await holder.remove_children()
        if bot_id != self.bot_id or generation != self._generation:
            return
        if page.entries:
            await holder.mount(
                *(entry_widget(entry, self.gbot.symbols) for entry in page.entries)
            )
        holder.scroll_end(animate=False)

    def choose(self, index: int) -> None:
        # The prompt mounts asynchronously; a key pressed before that finds nothing to answer.
        prompt = next(iter(self.query(CardPrompt)), None) if self.card else None
        if prompt:
            prompt.choose(index)
        else:
            self.notify("Nothing to answer")
