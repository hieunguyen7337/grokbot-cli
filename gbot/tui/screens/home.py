from collections.abc import Mapping, Sequence
from dataclasses import replace
from threading import Lock
from time import monotonic, time
from typing import TYPE_CHECKING, ClassVar, cast
from uuid import uuid4

from rich.text import Text
from textual import events, work
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal
from textual.screen import Screen
from textual.timer import Timer
from textual.widgets import Input, Static, TextArea

from gbot.output import terminal_safe
from gbot.service.models import Bot, ConnectionStatus
from gbot.tui import model, prefs
from gbot.tui.answering import answer_card
from gbot.tui.glyphs import glyphs
from gbot.tui.slash import SlashContext, run
from gbot.tui.widgets.botlist import BotList
from gbot.tui.widgets.peek import Peek
from gbot.tui.widgets.prompt import CardPrompt
from gbot.tui.widgets.slashmenu import SlashMenu

if TYPE_CHECKING:
    from gbot.tui.app import GbotApp

# Seconds before the connecting line also says that a cloud computer can take a while to start.
CONNECT_HINT_AFTER = 5
PROGRESS_CELLS = 30
PROGRESS_TICK = 0.2


def progress_text(
    stage: str | None,
    *,
    elapsed: int,
    done: int,
    total: int,
    ascii_only: bool,
    animate: bool,
    frame: int,
) -> str:
    """The home loading line for a stage, or "" when home has nothing to show."""
    if stage is None:
        return ""
    symbols = glyphs(ascii_only)
    # The spinner holds still with animations off and in ASCII mode.
    spinner = (
        symbols.working[frame % len(symbols.working)]
        if animate and not ascii_only
        else symbols.working[0]
    )
    if stage == "connecting":
        text = f"{spinner} Connecting to Grok Bot... {elapsed} s"
        if elapsed >= CONNECT_HINT_AFTER:
            text += "\n  starting your cloud computer can take about 30 s"
        return text
    if stage == "loading":
        return f"{spinner} Loading bots..."
    filled = round(PROGRESS_CELLS * done / total) if total else 0
    fill, empty = ("#", "-") if ascii_only else ("█", "░")
    bar = fill * filled + empty * (PROGRESS_CELLS - filled)
    return f"{spinner} Checking for cards {done}/{total} [{bar}]"


HOME_BINDINGS = [
    Binding(
        key,
        action,
        description,
        priority=key in {"up", "down", "pageup", "pagedown", "home", "end", "ctrl+x"},
    )
    for key, action, description in (
        ("up", "navigate(-1)", "Previous row or header"),
        ("down", "navigate(1)", "Next row or header"),
        ("pageup", "page(-1)", "Previous page"),
        ("pagedown", "page(1)", "Next page"),
        ("home", "edge(-1)", "First header"),
        ("end", "edge(1)", "Last row"),
        ("alt+up", "section(-1)", "Previous section"),
        ("alt+down", "section(1)", "Next section"),
        ("[", "printable_section(-1)", "Previous section"),
        ("]", "printable_section(1)", "Next section"),
        ("enter", "open", "Open bot / collapse section"),
        ("right", "open_row", "Open bot"),
        ("ctrl+t", "pin", "Toggle pin"),
        ("shift+up", "reorder(-1)", "Move bot up in section"),
        ("shift+down", "reorder(1)", "Move bot down in section"),
        ("ctrl+s", "group_by", "Toggle state / team grouping"),
        ("ctrl+f", "find", "Filter by name"),
        ("ctrl+x", "interrupt", "Stop"),
        ("space", "peek", "Toggle Peek"),
        ("tab", "peek_reply", "Focus Peek reply"),
        ("?", "help", "Keyboard help"),
        ("escape", "escape", "Clear input / focus list"),
    )
] + [
    *[Binding(str(n), f"peek_answer({n})", f"Peek answer {n}") for n in range(1, 10)],
    *[
        Binding(f"alt+{n}", f"open_number({n})", f"Open visible bot {n}")
        for n in range(1, 10)
    ],
]


