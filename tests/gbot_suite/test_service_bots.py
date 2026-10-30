import json
from pathlib import Path

import pytest

from gbot.service import bots, rooms
from gbot.service.fake import load_fake
from gbot.service.models import Bot
from gbot.service.transport import FakeTransport


def make_transport(temporal=False):
    transport = FakeTransport(bots.DEMO_COMMANDS, bots.DEMO_RPCS)
    transport.commands["listAgents"] = [{"id": "a", "name": "Alpha"}]
    transport.rpcs["GetGrokBotRuntimeCapabilities"] = {
        "capabilities": {
            "temporalCreationEnabled": temporal,
            "durableIdentityEnabled": True,
            "durableIdentityWritesEnabled": True,
        }
    }
    return transport


def test_temporal_request_and_retry():
    transport = make_transport(True)
    bot = bots.create(
        transport,
        " Alpha ",
        description="instructions",
        nonce="n",
        png=b"png",
        language="en",
    )
    assert bot.id == "n" and bot.raw["serverId"] == "demo-server-bot"
    expected = (
        "rpc",
        "CreateGrokBotTemporalAgent",
        {
            "agentId": "n",
            "name": "Alpha",
            "description": "instructions",
            "title": "",
            "avatarShape": "blob",
            "avatarColor": "blue",
            "harness": 2,
            "kickstartRequested": True,
            "introductionSuppressed": False,
            "avatarDataUrl": "data:image/png;base64,cG5n",
            "language": "en",
        },
    )
    assert transport.calls[-1] == expected
    bots.create(
        transport,
        " Alpha ",
        description="instructions",
        nonce="n",
        png=b"png",
        language="en",
    )
    assert transport.calls[-1] == expected
    assert not any(call[0] == "command" for call in transport.calls)


@pytest.mark.parametrize(
    "row",
    [
        {},
        {"agentId": "other", "harness": "temporal"},
        {"agentId": "n", "harness": "box"},
        {"agentId": "n", "harness": "temporal"},
    ],
)
def test_temporal_reply_validation(row):
    transport = make_transport(True)
    transport.rpcs["CreateGrokBotTemporalAgent"] = {"agent": row}
    with pytest.raises(ValueError):
        bots.create(transport, "Alpha", nonce="n")


def test_box_request_and_kickstart():
    transport = make_transport()
    bot = bots.create(transport, " Alpha ", nonce="n", png=b"png")
    assert transport.calls[-2:] == [
        (
            "command",
            "createAgent",
            {
                "name": "Alpha",
                "description": "",
                "avatarShape": "blob",
                "avatarColor": "blue",
                "origin": "user",
                "isKickstartRequested": True,
                "clientNonce": "n",
                "avatarPngBase64": "cG5n",
            },
        ),
        ("command", "kickstartAgent", {"id": bot.id}),
    ]
    expected = transport.calls[-2]
    bots.create(transport, " Alpha ", nonce="n", png=b"png")
    assert transport.calls[-2] == expected


@pytest.mark.parametrize(
    "name,kwargs",
    [
        (" ", {}),
        ("a" * 256, {}),
        ("Alpha", {"shape": "bad"}),
        ("Alpha", {"color": "bad"}),
        ("Alpha", {"nonce": ""}),
    ],
)
def test_create_validation(name, kwargs):
    transport = make_transport()
    with pytest.raises(ValueError):
        bots.create(transport, name, **kwargs)
    assert not transport.calls


@pytest.mark.parametrize(
    "missing", ["durableIdentityEnabled", "durableIdentityWritesEnabled"]
)
def test_capabilities_and_durable_gate(missing):
    transport = FakeTransport(rpcs={"GetGrokBotRuntimeCapabilities": {}})
    assert bots.capabilities(transport) == bots.Capabilities()
    assert bots.creation_route(transport) == "box"
    flags = {
        "temporalCreationEnabled": True,
        "durableIdentityEnabled": True,
        "durableIdentityWritesEnabled": True,
    }
    flags[missing] = False
    transport.rpcs["GetGrokBotRuntimeCapabilities"] = {"capabilities": flags}
    with pytest.raises(ValueError, match="durable identity"):
        bots.create(transport, "Alpha")
    assert not any(call[1].startswith("Create") for call in transport.calls)


