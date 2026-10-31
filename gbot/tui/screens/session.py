import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, cast
from uuid import uuid4

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.events import Mount, Paste
from textual.screen import Screen
from textual.widgets import Input, Static

from gbot.output import terminal_safe
from gbot.service import attachments, events
from gbot.service.attachments import Attachment
from gbot.service.models import Card, TranscriptPage
from gbot.tui.answering import answer_card
from gbot.tui.slash import SlashContext, run
from gbot.tui.widgets.prompt import CardPrompt
from gbot.tui.widgets.slashmenu import SlashMenu
from gbot.tui.widgets.transcript import Transcript, entry_widget

if TYPE_CHECKING:
    from gbot.tui.app import GbotApp


class _SessionInput(Input):
    def _on_paste(self, event: Paste) -> None:
        from gbot.tui.slash.attachments import file_path

        event.prevent_default()
        screen = cast("SessionScreen", self.screen)
        value = event.text.strip()
        if value and "\n" not in value and "\r" not in value:
            try:
                path = file_path(value)
                exists = path.is_file()
            except (OSError, ValueError, RuntimeError):
                pass
            else:
                if exists:
                    if not screen.gbot.read_only:
                        screen.stage_file(path)
                        event.stop()
                        return
                    screen.gbot.notify("Read-only mode", markup=False)
        super()._on_paste(event)

    def check_consume_key(self, key: str, character: str | None) -> bool:
        # Retry must remain reachable while the empty composer has focus.
        if key == "r" and not self.value and cast("SessionScreen", self.screen).failed:
            return False
        return super().check_consume_key(key, character)


class _SessionPrompt(CardPrompt):
    def on_mount(self, event: Mount | None = None) -> None:
        if event and self.screen.query_one("#session-input", Input).value:
            # A card arriving mid-sentence must not catch the next keystroke as an answer.
            event.prevent_default()
        self.query_one("#prompt-hint", Static).update(
            Text(
                f"tab reply {self.symbols.separator} enter choose {self.symbols.separator} 1-9 pick"
            )
        )

    def _choice_text(self) -> Text:
        return Text(super()._choice_text().plain.replace("\n", "   "))

    def _body(self) -> Text:
        body = super()._body()
        lines = body.plain.splitlines()
        if len(lines) > 3:
            if not self.expanded:
                return Text(
                    "\n".join([*lines[:3], f"{self.symbols.ellipsis} e to expand"])
                )
            if lines[-1] != "e to collapse":
                body.append("\ne to collapse")
        return body


