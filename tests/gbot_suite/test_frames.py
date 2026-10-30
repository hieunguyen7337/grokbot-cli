"""Offline frame-shape contracts."""

import pytest

from gbot.service.events import (
    BotChanged,
    BotOverlay,
    BoxChanged,
    EntryAdded,
    EntryChanged,
    EntryRemoved,
    Other,
    RosterReplaced,
    RosterResync,
    TranscriptReset,
)
from gbot.service.frames import parse_frame


def frame(channel, **payload):
    return parse_frame({"channel": channel, "payload": payload})


def test_agents():
    event = frame("agents", agents=[{"id": "b", "name": "Bot"}, {}, None])[0]
    assert isinstance(event, RosterReplaced)
    assert [bot.id for bot in event.bots] == ["b"]


def test_agent_upserted():
    assert isinstance(
        frame("agent-upserted", agent={"id": "b", "name": "Bot"})[0], BotChanged
    )


@pytest.mark.parametrize(
    "live,client",
    [
        (None, {"hasUnread": True}),
        ({"isRunning": True}, None),
        ({"isRunning": True}, {"hasUnread": True}),
    ],
)
def test_agent_activity(live, client):
    assert frame("agent-activity", agentId="b", live=live, client=client) == [
        BotOverlay("b", {**(live or {}), **(client or {})})
    ]


@pytest.mark.parametrize(
    "kind,event_type",
    [
        ("appended", EntryAdded),
        ("updated", EntryChanged),
        ("removed", EntryRemoved),
        ("cleared", TranscriptReset),
        ("snapshot", TranscriptReset),
    ],
)
@pytest.mark.parametrize(
    "replica,session", [("transcript:b", None), ("transcript:b\0s", "s"), (None, None)]
)
def test_transcript_types_and_identity(kind, event_type, replica, session):
    raw = {"id": "e", "seq": 1, "kind": "message", "content": "hello"}
    payload = {
        "type": kind,
        "agentId": "b",
        "activeAgentId": "b",
        "entry": raw,
        "entries": [raw, {}],
        "id": "e",
    }
    if replica:
        payload["ordered"] = {"replicaKey": replica}
        payload["agentId"] = payload["activeAgentId"] = "wrong"
    event = frame("transcript", **payload)[0]
    assert isinstance(event, event_type)
    assert isinstance(event, (EntryAdded, EntryChanged, EntryRemoved, TranscriptReset))
    target = event.entry if isinstance(event, (EntryAdded, EntryChanged)) else event
    assert target.bot_id == "b"
    assert target.session_id == session
    if kind == "snapshot":
        assert isinstance(event, TranscriptReset)
        assert len(event.entries) == 1


@pytest.mark.parametrize("state", ["absent", "hibernated", "running"])
def test_forever_box(state):
    assert frame("forever-box", agentId="b", state=state) == [BoxChanged("b", state)]


def test_roster_resync_and_settings():
    assert frame("server-roster-changed", kind="agent", agentId="b") == [
        RosterResync("b")
    ]
    assert frame("server-roster-changed", kind="resync") == [RosterResync()]
    assert isinstance(frame("server-roster-changed", kind="user-settings")[0], Other)


@pytest.mark.parametrize(
    "channel,payload",
    [
        ("unknown", 12),
        ("agents", {}),
        ("agents", {"agents": None}),
        ("agent-upserted", {"agent": {}}),
        ("agent-activity", {"agentId": "b", "live": 3}),
        ("forever-box", {"agentId": "b", "state": "bad"}),
        ("transcript", {"agentId": "b", "type": "appended", "entry": {}}),
        ("transcript", {"agentId": "b", "type": "snapshot", "entries": 3}),
        ("server-roster-changed", {"kind": "agent"}),
    ],
)
def test_unknown_and_malformed(channel, payload):
    assert parse_frame({"channel": channel, "payload": payload}) == [
        Other(channel, payload)
    ]


def test_transcript_without_bot_is_dropped():
    assert frame("transcript", type="cleared") == []


def test_snapshot_active_agent_fallback():
    event = frame("transcript", type="snapshot", activeAgentId="b", entries=[])[0]
    assert event == TranscriptReset("b", None)