class HomeScreen(Screen):
    BINDINGS: ClassVar[list[BindingType]] = [*HOME_BINDINGS]
    DEFAULT_CSS = """
    HomeScreen #home-progress { height: auto; color: $text-muted; }
    """

    def __init__(self) -> None:
        super().__init__()
        self.preferences = prefs.Prefs()
        self.rows: list[model.Row] = []
        self._expanded: set[str] = set()
        self._filter = ""
        self._save_lock = Lock()
        self._progress_text = ""
        self._progress_frame = 0
        self._progress_timer: Timer | None = None

    @property
    def gbot(self) -> "GbotApp":
        return cast("GbotApp", self.app)

    @property
    def bot_list(self) -> BotList:
        return self.query_one(BotList)

    def compose(self) -> ComposeResult:
        with Horizontal(id="header"):
            yield Static("Grok Bot", id="heading", markup=False)
            yield Static("connecting", id="connection", markup=False)
        yield Static("", id="home-progress", markup=False)
        yield BotList(
            ascii_only=self.gbot.ascii_only, animate=self.gbot.animations_enabled
        )
        separator = self.gbot.symbols.separator
        yield SlashMenu("home")
        yield Input(
            placeholder=f"> message {separator} @bot {separator} /command {separator} s: n: t: filters",
            id="dispatch",
        )
        yield Static(
            f"space peek {separator} enter open {separator} ctrl+t pin {separator} ctrl+s group {separator} ? help",
            id="home-hints",
            markup=False,
        )
        yield Peek()

    def on_mount(self) -> None:
        self.preferences = prefs.load(prefs.path())
        self.bot_list.focus()
        self.refresh_state()

    def initialize_preferences(self, bots: Sequence[Bot]) -> None:
        latest: dict[str, int] = {}
        for bot in bots:
            entry = bot.raw.get("lastEntry")
            if isinstance(entry, Mapping):
                seq = entry.get("seq")
                if isinstance(seq, int) and not isinstance(seq, bool) and seq >= 0:
                    latest[bot.id] = seq
        if latest:
            updated = prefs.first_run(self.preferences, latest)
            if updated != self.preferences:
                self.preferences = updated
                self.save_preferences(updated)

    def refresh_state(self, *, force: bool = False) -> None:
        if not self.is_mounted:
            return
        state = self.gbot.state
        bots = list(state.bots.values())
        now = int(time() * 1000)
        self.rows = model.build_rows(
            bots,
            [c for cards in state.cards.values() for c in cards],
            now_ms=now,
            pins=self.preferences.pins,
            main_id=self.gbot.main_bot_id,
            errors=state.errors,
        )
        totals = model.counts(self.rows)
        left, right = model.header_text(
            totals,
            state.status,
            ascii_only=self.gbot.ascii_only,
            attempt=state.connection.attempt,
        )
        if Text(left + " " + right).cell_len > self.content_size.width:
            right = right.split(f" {self.gbot.symbols.separator} ")[0]
            if state.status == ConnectionStatus.ASLEEP:
                right = f"{self.gbot.symbols.dot} asleep"
            if Text(left + " " + right).cell_len > self.content_size.width:
                # The counts matter more than the product name.
                left = left.removeprefix(f"Grok Bot {self.gbot.symbols.separator} ")
        heading = Text(left)
        if self.gbot.trays:
            count = len(self.gbot.trays)
            heading.append(
                f" {self.gbot.symbols.separator} {count} alert{'s' if count != 1 else ''}",
                style="#d2b45f",
            )
        self.query_one("#heading", Static).update(heading)
        color = (
            "#78b878"
            if state.status == ConnectionStatus.LIVE
            else "#d16969"
            if state.status in {ConnectionStatus.OFFLINE, ConnectionStatus.SIGNED_OUT}
            else "#d2b45f"
        )
        self.query_one("#connection", Static).update(Text(right, style=color))
        need = totals[model.RowState.NEEDS_INPUT]
        self.gbot.title = (
            f"{need} need you {self.gbot.symbols.separator} gbot" if need else "gbot"
        )
        rows = model.apply_filter(self.rows, model.parse_filter(self._filter), bots)
        sections = model.group(
            rows,
            by=self.preferences.group_by,
            order=self.preferences.order,
            collapsed=self.preferences.collapsed,
            expanded=frozenset(self._expanded),
        )
        other_lines = sum(
            1 + len(s.rows) + int(bool(s.hidden_count) and not s.collapsed)
            for s in sections
            if s.key != "idle"
        )
        height = self.bot_list.content_size.height
        sections = model.group(
            rows,
            by=self.preferences.group_by,
            order=self.preferences.order,
            collapsed=self.preferences.collapsed,
            expanded=frozenset(self._expanded),
            idle_limit=max(5, height - other_lines - 2) if height else 5,
        )
        if self.preferences.group_by == "team" and self.preferences.order:
            positions = {key: i for i, key in enumerate(self.preferences.order)}
            sections = [
                replace(
                    s,
                    rows=tuple(
                        sorted(
                            s.rows,
                            key=lambda r: positions.get(r.bot_id, len(positions)),
                        )
                    ),
                )
                for s in sections
            ]
        self.bot_list.set_sections(sections, force=force)
        self.sync_peek()
        self.refresh_progress()

    def refresh_progress(self) -> None:
        if not self.is_mounted:
            return
        done, total = self.gbot.sweep_progress
        text = progress_text(
            self.gbot.load_stage,
            elapsed=int(monotonic() - self.gbot.started_at),
            done=done,
            total=total,
            ascii_only=self.gbot.ascii_only,
            animate=self.gbot.animations_enabled,
            frame=self._progress_frame,
        )
        line = self.query_one("#home-progress", Static)
        line.display = bool(text)
        if text != self._progress_text:
            self._progress_text = text
            line.update(text)
        # The ticker runs only while the line shows: the elapsed seconds and the spinner need it.
        if text and self._progress_timer is None:
            self._progress_timer = self.set_interval(PROGRESS_TICK, self._tick_progress)
        elif not text and self._progress_timer is not None:
            self._progress_timer.stop()
            self._progress_timer = None

    def _tick_progress(self) -> None:
        self._progress_frame += 1
        self.refresh_progress()

    @property
    def peek(self) -> Peek:
        return self.query_one(Peek)

    def sync_peek(self) -> None:
        from gbot.tui.slash.runs import working

        bot = self.gbot.state.bots.get(self.bot_list.selected_id or "")
        stop_hint = (
            f" {self.gbot.symbols.separator} ctrl+x stop" if working(bot) else ""
        )
        self.query_one("#home-hints", Static).update(
            f"space peek {self.gbot.symbols.separator} enter open {self.gbot.symbols.separator} ctrl+t pin {self.gbot.symbols.separator} ctrl+s group{stop_hint} {self.gbot.symbols.separator} ? help"
        )

        if not self.peek.display:
            return
        selected = self.bot_list.selected_id
        bot = self.gbot.state.bots.get(selected or "")
        if self.bot_list.header_key is not None or bot is None:
            self.peek.close()
            self.bot_list.focus()
            return
        row = next((row for row in self.rows if row.bot_id == bot.id), None)
        word = {
            model.RowState.NEEDS_INPUT: "needs input",
            model.RowState.WORKING: "working",
            model.RowState.NEW_REPLY: "new reply",
            model.RowState.IDLE: "idle",
        }
        cards = self.gbot.state.cards.get(bot.id, [])
        self.peek.show_bot(
            bot, word[row.state] if row else "idle", next(iter(cards), None)
        )

    def action_peek(self) -> None:
        if self.peek.display:
            self.peek.close()
        elif self.bot_list.header_key is None and self.bot_list.selected_id:
            self.peek.display = True
            self.sync_peek()
        self.bot_list.focus()

    def action_peek_answer(self, number: int) -> None:
        if self.peek.display:
            self.peek.choose(number - 1)
        else:
            self.notify("Press space to peek", timeout=2)

    def action_peek_reply(self) -> None:
        menu = self.query_one(SlashMenu)
        if menu.display and self.query_one("#dispatch", Input).has_focus:
            if menu.selected:
                field = self.query_one("#dispatch", Input)
                field.value = f"/{menu.selected.name}" + (
                    " " if menu.selected.args else ""
                )
                field.cursor_position = len(field.value)
            return
        if self.peek.display:
            self.peek.reply.focus()
        else:
            self.query_one("#dispatch", Input).focus()

    def on_click(self) -> None:
        self.call_after_refresh(self.sync_peek)

    def on_card_prompt_chosen(self, message: CardPrompt.Chosen) -> None:
        message.stop()
        self.run_worker(self._answer_peek(message), exit_on_error=False)

    async def _answer_peek(self, message: CardPrompt.Chosen) -> None:
        result = await answer_card(
            self.gbot,
            self.gbot.service,
            message.card,
            message.action,
            confirm=message.confirm,
            effect=message.effect,
        )
        if result is not None:
            self.gbot.refresh_cards(message.card.bot_id)
            self.gbot.user_acted()
            if self.peek.bot_id == message.card.bot_id:
                self.peek.schedule_reload()

    def on_card_prompt_later(self, message: CardPrompt.Later) -> None:
        message.stop()
        self.peek.close()
        self.bot_list.focus()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "interrupt":
            from gbot.tui.slash.runs import working

            return self.bot_list.header_key is None and working(
                self.gbot.state.bots.get(self.bot_list.selected_id or "")
            )
        if (
            isinstance(self.focused, (Input, TextArea))
            and action
            not in {
                "find",
                "escape",
            }
            and not (
                action in {"navigate", "peek_reply"}
                and self.query_one(SlashMenu).display
            )
        ):
            return False
        if (
            action in {"later", "printable_section", "help"}
            and self.query_one("#dispatch", Input).value
        ):
            return False
        return super().check_action(action, parameters)

    def action_help(self) -> None:
        self.gbot.action_help()

    def action_navigate(self, delta: int) -> None:
        if self.query_one(SlashMenu).display:
            self.query_one(SlashMenu).move(delta)
            return
        self.bot_list.navigate(delta)
        self.sync_peek()

    def action_page(self, delta: int) -> None:
        self.bot_list.navigate(delta * max(1, self.bot_list.size.height - 1))
        self.sync_peek()

    def action_edge(self, delta: int) -> None:
        self.bot_list.navigate(delta, edge=True)
        self.sync_peek()

    def action_section(self, delta: int) -> None:
        self.bot_list.navigate(delta, section=True)
        self.sync_peek()

    def action_printable_section(self, delta: int) -> None:
        self.action_section(delta)

    def action_open(self) -> None:
        self.bot_list.activate()

    def action_open_row(self) -> None:
        if self.bot_list.header_key is None:
            self.bot_list.activate()

    def on_bot_list_open_bot(self, message: BotList.OpenBot) -> None:
        bot = self.gbot.state.bots.get(message.bot_id)
        if bot:
            self.gbot.open_bot(bot)

    def on_bot_list_show_more(self, message: BotList.ShowMore) -> None:
        section = next(
            (s for s in self.bot_list.sections if s.key == message.section_key), None
        )
        if section is None:
            # The list was rebuilt after the message was posted; there is nothing to expand.
            return
        next_index = len(section.rows)
        self._expanded.add(message.section_key)
        self.refresh_state(force=True)
        expanded = next(
            (s for s in self.bot_list.sections if s.key == message.section_key), None
        )
        if expanded and next_index < len(expanded.rows):
            self.bot_list.selected_id = expanded.rows[next_index].bot_id
            self.bot_list.header_key = None
            self.bot_list.navigate(0)
        self.sync_peek()

    def on_bot_list_toggle_section(self, message: BotList.ToggleSection) -> None:
        self.preferences = prefs.toggle_collapsed(self.preferences, message.key)
        self._changed()

    def action_open_number(self, number: int) -> None:
        ids = self.bot_list.visible_ids
        if number <= len(ids):
            self.gbot.open_bot(self.gbot.state.bots[ids[number - 1]])

    def action_pin(self) -> None:
        if self.bot_list.selected_id and self.bot_list.header_key is None:
            self.preferences = prefs.toggle_pin(
                self.preferences, self.bot_list.selected_id
            )
            self._changed()

    def action_reorder(self, delta: int) -> None:
        selected = self.bot_list.selected_id
        for section in self.bot_list.sections:
            ids = [r.bot_id for r in section.rows]
            if selected in ids and self.bot_list.header_key is None:
                self.preferences = prefs.move_in_order(
                    self.preferences, selected, delta, ids
                )
                if section.key == "pinned":
                    self.preferences = replace(
                        self.preferences,
                        pins=tuple(
                            dict.fromkeys(
                                i
                                for i in (
                                    *self.preferences.order,
                                    *self.preferences.pins,
                                )
                                if i in self.preferences.pins
                            )
                        ),
                    )
                self._changed()
                break

    def action_group_by(self) -> None:
        self.preferences = prefs.set_group_by(
            self.preferences,
            "team" if self.preferences.group_by == "state" else "state",
        )
        self._changed()

    def _changed(self) -> None:
        self.refresh_state(force=True)
        self.save_preferences(self.preferences)

    @work(thread=True, exit_on_error=False, group="preferences")
    def save_preferences(self, value: prefs.Prefs) -> None:
        try:
            with self._save_lock:
                if value == self.preferences:
                    prefs.save(prefs.path(), value)
        except Exception as error:  # noqa: BLE001 - service/worker boundary must notify
            self.app.call_from_thread(self.gbot.service_error, error)

    def action_find(self) -> None:
        field = self.query_one("#dispatch", Input)
        field.value = "n:"
        field.focus()
        field.cursor_position = len(field.value)

    def action_escape(self) -> None:
        field = self.query_one("#dispatch", Input)
        if field.value.startswith("/"):
            field.value = ""
            return
        if self.peek.display:
            if self.peek.reply.has_focus:
                self.peek.reply.value = ""
            else:
                self.peek.close()
            self.bot_list.focus()
            return
        field = self.query_one("#dispatch", Input)
        if field.value:
            field.value = ""
        else:
            self.bot_list.focus()

    def action_later(self, feature: str) -> None:
        self.notify(f"{feature} arrives in a later unit")

    def action_interrupt(self) -> None:
        from gbot.tui.slash.runs import stop

        stop(SlashContext(self.gbot, self, self.bot_list.selected_id, None))

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "dispatch":
            return
        self.query_one(SlashMenu).update_input(event.value)
        tokens = event.value.split()
        self._filter = (
            event.value
            if tokens and all(t[:2].casefold() in {"s:", "n:", "t:"} for t in tokens)
            else ""
        )
        self.refresh_state(force=True)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "peek-reply":
            event.stop()
            text = event.value.strip()
            if text and self.peek.bot_id:
                card = self.peek.card
                self.send_peek_reply(
                    self.peek.bot_id,
                    text,
                    card.session_id if card else None,
                    str(uuid4()),
                )
            return
        if event.input.id != "dispatch":
            return
        text = event.value.strip()
        if not text or self._filter:
            return
        if text.startswith("//"):
            text = text[1:]
        elif text.startswith("/"):
            menu = self.query_one(SlashMenu)
            selected = menu.selected
            if menu.display and selected and text[1:].casefold() != selected.name:
                text = f"/{selected.name}"
            error = run(
                SlashContext(self.gbot, self, self.bot_list.selected_id, None), text
            )
            if error:
                self.gbot.notify(error, severity="warning", markup=False)
            else:
                event.input.value = ""
            return
        selected = self.bot_list.selected_id
        if text.startswith("@"):
            selector, _, text = text.partition(" ")
            name = selector[1:].casefold()
            # An exact name wins over longer names that share its prefix.
            matches = [b.id for b in self.gbot.bots if b.name.casefold() == name] or [
                b.id
                for b in self.gbot.bots
                if name and b.name.casefold().startswith(name)
            ]
            if len(matches) != 1 or not text.strip():
                self.notify("Use @name message with a unique bot name")
                return
            selected = matches[0]
        if selected is None:
            self.notify("Select a bot first")
            return
        event.input.value = ""
        self.send_message(selected, text.strip(), str(uuid4()))

    @work(thread=True, exit_on_error=False)
    def send_message(self, bot_id: str, text: str, nonce: str) -> None:
        try:
            result = self.gbot.service.send(bot_id, text, nonce=nonce)
            if not result.accepted:
                raise ValueError("Message was not accepted")
            self.app.call_from_thread(self.gbot.bot_error, bot_id)
            self.app.call_from_thread(self.gbot.user_acted)
            name = terminal_safe(self.gbot.state.bots[bot_id].name)
            self.app.call_from_thread(self.notify, f"Sent to {name}", markup=False)
        except Exception as error:  # noqa: BLE001 - service/worker boundary must notify
            self.app.call_from_thread(self.gbot.bot_error, bot_id, error)

    @work(thread=True, exit_on_error=False, group="peek-send")
    def send_peek_reply(
        self, bot_id: str, text: str, session_id: str | None, nonce: str
    ) -> None:
        try:
            result = self.gbot.service.send(
                bot_id, text, session_id=session_id, nonce=nonce
            )
            if not result.accepted:
                raise ValueError("Message was not accepted")
            self.app.call_from_thread(self._peek_sent, bot_id, text)
        except Exception as error:  # noqa: BLE001 - service/worker boundary must notify
            self.app.call_from_thread(self.gbot.bot_error, bot_id, error)

    def _peek_sent(self, bot_id: str, text: str) -> None:
        if self.peek.bot_id == bot_id and self.peek.reply.value.strip() == text:
            self.peek.reply.value = ""
        self.gbot.bot_error(bot_id)
        self.gbot.user_acted()
        name = terminal_safe(self.gbot.state.bots[bot_id].name)
        self.notify(f"Sent to {name}", markup=False)

    def on_key(self, event: events.Key) -> None:
        if (
            self.focused is self.bot_list
            and event.is_printable
            and event.character
            and event.character not in "?[] 123456789"
        ):
            field = self.query_one("#dispatch", Input)
            field.focus()
            field.value += event.character
            field.cursor_position = len(field.value)
            event.stop()
