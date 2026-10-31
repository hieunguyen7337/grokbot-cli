import pytest

from gbot.protocol import USED_COMMANDS
from gbot.service import search
from gbot.service.transport import FakeTransport


def test_search_shapes_and_parsing():
    transport = FakeTransport(
        {
            "searchAgents": [
                {
                    "agentId": "a",
                    "entryId": "e",
                    "role": "assistant",
                    "snippet": "hello",
                    "timestampMs": 1,
                },
                {},
            ],
            "searchMedia": [],
            "searchConversation": {
                "matches": [
                    {
                        "entryId": "e",
                        "role": "user",
                        "seq": 2,
                        "snippet": "hello",
                        "timestampMs": 3,
                    },
                    {},
                ],
                "isComplete": False,
            },
        }
    )
    assert search.messages(transport, "hello")[0].entry_id == "e"
    assert search.media(transport, "") == []
    result = search.conversation(transport, "a", "hello", before_seq=5)
    assert not result.complete and result.matches[0].seq == 2
    assert transport.calls[-1][2] == {
        "agentId": "a",
        "query": "hello",
        "beforeSeq": 5,
        "limit": 50,
    }
    assert set(search.COMMANDS) <= USED_COMMANDS.keys()
    for command, call in [
        ("searchAgents", lambda: search.messages(transport, "x")),
        ("searchMedia", lambda: search.media(transport, "")),
        ("searchConversation", lambda: search.conversation(transport, "a", "x")),
    ]:
        transport.commands[command] = None
        with pytest.raises(ValueError, match=f"Unexpected reply to {command}"):
            call()
