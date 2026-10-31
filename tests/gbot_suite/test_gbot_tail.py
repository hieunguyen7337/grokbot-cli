import argparse
import json
from typing import cast

import pytest

from gbot.commands import tail
from gbot.context import Context
from gbot.output import Output
from gbot.service.events import EntryAdded
from gbot.service.models import Entry, TranscriptPage


@pytest.mark.parametrize(
    "kind,body,marker,state",
    [
        (
            "widget",
            {"widget": {"prompt": "Pick", "options": [{"label": "A"}]}},
            {"respondedValue": "A"},
            "answered: A",
        ),
        (
            "user-form",
            {"formRequest": {"title": "Form"}},
            {"formResolution": "submitted"},
            "submitted",
        ),
        (
            "email-draft",
            {"draft": {"from": "a", "to": ["b"], "subject": "c"}},
            {"draftSendState": "discarded"},
            "discarded",
        ),
    ],
)
def test_card_render(kind, body, marker, state):
    row = {"id": "x", "kind": "send-message", "message": {"type": kind, **body}}
    summary = {
        "widget": "Pick",
        "user-form": "Form",
        "email-draft": "From: a; To: b; Subject: c",
    }[kind]
    assert tail.render(row, True).endswith(f"{kind}: {summary} (pending)")
    assert tail.render({**row, **marker}, True).endswith(f"{kind}: {summary} ({state})")
    assert tail.render(
        {"kind": "send-message", "message": {"type": "new-card"}}, True
    ).endswith("new-card")


@pytest.mark.parametrize("follow", [False, True])
def test_after_backfill_and_follow(monkeypatch, capsys, follow):
    entries = [
        {"id": str(n), "seq": n, "kind": "message", "content": str(n)}
        for n in range(1, 5)
    ] + [{"id": "missing", "kind": "message"}]

    class Manager:
        def command(self, method, args=None):
            assert (method, args) == (
                "getAgentTranscriptTail",
                {"id": "a", "limit": 100},
            )
            return {"entries": entries}

        def transcript(self, bot_id, limit):
            return TranscriptPage(
                tuple(e for row in entries if (e := Entry.from_raw(bot_id, row)))
            )

        def event_source(self):
            return self

        def follow(self, bot_id):
            assert bot_id == "a"

        def start(self, sink):
            for seq in (2, 4, 5, 5):
                entry = Entry.from_raw("a", {"id": str(seq), "seq": seq})
                assert entry is not None
                sink(EntryAdded(entry))

    class Ctx:
        out = Output(json_mode=True)

        def manager(self):
            return Manager()

        def service(self):
            return Manager()

        def close(self):
            pass

    from queue import SimpleQueue

    class Queue(SimpleQueue):
        def get(self, block=True, timeout=None):
            if self.empty():
                raise KeyboardInterrupt
            return super().get(block, timeout)

    monkeypatch.setattr(tail, "SimpleQueue", Queue)

    monkeypatch.setattr(tail, "resolve_bot", lambda ctx, requested: ("a", "Alpha"))
    args = argparse.Namespace(
        bot=None, n=1, since=None, after=2, full=False, follow=follow
    )
    assert tail.run(args, cast(Context, Ctx())) == 0
    output = capsys.readouterr().out
    rows = (
        [json.loads(line) for line in output.splitlines()]
        if follow
        else json.loads(output)
    )
    assert [row["seq"] for row in rows] == ([4, 5] if follow else [4])
