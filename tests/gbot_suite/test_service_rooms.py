from dataclasses import replace

import pytest

from gbot.protocol import USED_COMMANDS, USED_RPCS
from gbot.service import rooms
from gbot.service.models import Bot
from gbot.service.transport import FakeTransport


def test_group_arguments_and_routes():
    transport = FakeTransport(rooms.DEMO_COMMANDS, rooms.DEMO_RPCS)
    bot = rooms.create_group(transport, "Team", ["a", "b"], nonce="nonce")
    assert bot and bot.is_group and bot.raw["id"] == bot.id
    assert transport.calls[-1] == (
        "command",
        "createGroup",
        {
            "name": "Team",
            "memberAgentIds": ["a", "b"],
            "namedBy": "user",
            "clientNonce": "nonce",
        },
    )
    rooms.create_group(transport, "Team", ["a", "b"], description="Work", nonce="two")
    assert transport.calls[-1][2]["description"] == "Work"
    group = Bot("g", "Group", is_group=True)
    rooms.set_members(transport, group, ["b", "a"])
    assert transport.calls[-1] == (
        "command",
        "setGroupMembers",
        {"id": "g", "memberAgentIds": ["b", "a"]},
    )
    rooms.set_members(transport, replace(group, raw={"harness": "temporal"}), ["a"])
    assert transport.calls[-1] == (
        "rpc",
        "SetGrokBotRoomMembers",
        {"agentId": "g", "memberAgentIds": ["a"]},
    )
    rooms.remove_people(transport, "g", [42])
    assert transport.calls[-1] == (
        "rpc",
        "RemoveGrokBotRoomPeople",
        {"agentId": "g", "userIds": [42]},
    )
    assert rooms.COMMANDS.keys() <= USED_COMMANDS.keys()
    assert set(rooms.RPCS) <= set(USED_RPCS)


@pytest.mark.parametrize(
    "reply",
    [
        None,
        {},
        [],
        {"agent": None},
        {"agent": {"id": "g"}},
        {"agent": {"id": 1, "name": "Bad"}},
    ],
)
def test_malformed_reply(reply):
    assert (
        rooms.create_group(FakeTransport({"createGroup": reply}), "Team", [], nonce="n")
        is None
    )


def test_people():
    bot = Bot(
        "g",
        "Group",
        raw={
            "people": [
                {"displayName": "Me", "isViewer": True},
                {"displayName": "Other", "isViewer": False, "userId": 42},
                None,
                {},
                {"displayName": "Bad", "isViewer": "yes"},
                {"displayName": "Bad", "isViewer": False, "userId": True},
            ]
        },
    )
    assert rooms.people(bot) == [
        rooms.Person("Me", True),
        rooms.Person("Other", False, 42),
    ]
    assert rooms.people(Bot("g", "G", raw={"people": "bad"})) == []
