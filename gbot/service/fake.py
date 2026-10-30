"""An in-memory Service for tests and `gbot tui --demo`. Deterministic unless `auto_reply` is on."""

import copy
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence

from gbot.pending import classify, is_pending

from .demo import DemoState, demo_state
from .events import (
    BotChanged,
    BoxChanged,
    ConnectionChanged,
    EntryAdded,
    EntryChanged,
    Event,
    Sink,
)
from .models import (
    Action,
    AnswerResult,
    Bot,
    Card,
    ConnectionStatus,
    Entry,
    SendResult,
    TranscriptPage,
)
from .transport import FakeTransport

_DRAFTS = {"email-draft", "slack-draft", "meeting-chat-draft"}
_STATUS = {"auto-review-approval": "approval", "local-tool-permission": "ask"}


class FakeEventSource:
    """Delivers pushed events synchronously to the sink once started."""

    def __init__(self) -> None:
        self._sink: Sink | None = None
        self._lock = threading.Lock()
        self.closed = False

    def start(self, sink: Sink) -> None:
        with self._lock:
            self._sink = sink
        self.push(ConnectionChanged(ConnectionStatus.LIVE))

    def push(self, event: Event) -> None:
        with self._lock:
            sink = None if self.closed else self._sink
        if sink is not None:
            sink(event)

    def close(self, timeout_s: float = 1.0) -> None:
        with self._lock:
            self.closed = True
            self._sink = None


