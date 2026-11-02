import pytest

from gbot.service import conversation as c
from gbot.service.routing import Harness, Router
from gbot.service.transport import FakeTransport


@pytest.mark.parametrize("wrapped", [False, True])
def test_roster(wrapped):
    rows = [{"id": "a", "name": "Alpha"}, {}, {"id": "b"}]
    transport = FakeTransport({"listAgents": {"agents": rows} if wrapped else rows})
    assert [bot.id for bot in c.roster(transport)] == ["a"]


@pytest.mark.parametrize("reply", [None, {}, {"agents": 1}, "junk", 42])
def test_invalid_roster(reply):
    with pytest.raises(TypeError, match="Invalid bot list from gateway."):
        c.roster(FakeTransport({"listAgents": reply}))


def test_pages_and_sessions():
    reply = {
        "entries": [{"id": "b", "seq": 9}, {}, {"id": "a", "seq": 2}],
        "nextBeforeSeq": 2,
    }
    transport = FakeTransport({"openAgentTail": reply, "getAgentTranscriptTail": reply})
    page = c.open_chat(transport, "bot", session_id="s")
    assert [e.seq for e in page.entries] == [2, 9]
    assert all(e.session_id == "s" for e in page.entries)
    assert page.next_before_seq == 2
    assert (
        c.transcript(transport, "bot", before_seq=10, limit=3, session_id="s") == page
    )
    assert transport.calls == [
        ("command", "openAgentTail", {"id": "bot", "limit": 200, "sessionId": "s"}),
        (
            "command",
            "getAgentTranscriptTail",
            {"id": "bot", "limit": 3, "beforeSeq": 10, "sessionId": "s"},
        ),
    ]


def test_send_nonce_and_blank():
    transport = FakeTransport(
        {
            "getAgentTranscriptTail": {"entries": [{"id": "e", "seq": 7}]},
            "sendPrompt": {"accepted": True},
        }
    )
    first = c.send(transport, "b", "hi", session_id="s")
    again = c.send(transport, "b", "hi", session_id="s", nonce=first.nonce)
    assert first == again
    assert first.accepted and first.last_seq == 7
    assert transport.calls[0][2] == {"id": "b", "limit": 1, "sessionId": "s"}
    assert (
        transport.calls[1][2]
        == transport.calls[3][2]
        == {
            "agentId": "b",
            "prompt": "hi",
            "sessionId": "s",
            "clientNonce": first.nonce,
        }
    )
    count = len(transport.calls)
    with pytest.raises(ValueError, match="Prompt must not be empty."):
        c.send(transport, "b", " \n")
    assert len(transport.calls) == count


@pytest.mark.parametrize(
    "reply, expected",
    [
        (None, None),
        ([], None),
        ({"state": 4}, None),
        ({}, None),
        ({"state": "running"}, "running"),
    ],
)
def test_box_state(reply, expected):
    assert c.box_state(FakeTransport({"getForeverBoxStatus": reply}), "b") == expected


def test_send_status_box_uses_the_gateway_command():
    transport = FakeTransport({"promptAcceptanceStatus": {"status": "accepted"}})
    assert c.send_status(transport, "b", "n", session_id="s", task_id="k") == {
        "status": "accepted"
    }
    assert c.send_status(transport, "b", "n") == {"status": "accepted"}
    assert transport.calls == [
        (
            "command",
            "promptAcceptanceStatus",
            {"agentId": "b", "clientNonce": "n", "sessionId": "s", "taskId": "k"},
        ),
        ("command", "promptAcceptanceStatus", {"agentId": "b", "clientNonce": "n"}),
    ]


@pytest.mark.parametrize("reply", [None, [], "junk"])
def test_send_status_odd_reply_is_unknown(reply):
    transport = FakeTransport({"promptAcceptanceStatus": reply})
    assert c.send_status(transport, "b", "n") == {"outcome": "unknown-durability"}


def test_send_status_needs_a_nonce():
    transport = FakeTransport({"promptAcceptanceStatus": {}})
    with pytest.raises(ValueError, match="nonce"):
        c.send_status(transport, "b", " ")
    assert transport.calls == []


def test_send_status_temporal_uses_the_backend():
    fake = FakeTransport(
        {"promptAcceptanceStatus": {}},
        {"GetGrokBotSendStatus": {"outcome": "X_NOT_FOUND"}},
    )
    harness = Harness()
    harness.learn([{"id": "t", "harness": "temporal"}])
    assert c.send_status(Router(fake, harness), "t", "n") == {"outcome": "not-found"}
    assert [call[:2] for call in fake.calls] == [("rpc", "GetGrokBotSendStatus")]


def test_list_sessions_parses_kinds_and_times():
    reply = {
        "sessions": [
            {
                "agentId": "b",
                "sessionId": "",
                "kind": "GROK_BOT_AGENT_SESSION_KIND_MAIN",
                "createdAtMs": "1800000000000",
                "updatedAtMs": "1800000001000",
                "lastActivityAtMs": "1800000002000",
            },
            {
                "agentId": "b",
                "sessionId": "task:0123456789",
                "kind": "GROK_BOT_AGENT_SESSION_KIND_SLACK_THREAD",
                "createdAtMs": 5,
                "updatedAtMs": "6",
            },
            {"sessionId": "x", "kind": 3},
            "junk",
        ]
    }
    transport = FakeTransport(rpcs={"ListGrokBotAgentSessions": reply})
    assert c.list_sessions(transport, "b") == [
        {
            "agentId": "b",
            "sessionId": "",
            "kind": "main",
            "createdAtMs": 1_800_000_000_000,
            "updatedAtMs": 1_800_000_001_000,
            "lastActivityAtMs": 1_800_000_002_000,
        },
        {
            "agentId": "b",
            "sessionId": "task:0123456789",
            "kind": "slack_thread",
            "createdAtMs": 5,
            "updatedAtMs": 6,
        },
        {
            "agentId": "b",
            "sessionId": "x",
            "kind": "unspecified",
            "createdAtMs": 0,
            "updatedAtMs": 0,
        },
    ]
    assert transport.calls == [("rpc", "ListGrokBotAgentSessions", {"agentId": "b"})]


@pytest.mark.parametrize("reply", [{}, {"sessions": None}, {"sessions": "x"}])
def test_list_sessions_empty(reply):
    transport = FakeTransport(rpcs={"ListGrokBotAgentSessions": reply})
    assert c.list_sessions(transport, "b") == []


def test_demo_data_parses():
    transport = FakeTransport(dict(c.DEMO_COMMANDS), dict(c.DEMO_RPCS))
    rows = c.list_sessions(transport, "demo-bot")
    assert [row["kind"] for row in rows] == ["main", "dm"]
    assert all(row["agentId"] == "demo-bot" for row in rows)
    status = c.send_status(transport, "demo-bot", "nonce-1")
    assert status["status"] == "accepted" and status["clientNonce"] == "nonce-1"
