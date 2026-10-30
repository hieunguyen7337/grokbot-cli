"""Read-only transcript entries. Untrusted text never passes through Rich markup."""

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Markdown, Static

from gbot.output import terminal_safe
from gbot.pending import describe, one_line
from gbot.service.models import Entry
from gbot.service.reactions import entry_reactions
from gbot.tui.glyphs import Glyphs


class UserEntry(Static):
    DEFAULT_CSS = "UserEntry { height: auto; margin: 1 0; }"


class BotEntry(Widget):
    DEFAULT_CSS = """
    BotEntry { layout: horizontal; height: auto; margin: 1 0; }
    BotEntry > Static { width: 2; height: 1; }
    BotEntry > Markdown { width: 1fr; height: auto; padding: 0; margin: 0; }
    BotEntry MarkdownBlock { margin: 0; }
    """

    def __init__(
        self, text: str, symbols: Glyphs, streaming: bool, *, name: str | None = None
    ) -> None:
        super().__init__(name=name)
        self.text = terminal_safe(text)
        self.symbols = symbols
        self.streaming = streaming

    def compose(self) -> ComposeResult:
        yield Static(Text(self.symbols.bot))
        suffix = f"\n\n{self.symbols.working[0]}" if self.streaming else ""
        yield Markdown(self.text + suffix, open_links=False)


class ToolEntry(Static):
    DEFAULT_CSS = """
    ToolEntry { height: auto; padding-left: 2; color: $text-muted; text-style: dim; }
    ToolEntry.failed { color: $error; text-style: none; }
    """


class NoticeEntry(Static):
    DEFAULT_CSS = """
    NoticeEntry { height: auto; color: $text-muted; text-style: dim italic; }
    """


class CardEntry(Static):
    DEFAULT_CSS = """
    CardEntry { height: 1; margin: 1 0; text-overflow: ellipsis; }
    """


class UnsupportedEntry(Static):
    DEFAULT_CSS = """
    UnsupportedEntry { height: 1; color: $text-muted; text-style: dim; }
    """


def entry_widget(entry: Entry, symbols: Glyphs) -> Widget:
    """Render a single entry without interpreting user text as markup."""
    text = terminal_safe(entry.text)
    widget: Widget
    if entry.card_type:
        summary = one_line(terminal_safe(describe(dict(entry.raw))))
        if summary == "unknown":
            summary = one_line(terminal_safe(entry.card_type))
        widget = CardEntry(
            Text(f"{symbols.bot} {summary} (answer from the card prompt)"),
            name=entry.id,
        )
    elif entry.is_user:
        widget = UserEntry(Text(f"{symbols.user} {text}"), name=entry.id)
    elif entry.kind == "send-message" or (
        entry.kind == "message" and entry.role == "assistant"
    ):
        widget = BotEntry(entry.text, symbols, entry.streaming, name=entry.id)
    elif entry.kind == "tool-call":
        pending = (
            f" {symbols.working[0]}" if entry.raw.get("status") == "pending" else ""
        )
        widget = ToolEntry(
            Text(f"{symbols.tool} {one_line(text)}{pending}"), name=entry.id
        )
        widget.set_class(entry.raw.get("status") == "failed", "failed")
    elif entry.kind == "notice":
        widget = NoticeEntry(Text(text), name=entry.id)
    else:
        suffix = (
            " (open the Grok Bot app)"
            if entry.kind in {"voice-call", "mcp-app"}
            else ""
        )
        widget = UnsupportedEntry(
            Text(one_line(terminal_safe(entry.kind)) + suffix), name=entry.id
        )
    reactions = entry_reactions(entry)
    if reactions:
        line = Text(
            "  ".join(
                f"{terminal_safe(emoji)} {count}" for emoji, count, _ in reactions
            ),
            style="dim",
        )
        widget = Vertical(widget, Static(line), name=entry.id, classes="reacted-entry")
        widget.styles.height = "auto"
    setattr(widget, "entry", entry)  # noqa: B010 - widgets retain their source entry
    return widget


class NewEntries(Static):
    DEFAULT_CSS = """
    NewEntries { dock: bottom; height: 1; width: auto; align-horizontal: center;
        background: $accent; color: $text; padding: 0 1; }
    """

    def on_click(self) -> None:
        self.post_message(self.Latest())

    class Latest(Message):
        """Jump to the latest entries."""


