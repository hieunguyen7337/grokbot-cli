import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum

from rich.cells import cell_len

from gbot.output import terminal_safe
from gbot.pending import PendingItem, one_line
from gbot.service.models import Bot, ConnectionStatus
from gbot.tui.glyphs import glyphs


def _summary_labels(text: str) -> str:
    return re.sub(
        r"(`+)([\s\S]*?)\1|!?\[((?:[^\[\]]|\[[^\]]*\])*)\]\((?:[^()]|\([^()]*\))*\)",
        lambda match: match[0] if match[1] else match[3],
        text,
    )


def _safe(text: str) -> str:
    return one_line(terminal_safe(text))


class RowState(Enum):
    NEEDS_INPUT = "input"
    WORKING = "working"
    NEW_REPLY = "new"
    IDLE = "idle"


@dataclass(frozen=True)
class Row:
    bot_id: str
    name: str
    state: RowState
    variant: str | None
    summary: str
    age_ms: int | None
    badge: str | None
    is_group: bool
    is_shared_room: bool
    pinned: bool
    card_count: int
    member_ids: tuple[str, ...] = ()
    pin_index: int = 0


def build_rows(
    bots: Iterable[Bot],
    cards: Iterable[PendingItem],
    *,
    now_ms: int,
    pins: Iterable[str] = (),
    errors: Mapping[str, str] = {},
) -> list[Row]:
    card_list, pin_list = list(cards), list(pins)
    pin_set = set(pin_list)
    result = []
    for bot in bots:
        if bot.hidden:
            continue
        found = [c for c in card_list if c.bot_id == bot.id]
        main = [c for c in found if c.session_id is None]
        answerable = next((c for c in main if c.allowed_actions), None)
        card = answerable or next(iter(main), None)
        variant = None
        if card:
            state = RowState.NEEDS_INPUT
            variant = "card" if card.allowed_actions else "app_only"
            summary = card.summary
            if card.type in {"email-draft", "slack-draft", "meeting-chat-draft"}:
                summary = f"{card.type.replace('-', ' ').capitalize()}: {summary}"
            if card.type == "widget":
                summary += f" ({len(card.options or [])} choices)"
            if variant == "app_only":
                summary += " (open the Grok Bot app)"
        elif found:
            state, variant, summary = (
                RowState.NEEDS_INPUT,
                "other_session",
                "Needs you in another chat",
            )
        elif bot.awaiting:
            state, variant = RowState.NEEDS_INPUT, "awaiting"
            summary = f"Waiting for you: {bot.awaiting.reason}"
        elif bot.busy:
            state, summary = RowState.WORKING, bot.activity or "Thinking"
        elif bot.unread:
            state, summary = RowState.NEW_REPLY, bot.preview or bot.description
        else:
            state, summary = RowState.IDLE, bot.preview or bot.description
        age = (
            None
            if bot.last_activity_at is None
            else max(0, now_ms - bot.last_activity_at)
        )
        badge = (
            "failed"
            if bot.last_outcome == "failed"
            else "retrying"
            if bot.retrying
            else "error"
            if bot.id in errors
            else None
        )
        result.append(
            Row(
                bot.id,
                _safe(bot.name),
                state,
                variant,
                _safe(_summary_labels(summary)),
                age,
                badge,
                bot.is_group,
                bot.is_shared_room,
                bot.id in pin_set,
                len(found),
                bot.member_ids,
                pin_list.index(bot.id) if bot.id in pin_set else 0,
            )
        )
    return result


def age_text(age_ms: int) -> str:
    seconds = max(0, age_ms) // 1000
    if seconds < 10:
        return "now"
    for size, suffix in ((604800, "w"), (86400, "d"), (3600, "h"), (60, "m")):
        if seconds >= size:
            return f"{seconds // size}{suffix}"
    return f"{seconds}s"


@dataclass(frozen=True)
class Section:
    key: str
    title: str
    rows: tuple[Row, ...]
    hidden_count: int = 0
    collapsed: bool = False


def group(
    rows: Sequence[Row],
    *,
    by: str = "state",
    order: Sequence[str] = (),
    collapsed: frozenset[str] = frozenset(),
    expanded: frozenset[str] = frozenset(),
    idle_limit: int = 5,
) -> list[Section]:
    sections: list[Section] = []

    def add(key: str, title: str, items: list[Row], hidden: int = 0) -> None:
        if items or hidden:
            sections.append(
                Section(
                    key,
                    title,
                    () if key in collapsed else tuple(items),
                    hidden,
                    key in collapsed,
                )
            )

    if by == "team":
        assigned: set[str] = set()
        lookup = {r.bot_id: r for r in rows}
        for team in (r for r in rows if r.is_group):
            members = [
                lookup[i]
                for i in team.member_ids
                if i in lookup and i != team.bot_id and not lookup[i].is_group
            ]
            assigned.update(r.bot_id for r in members)
            assigned.add(team.bot_id)
            add(team.bot_id, team.name, [team, *members])
        add("other", "Other", [r for r in rows if r.bot_id not in assigned])
    elif by == "state":
        positions = {v: i for i, v in enumerate(order)}

        def sort_key(r: Row) -> tuple[int, int, float]:
            return (
                0 if r.bot_id in positions else 1,
                positions.get(r.bot_id, 0),
                r.age_ms if r.age_ms is not None else float("inf"),
            )

        pinned = [r for r in rows if r.pinned]
        pinned.sort(key=lambda r: r.pin_index)
        add("pinned", "Pinned", pinned)
        for state, key, title in (
            (RowState.NEEDS_INPUT, "input", "Needs input"),
            (RowState.WORKING, "working", "Working"),
            (RowState.NEW_REPLY, "new", "New replies"),
            (RowState.IDLE, "idle", "Idle"),
        ):
            items = sorted(
                (r for r in rows if not r.pinned and r.state == state), key=sort_key
            )
            hidden = 0
            if state == RowState.IDLE and key not in expanded:
                limit = max(0, idle_limit)
                hidden = max(0, len(items) - limit)
                items = items[:limit]
            add(key, title, items, hidden)
    else:
        raise ValueError("Unknown grouping")
    return sections


