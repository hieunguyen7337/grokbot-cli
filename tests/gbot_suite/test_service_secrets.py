import pytest

from gbot.service import bots, secrets
from gbot.service.transport import FakeTransport


def transport():
    return FakeTransport(
        secrets.DEMO_COMMANDS,
        {
            **secrets.DEMO_RPCS,
            "ListGrokBotAgents": {"agents": [{"agentId": "bot", "id": "backend"}]},
        },
    )


def test_metadata_and_writes():
    fake = transport()
    rows = secrets.list_secrets(fake, "bot")
    assert rows == [secrets.SecretInfo("DEMO_TOKEN", "Demo integration", 1800000000000)]
    assert fake.calls[-1] == ("rpc", "ListGrokBotSecrets", {"id": "backend"})
    fake.rpcs["ListGrokBotSecrets"] = {}
    assert secrets.list_secrets(fake, "bot") == []
    value = "test-value-not-for-output"
    fake.rpcs["PutGrokBotSecret"] = {
        "secret": {"name": "TOKEN", "description": "test", "updatedAtMs": "123"}
    }
    result = secrets.put_secret(fake, "bot", " token ", f" {value} ", "test")
    assert result == secrets.SecretInfo("TOKEN", "test", 123)
    assert fake.calls[-1] == (
        "rpc",
        "PutGrokBotSecret",
        {"id": "backend", "name": "TOKEN", "description": "test", "value": value},
    )
    secrets.delete_secret(fake, "bot", "token")
    assert fake.calls[-1] == (
        "rpc",
        "DeleteGrokBotSecret",
        {"id": "backend", "name": "TOKEN"},
    )
    box = secrets.box_secrets(fake)
    assert box.keys == ("DEMO_TOKEN", "DEMO_KEY") and box.is_applied
    assert secrets.carry_to_bot(fake, "bot", ["TOKEN", "TOKEN", "KEY"]) == [
        ("TOKEN", "copied"),
        ("KEY", "copied"),
    ]
    assert fake.calls[-1] == (
        "command",
        "carryBoxSecretsToBot",
        {"serverId": "backend", "names": ["TOKEN", "KEY"]},
    )
    assert value not in repr((rows, result, box))
    assert all(
        value not in repr(call) for call in fake.calls if call[1] != "PutGrokBotSecret"
    )


@pytest.mark.parametrize(
    "row,message",
    [
        (None, "no server identity"),
        ({"agentId": "bot"}, "no server identity"),
        (
            {"agentId": "bot", "id": "backend", "viewerIsOwner": False},
            bots._OWNER_ERROR,
        ),
    ],
)
@pytest.mark.parametrize("action", ["put", "delete", "carry"])
def test_identity_and_owner_refusal(row, message, action):
    fake = transport()
    fake.rpcs["ListGrokBotAgents"] = {"agents": [row] if row else []}
    with pytest.raises(ValueError, match=message):
        if action == "put":
            secrets.put_secret(fake, "bot", "TOKEN", "value")
        elif action == "delete":
            secrets.delete_secret(fake, "bot", "TOKEN")
        else:
            secrets.carry_to_bot(fake, "bot", ["TOKEN"])
    assert [call[1] for call in fake.calls] == ["ListGrokBotAgents"]


@pytest.mark.parametrize(
    "name",
    [
        "PATH",
        "HOME",
        "USER",
        "SHELL",
        "TERM",
        "PWD",
        "DISPLAY",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "CURSOR_SANDBOX",
        "LD_TOKEN",
        "CURSOR_TOKEN",
        "CLOUD_AGENT_TOKEN",
        "SAND_TOKEN",
        "",
        "A" * 129,
        "1TOKEN",
        "_TOKEN",
        "A-B",
        "é",
    ],
)
def test_invalid_names(name):
    with pytest.raises(ValueError):
        secrets.normalize_name(name.lower())


def test_validation_and_redaction():
    assert secrets.normalize_name(" abc_123 ") == "ABC_123"
    assert secrets.normalize_name("A" * 128) == "A" * 128
    assert secrets.check_value(" x ") == "x"
    assert secrets.check_value("é" * 2048) == "é" * 2048
    for value in (" ", "x" * 4097, "é" * 2049):
        with pytest.raises(ValueError) as error:
            secrets.check_value(value)
        if value.strip():
            assert value not in str(error.value)
    fake = transport()
    fake.rpcs["PutGrokBotSecret"] = ValueError("private-test-value")
    with pytest.raises(ValueError) as error:
        secrets.put_secret(fake, "bot", "TOKEN", "private-test-value")
    assert "private-test-value" not in str(error.value)


def test_empty_identity_box_metadata_and_carry_outcomes():
    fake = transport()
    fake.rpcs["ListGrokBotAgents"] = {}
    with pytest.raises(ValueError, match="no server identity"):
        secrets.list_secrets(fake, "bot")
    assert [call[1] for call in fake.calls] == ["ListGrokBotAgents"]
    fake = transport()
    fake.commands["getBoxSecretsStatus"] = {
        "keys": [],
        "cardKeys": ["CARD_KEY"],
        "isApplied": False,
        "lastAppliedAtMs": 123,
    }
    assert secrets.box_secrets(fake) == secrets.BoxSecrets(
        (), ("CARD_KEY",), False, 123
    )
    outcomes = [
        "box-unreachable",
        "copied",
        "failed",
        "invalid-name",
        "invalid-value",
        "missing",
    ]
    fake.commands["carryBoxSecretsToBot"] = [
        {"name": str(i), "outcome": outcome} for i, outcome in enumerate(outcomes)
    ]
    assert secrets.carry_to_bot(fake, "bot", ["TOKEN", "TOKEN"]) == [
        (str(i), outcome) for i, outcome in enumerate(outcomes)
    ]
    assert fake.calls[-1][2] == {"serverId": "backend", "names": ["TOKEN"]}