@pytest.mark.parametrize("temporal", [False, True])
def test_room_creation_routes(temporal):
    transport = make_transport(temporal)
    transport.commands.update(rooms.DEMO_COMMANDS)
    transport.rpcs["CreateGrokBotRoom"] = rooms.DEMO_RPCS["CreateGrokBotRoom"]
    group = rooms.create(
        transport, "Team", ["a", "b"], description="work", nonce="room"
    )
    assert group and group.is_group
    if temporal:
        assert group.id == "room"
        assert transport.calls[-1] == (
            "rpc",
            "CreateGrokBotRoom",
            {
                "agentId": "room",
                "name": "Team",
                "description": "work",
                "memberAgentIds": ["a", "b"],
                "humanMemberUserIds": [],
            },
        )
    else:
        assert transport.calls[-1][1] == "createGroup"


def test_update_profile_and_no_changes():
    transport = make_transport()
    bot = Bot("a", "Alpha", description="keep", title="old")
    assert bots.update(transport, bot, title="new")
    assert transport.calls[-1] == (
        "command",
        "updateAgent",
        {
            "id": "a",
            "profile": {"name": "Alpha", "description": "keep", "title": "new"},
            "editedFields": ["title"],
        },
    )
    bots.update(transport, bot, name="Beta", description="", title="")
    assert transport.calls[-1][2]["editedFields"] == ["name", "description", "title"]
    count = len(transport.calls)
    with pytest.raises(ValueError, match="No bot fields changed"):
        bots.update(transport, bot, name="Alpha", description="keep")
    assert len(transport.calls) == count


def test_update_shape_and_color():
    transport = make_transport()
    shape, color = bots.SHAPES[1], bots.COLORS[1]
    bot = Bot("a", "Alpha", avatar_color=color, raw={"avatarShape": bots.SHAPES[0]})
    bots.update(transport, bot, shape=shape, color=color)
    assert transport.calls[-1][2]["profile"]["avatarShape"] == shape
    assert transport.calls[-1][2]["editedFields"] == ["avatarShape"]
    count = len(transport.calls)
    with pytest.raises(ValueError, match="Unknown bot shape or color"):
        bots.update(transport, bot, color="no-such-color")
    assert len(transport.calls) == count


def test_delete_and_main_guard():
    transport = make_transport()
    transport.commands["deleteAgents"] = {
        "refusedAgentIds": ["a"],
        "failedAgentIds": ["b", None],
    }
    assert bots.delete(transport, ["a", "b", "c"]) == bots.DeleteResult(("a",), ("b",))
    assert transport.calls[-1] == ("command", "deleteAgents", {"ids": ["a", "b", "c"]})
    transport.rpcs["GetGrokBotUserRuntimeSettings"] = {"settings": {"mainAgentId": "a"}}
    before = len(transport.calls)
    with pytest.raises(ValueError, match="current main bot"):
        bots.delete(transport, ["a", "b"])
    assert not any(call[1] == "deleteAgents" for call in transport.calls[before:])


@pytest.mark.parametrize("value", [False, True])
def test_toggle_arguments(value):
    transport = make_transport()
    for func, command, key in (
        (bots.set_hidden, "setAgentHiddenFromSidebar", "isHidden"),
        (bots.set_notify_on_updates, "setAgentNotifyOnUpdates", "isEnabled"),
        (bots.set_drafting_disabled, "setAgentDraftingDisabled", "isDisabled"),
    ):
        func(transport, "a", value)
        assert transport.calls[-1] == ("command", command, {"id": "a", key: value})


