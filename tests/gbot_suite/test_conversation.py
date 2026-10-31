import pytest

from gbot.service import conversation as c
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
