from collections.abc import Mapping, Sequence
from dataclasses import replace
from threading import Lock
from time import time
from typing import TYPE_CHECKING, ClassVar, cast
from uuid import uuid4

from rich.text import Text
from textual import events, work
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Input, Static, TextArea

from gbot.output import terminal_safe
from gbot.service.models import Bot, ConnectionStatus
from gbot.tui import model, prefs
from gbot.tui.widgets.botlist import BotList

if TYPE_CHECKING:
    from gbot.tui.app import GbotApp

HOME_BINDINGS = [
    Binding(key, action, description)
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
        ("ctrl+x", "interrupt", "Interrupt (arrives later)"),
        ("space", "later('Peek')", "Peek (arrives later)"),
        ("?", "help", "Keyboard help"),
        ("escape", "escape", "Clear input / focus list"),
    )
] + [
    *[
        Binding(str(n), "later('Peek answers')", f"Peek answer {n} (arrives later)")
        for n in range(1, 10)
    ],
    *[
        Binding(f"alt+{n}", f"open_number({n})", f"Open visible bot {n}")
        for n in range(1, 10)
    ],
]


class HomeScreen(Screen):
    BINDINGS: ClassVar[list[BindingType]] = [*HOME_BINDINGS]

    def __init__(self) -> None:
        super().__init__()
        self.preferences = prefs.Prefs()
        self.rows: list[model.Row] = []
        self._filter = ""
        self._save_lock = Lock()

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
        yield BotList(
            ascii_only=self.gbot.ascii_only, animate=self.gbot.animations_enabled
        )
        separator = self.gbot.symbols.separator
        yield Input(
            placeholder=f"> message {separator} @bot {separator} /command {separator} s: n: t: filters",
            id="dispatch",
        )
        yield Static(
            f"space peek {separator} enter open {separator} ctrl+t pin {separator} ctrl+s group {separator} ? help",
            id="home-hints",
            markup=False,
        )

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
        )
        totals = model.counts(self.rows)
        left, right = model.header_text(
            totals, state.status, ascii_only=self.gbot.ascii_only
        )
        self.query_one("#heading", Static).update(Text(left))
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

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if isinstance(self.focused, (Input, TextArea)) and action not in {
            "find",
            "escape",
        }:
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
        self.bot_list.navigate(delta)

    def action_page(self, delta: int) -> None:
        self.bot_list.navigate(delta * max(1, self.bot_list.size.height - 1))

    def action_edge(self, delta: int) -> None:
        self.bot_list.navigate(delta, edge=True)

    def action_section(self, delta: int) -> None:
        self.bot_list.navigate(delta, section=True)

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
        if field.value:
            field.value = ""
        else:
            self.bot_list.focus()

    def action_later(self, feature: str) -> None:
        self.notify(f"{feature} arrives in a later unit")

    def action_interrupt(self) -> None:
        self.action_later("Interrupt")

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "dispatch":
            return
        tokens = event.value.split()
        self._filter = (
            event.value
            if tokens and all(t[:2].casefold() in {"s:", "n:", "t:"} for t in tokens)
            else ""
        )
        self.refresh_state(force=True)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "dispatch":
            return
        text = event.value.strip()
        if not text or self._filter:
            return
        if text.startswith("/"):
            self.action_later("Slash commands")
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
            name = terminal_safe(self.gbot.state.bots[bot_id].name)
            self.app.call_from_thread(self.notify, f"Sent to {name}", markup=False)
        except Exception as error:  # noqa: BLE001 - service/worker boundary must notify
            self.app.call_from_thread(self.gbot.service_error, error)

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
