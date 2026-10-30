import argparse
import json
import threading
from queue import SimpleQueue
from typing import cast

from gbot.commands import tail, watch
from gbot.context import Context
from gbot.output import Output
from gbot.service.events import (
    BotOverlay,
    ConnectionChanged,
    EntryAdded,
    Event,
    RosterReplaced,
)
from gbot.service.models import Bot, ConnectionStatus, Entry


class Queue(SimpleQueue):
    def get(self, block=True, timeout=None):
        if self.empty():
            raise KeyboardInterrupt
        return super().get(block, timeout)


class Service:
    def __init__(self, awaiting=False):
        row: dict[str, object] = {
            "id": "a",
            "name": "Inbox",
            "lastMessagePreview": "Hello",
        }
        if awaiting:
            row["awaitingUserResponse"] = {"reason": "approval"}
        bot = Bot.from_row(row)
        assert bot is not None
        self.bot = bot
        self.closed = False

    def roster(self):
        return [self.bot]

    def event_source(self):
        return self

    def follow(self, bot_id):
        assert bot_id == "a"

    def start(self, sink):
        sink(RosterReplaced((self.bot,)))
        sink(BotOverlay("a", {"isRunning": True}))
        sink(BotOverlay("a", {"isRunning": True}))
        sink(BotOverlay("a", {"isRunning": False, "hasUnread": True}))
        sink(ConnectionChanged(ConnectionStatus.LIVE))
        entry = Entry.from_raw("a", {"id": "e", "seq": 1, "content": "reply"})
        assert entry is not None
        sink(EntryAdded(entry))

    def close(self):
        self.closed = True


def invoke(service, *, once=False, json_mode=False, bot=None):
    class Ctx:
        out = Output(json_mode)

        def service(self):
            return service

        def close(self):
            service.close()

    return watch.run(argparse.Namespace(once=once, bot=bot), cast(Context, Ctx()))


def test_once(capsys):
    service = Service(True)
    assert invoke(service, once=True) == 2
    assert (
        capsys.readouterr().out == "NAME   STATE     SUMMARY\nInbox  awaiting  Hello\n"
    )
    assert service.closed
    assert invoke(Service(), once=True, json_mode=True) == 0
    assert json.loads(capsys.readouterr().out) == [
        {
            "id": "a",
            "name": "Inbox",
            "state": "idle",
            "summary": "Hello",
            "last_activity_at": None,
        }
    ]


def test_stream(monkeypatch, capsys):
    monkeypatch.setattr(watch, "SimpleQueue", Queue)
    monkeypatch.setattr(watch.time, "time", lambda: 123.0)
    assert invoke(Service(), json_mode=True, bot="Inbox") == 0
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert rows == [
        {
            "type": "state",
            "id": "a",
            "name": "Inbox",
            "state": state,
            "summary": "Hello",
            "at": 123000,
        }
        for state in ("idle", "working", "new")
    ] + [
        {"type": "connection", "status": "live", "detail": ""},
        {
            "type": "entry",
            "id": "a",
            "entry": {"id": "e", "seq": 1, "content": "reply"},
        },
    ]


def test_next_event_waits_past_one_slice():
    queue: SimpleQueue[Event] = SimpleQueue()
    event = ConnectionChanged(ConnectionStatus.LIVE)
    threading.Timer(0.6, queue.put, (event,)).start()
    assert tail.next_event(queue) is event