class Transcript(VerticalScroll, can_focus=False):
    DEFAULT_CSS = """
    Transcript { overflow-x: hidden; }
    Transcript > #history-marker { height: 1; color: $text-muted; text-style: dim; }
    """

    class TopReached(Message):
        """The user scrolled into the oldest loaded history."""

    def __init__(self, *, id: str | None = None, ascii_only: bool = False) -> None:
        super().__init__(id=id)
        self.marker = Static("Loading…", id="history-marker", markup=False)
        self.entries: dict[str, Widget] = {}
        self.new_count = 0
        self.pill = NewEntries(markup=False)
        self.ascii_only = ascii_only
        self._pin_pending = False

    @property
    def at_bottom(self) -> bool:
        # Textual anchors short transcripts with a negative scroll offset.
        return self.max_scroll_y == 0 or self.max_scroll_y - self.scroll_y <= 1

    def latest(self) -> None:
        self._pin_pending = True
        self._clear_new()
        self.call_after_refresh(self._pin_bottom)

    def _pin_bottom(self) -> None:
        self.anchor()
        self._pin_pending = False

    def _clear_new(self) -> None:
        self.new_count = 0
        if self.pill.is_mounted:
            self.pill.remove()
            self.pill = NewEntries(markup=False)

    def on_new_entries_latest(self, message: NewEntries.Latest) -> None:
        message.stop()
        self.latest()

    def compose(self) -> ComposeResult:
        yield self.marker

    def watch_scroll_y(self, old_value: float, new_value: float) -> None:
        super().watch_scroll_y(old_value, new_value)
        if old_value != new_value and self.at_bottom:
            self._clear_new()
        if old_value != new_value and new_value == 0:
            self.post_message(self.TopReached())

    async def prepend_entries(self, widgets: list[Widget], *, initial: bool) -> None:
        anchor = next(iter(self.entries.values()), None)
        anchor_y = anchor.virtual_region.y if anchor else 0
        scroll_y = self.scroll_y
        fresh = []
        for widget in widgets:
            if widget.name is not None:
                if widget.name in self.entries:
                    continue
                self.entries[widget.name] = widget
            fresh.append(widget)
        # Dict order follows the visual history, including newly loaded older pages.
        self.entries = {
            **{w.name: w for w in fresh if w.name is not None},
            **self.entries,
        }
        if fresh:
            await self.mount(*fresh, after=self.marker)

        def restore() -> None:
            if initial:
                self.anchor()
                # Land on the newest entry in this frame rather than after the next layout pass.
                self.scroll_end(animate=False, immediate=True)
            elif anchor:
                self.scroll_to(
                    y=scroll_y + anchor.virtual_region.y - anchor_y,
                    animate=False,
                    immediate=True,
                )

        self.call_after_refresh(restore)

    async def append_entry(self, widget: Widget) -> None:
        if widget.name in self.entries:
            await self.replace_entry(widget)
            return
        pinned = self._pin_pending or (self.at_bottom and not self.new_count)
        self._pin_pending = pinned
        if widget.name is not None:
            self.entries[widget.name] = widget
        await self.mount(widget)
        if pinned:
            self.call_after_refresh(self._pin_bottom)
        else:
            self.new_count += 1
            self.pill.update(f"{self.new_count} new {'v' if self.ascii_only else '↓'}")
            if not self.pill.is_mounted:
                await self.mount(self.pill)

    async def replace_entry(self, widget: Widget) -> None:
        old = self.entries.get(widget.name or "")
        if old is None:
            await self.append_entry(widget)
            return
        pinned = self._pin_pending or (self.at_bottom and not self.new_count)
        self._pin_pending = pinned
        await self.mount(widget, before=old)
        await old.remove()
        self.entries[widget.name or ""] = widget
        if pinned:
            self.call_after_refresh(self._pin_bottom)

    async def remove_entry(self, entry_id: str) -> None:
        pinned = self.at_bottom and not self.new_count
        widget = self.entries.pop(entry_id, None)
        if widget is not None:
            await widget.remove()
        if pinned:
            self.latest()

    async def reset_entries(self, widgets: list[Widget]) -> None:
        await self.remove_children(list(self.entries.values()))
        self.entries.clear()
        self._clear_new()
        await self.prepend_entries(widgets, initial=True)
