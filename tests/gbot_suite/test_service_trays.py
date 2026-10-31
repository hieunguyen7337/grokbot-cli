from unittest.mock import patch

import pytest

from gbot.protocol import USED_COMMANDS
from gbot.service import trays
from gbot.service.transport import FakeTransport


def test_parsing_and_commands():
    actions = [
        {
            "kind": "dashboard-action",
            "label": "More",
            "action": "requestLimitIncrease",
            "args": {},
            "successMessage": None,
        },
        {"kind": "open-buy-credits", "label": "Buy", "entrypoint": "tray"},
        {"kind": "roll-back", "sessionId": "sub", "fromSeq": 3, "emphasis": "primary"},
        {"kind": "open-url", "label": "Help", "url": "https://example.com"},
        {"kind": "start-fresh", "sessionId": "sub"},
        {"kind": "upgrade", "url": "https://example.com"},
        {"kind": "upgradeChoice", "url": "https://example.com"},
        {"kind": "switch-model"},
        {"kind": "future-kind"},
    ]
    minimal = {"id": "old", "agentId": "bot", "title": "Old", "createdAt": 1}
    full = dict(
        minimal,
        id="new",
        createdAt=2,
        detail="Detail",
        severity="info",
        count=3,
        actions=actions,
    )
    transport = FakeTransport(
        commands={"getTrays": [minimal, full], "dismissTray": None, "clearTrays": None}
    )
    result = trays.trays(transport)
    assert [tray.id for tray in result] == ["new", "old"]
    assert [action.kind for action in result[0].actions] == [a["kind"] for a in actions]
    assert result[0].actions[2].session_id == "sub"
    assert result[0].actions[2].from_seq == 3
    assert result[0].actions[2].emphasis == "primary"
    assert result[0].actions[1].entrypoint == "tray"
    assert result[0].detail == "Detail" and result[0].count == 3
    assert result[0].raw == full
    assert result[1].actions == () and result[1].count == 1
    trays.dismiss(transport, "new")
    trays.clear(transport)
    assert transport.calls == [
        ("command", "getTrays", {}),
        ("command", "dismissTray", {"id": "new"}),
        ("command", "clearTrays", {}),
    ]
    assert {key: USED_COMMANDS[key] for key in trays.COMMANDS} == trays.COMMANDS
    with patch.object(transport, "command", wraps=transport.command) as command:
        trays.trays(transport)
        command.assert_called_once_with("getTrays")
        command.reset_mock()
        trays.clear(transport)
        command.assert_called_once_with("clearTrays")


def test_defensive_parsing():
    valid = {"id": "x", "agentId": "bot", "title": "Title", "createdAt": 1}
    invalid = [
        None,
        [],
        {},
        dict(valid, id=3),
        dict(valid, agentId=None),
        dict(valid, title=[]),
        dict(valid, createdAt=True),
        dict(valid, createdAt="1"),
    ]
    invalid_actions = [
        None,
        {},
        {"kind": 5},
        {"kind": "start-fresh"},
        {"kind": "roll-back", "sessionId": 3},
        {"kind": "open-url", "label": "Link"},
    ]
    transport = FakeTransport(
        commands={"getTrays": [*invalid, dict(valid, actions=invalid_actions)]}
    )
    result = trays.trays(transport)
    assert len(result) == 1 and not result[0].actions
    transport.commands["getTrays"] = None
    assert trays.trays(transport) == []
    for reply in ({}, "bad", 3):
        transport.commands["getTrays"] = reply
        with pytest.raises(ValueError, match="Unexpected reply to getTrays"):
            trays.trays(transport)
