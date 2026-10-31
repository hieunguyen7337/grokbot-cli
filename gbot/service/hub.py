"""One background event subscription with read-only recovery and bounded shutdown."""

import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping

import httpx

from .api import FrameFeed, StreamOpener
from .errors import AsleepError, SignedOutError
from .events import (
    ConnectionChanged,
    EntryAdded,
    EntryChanged,
    EntryRemoved,
    Event,
    Resynced,
    Sink,
    TranscriptReset,
)
from .frames import parse_frame
from .models import ConnectionStatus, Entry
from .transport import Transport


class EventHub:
    """Deliver ordered events on a single daemon thread. An instance starts only once.

    The optional sleep hook replaces the interruptible retry wait for deterministic tests.
    """

    def __init__(
        self,
        opener: StreamOpener,
        transport: Transport,
        *,
        stall_s: float = 35.0,
        backoff_start_s: float = 1.0,
        backoff_cap_s: float = 10.0,
        asleep_retry_s: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], object] | None = None,
    ) -> None:
        self._opener, self._transport = opener, transport
        self._stall = stall_s
        self._backoff_start, self._backoff_cap = backoff_start_s, backoff_cap_s
        self._asleep_retry = asleep_retry_s
        self._clock, self._sleep = clock, sleep
        self._stop, self._wake = threading.Event(), threading.Event()
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._feed: FrameFeed | None = None
        self._sink: Sink | None = None
        self._followed: dict[tuple[str, str | None], None] = {}
        self._seen: dict[tuple[str, str | None], OrderedDict[str, None]] = {}

    def start(self, sink: Sink) -> None:
        with self._lock:
            if self._thread is not None or self._stop.is_set():
                return
            self._sink = sink
            self._thread = threading.Thread(
                target=self._run, name="gbot-event-hub", daemon=True
            )
            self._thread.start()

    def follow(self, bot_id: str, session_id: str | None = None) -> None:
        with self._lock:
            self._followed[bot_id, session_id] = None

    def unfollow(self, bot_id: str, session_id: str | None = None) -> None:
        with self._lock:
            self._followed.pop((bot_id, session_id), None)

    def nudge(self) -> None:
        self._wake.set()

    def close(self, timeout_s: float = 1.0) -> None:
        deadline = time.monotonic() + max(0.0, timeout_s)
        self._stop.set()
        self._wake.set()
        # FrameFeed.close is contractually nonblocking and unblocks next_frame.
        feed = self._feed
        if feed is not None:
            self._close_feed(feed)
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(max(0.0, deadline - time.monotonic()))

    @staticmethod
    def _close_feed(feed: FrameFeed) -> None:
        try:
            feed.close()
        except Exception:  # noqa: BLE001, S110 - cleanup must not prevent shutdown
            pass

    def _emit(self, event: Event) -> None:
        if self._stop.is_set():
            return
        if isinstance(event, (EntryAdded, EntryChanged)):
            entry = event.entry
            seen = self._seen.setdefault(entry.key[:2], OrderedDict())
            if isinstance(event, EntryAdded) and entry.id in seen:
                return
            seen[entry.id] = None
            seen.move_to_end(entry.id)
            while len(seen) > 2000:
                seen.popitem(last=False)
        elif isinstance(event, EntryRemoved):
            self._seen.get((event.bot_id, event.session_id), {}).pop(
                event.entry_id, None
            )
        elif isinstance(event, TranscriptReset):
            self._seen[event.bot_id, event.session_id] = OrderedDict(
                (entry.id, None) for entry in event.entries[-2000:]
            )
        try:
            if not self._stop.is_set() and self._sink is not None:
                self._sink(event)
        except Exception:  # noqa: BLE001, S110 - a consumer must not stop the stream
            pass

    def _wait(self, delay: float | None) -> None:
        if self._stop.is_set():
            return
        if self._sleep is not None and delay is not None and not self._wake.is_set():
            self._sleep(delay)
        else:
            deadline = None if delay is None else self._clock() + delay
            while not self._stop.is_set():
                remaining = (
                    None if deadline is None else max(0.0, deadline - self._clock())
                )
                if (
                    self._wake.wait(remaining)
                    or deadline is not None
                    and self._clock() >= deadline
                ):
                    break
        self._wake.clear()

    def _seed(self) -> None:
        if self._stop.is_set():
            return
        rows = self._transport.command("listAgents")
        if isinstance(rows, Mapping):
            rows = rows.get("agents")
        for event in parse_frame({"channel": "agents", "payload": {"agents": rows}}):
            self._emit(event)
        with self._lock:
            followed = tuple(self._followed)
        for bot, session in followed:
            if self._stop.is_set():
                return
            args: dict[str, object] = {"id": bot, "limit": 50, "background": True}
            if session is not None:
                args["sessionId"] = session
            page = self._transport.command("getAgentTranscriptTail", args)
            rows = page.get("entries") if isinstance(page, Mapping) else None
            if isinstance(rows, list):
                for raw in rows:
                    entry = Entry.from_raw(bot, raw, session)
                    if entry is not None:
                        self._emit(EntryAdded(entry))
        self._emit(Resynced())

    def _run(self) -> None:
        attempt, network_failures = 0, 0
        backoff = self._backoff_start
        connected_once = False
        while not self._stop.is_set():
            attempt += 1
            status = (
                ConnectionStatus.RECONNECTING
                if connected_once or attempt > 1
                else ConnectionStatus.CONNECTING
            )
            if network_failures >= 3:
                status = ConnectionStatus.OFFLINE
            self._emit(ConnectionChanged(status, attempt))
            feed = None
            delay: float | None = 0.0
            try:
                feed = self._opener.open_stream()
                with self._lock:
                    self._feed = feed
                if self._stop.is_set():
                    break
                connected_once = True
                self._emit(ConnectionChanged(ConnectionStatus.LIVE))
                self._seed()
                attempt, network_failures = 0, 0
                received = False
                while not self._stop.is_set():
                    try:
                        frame = feed.next_frame(self._stall)
                    except (TimeoutError, EOFError):
                        # A stream that delivered something reconnects at once; one that ended empty is
                        # flapping and backs off, so a failing gateway is not re-read in a tight loop.
                        if not received:
                            delay = backoff
                            backoff = min(self._backoff_cap, backoff * 2)
                        break
                    if not received:
                        received = True
                        backoff = self._backoff_start
                    if frame is not None:
                        for event in parse_frame(frame):
                            self._emit(event)
            except AsleepError as exc:
                self._emit(
                    ConnectionChanged(ConnectionStatus.ASLEEP, attempt, str(exc)[:160])
                )
                delay = self._asleep_retry
            except SignedOutError as exc:
                self._emit(
                    ConnectionChanged(
                        ConnectionStatus.SIGNED_OUT, attempt, str(exc)[:160]
                    )
                )
                delay = None
            except Exception as exc:  # noqa: BLE001 - worker boundary reports failures
                network_failures = (
                    network_failures + 1 if isinstance(exc, httpx.TransportError) else 0
                )
                offline = network_failures >= 3
                status = (
                    ConnectionStatus.OFFLINE
                    if offline
                    else ConnectionStatus.RECONNECTING
                )
                self._emit(ConnectionChanged(status, max(1, attempt), str(exc)[:160]))
                delay = self._backoff_cap if offline else backoff
                backoff = min(self._backoff_cap, backoff * 2)
            finally:
                if feed is not None:
                    self._close_feed(feed)
                with self._lock:
                    self._feed = None
            if delay != 0.0:
                self._wait(delay)
