"""Scripted streams only: ordering, recovery and shutdown contracts."""

import queue
import threading
import time
from collections import deque

import httpx
import pytest

from gbot.service.errors import AsleepError, SignedOutError
from gbot.service.events import (
    ConnectionChanged,
    EntryAdded,
    EntryChanged,
    Other,
    Resynced,
    RosterReplaced,
)
from gbot.service.hub import EventHub
from gbot.service.models import ConnectionStatus
from gbot.service.transport import FakeTransport
from groken.client import ConnectError


def transcript(kind="appended", entry_id="e", session=None):
    key = "transcript:b" + ("\0" + session if session else "")
    return {
        "channel": "transcript",
        "payload": {
            "type": kind,
            "ordered": {"replicaKey": key},
            "entry": {"id": entry_id, "seq": 1, "kind": "message"},
            "id": entry_id,
            "entries": [{"id": entry_id, "seq": 1}],
        },
    }


class Feed:
    def __init__(self, *frames):
        self.frames = deque(frames)
        self.closed = threading.Event()
        self.reading = threading.Event()

    def next_frame(self, timeout_s):
        self.reading.set()
        if self.frames:
            item = self.frames.popleft()
            if isinstance(item, Exception):
                raise item
            return item
        self.closed.wait()
        raise EOFError

    def close(self):
        self.closed.set()


class Opener:
    def __init__(self, *steps):
        self.steps = deque(steps)
        self.calls = 0
        self.opened = threading.Event()

    def open_stream(self):
        self.calls += 1
        self.opened.set()
        item = self.steps.popleft() if self.steps else Feed()
        if isinstance(item, Exception):
            raise item
        return item


class Sink:
    def __init__(self):
        self.queue = queue.Queue()
        self.events = []
        self.threads = []

    def __call__(self, event):
        self.events.append(event)
        self.threads.append(threading.current_thread())
        self.queue.put(event)

    def until(self, predicate):
        deadline = time.monotonic() + 2
        while True:
            event = self.queue.get(timeout=max(0.001, deadline - time.monotonic()))
            if predicate(event):
                return event

    def status(self, status):
        return self.until(
            lambda e: isinstance(e, ConnectionChanged) and e.status == status
        )


def transport(entries=()):
    return FakeTransport(
        {
            "listAgents": [{"id": "b", "name": "Bot"}],
            "getAgentTranscriptTail": {"entries": list(entries)},
        }
    )


def test_connect_order_dedup_updates_and_thread():
    feed = Feed(
        transcript(), transcript("updated"), {"channel": "marker", "payload": None}
    )
    opener, sink, wire = Opener(feed), Sink(), transport([{"id": "e", "seq": 1}])
    hub = EventHub(opener, wire)
    hub.follow("b", "s")
    hub.unfollow("b", "s")
    hub.follow("b")
    hub.start(sink)
    try:
        sink.until(lambda e: isinstance(e, Other))
        assert [type(e) for e in sink.events] == [
            ConnectionChanged,
            ConnectionChanged,
            RosterReplaced,
            EntryAdded,
            Resynced,
            EntryChanged,
            Other,
        ]
        assert sink.events[0].status == ConnectionStatus.CONNECTING
        assert sink.events[1].status == ConnectionStatus.LIVE
        assert wire.calls == [
            ("command", "listAgents", {}),
            (
                "command",
                "getAgentTranscriptTail",
                {"id": "b", "limit": 50, "background": True},
            ),
        ]
        assert all(t.name == "gbot-event-hub" and t.daemon for t in sink.threads)
    finally:
        hub.close()


@pytest.mark.parametrize("failure", [TimeoutError(), EOFError()])
def test_quiet_reconnect_no_backoff_and_reconnect_dedup(failure):
    first, second = (
        Feed(None, transcript(), failure),
        Feed(transcript(), {"channel": "done", "payload": None}),
    )
    opener, sink, waits = Opener(first, second), Sink(), []
    hub = EventHub(opener, transport(), sleep=waits.append)
    hub.follow("b")
    hub.start(sink)
    try:
        sink.until(lambda e: isinstance(e, Other))
        assert opener.calls == 2 and first.closed.is_set()
        assert waits == []
        assert sum(isinstance(e, EntryAdded) for e in sink.events) == 1
        assert sum(isinstance(e, Resynced) for e in sink.events) == 2
    finally:
        hub.close()


