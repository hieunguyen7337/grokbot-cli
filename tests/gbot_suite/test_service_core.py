import json
from pathlib import Path

import pytest

from gbot.protocol import USED_COMMANDS, USED_RPCS
from gbot.service.events import BotChanged, EntryAdded, EntryChanged
from gbot.service.fake import load_fake
from gbot.service.models import Action, Bot, Entry
from gbot.service.transport import FakeTransport
from groken.client import ConnectError

ROOT = Path(__file__).resolve().parents[2]


def bots_by_name() -> dict[str, Bot]:
    return {bot.name: bot for bot in load_fake().roster()}


def test_roster_rows_parse_state():
    bots = bots_by_name()
    assert len(bots) == 8
    assert (
        bots["Research"].busy
        and bots["Research"].activity == "web.search flights SFO to NRT"
    )
    assert bots["Inbox"].awaiting is not None and not bots["Inbox"].busy
    assert bots["Ledger"].unread and bots["Ledger"].unread_count == 1
    assert bots["Helper"].last_outcome == "failed"
    team = bots["Email team"]
    assert team.is_group and team.member_ids == (
        "demo-inbox",
        "demo-outbox",
        "demo-ledger",
    )
    assert not bots["Outbox"].busy and not bots["Outbox"].unread


def test_bot_rejects_rows_without_identity_and_applies_overlays():
    assert Bot.from_row({"name": "x"}) is None
    assert Bot.from_row("nope") is None
    bot = Bot.from_row({"id": "b", "name": "B"})
    assert bot is not None and not bot.busy
    busy = bot.with_overlay({"isComposingMessage": True})
    assert busy.busy and busy.name == "B"
    blocked = busy.with_overlay(
        {"awaitingUserResponse": {"reason": "x", "since": 5, "tabId": "main"}}
    )
    assert (
        not blocked.busy
        and blocked.awaiting is not None
        and blocked.awaiting.since_ms == 5
    )


@pytest.mark.parametrize(
    ("raw", "kind", "text", "user"),
    [
        (
            {"id": "t1u", "seq": 1, "kind": "message", "role": "user", "content": "hi"},
            "message",
            "hi",
            True,
        ),
        (
            {
                "id": "t1a",
                "seq": 2,
                "kind": "message",
                "role": "assistant",
                "content": "yo",
            },
            "message",
            "yo",
            False,
        ),
        (
            {
                "id": "t1s0",
                "seq": 3,
                "kind": "send-message",
                "message": {"type": "text", "content": "ok"},
            },
            "send-message",
            "ok",
            False,
        ),
        (
            {
                "id": "t1a0",
                "seq": 4,
                "kind": "tool-call",
                "name": "web",
                "summary": "Searched",
            },
            "tool-call",
            "Searched",
            False,
        ),
        (
            {"id": "n", "seq": 5, "kind": "notice", "text": "Stopped"},
            "notice",
            "Stopped",
            False,
        ),
    ],
)
def test_entry_kinds(raw, kind, text, user):
    entry = Entry.from_raw("bot", raw, session_id="s1")
    assert entry is not None
    assert (entry.kind, entry.text, entry.is_user, entry.session_id) == (
        kind,
        text,
        user,
        "s1",
    )
    assert entry.key == ("bot", "s1", raw["id"])


def test_entry_card_type_and_turn():
    entry = Entry.from_raw(
        "b",
        {
            "id": "t12s4",
            "seq": 9,
            "kind": "send-message",
            "message": {"type": "widget"},
        },
    )
    assert entry is not None and entry.card_type == "widget" and entry.turn == 12
    assert Entry.from_raw("b", {"id": "x"}) is None


def test_fake_transport_records_and_scripts_replies():
    boom = ConnectError(500, "boom")
    transport = FakeTransport(
        {"listAgents": [], "echo": lambda args: args["v"], "bad": boom},
        {"RespondGrokBotWidget": {"accepted": True}},
    )
    assert transport.command("listAgents") == []
    assert transport.command("echo", {"v": 3}) == 3
    with pytest.raises(ConnectError):
        transport.command("bad")
    with pytest.raises(ConnectError) as missing:
        transport.command("nope")
    assert missing.value.status == 404
    assert transport.rpc("RespondGrokBotWidget", {"agentId": "b"}) == {"accepted": True}
    assert [call[:2] for call in transport.calls] == [
        ("command", "listAgents"),
        ("command", "echo"),
        ("command", "bad"),
        ("command", "nope"),
        ("rpc", "RespondGrokBotWidget"),
    ]


def test_fake_service_pending_and_paging():
    service = load_fake()
    cards, warnings = service.pending()
    assert warnings == []
    assert sorted((card.bot_name, card.type) for card in cards) == [
        ("Inbox", "email-draft"),
        ("Planner", "widget"),
        ("Travel", "auto-review-approval"),
    ]
    page = service.transcript("demo-inbox", limit=2)
    assert [entry.seq for entry in page.entries] == [3, 4] and page.next_before_seq == 3
    older = service.transcript("demo-inbox", before_seq=3, limit=5)
    assert [entry.seq for entry in older.entries] == [
        1,
        2,
    ] and older.next_before_seq is None
    with pytest.raises(ValueError):
        service.transcript("nope")


def test_fake_service_send_reply_and_answer_emit_events():
    service = load_fake()
    events = []
    source = service.event_source()
    source.start(events.append)
    result = service.send("demo-outbox", "Send the report", session_id="main")
    assert result.accepted and result.last_seq == 2
    assert isinstance(events[1], EntryAdded) and events[1].entry.is_user
    assert isinstance(events[2], BotChanged) and events[2].bot.busy
    service.reply("demo-outbox", "Sent.")
    assert isinstance(events[3], EntryAdded) and events[3].entry.text == "Sent."
    assert (
        isinstance(events[4], BotChanged)
        and not events[4].bot.busy
        and events[4].bot.unread
    )

    card = next(card for card in service.pending()[0] if card.type == "widget")
    answer = service.answer(card, Action("respond", value="City Loft"))
    assert answer.rpc == "RespondGrokBotWidget"
    assert not service.still_pending(card)
    assert any(isinstance(event, EntryChanged) for event in events)
    planner = next(bot for bot in service.roster() if bot.name == "Planner")
    assert planner.awaiting is None
    with pytest.raises(ValueError):
        service.answer(card, Action("respond", value="City Loft"))
    source.close()
    service.send("demo-outbox", "after close")
    assert not any(
        isinstance(e, EntryAdded) and e.entry.text == "after close" for e in events
    )


def test_fake_service_open_clears_unread():
    service = load_fake()
    service.open("demo-ledger")
    ledger = next(bot for bot in service.roster() if bot.name == "Ledger")
    assert not ledger.unread


def test_parity_file_matches_the_code():
    parity = json.loads((ROOT / "docs" / "parity.json").read_text(encoding="utf-8"))
    entries = {entry["name"]: entry for entry in parity["entries"]}
    assert len(entries) == len(parity["entries"])
    used = set(USED_COMMANDS) | set(USED_RPCS)
    not_done = sorted(
        name for name in used if entries.get(name, {}).get("status") != "done"
    )
    assert not_done == [], "mark these done in docs/parity.json"
    stale = sorted(
        name
        for name, entry in entries.items()
        if entry["status"] == "done" and name not in used
    )
    assert stale == [], "these are marked done but no code declares them"