@dataclass(frozen=True)
class Filter:
    words: tuple[str, ...] = ()
    states: tuple[str, ...] = ()
    names: tuple[str, ...] = ()
    teams: tuple[str, ...] = ()


def parse_filter(text: str) -> Filter:
    parts: dict[str, list[str]] = {"words": [], "states": [], "names": [], "teams": []}
    for token in text.casefold().split():
        key = {"s:": "states", "n:": "names", "t:": "teams"}.get(token[:2])
        if key and len(token) > 2:
            parts[key].append(token[2:])
        else:
            parts["words"].append(token)
    return Filter(*(tuple(parts[k]) for k in ("words", "states", "names", "teams")))


def apply_filter(rows: Sequence[Row], filter: Filter, bots: Sequence[Bot]) -> list[Row]:
    teams = [b for b in bots if b.is_group]
    return [
        r
        for r in rows
        if all(w in (r.name + " " + r.summary).casefold() for w in filter.words)
        and all(s == r.state.value for s in filter.states)
        and all(n in r.name.casefold() for n in filter.names)
        and all(
            any(
                t in _safe(b.name).casefold() and r.bot_id in b.member_ids
                for b in teams
            )
            for t in filter.teams
        )
    ]


def counts(rows: Iterable[Row]) -> dict[RowState, int]:
    result = dict.fromkeys(RowState, 0)
    for row in rows:
        result[row.state] += 1
    return result


def header_text(
    counts: dict[RowState, int],
    status: ConnectionStatus,
    *,
    ascii_only: bool = False,
    attempt: int = 0,
) -> tuple[str, str]:
    g = glyphs(ascii_only)
    labels = (
        (RowState.NEEDS_INPUT, "need you", "need you"),
        (RowState.WORKING, "working", "working"),
        (RowState.NEW_REPLY, "new reply", "new replies"),
        (RowState.IDLE, "idle", "idle"),
    )
    parts = [
        "Grok Bot",
        *(
            f"{n} {one if n == 1 else many}"
            for state, one, many in labels
            if (n := counts.get(state, 0))
        ),
    ]
    label = {
        ConnectionStatus.ASLEEP: f"computer asleep {g.separator} wakes when you act",
        ConnectionStatus.SIGNED_OUT: f"signed out {g.separator} run gbot login",
        ConnectionStatus.OFFLINE: f"offline {g.separator} retrying",
    }.get(status, status.value)
    if status == ConnectionStatus.RECONNECTING and attempt > 0:
        label += f" ({attempt})"
    return f" {g.separator} ".join(parts), f"{g.dot} {label}"


@dataclass(frozen=True)
class RowLine:
    glyph: str
    name: str
    summary: str
    age: str


def _cut(text: str, width: int, ellipsis: str = "") -> str:
    if cell_len(text) <= width:
        return text
    if width <= 0:
        return ""
    marker = ellipsis if cell_len(ellipsis) <= width else ""
    budget = width - cell_len(marker)
    out = ""
    for char in text:
        if cell_len(out + char) > budget:
            break
        out += char
    return out + marker


def layout_row(
    row: Row,
    width: int,
    *,
    frame: int = 0,
    ascii_only: bool = False,
    name_width: int = 16,
) -> RowLine:
    g = glyphs(ascii_only)
    glyph = (
        g.working[frame % len(g.working)] if row.state == RowState.WORKING else g.idle
    )
    age = age_text(row.age_ms) if row.age_ms is not None else ""
    available = max(0, width - 2 - cell_len(glyph) - 1 - 2 - len(age))
    nw = min(max(0, name_width), available)
    name = _cut(row.name, nw, g.ellipsis)
    name += " " * (nw - cell_len(name))
    remaining = available - nw
    summary = (
        _cut(row.summary, max(0, remaining - (1 if age else 0)), g.ellipsis)
        if width >= 30
        else ""
    )
    age = " " * max(0, remaining - cell_len(summary)) + age
    return RowLine(glyph, name, summary, age)


def move(sections: Sequence[Section], current_id: str | None, delta: int) -> str | None:
    ids = [r.bot_id for s in sections if not s.collapsed for r in s.rows]
    if not ids:
        return None
    if current_id not in ids:
        return ids[0] if delta >= 0 else ids[-1]
    return ids[max(0, min(len(ids) - 1, ids.index(current_id) + delta))]


def jump_section(
    sections: Sequence[Section], current_id: str | None, delta: int
) -> str | None:
    visible = [s for s in sections if not s.collapsed and s.rows]
    if not visible:
        return None
    index = next(
        (
            i
            for i, s in enumerate(visible)
            if any(r.bot_id == current_id for r in s.rows)
        ),
        None,
    )
    if index is None:
        return visible[0 if delta >= 0 else -1].rows[0].bot_id
    return visible[max(0, min(len(visible) - 1, index + delta))].rows[0].bot_id
