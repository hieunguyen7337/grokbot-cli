import argparse
import json
from typing import cast

import pytest

from gbot.commands import tail
from gbot.context import Context
from gbot.output import Output


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

        def transcript_tail(self, bot_id):
            return entries

        def events(self, channels):
            for seq in (2, 5):
                yield {
                    "data": {
                        "channel": "transcript",
                        "payload": {
                            "type": "appended",
                            "agentId": "a",
                            "entry": {"id": str(seq), "seq": seq},
                        },
                    }
                }
            raise KeyboardInterrupt

    class Ctx:
        out = Output(json_mode=True)

        def manager(self):
            return Manager()

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
