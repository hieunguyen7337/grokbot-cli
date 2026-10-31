"""Typed views of gateway data. Parsing is tolerant: unknown fields are ignored, missing ones get defaults."""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from gbot.pending import PendingItem

Card = PendingItem


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _strings(value: object) -> tuple[str, ...]:
    return (
        tuple(item for item in value if isinstance(item, str))
        if isinstance(value, list)
        else ()
    )


def _record(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


@dataclass(frozen=True)
class Awaiting:
    """The roster's `awaitingUserResponse`: the bot is blocked on the user."""

    reason: str
    since_ms: int | None = None
    tab_id: str | None = None


@dataclass(frozen=True)
class Bot:
    """One roster row from `listAgents` or the `agent-upserted` channel."""

    id: str
    name: str
    description: str = ""
    title: str = ""
    avatar_color: str | None = None
    running: bool = False
    running_turn: bool | None = None
    composing: bool = False
    retrying: bool = False
    awaiting: Awaiting | None = None
    awaiting_session_ids: tuple[str, ...] = ()
    has_unread: bool = False
    unread_count: int = 0
    last_viewed_at: int | None = None
    last_activity_at: int | None = None
    preview: str = ""
    last_outcome: str | None = None
    is_group: bool = False
    is_shared_room: bool = False
    member_ids: tuple[str, ...] = ()
    hidden: bool = False
    notifications: bool = True
    activity: str = ""
    running_session_ids: tuple[str, ...] = ()
    unread_thread_count: int = 0
    raw: Mapping[str, object] = field(default_factory=dict, compare=False, repr=False)

    @property
    def busy(self) -> bool:
        """The app's rule: working means running or composing and not blocked on the user."""
        return self.awaiting is None and (self.running or self.composing)

    @property
    def unread(self) -> bool:
        return self.has_unread or self.unread_count > 0 or self.unread_thread_count > 0

    def with_overlay(self, fields: Mapping[str, object]) -> "Bot":
        """Apply an `agent-activity` live/client overlay (roster field names) to this row."""
        return Bot.from_row({**self.raw, **fields}) or self

    @classmethod
    def from_row(cls, row: object) -> "Bot | None":
        data = _record(row)
        bot_id, name = data.get("id"), data.get("name")
        if (
            not isinstance(bot_id, str)
            or not bot_id
            or not isinstance(name, str)
            or not name
        ):
            return None
        awaiting_raw = data.get("awaitingUserResponse")
        awaiting = None
        if isinstance(awaiting_raw, Mapping):
            tab = awaiting_raw.get("tabId")
            awaiting = Awaiting(
                _text(awaiting_raw.get("reason")) or "awaiting",
                _int(awaiting_raw.get("since")),
                tab if isinstance(tab, str) else None,
            )
        last_entry = _record(data.get("lastEntry"))
        preview = _text(data.get("lastMessagePreview")) or _text(last_entry.get("text"))
        settlement = _record(data.get("lastTurnSettlement"))
        running_turn = data.get("isRunningTurn")
        color = data.get("avatarColor")
        current = _record(data.get("currentActivity"))
        activity = " ".join(
            part
            for part in (
                _text(current.get("tool")) or _text(current.get("kind")),
                _text(current.get("detail")) or _text(current.get("target")),
            )
            if part
        )
        return cls(
            id=bot_id,
            name=name,
            description=_text(data.get("description")),
            title=_text(data.get("title")),
            avatar_color=color if isinstance(color, str) else None,
            running=data.get("isRunning") is True,
            running_turn=running_turn if isinstance(running_turn, bool) else None,
            composing=data.get("isComposingMessage") is True,
            retrying=data.get("isRetrying") is True,
            awaiting=awaiting,
            awaiting_session_ids=_strings(data.get("awaitingSessionIds")),
            has_unread=data.get("hasUnread") is True,
            unread_count=_int(data.get("unreadCount")) or 0,
            last_viewed_at=_int(data.get("lastViewedAt")),
            last_activity_at=_int(data.get("lastActivityAt"))
            or _int(data.get("localActivityAt")),
            preview=preview,
            last_outcome=_text(settlement.get("outcome")) or None,
            is_group=data.get("isGroup") is True,
            is_shared_room=data.get("isSharedRoom") is True,
            member_ids=_strings(data.get("memberIds")),
            hidden=data.get("isHiddenFromSidebar") is True
            or data.get("isRemovedFromSidebar") is True,
            notifications=data.get("notificationsEnabled") is not False,
            activity=activity,
            running_session_ids=_strings(data.get("runningSessionIds")),
            unread_thread_count=_int(data.get("unreadThreadCount")) or 0,
            raw=dict(data),
        )


_TURN = re.compile(r"t(\d+)")


@dataclass(frozen=True)
class Entry:
    """One transcript entry (docs/protocol-tui.md section 2).

    Kinds: `message` (role user or assistant), `send-message` (bot text or a card in `message`), `tool-call`,
    `notice`, `event`, `mcp-app`, `feedback`, `user-attachment`, `voice-call`. `seq` is only unique within one
    bot and session, so identity is (bot_id, session_id, id).
    """

    bot_id: str
    id: str
    seq: int
    kind: str
    timestamp_ms: int | None = None
    session_id: str | None = None
    role: str = ""
    text: str = ""
    card_type: str | None = None
    streaming: bool = False
    raw: Mapping[str, object] = field(default_factory=dict, compare=False, repr=False)

    @property
    def is_user(self) -> bool:
        return self.kind == "message" and self.role != "assistant"

    @property
    def key(self) -> tuple[str, str | None, str]:
        return (self.bot_id, self.session_id, self.id)

    @property
    def turn(self) -> int | None:
        match = _TURN.match(self.id)
        return int(match.group(1)) if match else None

    @classmethod
    def from_raw(
        cls, bot_id: str, raw: object, session_id: str | None = None
    ) -> "Entry | None":
        data = _record(raw)
        entry_id, seq = data.get("id"), _int(data.get("seq"))
        if not isinstance(entry_id, str) or seq is None:
            return None
        kind = _text(data.get("kind"))
        message = _record(data.get("message"))
        message_type = _text(message.get("type"))
        if kind == "tool-call":
            text = _text(data.get("summary")) or _text(data.get("name"))
        elif kind == "notice":
            text = _text(data.get("text"))
        else:
            text = _text(data.get("content")) or _text(message.get("content"))
        session = data.get("sessionId")
        return cls(
            bot_id=bot_id,
            id=entry_id,
            seq=seq,
            kind=kind,
            timestamp_ms=_int(data.get("timestampMs")),
            session_id=session_id
            or (session if isinstance(session, str) and session else None),
            role=_text(data.get("role")),
            text=text,
            card_type=message_type if message_type and message_type != "text" else None,
            streaming=data.get("isStreaming") is True or data.get("streaming") is True,
            raw=dict(data),
        )


@dataclass(frozen=True)
class TranscriptPage:
    entries: tuple[Entry, ...]
    next_before_seq: int | None = None


@dataclass(frozen=True)
class SendResult:
    accepted: bool
    nonce: str
    last_seq: int | None = None


ActionKind = Literal["approve", "deny", "respond", "dismiss", "secret"]


@dataclass(frozen=True)
class Action:
    """What the user chose for a card. `secret` never appears in repr; `draft` carries an edited draft to send."""

    kind: ActionKind
    always: bool = False
    never: bool = False
    value: str | None = None
    fields: tuple[tuple[str, str], ...] = ()
    secret: str | None = field(default=None, repr=False)
    draft: Mapping[str, object] | None = None
    all_bots: bool = False


@dataclass(frozen=True)
class AnswerResult:
    rpc: str
    effect: str


class ConnectionStatus(Enum):
    CONNECTING = "connecting"
    LIVE = "live"
    RECONNECTING = "reconnecting"
    ASLEEP = "asleep"
    SIGNED_OUT = "signed out"
    OFFLINE = "offline"