@pytest.mark.parametrize("server_group", [False, True])
def test_group_drafting_refusal(server_group):
    transport = make_transport()
    if server_group:
        transport.rpcs["ListGrokBotAgents"] = {
            "agents": [{"agentId": "a", "kind": "ROOM"}]
        }
    else:
        transport.commands["listAgents"] = [
            {"id": "a", "name": "Team", "isGroup": True}
        ]
    with pytest.raises(ValueError, match="non-group"):
        bots.set_drafting_disabled(transport, "a", True)
    assert not any(call[1] == "setAgentDraftingDisabled" for call in transport.calls)


@pytest.mark.parametrize("action", ["update", "delete", "hide", "notify", "drafting"])
def test_nonowner_guard(action):
    transport = make_transport()
    transport.rpcs["ListGrokBotAgents"] = {
        "agents": [{"agentId": "a", "viewerIsOwner": False, "viewerCanManage": True}]
    }
    with pytest.raises(
        ValueError, match="Only the bot's owner can change this in gbot; use the app"
    ):
        if action == "update":
            bots.update(transport, Bot("a", "Alpha"), name="Beta")
        elif action == "delete":
            bots.delete(transport, ["a"])
        else:
            {
                "hide": bots.set_hidden,
                "notify": bots.set_notify_on_updates,
                "drafting": bots.set_drafting_disabled,
            }[action](transport, "a", True)
    assert not any(call[0] == "command" for call in transport.calls)


def test_server_identities_and_voice():
    transport = make_transport()
    transport.rpcs["ListGrokBotAgents"] = {
        "agents": [
            None,
            {},
            {
                "id": "server",
                "agentId": "gateway",
                "harness": "temporal",
                "kind": "ROOM",
                "draftingDisabled": True,
                "voiceId": "v",
                "voiceSpeed": 1.25,
                "voiceLanguage": "en",
                "viewerCanManage": False,
            },
        ]
    }
    assert bots.server_bots(transport) == {
        "gateway": bots.ServerBot(
            "server", "temporal", True, True, True, False, "v", 1.25, "en"
        )
    }


def test_main_settings_and_context():
    transport = make_transport()
    assert bots.main_agent(transport) is None
    transport.rpcs["GetGrokBotUserRuntimeSettings"] = {"settings": {"mainAgentId": "a"}}
    assert bots.main_agent(transport) == "a"
    bots.set_main(transport, "b")
    assert transport.calls[-1] == ("rpc", "SetGrokBotMainAgent", {"agentId": "b"})
    for value, expected in [
        (1, "created"),
        (2, "present"),
        (3, "has_main_agent"),
        ("HAS_MAIN_AGENT", "has_main_agent"),
    ]:
        transport.rpcs["EnsureGrokBotDefaultMainAgent"] = {
            "agentId": "a",
            "outcome": value,
        }
        assert bots.ensure_main(transport) == ("a", expected)
    assert bots.main_context(transport, "a") == bots.MainContext("demo-helper", False)
    assert transport.calls[-1] == ("command", "readMainAgentContext", {"id": "a"})


def test_demo_and_parity():
    transport = load_fake().transport
    assert set(bots.COMMANDS) <= transport.commands.keys()
    assert set(bots.RPCS) <= transport.rpcs.keys()
    assert bots.create(transport, "Demo")
    bots.set_drafting_disabled(transport, "demo-helper", True)
    entries = json.loads(
        (Path(__file__).resolve().parents[2] / "docs/parity.json").read_text(
            encoding="utf-8"
        )
    )["entries"]
    index = {row["name"]: row for row in entries}
    for name in set(bots.COMMANDS) | set(bots.RPCS) | {"CreateGrokBotRoom"}:
        row = index[name]
        assert row["status"] == "done" and row["milestone"] == "M3"
        assert row["area"] in {"bots", "roster", "rooms"}
    assert index["seedConversationName"]["status"] == "planned"
