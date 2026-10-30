"""Read-only transcript entries. Untrusted text never passes through Rich markup."""

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Markdown, Static

from gbot.output import terminal_safe
from gbot.pending import describe, one_line
from gbot.service.models import Entry
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

    def __init__(self, text: str, symbols: Glyphs, streaming: bool) -> None:
        super().__init__()
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
            Text(f"{symbols.bot} {summary} (answer from the card prompt)")
        )
    elif entry.is_user:
        widget = UserEntry(Text(f"{symbols.user} {text}"))
    elif entry.kind == "send-message" or (
        entry.kind == "message" and entry.role == "assistant"
    ):
        widget = BotEntry(entry.text, symbols, entry.streaming)
    elif entry.kind == "tool-call":
        pending = (
            f" {symbols.working[0]}" if entry.raw.get("status") == "pending" else ""
        )
        widget = ToolEntry(Text(f"{symbols.tool} {one_line(text)}{pending}"))
        widget.set_class(entry.raw.get("status") == "failed", "failed")
    elif entry.kind == "notice":
        widget = NoticeEntry(Text(text))
    else:
        suffix = (
            " (open the Grok Bot app)"
            if entry.kind in {"voice-call", "mcp-app"}
            else ""
        )
        widget = UnsupportedEntry(Text(one_line(terminal_safe(entry.kind)) + suffix))
    return widget


class Transcript(VerticalScroll):
    DEFAULT_CSS = """
    Transcript { overflow-x: hidden; }
    Transcript > #history-marker { height: 1; color: $text-muted; text-style: dim; }
    """

    class TopReached(Message):
        """The user scrolled into the oldest loaded history."""

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.marker = Static("Loading…", id="history-marker", markup=False)

    def compose(self) -> ComposeResult:
        yield self.marker

    def watch_scroll_y(self, old_value: float, new_value: float) -> None:
        super().watch_scroll_y(old_value, new_value)
        if old_value != new_value and new_value == 0:
            self.post_message(self.TopReached())

    async def prepend_entries(self, widgets: list[Widget], *, initial: bool) -> None:
        anchor = next(iter(self.children[1:]), None)
        anchor_y = anchor.virtual_region.y if anchor else 0
        scroll_y = self.scroll_y
        if widgets:
            await self.mount(*widgets, after=self.marker)

        def restore() -> None:
            if initial:
                self.scroll_end(animate=False, immediate=True)
            elif anchor:
                self.scroll_to(
                    y=scroll_y + anchor.virtual_region.y - anchor_y,
                    animate=False,
                    immediate=True,
                )

        self.call_after_refresh(restore)