def test_backoff_capped_and_reset_after_success():
    error = ConnectError(503, "unavailable")
    waits, sink = [], Sink()
    opener = Opener(*([error] * 6), Feed(None, EOFError()), error, Feed())
    hub = EventHub(opener, transport(), sleep=waits.append)
    hub.start(sink)
    try:
        sink.until(lambda e: isinstance(e, Resynced) and opener.calls == 9)
        assert waits == [1, 2, 4, 8, 10, 10, 1]
        failures = [
            e for e in sink.events if isinstance(e, ConnectionChanged) and e.detail
        ]
        assert failures[0].attempt == 1 and failures[5].attempt == 6
    finally:
        hub.close()


def test_streams_that_end_empty_back_off():
    waits, sink = [], Sink()
    opener = Opener(Feed(EOFError()), Feed(EOFError()), Feed(EOFError()), Feed())
    hub = EventHub(opener, transport(), sleep=waits.append)
    hub.start(sink)
    try:
        sink.until(lambda e: isinstance(e, Resynced) and opener.calls == 4)
        assert waits == [1, 2, 4]
    finally:
        hub.close()


def test_roster_seed_accepts_wrapped_rows_and_removal_forgets_one_key():
    feed = Feed(
        transcript(entry_id="a"),
        transcript(entry_id="b"),
        transcript("removed", entry_id="a"),
        transcript(entry_id="a"),
        transcript(entry_id="b"),
        {"channel": "done", "payload": None},
    )
    sink = Sink()
    wire = FakeTransport(
        {
            "listAgents": {"agents": [{"id": "b", "name": "Bot"}]},
            "getAgentTranscriptTail": {"entries": []},
        }
    )
    hub = EventHub(Opener(feed), wire)
    hub.start(sink)
    try:
        sink.until(lambda e: isinstance(e, Other))
        roster = next(e for e in sink.events if isinstance(e, RosterReplaced))
        assert [bot.id for bot in roster.bots] == ["b"]
        assert [e.entry.id for e in sink.events if isinstance(e, EntryAdded)] == [
            "a",
            "b",
            "a",
        ]
    finally:
        hub.close()


@pytest.mark.parametrize(
    "error,status",
    [
        (AsleepError(), ConnectionStatus.ASLEEP),
        (SignedOutError(), ConnectionStatus.SIGNED_OUT),
    ],
)
def test_sleep_and_signout_wait_for_nudge(error, status):
    opener, sink = Opener(error, Feed()), Sink()
    hub = EventHub(opener, transport(), asleep_retry_s=60)
    hub.start(sink)
    try:
        sink.status(status)
        assert opener.calls == 1
        hub.nudge()
        sink.until(lambda e: isinstance(e, Resynced))
        assert opener.calls == 2
    finally:
        hub.close()


def test_asleep_retry_interval():
    waits, sink = [], Sink()
    hub = EventHub(
        Opener(AsleepError(), Feed()),
        transport(),
        asleep_retry_s=30,
        sleep=waits.append,
    )
    hub.start(sink)
    try:
        sink.until(lambda e: isinstance(e, Resynced))
        assert waits == [30]
    finally:
        hub.close()


def test_three_transport_failures_report_offline_at_cap():
    waits, sink = [], Sink()
    hub = EventHub(
        Opener(*[httpx.ConnectError("offline") for _ in range(4)], Feed()),
        transport(),
        sleep=waits.append,
    )
    hub.start(sink)
    try:
        sink.until(lambda e: isinstance(e, Resynced))
        assert waits == [1, 2, 10, 10]
        statuses = [e.status for e in sink.events if isinstance(e, ConnectionChanged)]
        offline_at = statuses.index(ConnectionStatus.OFFLINE)
        assert statuses[offline_at:-1] == [ConnectionStatus.OFFLINE] * 4
    finally:
        hub.close()