class SessionScreen(Screen):
    DEFAULT_CSS = """
    SessionScreen { layout: vertical; }
    SessionScreen #session-status { height: 1; }
    SessionScreen #session-history { height: 1fr; margin-top: 1; }
    SessionScreen #session-input { height: 3; border: round $secondary; }
    SessionScreen #session-notice { height: auto; color: $text-muted; }
    SessionScreen #session-alert { height: auto; color: $warning; }
    SessionScreen #session-attachments { height: auto; color: $text-muted; }
    SessionScreen #session-card { height: auto; max-height: 50%; }
    SessionScreen CardPrompt { max-height: 100%; }
    SessionScreen #session-footer { height: 1; color: $text-muted; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "escape", "Home", priority=True),
        Binding("ctrl+x", "interrupt", "Stop", priority=True),
        Binding("up", "menu_up", "Previous command", priority=True),
        Binding("down", "menu_down", "Next command", priority=True),
        Binding("pageup", "earlier", "Earlier", priority=True),
        Binding("home", "history_top", "Top", priority=True),
        Binding("end", "latest", "Latest", priority=True),
        Binding("tab", "prompt_focus", "Prompt", priority=True),
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
        self.card: Card | None = None
        self._box: str | None = None
        self._box_live = False
        self._pending: list[events.Event] = []
        self._applying = False
        self._transcript_lock = asyncio.Lock()
        self._page_generation = 0
        self._sending = False
        self._send_text: str | None = None
        self._send_nonce: str | None = None
        self.attachments: list[Attachment] = []
        self.uploads = 0
        self._upload_progress: dict[int, str] = {}
        self._upload_id = 0
        self._send_paths: tuple[str, ...] = ()
        self._sending_attachments: tuple[Attachment, ...] = ()

    @property
    def gbot(self) -> "GbotApp":
        return cast("GbotApp", self.app)

    def compose(self) -> ComposeResult:
        yield Static(terminal_safe(self.bot_name), id="session-status", markup=False)
        yield Transcript(id="session-history", ascii_only=self.gbot.ascii_only)
        yield Vertical(id="session-card")
        yield Static("", id="session-notice", markup=False)
        yield SlashMenu("session")
        yield Static("", id="session-alert", markup=False)
        line = Static("", id="session-attachments", markup=False)
        line.display = False
        yield line
        yield _SessionInput(placeholder="message", id="session-input")
        yield Static("esc home · pgup earlier", id="session-footer", markup=False)

    def on_mount(self) -> None:
        self.query_one(Input).focus()
        self.refresh_state()
        self.gbot.follow(self.bot_id, self.session_id)
        self._start_load()
        self.load_box()

    def on_unmount(self) -> None:
        self.gbot.unfollow(self.bot_id, self.session_id)

    def refresh_attachments(self) -> None:
        if not self.is_mounted:
            return
        line = self.query_one("#session-attachments", Static)
        parts = [terminal_safe(item.name) for item in self.attachments]
        parts.extend(self._upload_progress.values())
        line.display = bool(parts)
        line.update(
            Text(
                f"{self.gbot.symbols.attachment} "
                + " · ".join(parts + ["/detach to remove"])
            )
        )

    def stage_file(self, path: Path) -> None:
        if self.gbot.read_only:
            self.gbot.notify("Read-only mode", markup=False)
            return
        self._upload_id += 1
        token = self._upload_id
        self.uploads += 1
        self._progress(token, path.name, 0, 1)
        self._upload_file(path, token)

    def _progress(self, token: int, name: str, done: int, total: int) -> None:
        self._upload_progress[token] = (
            f"Uploading {terminal_safe(name)} {done * 100 // max(total, 1)}%"
        )
        self.refresh_attachments()

    @work(thread=True, exit_on_error=False)
    def _upload_file(self, path: Path, token: int) -> None:
        try:
            item = attachments.upload(
                self.gbot.service.transport,
                self.bot_id,
                path,
                progress=lambda done, total: self.app.call_from_thread(
                    self._progress, token, path.name, done, total
                ),
            )
        except Exception as error:  # noqa: BLE001 - upload worker boundary
            self.app.call_from_thread(self._uploaded, token, None, str(error))
        else:
            self.app.call_from_thread(self._uploaded, token, item, "")

    def _uploaded(self, token: int, item: Attachment | None, error: str) -> None:
        self.uploads -= 1
        self._upload_progress.pop(token, None)
        if item is not None:
            self.attachments.append(item)
            self.gbot.notify(
                f"Attached {terminal_safe(item.name)} · /detach to remove", markup=False
            )
        else:
            self.gbot.notify(terminal_safe(error), severity="warning", markup=False)
        self.refresh_attachments()

    def refresh_state(self) -> None:
        if not self.is_mounted:
            return
        bot = self.gbot.state.bots.get(self.bot_id)
        alerts = [tray for tray in self.gbot.trays if tray.agent_id == self.bot_id]
        indicator = self.query_one("#session-alert", Static)
        indicator.display = bool(alerts)
        if alerts:
            newest = max(alerts, key=lambda tray: tray.created_at)
            more = f" +{len(alerts) - 1} more" if len(alerts) > 1 else ""
            indicator.update(terminal_safe(f"! {newest.title}{more} · /trays"))
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
        }.get(self._box or "")
        if computer:
            parts.append(computer)
        self.query_one("#session-status", Static).update(
            f" {self.gbot.symbols.separator} ".join(parts)
        )
        card = next(
            (
                card
                for card in self.gbot.state.cards.get(self.bot_id, [])
                if card.session_id == self.session_id
            ),
            None,
        )
        if (card.entry_id if card else None) != (
            self.card.entry_id if self.card else None
        ):
            self.card = card
            holder = self.query_one("#session-card", Vertical)
            holder.remove_children()
            if card:
                holder.mount(_SessionPrompt(card, ascii_only=self.gbot.ascii_only))
            else:
                self.query_one("#session-input", Input).focus()
        separator = f" {self.gbot.symbols.separator} "
        footer = ["esc home", "pgup earlier", "end latest"]
        if card:
            footer.append("tab prompt")
        self.query_one("#session-footer", Static).update(separator.join(footer))

    def _show_box(self, box: str | None) -> None:
        if not self._box_live:
            self._box = box
        self.refresh_state()

    @work(thread=True, exit_on_error=False)
    def load_box(self) -> None:
        try:
            box = self.gbot.service.box_state(self.bot_id)
        except Exception:  # noqa: BLE001 — optional status must not hide the transcript
            box = None
        self.app.call_from_thread(self._show_box, box)

    def _start_load(self) -> None:
        if (
            self._loading_page
            or self._applying
            or (self.loaded and self.next_before_seq is None)
        ):
            return
        self._loading_page = True
        self.failed = False
        # The loading line shows for the first page and for older pages alike.
        self.query_one(Transcript).marker.update(f"Loading{self.gbot.symbols.ellipsis}")
        self.load_page(
            self.next_before_seq if self.loaded else None, self._page_generation
        )

    @work(thread=True, exit_on_error=False)
    def load_page(self, before: int | None, generation: int) -> None:
        try:
            if before is None:
                first_page = (
                    self.gbot.service.transcript
                    if self.gbot.read_only
                    else self.gbot.service.open
                )
                page = first_page(self.bot_id, session_id=self.session_id, limit=200)
            else:
                page = self.gbot.service.transcript(
                    self.bot_id,
                    before_seq=before,
                    limit=50,
                    session_id=self.session_id,
                )
        except Exception as exc:  # noqa: BLE001 — worker errors become inline retry notices
            self.app.call_from_thread(self._load_error, str(exc), generation)
        else:
            self.app.call_from_thread(self._show_page, page, generation)

    def _load_error(self, error: str, generation: int) -> None:
        if not self.is_mounted or generation != self._page_generation:
            return
        self._loading_page = False
        self.failed = True
        self.query_one(Transcript).marker.update(
            f"{terminal_safe(error)} — press r to retry"
        )
        self.call_after_refresh(self.query_one("#session-input", Input).focus)
        self._drain_events()

    async def _show_page(self, page: TranscriptPage, generation: int) -> None:
        async with self._transcript_lock:
            if not self.is_mounted or generation != self._page_generation:
                return
            history = self.query_one(Transcript)
            await history.prepend_entries(
                [entry_widget(e, self.gbot.symbols) for e in page.entries],
                initial=not self.loaded,
            )
            self.next_before_seq = page.next_before_seq
            self.loaded = True
            self._update_marker()
            self._drain_events()
            self.call_after_refresh(self._load_finished)

    def _update_marker(self) -> None:
        history = self.query_one(Transcript)
        history.marker.update(
            "Beginning of conversation"
            if self.next_before_seq is None
            else "pgup earlier"
        )

    def apply_event(self, event: events.Event) -> None:
        if isinstance(event, (events.EntryAdded, events.EntryChanged)):
            bot_id, session_id = event.entry.bot_id, event.entry.session_id
        elif isinstance(event, (events.EntryRemoved, events.TranscriptReset)):
            bot_id, session_id = event.bot_id, event.session_id
        elif isinstance(event, events.BoxChanged):
            if event.bot_id == self.bot_id:
                self._box, self._box_live = event.state, True
                self.refresh_state()
            return
        else:
            return
        if bot_id != self.bot_id or session_id != self.session_id:
            return
        self._pending.append(event)
        self._drain_events()

    def _drain_events(self) -> None:
        if self.loaded and self._pending and not self._applying:
            self._applying = True
            self.run_worker(self._apply_pending(), exit_on_error=False)

    async def _apply_pending(self) -> None:
        async with self._transcript_lock:
            history = self.query_one(Transcript)
            try:
                while self._pending:
                    event = self._pending.pop(0)
                    if isinstance(event, (events.EntryAdded, events.EntryChanged)):
                        await history.replace_entry(
                            entry_widget(event.entry, self.gbot.symbols)
                        )
                    elif isinstance(event, events.EntryRemoved):
                        await history.remove_entry(event.entry_id)
                    elif isinstance(event, events.TranscriptReset):
                        self._page_generation += 1
                        self._loading_page = False
                        self.failed = False
                        entries = [
                            entry
                            for entry in event.entries
                            if entry.bot_id == self.bot_id
                            and entry.session_id == self.session_id
                        ]
                        await history.reset_entries(
                            [
                                entry_widget(entry, self.gbot.symbols)
                                for entry in entries
                            ]
                        )
                        oldest = min((entry.seq for entry in entries), default=0)
                        self.next_before_seq = oldest if oldest > 1 else None
                        self._update_marker()
            finally:
                self._applying = False

    def _load_finished(self) -> None:
        self._loading_page = False
        self._drain_events()

    def on_transcript_top_reached(self) -> None:
        if self.loaded and not self.failed and not self._applying:
            self._start_load()

    def action_earlier(self) -> None:
        history = self.query_one(Transcript)
        if history.scroll_y <= 0:
            self._start_load()
        else:
            history.scroll_page_up(animate=False)

    def action_history_top(self) -> None:
        history = self.query_one(Transcript)
        if history.scroll_y <= 0:
            self._start_load()
        else:
            history.scroll_home(animate=False)

    def action_later(self) -> None:
        self.query_one(Transcript).scroll_page_down(animate=False)

    def action_latest(self) -> None:
        self.query_one(Transcript).latest()

    def action_prompt_focus(self) -> None:
        menu = self.query_one(SlashMenu)
        if menu.display:
            if menu.selected:
                composer = self.query_one("#session-input", Input)
                composer.value = f"/{menu.selected.name}" + (
                    " " if menu.selected.args else ""
                )
                composer.cursor_position = len(composer.value)
            return
        prompt = next(iter(self.query(CardPrompt)), None)
        composer = self.query_one("#session-input", Input)
        if prompt is not None and composer.has_focus:
            prompt.focus()
        else:
            composer.focus()

    def on_card_prompt_later(self, message: CardPrompt.Later) -> None:
        message.stop()
        self.query_one("#session-input", Input).focus()

    def on_card_prompt_chosen(self, message: CardPrompt.Chosen) -> None:
        message.stop()
        self.run_worker(self._answer(message), exit_on_error=False)

    async def _answer(self, message: CardPrompt.Chosen) -> None:
        result = await answer_card(
            self.gbot,
            self.gbot.service,
            message.card,
            message.action,
            confirm=message.confirm,
            effect=message.effect,
        )
        if result is not None:
            self.gbot.refresh_cards(self.bot_id)
            self.gbot.user_acted()

    def action_retry(self) -> None:
        if self.failed:
            self._start_load()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "interrupt":
            from gbot.tui.slash.runs import working

            return working(self.gbot.state.bots.get(self.bot_id))
        # Printable and editing keys belong to the composer once it holds text.
        empty = not self.query_one("#session-input", Input).value
        if action == "retry":
            return self.failed and empty
        if action in {"back_if_empty", "history_top", "latest"}:
            return empty
        if action == "prompt_focus":
            return self.query_one(SlashMenu).display or self.card is not None
        if action in {"menu_up", "menu_down"}:
            return self.query_one(SlashMenu).display
        return super().check_action(action, parameters)

    def action_interrupt(self) -> None:
        from gbot.tui.slash.runs import stop

        stop(SlashContext(self.gbot, self, self.bot_id, self.session_id))

    def restore_draft(self, text: str) -> None:
        field = self.query_one("#session-input", Input)
        field.value = text
        field.cursor_position = len(text)
        field.focus()

    def action_menu_up(self) -> None:
        self.query_one(SlashMenu).move(-1)

    def action_menu_down(self) -> None:
        self.query_one(SlashMenu).move(1)

    def action_escape(self) -> None:
        field = self.query_one("#session-input", Input)
        if field.value.startswith("/"):
            field.value = ""
        else:
            self.app.pop_screen()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "session-input":
            self.query_one(SlashMenu).update_input(event.value)

    def action_back_if_empty(self) -> None:
        self.app.pop_screen()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "session-input":
            return
        event.stop()
        text = event.value.strip()
        if self._sending:
            return
        if text.startswith("//"):
            text = text[1:]
        elif text.startswith("/"):
            menu = self.query_one(SlashMenu)
            selected = menu.selected
            if menu.display and selected and text[1:].casefold() != selected.name:
                text = f"/{selected.name}"
            error = run(
                SlashContext(self.gbot, self, self.bot_id, self.session_id), text
            )
            if error:
                self.gbot.notify(error, severity="warning", markup=False)
            else:
                event.input.value = ""
            return
        if self.uploads:
            self.gbot.notify("Wait for the upload to finish", markup=False)
            return
        if not text and not self.attachments:
            return
        if self.gbot.read_only:
            self.gbot.notify("Read-only mode", markup=False)
            return
        paths = tuple(item.path for item in self.attachments)
        if (
            text != self._send_text
            or paths != self._send_paths
            or self._send_nonce is None
        ):
            self._send_text, self._send_nonce = text, str(uuid4())
            self._send_paths = paths
        self._sending_attachments = tuple(self.attachments)
        self._sending = True
        self.query_one("#session-notice", Static).update("Sending…")
        self.send_message(text, self._send_nonce, self._sending_attachments)

    @work(thread=True, exit_on_error=False)
    def send_message(
        self, text: str, nonce: str, files: tuple[Attachment, ...] = ()
    ) -> None:
        try:
            result = self.gbot.service.send(
                self.bot_id,
                text,
                session_id=self.session_id,
                nonce=nonce,
                attachments=files,
            )
            if not result.accepted:
                raise ValueError("Message was not accepted")
        except Exception as error:  # noqa: BLE001 - keep the composer available for retry
            self.app.call_from_thread(self._sent, error)
        else:
            self.app.call_from_thread(self._sent, None)

    def _sent(self, error: Exception | None) -> None:
        self._sending = False
        if self.is_mounted:
            self.query_one("#session-notice", Static).update(
                terminal_safe(str(error)) if error else ""
            )
            if error is None:
                self.query_one("#session-input", Input).value = ""
        self.gbot.bot_error(self.bot_id, error)
        if error is None:
            for item in self._sending_attachments:
                if item in self.attachments:
                    self.attachments.remove(item)
            self.refresh_attachments()
            self._send_text, self._send_nonce = None, None
            self.gbot.user_acted()
