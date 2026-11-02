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


def test_places_area_mapping_outcomes_and_raw_card():
    fake = FakeTransport(
        rpcs={
            "SearchGrokBotPlacesArea": {
                "outcome": "FOUND",
                "placesCardJson": '{"title":"Nearby","futureField":true}',
            }
        }
    )
    result = search.places_area(
        fake,
        "bot",
        "entry",
        3,
        south_west={"latitude": 1.0, "longitude": 2.0},
        north_east={"latitude": 4.0, "longitude": 5.0},
        language="en",
        session_id="session",
    )
    assert result.outcome == "found"
    assert result.card == {"title": "Nearby", "futureField": True}
    assert fake.calls == [
        (
            "rpc",
            "SearchGrokBotPlacesArea",
            {
                "agentId": "bot",
                "entryId": "entry",
                "sessionId": "session",
                "language": "en",
                "cardIndex": 3,
                "area": {
                    "southWest": {"latitude": 1.0, "longitude": 2.0},
                    "northEast": {"latitude": 4.0, "longitude": 5.0},
                },
            },
        )
    ]
    fake.rpcs["SearchGrokBotPlacesArea"] = {
        "outcome": "RATE_LIMITED",
        "placesCardJson": "",
    }
    result = search.places_area(fake, "bot", "entry", 0)
    assert result.outcome == "rate_limited" and result.card is None


@pytest.mark.parametrize(
    "reply",
    [
        {"outcome": "FOUND"},
        {"outcome": "FOUND", "placesCardJson": ""},
        {"outcome": "FOUND", "placesCardJson": 5},
        {"outcome": "FOUND", "placesCardJson": "[1]"},
        {"outcome": "FOUND", "placesCardJson": "{"},
    ],
)
def test_places_found_without_a_card_is_failed(reply):
    transport = FakeTransport(rpcs={"SearchGrokBotPlacesArea": reply})
    result = search.places_area(transport, "a", "e", 0)
    assert (result.outcome, result.card) == ("failed", None)
