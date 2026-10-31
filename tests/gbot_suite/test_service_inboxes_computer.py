import pytest

from gbot.service import computer, inboxes
from gbot.service.models import Bot
from gbot.service.transport import FakeTransport

URL = "https://viewer.invalid/?token=private"


def test_inboxes():
    transport = FakeTransport(rpcs={**inboxes.DEMO_RPCS, "ListGrokBotEmailInboxes": {}})
    assert inboxes.list_inboxes(transport) == []
    assert transport.calls == [
        ("rpc", "ListGrokBotEmailInboxes", {"showsAssigned": True})
    ]
    transport.rpcs["ListGrokBotEmailInboxes"] = {
        "inboxes": [{"email": "a@example.com", "createdAtMs": "123", "assigned": True}]
    }
    assert inboxes.list_inboxes(transport)[0].created_at_ms == 123
    inboxes.create_inbox(transport, "  ALPHA  ")
    assert transport.calls[-1][2] == {"username": "alpha", "displayName": ""}
    before = len(transport.calls)
    for value in ("", "   ", "a@b", "a b", "a\tb", "a\nb"):
        with pytest.raises(ValueError):
            inboxes.create_inbox(transport, value)
    assert len(transport.calls) == before


@pytest.mark.parametrize(
    "row,state,phase",
    [
        (None, "absent", "off"),
        ({"state": "absent"}, "absent", "off"),
        ({"state": "hibernated"}, "hibernated", "sleeping"),
        ({"state": "running", "vncUrl": URL}, "running", "running"),
        ({"state": "running", "pull": {"percent": 0}}, "running", "pulling"),
    ],
)
def test_status(row, state, phase):
    transport = FakeTransport({"getForeverBoxStatus": row})
    value = computer.status(transport, "bot")
    assert (value.state, value.phase) == (state, phase)
    assert transport.calls[-1][2] == {"id": "bot"}
    assert URL not in repr(value)


def test_status_details_and_actions():
    row = {
        "state": "running",
        "vncUrl": URL,
        "windows": [{"windowIndex": 0, "vncUrl": URL}],
        "handoff": {"requestId": "req", "instruction": "Review"},
        "pull": {"percent": 42},
        "hostVersion": "0.77",
        "hostUpdateAvailable": True,
        "imageUpdateAvailable": False,
        "diskPressure": {"level": "hard"},
    }
    transport = FakeTransport({name: row for name in computer.COMMANDS})
    value = computer.status(transport, "bot")
    assert value.handoff_request_id == "req" and value.handoff_instruction == "Review"
    assert value.disk_pressure == "hard" and value.pull_percent == 42
    assert value.host_version == "0.77" and value.host_update_available is True
    assert value.image_update_available is False and value.windows[0]["vncUrl"] == URL
    assert URL not in repr(value)
    assert computer.wake(transport, "bot") == value
    assert computer.update(transport, "bot") == value
    assert [call[1:] for call in transport.calls[-2:]] == [
        ("ensureForeverBox", {"id": "bot"}),
        ("updateForeverBox", {"id": "bot"}),
    ]


@pytest.mark.parametrize("harness", ["temporal", "box"])
@pytest.mark.parametrize(
    "trigger,number", [("button", 1), ("viewer-closed", 2), ("dismissed", 3)]
)
def test_hand_back(harness, trigger, number):
    transport = FakeTransport(computer.DEMO_COMMANDS, computer.DEMO_RPCS)
    bot = Bot.from_row({"id": "bot", "name": "Alpha", "harness": harness})
    assert bot is not None
    with pytest.raises(ValueError, match="Nothing to hand back"):
        computer.hand_back(transport, bot, "")
    assert not transport.calls
    computer.hand_back(transport, bot, "req", trigger)
    expected = (
        (
            "rpc",
            "EndGrokBotBoxHandoff",
            {"agentId": "bot", "requestId": "req", "trigger": number},
        )
        if harness == "temporal"
        else (
            "command",
            "handBackForeverBox",
            {"id": "bot", "requestId": "req", "trigger": trigger},
        )
    )
    assert transport.calls == [expected]
