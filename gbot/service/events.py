"""Typed live events from the gateway's `/events` stream (docs/protocol-tui.md section 1), and the interface of
anything that produces them."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Protocol

from .models import Bot, ConnectionStatus, Entry


@dataclass(frozen=True)
class RosterReplaced:
    """The `agents` channel: a full roster snapshot."""

    bots: tuple[Bot, ...]


@dataclass(frozen=True)
class BotChanged:
    """The `agent-upserted` channel: one complete roster row."""

    bot: Bot


@dataclass(frozen=True)
class BotOverlay:
    """The `agent-activity` channel: live and client overlay fields (roster field names) for one bot."""

    bot_id: str
    fields: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class EntryAdded:
    """A transcript entry was appended."""

    entry: Entry


@dataclass(frozen=True)
class EntryChanged:
    """A newer version of an entry; it replaces the entry with the same (bot, session, id)."""

    entry: Entry


@dataclass(frozen=True)
class EntryRemoved:
    bot_id: str
    session_id: str | None
    entry_id: str


@dataclass(frozen=True)
class TranscriptReset:
    """A transcript `snapshot` (entries given) or `cleared` (no entries) for one bot and session."""

    bot_id: str
    session_id: str | None
    entries: tuple[Entry, ...] = ()


@dataclass(frozen=True)
class BoxChanged:
    """The bot's desktop computer changed state (`forever-box`)."""

    bot_id: str
    state: str


@dataclass(frozen=True)
class RosterResync:
    """`server-roster-changed`: re-read one bot (bot_id set) or the whole roster (bot_id None)."""

    bot_id: str | None = None


@dataclass(frozen=True)
class ConnectionChanged:
    status: ConnectionStatus
    attempt: int = 0
    detail: str = ""


@dataclass(frozen=True)
class Resynced:
    """The stream (re)connected and missed entries were backfilled; consumers should refresh the roster."""


@dataclass(frozen=True)
class Other:
    """A channel this version does not model; passed through so nothing is silently lost."""

    channel: str
    payload: object


Event = (
    RosterReplaced
    | BotChanged
    | BotOverlay
    | EntryAdded
    | EntryChanged
    | EntryRemoved
    | TranscriptReset
    | BoxChanged
    | RosterResync
    | ConnectionChanged
    | Resynced
    | Other
)

Sink = Callable[[Event], None]


class EventSource(Protocol):
    def start(self, sink: Sink) -> None:
        """Begin delivering events to `sink` from a background thread; returns immediately."""
        ...

    def close(self, timeout_s: float = 1.0) -> None:
        """Stop delivering events; must return within `timeout_s` even if the network read is blocked."""
        ...
