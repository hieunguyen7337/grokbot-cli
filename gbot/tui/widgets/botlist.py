"""A full-width, line-rendered roster with stable identity and ordering."""

from dataclasses import replace
from time import monotonic
from typing import ClassVar

from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual import events
from textual.binding import BindingType
from textual.geometry import Region, Size
from textual.message import Message
from textual.scroll_view import ScrollView
from textual.strip import Strip

from gbot.tui.glyphs import glyphs
from gbot.tui.model import Row, RowState, Section, jump_section, layout_row, move


class BotList(ScrollView, can_focus=True):
    # Disable ScrollView's navigation bindings: HomeScreen owns the home keys.
    BINDINGS: ClassVar[list[BindingType]] = []
    freeze_delay = 1.0

    class OpenBot(Message):
        def __init__(self, bot_id: str) -> None:
            super().__init__()
            self.bot_id = bot_id

    class ToggleSection(Message):
        def __init__(self, key: str) -> None:
            super().__init__()
            self.key = key

    def __init__(self, *, ascii_only: bool = False, animate: bool = True) -> None:
        super().__init__(id="bot-list")
        self.ascii_only = ascii_only
        self.animations_enabled = animate
        self.sections: list[Section] = []
        self.selected_id: str | None = None
        self.header_key: str | None = None
        self.lines: list[Section | Row | str] = []
        self.frame = 0
        self._frozen_until = 0.0
        self._pending: list[Section] | None = None

    def on_mount(self) -> None:
        if self.animations_enabled:
            self.set_interval(0.15, self._tick)

    def _tick(self) -> None:
        self.frame += 1
        self.refresh()

    @property
    def visible_ids(self) -> list[str]:
        return [row.bot_id for section in self.sections for row in section.rows]

    def set_sections(self, sections: list[Section], *, force: bool = False) -> None:
        if not force and monotonic() < self._frozen_until:
            self._pending = sections
            latest = {r.bot_id: r for s in sections for r in s.rows}
            sections = [
                replace(s, rows=tuple(latest.get(r.bot_id, r) for r in s.rows))
                for s in self.sections
            ]
        else:
            self._pending = None
        self.sections = sections
        if self.selected_id not in self.visible_ids and self.header_key is None:
            self.selected_id = move(sections, None, 1)
        if self.header_key not in {s.key for s in sections}:
            self.header_key = None
        self.lines = []
        for section in sections:
            self.lines.append(section)
            self.lines.extend(section.rows)
            if section.hidden_count and not section.collapsed:
                self.lines.append(
                    f"  {glyphs(self.ascii_only).ellipsis} {section.hidden_count} more"
                )
        self.virtual_size = Size(self.size.width, len(self.lines))
        self.refresh()

    def _thaw(self) -> None:
        if monotonic() >= self._frozen_until and self._pending is not None:
            self.set_sections(self._pending, force=True)
            self._reveal()

    def freeze(self) -> None:
        self._frozen_until = monotonic() + self.freeze_delay
        self.set_timer(self.freeze_delay, self._thaw)

    def _index(self) -> int:
        for i, line in enumerate(self.lines):
            if isinstance(line, Section) and line.key == self.header_key:
                return i
            if (
                self.header_key is None
                and isinstance(line, Row)
                and line.bot_id == self.selected_id
            ):
                return i
        return 0

    def _select_line(self, index: int) -> None:
        line = self.lines[index]
        if isinstance(line, Section):
            self.header_key = line.key
        elif isinstance(line, Row):
            self.selected_id, self.header_key = line.bot_id, None
        self._reveal()
        self.refresh()

    def navigate(
        self, delta: int, *, edge: bool = False, section: bool = False
    ) -> None:
        self.freeze()
        if section:
            self.selected_id = jump_section(self.sections, self.selected_id, delta)
            self.header_key = None
        elif self.lines:
            index = (
                (0 if delta < 0 else len(self.lines) - 1)
                if edge
                else max(0, min(len(self.lines) - 1, self._index() + delta))
            )
            step = 1 if delta > 0 else -1
            while isinstance(self.lines[index], str) and 0 <= index + step < len(
                self.lines
            ):
                index += step
            self._select_line(index)
        self._reveal()
        self.refresh()

    def _reveal(self) -> None:
        self.scroll_to_region(
            Region(0, self._index(), self.size.width, 1), animate=False
        )

    def activate(self) -> None:
        if self.header_key:
            self.post_message(self.ToggleSection(self.header_key))
        elif self.selected_id:
            self.post_message(self.OpenBot(self.selected_id))

    def on_click(self, event: events.Click) -> None:
        index = int(self.scroll_y) + event.y
        if 0 <= index < len(self.lines):
            self.focus()
            self.freeze()
            self._select_line(index)
            if event.chain == 2:
                self.activate()

    def render_line(self, y: int) -> Strip:
        index = y + int(self.scroll_y)
        width = self.scrollable_content_region.width
        base = self.rich_style
        if index >= len(self.lines):
            return Strip.blank(width, base)
        line = self.lines[index]
        if isinstance(line, Row):
            selected = self.header_key is None and line.bot_id == self.selected_id
            style = base + Style(bgcolor="#493229") if selected else base
            layout = layout_row(
                line,
                width - (len(line.badge) + 1 if line.badge else 0),
                frame=self.frame,
                ascii_only=self.ascii_only,
            )
            text = Text("  ", style=style)
            text.append(
                layout.glyph,
                style="#d2b45f" if line.state == RowState.NEEDS_INPUT else None,
            )
            text.append(f" {layout.name} ")
            # Reserve room for the badge so failures remain visible at narrow widths.
            if line.badge:
                text.append(
                    line.badge + " ",
                    style="#d16969" if line.badge == "failed" else "#d2b45f",
                )
            text.append(layout.summary)
            text.append(layout.age, style="dim")
        elif isinstance(line, Section):
            style = (
                base + Style(bgcolor="#493229") if self.header_key == line.key else base
            )
            text = Text(
                line.title + (" (collapsed)" if line.collapsed else ""),
                style=style + Style(dim=True),
            )
        else:
            style = base
            text = Text(line, style=base + Style(dim=True))
        segments = [
            Segment(
                segment.text, style + (segment.style or Style.null()), segment.control
            )
            for segment in text.render(self.app.console, end="")
        ]
        return Strip(segments or [Segment("", style)]).adjust_cell_length(width, style)