@pytest.mark.parametrize("blocked", ["read", "backoff", "signed-out"])
def test_bounded_close_and_no_late_delivery(blocked):
    feed, sink = Feed(), Sink()
    step = (
        feed
        if blocked == "read"
        else SignedOutError()
        if blocked == "signed-out"
        else ConnectError(503, "retry")
    )
    hub = EventHub(Opener(step), transport(), backoff_start_s=60)
    hub.start(sink)
    if blocked == "read":
        assert feed.reading.wait(1)
    else:
        sink.until(lambda e: isinstance(e, ConnectionChanged) and bool(e.detail))
    started = time.monotonic()
    hub.close(0.2)
    hub.close(0.2)
    assert time.monotonic() - started < 1
    count = len(sink.events)
    hub.nudge()
    assert hub._thread is not None and not hub._thread.is_alive()
    assert len(sink.events) == count


def test_close_before_start_and_raising_sink():
    opener = Opener(Feed())
    hub = EventHub(opener, transport())
    hub.close()
    hub.start(Sink())
    assert opener.calls == 0
    done = threading.Event()

    def sink(event):
        if isinstance(event, Resynced):
            done.set()
        else:
            raise TypeError("consumer failure")

    hub = EventHub(Opener(Feed()), transport())
    hub.start(sink)
    try:
        assert done.wait(1)
    finally:
        hub.close()


def test_resets_removals_and_session_scoped_dedup():
    feed, sink = (
        Feed(
            transcript(),
            transcript(session="s"),
            transcript("removed"),
            transcript(),
            transcript("snapshot"),
            transcript(),
            transcript("cleared"),
            transcript(),
            {"channel": "done", "payload": None},
        ),
        Sink(),
    )
    hub = EventHub(Opener(feed), transport())
    hub.start(sink)
    try:
        sink.until(lambda e: isinstance(e, Other))
        assert [
            e.entry.session_id for e in sink.events if isinstance(e, EntryAdded)
        ] == [None, "s", None, None]
    finally:
        hub.close()


def test_seen_keys_are_bounded_and_session_tail_arguments():
    frames = [transcript(entry_id=str(i)) for i in range(2001)]
    frames.extend([transcript(entry_id="0"), {"channel": "done", "payload": None}])
    wire, sink = transport(), Sink()
    hub = EventHub(Opener(Feed(*frames)), wire)
    hub.follow("b", "s")
    hub.start(sink)
    try:
        sink.until(lambda e: isinstance(e, Other))
        assert wire.calls[1][2]["sessionId"] == "s"
        assert len(hub._seen["b", None]) == 2000
        assert sum(isinstance(e, EntryAdded) for e in sink.events) == 2002
    finally:
        hub.close()


def test_close_during_open_discards_late_feed():
    entered, release = threading.Event(), threading.Event()
    feed, sink, wire = Feed(), Sink(), transport()

    class DelayedOpener:
        def open_stream(self):
            entered.set()
            release.wait()
            return feed

    hub = EventHub(DelayedOpener(), wire)
    hub.start(sink)
    try:
        assert entered.wait(1)
        started = time.monotonic()
        hub.close(0.02)
        assert time.monotonic() - started < 0.2
        count = len(sink.events)
        release.set()
        assert feed.closed.wait(1)
        hub.close()
        assert len(sink.events) == count
        assert wire.calls == []
    finally:
        release.set()
        hub.close()


def test_reconnect_backfills_missed_entries_before_queued_frames():
    opener = Opener(
        Feed(transcript(entry_id="old"), EOFError()),
        Feed(
            transcript(entry_id="missed"),
            transcript(entry_id="queued"),
            {"channel": "done", "payload": None},
        ),
    )
    wire, sink = transport(), Sink()

    def tail(args):
        ids = ["old"] if opener.calls == 1 else ["old", "missed"]
        return {
            "entries": [{"id": entry_id, "seq": i} for i, entry_id in enumerate(ids)]
        }

    wire.commands["getAgentTranscriptTail"] = tail
    hub = EventHub(opener, wire)
    hub.follow("b")
    hub.start(sink)
    try:
        sink.until(lambda e: isinstance(e, Other))
        assert [e.entry.id for e in sink.events if isinstance(e, EntryAdded)] == [
            "old",
            "missed",
            "queued",
        ]
        assert sum(call[1] == "getAgentTranscriptTail" for call in wire.calls) == 2
    finally:
        hub.close()
