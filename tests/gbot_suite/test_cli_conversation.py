import json

import pytest

from gbot import cli, context
from gbot.service import conversation, routing
from gbot.service.transport import FakeTransport

ROWS = [
    {"id": "box-bot", "name": "Box"},
    {"id": "temporal-bot", "name": "Temporal", "harness": "temporal"},
]


def setup_cli(monkeypatch):
    fake = FakeTransport(
        {
            "listAgents": ROWS,
            "getAgentTranscriptTail": {"entries": [{"id": "e", "seq": 3}]},
            "sendPrompt": {"accepted": True},
            **conversation.DEMO_COMMANDS,
        },
        {
            "SendGrokBotUserMessage": {"delivery": "X_ACCEPTED_TEMPORAL"},
            **conversation.DEMO_RPCS,
        },
    )
    monkeypatch.setattr(context, "manager_factory", lambda: fake)

    class Backend:
        def unary(self, service, name, payload):
            return fake.rpc(name, payload)

    monkeypatch.setattr(context, "backend_factory", Backend)
    monkeypatch.setattr(routing, "now_ms", lambda: 1_800_000_000_000)
    return fake


def sent(fake):
    return [
        (kind, name, args)
        for kind, name, args in fake.calls
        if name in {"sendPrompt", "SendGrokBotUserMessage"}
    ]


def test_send_box_bot_uses_the_gateway(monkeypatch, capsys):
    fake = setup_cli(monkeypatch)
    assert cli.main(["send", "--bot", "Box", "--nonce", "key-1", "--json", "hi"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "accepted": True,
        "bot": {"id": "box-bot", "name": "Box"},
        "last_seq": 3,
    }
    assert sent(fake) == [
        (
            "command",
            "sendPrompt",
            {"agentId": "box-bot", "prompt": "hi", "clientNonce": "key-1"},
        )
    ]


def test_send_temporal_bot_uses_the_backend(monkeypatch, capsys):
    fake = setup_cli(monkeypatch)
    argv = ["send", "--bot", "Temporal", "--session", "s", "--nonce", "key-1", "hi"]
    assert cli.main([*argv, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["accepted"] is True
    assert cli.main(argv) == 0
    assert "Sent to Temporal." in capsys.readouterr().out
    payload = {
        "agentId": "temporal-bot",
        "messageId": "key-1",
        "text": "hi",
        "sentAtMs": "1800000000000",
        "attachmentPaths": [],
        "attachmentNames": [],
        "sessionId": "s",
    }
    assert sent(fake) == [("rpc", "SendGrokBotUserMessage", payload)] * 2


def test_send_temporal_refusal_exits_one(monkeypatch, capsys):
    fake = setup_cli(monkeypatch)
    fake.rpcs["SendGrokBotUserMessage"] = {"delivery": "X_REFUSED"}
    assert cli.main(["send", "--bot", "Temporal", "hi"]) == 1
    assert "Send refused" in capsys.readouterr().err
    assert [name for _, name, _ in sent(fake)] == ["SendGrokBotUserMessage"]


@pytest.mark.parametrize(
    "bot, kind, name",
    [
        ("Box", "command", "promptAcceptanceStatus"),
        ("Temporal", "rpc", "GetGrokBotSendStatus"),
    ],
)
def test_send_status_reads_without_sending(monkeypatch, capsys, bot, kind, name):
    fake = setup_cli(monkeypatch)
    argv = ["send", "--bot", bot, "--status", "nonce-1", "--json"]
    assert cli.main(argv) == 0
    value = json.loads(capsys.readouterr().out)
    assert value["bot"]["name"] == bot
    assert value["nonce"] == "nonce-1"
    assert value["status"]["status"] == "accepted"
    assert not sent(fake)
    assert [call[:2] for call in fake.calls if call[1] != "listAgents"] == [
        (kind, name)
    ]
    assert cli.main(argv[:-1]) == 0
    assert "accepted" in capsys.readouterr().out


def test_send_status_rejects_text(monkeypatch, capsys):
    fake = setup_cli(monkeypatch)
    assert cli.main(["send", "--bot", "Box", "--status", "n", "hi"]) == 1
    assert "--status" in capsys.readouterr().err
    assert not [call for call in fake.calls if call[1] != "listAgents"]


@pytest.mark.parametrize("bot", ["Box", "Temporal"])
def test_sessions_lists_kinds_and_times(monkeypatch, capsys, bot):
    fake = setup_cli(monkeypatch)
    assert cli.main(["sessions", "--bot", bot, "--json"]) == 0
    value = json.loads(capsys.readouterr().out)
    assert value["bot"]["name"] == bot
    assert [row["kind"] for row in value["sessions"]] == ["main", "dm"]
    bot_id = value["bot"]["id"]
    assert ("rpc", "ListGrokBotAgentSessions", {"agentId": bot_id}) in fake.calls
    assert cli.main(["sessions", "--bot", bot]) == 0
    text = capsys.readouterr().out
    assert "main" in text and "dm" in text


def test_sessions_empty_text(monkeypatch, capsys):
    fake = setup_cli(monkeypatch)
    fake.rpcs["ListGrokBotAgentSessions"] = {}
    assert cli.main(["sessions", "--bot", "Box"]) == 0
    assert "No sessions" in capsys.readouterr().out