class FakeService:
    """Implements `gbot.service.api.Service` over `DemoState`.

    `send` appends the user entry and marks the bot busy; the reply arrives when a test calls `reply()`, or after
    `reply_delay_s` when `auto_reply` is on (demo mode). Answers mark the card resolved and emit EntryChanged.
    """

    def __init__(
        self,
        state: DemoState | None = None,
        *,
        now_ms: Callable[[], int] | None = None,
        auto_reply: bool = False,
        reply_delay_s: float = 1.5,
        transport: FakeTransport | None = None,
    ) -> None:
        self._now = now_ms or (lambda: int(time.time() * 1000))
        self.state = state or demo_state(self._now())
        self.auto_reply = auto_reply
        self.reply_delay_s = reply_delay_s
        self.transport = transport or FakeTransport()
        self._lock = threading.RLock()
        self._sources: list[FakeEventSource] = []
        self._timers: list[threading.Timer] = []
        self.sent: list[tuple[str, str, str | None]] = []
        self.answered: list[tuple[str, str, Action]] = []

    # Reading -----------------------------------------------------------------------------------------------

    def _row(self, bot_id: str) -> dict[str, object]:
        for row in self.state.rows:
            if row["id"] == bot_id:
                return row
        raise ValueError(f"Unknown bot: {bot_id}")

    def roster(self) -> list[Bot]:
        with self._lock:
            return [
                bot
                for row in self.state.rows
                if (bot := Bot.from_row(copy.deepcopy(row)))
            ]

    def _page(self, bot_id: str, before_seq: int | None, limit: int) -> TranscriptPage:
        with self._lock:
            self._row(bot_id)
            raw = [
                entry
                for entry in self.state.transcripts.get(bot_id, [])
                if before_seq is None or int(str(entry["seq"])) < before_seq
            ]
            chosen = raw[-limit:] if limit > 0 else []
            entries = tuple(
                e
                for item in chosen
                if (e := Entry.from_raw(bot_id, copy.deepcopy(item)))
            )
            more = len(raw) > len(chosen) and entries
            return TranscriptPage(entries, entries[0].seq if more else None)

    def open(
        self, bot_id: str, *, session_id: str | None = None, limit: int = 200
    ) -> TranscriptPage:
        with self._lock:
            row = self._row(bot_id)
            row["hasUnread"] = False
            row["unreadCount"] = 0
            row["lastViewedAt"] = self._now()
        return self._page(bot_id, None, limit)

    def transcript(
        self,
        bot_id: str,
        *,
        before_seq: int | None = None,
        limit: int = 50,
        session_id: str | None = None,
    ) -> TranscriptPage:
        return self._page(bot_id, before_seq, limit)

    def pending(
        self, bot_ids: Sequence[str] | None = None
    ) -> tuple[list[Card], list[str]]:
        with self._lock:
            cards: list[Card] = []
            for row in self.state.rows:
                bot_id, name = str(row["id"]), str(row["name"])
                if bot_ids is not None and bot_id not in bot_ids:
                    continue
                for entry in self.state.transcripts.get(bot_id, []):
                    card = classify(copy.deepcopy(entry), bot_id, name)
                    if card is not None:
                        cards.append(card)
            return cards, []

    def _entry(self, card: Card) -> dict[str, object]:
        for entry in self.state.transcripts.get(card.bot_id, []):
            if entry["id"] == card.entry_id:
                return entry
        raise ValueError(f"Unknown card: {card.entry_id}")

    def still_pending(self, card: Card) -> bool:
        with self._lock:
            return is_pending(self._entry(card))

    def box_state(self, bot_id: str) -> str | None:
        with self._lock:
            return self.state.boxes.get(bot_id, "absent")

    # Changing ----------------------------------------------------------------------------------------------

    def _emit(self, event: Event) -> None:
        for source in list(self._sources):
            source.push(event)

    def _next_seq(self, bot_id: str) -> int:
        entries = self.state.transcripts.setdefault(bot_id, [])
        return max((int(str(e["seq"])) for e in entries), default=0) + 1

    def _set_row(self, bot_id: str, **fields: object) -> None:
        row = self._row(bot_id)
        row.update(fields)
        bot = Bot.from_row(copy.deepcopy(row))
        if bot is not None:
            self._emit(BotChanged(bot))

    def send(
        self,
        bot_id: str,
        text: str,
        *,
        session_id: str | None = None,
        nonce: str | None = None,
    ) -> SendResult:
        if not text.strip():
            raise ValueError("Prompt must not be empty.")
        nonce = nonce or str(uuid.uuid4())
        with self._lock:
            self._row(bot_id)
            last = self._next_seq(bot_id) - 1
            turn = 1 + sum(
                1 for e in self.state.transcripts[bot_id] if e.get("kind") == "message"
            )
            raw: dict[str, object] = {
                "id": f"t{turn}u",
                "seq": last + 1,
                "kind": "message",
                "role": "user",
                "content": text,
                "isStreaming": False,
                "clientNonce": nonce,
                "timestampMs": self._now(),
            }
            self.state.transcripts[bot_id].append(raw)
            self.sent.append((bot_id, text, session_id))
            entry = Entry.from_raw(bot_id, copy.deepcopy(raw))
            if entry is not None:
                self._emit(EntryAdded(entry))
            self._set_row(
                bot_id,
                isRunning=True,
                isRunningTurn=True,
                currentActivity={"kind": "thinking"},
                lastMessagePreview=text,
                lastActivityAt=self._now(),
            )
        if self.auto_reply:
            timer = threading.Timer(
                self.reply_delay_s, self.reply, (bot_id, f"Done: {text[:60]}")
            )
            timer.daemon = True
            self._timers.append(timer)
            timer.start()
        return SendResult(True, nonce, last or None)

    def reply(self, bot_id: str, text: str) -> None:
        """Finish the bot's turn with a text reply."""
        with self._lock:
            entries = self.state.transcripts.setdefault(bot_id, [])
            turn = sum(1 for e in entries if e.get("kind") == "message")
            steps = sum(
                1 for e in entries if str(e.get("id", "")).startswith(f"t{turn}s")
            )
            raw: dict[str, object] = {
                "id": f"t{turn}s{steps}",
                "seq": self._next_seq(bot_id),
                "kind": "send-message",
                "timestampMs": self._now(),
                "message": {"type": "text", "content": text},
            }
            entries.append(raw)
            entry = Entry.from_raw(bot_id, copy.deepcopy(raw))
            if entry is not None:
                self._emit(EntryAdded(entry))
            self._set_row(
                bot_id,
                isRunning=False,
                isRunningTurn=False,
                currentActivity=None,
                hasUnread=True,
                unreadCount=int(str(self._row(bot_id).get("unreadCount") or 0)) + 1,
                lastMessagePreview=text,
                lastActivityAt=self._now(),
            )

    def set_box(self, bot_id: str, state: str) -> None:
        with self._lock:
            self.state.boxes[bot_id] = state
        self._emit(BoxChanged(bot_id, state))

    def answer(self, card: Card, action: Action) -> AnswerResult:
        from . import cards

        rpc, _ = cards.plan(card, action)
        with self._lock:
            entry = self._entry(card)
            if not is_pending(entry):
                raise ValueError("This card was already answered.")
            message = entry["message"]
            assert isinstance(message, dict)
            kind = card.type
            if kind in _DRAFTS:
                sent = action.kind == "approve"
                entry["draftSendState"] = "sent" if sent else "discarded"
                result = AnswerResult(
                    rpc,
                    "sent" if sent else "discarded",
                )
            elif kind in _STATUS:
                approved = action.kind == "approve"
                body = message[_STATUS[kind]]
                assert isinstance(body, dict)
                body["status"] = "approved" if approved else "denied"
                result = AnswerResult(rpc, "approved" if approved else "denied")
            elif kind == "widget":
                if action.kind == "dismiss":
                    entry["widgetDismissed"] = True
                    result = AnswerResult(rpc, "dismissed")
                else:
                    entry["respondedValue"] = action.value
                    result = AnswerResult(rpc, f"answered {action.value}")
            elif kind == "user-form":
                if action.kind == "dismiss":
                    entry["formResolution"] = {"kind": "dismissed"}
                    result = AnswerResult(rpc, "dismissed")
                else:
                    entry["formResolution"] = {
                        "kind": "submitted",
                        "values": dict(action.fields),
                    }
                    result = AnswerResult(rpc, "submitted")
            elif kind == "secret-request":
                entry["secretProvided"] = True
                result = AnswerResult(rpc, "secret stored")
            else:
                raise ValueError(f"{kind} cards are answered in the Grok Bot app.")
            self.answered.append((card.bot_id, card.entry_id, action))
            changed = Entry.from_raw(card.bot_id, copy.deepcopy(entry))
            if changed is not None:
                self._emit(EntryChanged(changed))
            still = any(
                is_pending(e) for e in self.state.transcripts.get(card.bot_id, [])
            )
            if not still:
                self._set_row(card.bot_id, awaitingUserResponse=None)
            return result

    def event_source(self) -> FakeEventSource:
        source = FakeEventSource()
        self._sources.append(source)
        return source

    def close(self) -> None:
        for timer in self._timers:
            timer.cancel()
        for source in self._sources:
            source.close()


def load_fake(overrides: Mapping[str, object] | None = None) -> FakeService:
    """A FakeService over the demo data with a fixed clock (for tests); `overrides` patch FakeService attributes."""
    service = FakeService(now_ms=lambda: 1_800_000_000_000)
    for name, value in (overrides or {}).items():
        setattr(service, name, value)
    return service
