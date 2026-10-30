"""The core service the terminal UI (and, over time, the CLI) talks to. Area features live in their own modules
built on `Transport` (for example `gbot.service.automations.Automations(service.transport)`)."""

from collections.abc import Mapping, Sequence
from typing import Protocol

from .events import EventSource
from .models import Action, AnswerResult, Bot, Card, SendResult, TranscriptPage
from .transport import Transport


class FrameFeed(Protocol):
    """One open `GET /events` stream (all channels)."""

    def next_frame(self, timeout_s: float) -> Mapping[str, object] | None:
        """The next `data:` frame decoded from JSON (bare /events sends `{channel, payload}`), or None for a comment
        line (`:ping` every 15 s, `:echo`). Raises TimeoutError when nothing arrives within `timeout_s`, EOFError when
        the server ends the stream, and ConnectError or httpx errors when the read fails."""
        ...

    def close(self) -> None:
        """Close the stream; must make a `next_frame` blocked in another thread return or raise promptly."""
        ...


class StreamOpener(Protocol):
    def open_stream(self) -> FrameFeed:
        """Open the event stream with the current gateway credentials.

        Re-mints and retries once on 401/403. Raises `errors.AsleepError` on 417 without waking the pod,
        `errors.SignedOutError` when there is no usable login, and ConnectError or httpx errors otherwise. A read
        timeout or the end of a stream is never a reason to re-mint: the caller simply opens a new stream.
        """
        ...


class Service(Protocol):
    transport: Transport

    def roster(self) -> list[Bot]:
        """Every bot and group row, in gateway order."""
        ...

    def open(
        self, bot_id: str, *, session_id: str | None = None, limit: int = 200
    ) -> TranscriptPage:
        """Open a chat the way the app does (`openAgentTail`; the server may mark it read), oldest first."""
        ...

    def transcript(
        self,
        bot_id: str,
        *,
        before_seq: int | None = None,
        limit: int = 50,
        session_id: str | None = None,
    ) -> TranscriptPage:
        """Read without side effects: the newest `limit` entries older than `before_seq`, oldest first."""
        ...

    def send(
        self,
        bot_id: str,
        text: str,
        *,
        session_id: str | None = None,
        nonce: str | None = None,
    ) -> SendResult:
        """Send a prompt. Reuse `nonce` when retrying the same submission so the gateway can de-duplicate it."""
        ...

    def pending(
        self, bot_ids: Sequence[str] | None = None
    ) -> tuple[list[Card], list[str]]:
        """Cards waiting on the user (all bots when `bot_ids` is None) and per-bot warnings, never printed."""
        ...

    def still_pending(self, card: Card) -> bool:
        """Re-read the card's entry right before answering; False if it was answered elsewhere."""
        ...

    def answer(self, card: Card, action: Action) -> AnswerResult:
        """Send the answer through the backend RPC the app uses; raises ValueError on a refusal."""
        ...

    def box_state(self, bot_id: str) -> str | None:
        """The desktop computer state: absent, hibernated, running, or None when unknown."""
        ...

    def event_source(self) -> EventSource:
        """A new live event source; the caller starts and closes it."""
        ...

    def close(self) -> None: ...
