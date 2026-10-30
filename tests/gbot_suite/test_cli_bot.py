import json
from types import SimpleNamespace

import pytest

from gbot import cli, context
from gbot.commands import bot as command
from gbot.service import bots
from gbot.service.transport import FakeTransport


def setup_cli(monkeypatch):
    transport = FakeTransport(bots.DEMO_COMMANDS, bots.DEMO_RPCS)
    transport.commands["listAgents"] = [
        {"id": "a", "name": "Alpha", "title": "Title", "description": "instructions"}
    ]
    monkeypatch.setattr(command, "ContextTransport", lambda ctx: transport)
    monkeypatch.setattr(
        command, "resolve_bot", lambda ctx, name: ({"Beta": "b"}.get(name, "a"), name)
    )
    return transport


@pytest.mark.parametrize(
    "argv,expected",
    [
        (
            ["new", "New"],
            {"action": "new", "bot_id": "demo-new-bot", "name": "New bot"},
        ),
        (
            ["edit", "Alpha", "--name", "Changed"],
            {
                "action": "edit",
                "bot_id": "a",
                "bot": {"id": "demo-helper", "name": "Helper"},
            },
        ),
        (
            ["delete", "Alpha"],
            {"action": "delete", "bot_ids": ["a"], "refused_ids": [], "failed_ids": []},
        ),
        (["hide", "Alpha"], {"action": "hide", "bot_id": "a", "hidden": True}),
        (["show", "Alpha"], {"action": "show", "bot_id": "a", "hidden": False}),
        (
            ["notify", "Alpha", "on"],
            {"action": "notify", "bot_id": "a", "notify": True},
        ),
        (
            ["notify", "Alpha", "off"],
            {"action": "notify", "bot_id": "a", "notify": False},
        ),
        (
            ["drafting", "Alpha", "on"],
            {"action": "drafting", "bot_id": "a", "drafting_disabled": False},
        ),
        (
            ["drafting", "Alpha", "off"],
            {"action": "drafting", "bot_id": "a", "drafting_disabled": True},
        ),
        (["main", "Alpha"], {"action": "main", "bot_id": "a", "main_agent_id": "a"}),
        (["main"], {"main_agent_id": None}),
    ],
)
def test_actions_json(monkeypatch, capsys, argv, expected):
    setup_cli(monkeypatch)
    assert cli.main(["bot", *argv, "--yes", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == expected


@pytest.mark.parametrize(
    "argv",
    [
        ["new", "New"],
        ["edit", "Alpha", "--title", "Title"],
        ["delete", "Alpha"],
        ["hide", "Alpha"],
        ["show", "Alpha"],
        ["notify", "Alpha", "on"],
        ["drafting", "Alpha", "off"],
        ["main", "Alpha"],
    ],
)
def test_yes_required_without_terminal(monkeypatch, capsys, argv):
    transport = setup_cli(monkeypatch)
    assert cli.main(["bot", *argv, "--json"]) == 1
    assert "--yes" in json.loads(capsys.readouterr().err)["error"]["message"]
    assert not transport.calls


def test_info(monkeypatch, capsys):
    transport = setup_cli(monkeypatch)
    transport.rpcs["ListGrokBotAgents"] = {
        "agents": [
            {
                "agentId": "a",
                "harness": "temporal",
                "viewerIsOwner": False,
                "draftingDisabled": True,
                "voiceId": "v",
                "voiceSpeed": 1.1,
                "voiceLanguage": "en",
            }
        ]
    }
    transport.rpcs["GetGrokBotUserRuntimeSettings"] = {"settings": {"mainAgentId": "a"}}
    assert cli.main(["bot", "info", "Alpha", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "id": "a",
        "name": "Alpha",
        "title": "Title",
        "description": "instructions",
        "harness": "temporal",
        "owner": False,
        "hidden": False,
        "notify": True,
        "drafting_disabled": True,
        "voice": {"id": "v", "speed": 1.1, "language": "en"},
        "main": True,
    }
    assert cli.main(["bot", "info", "Alpha"]) == 0
    assert "description: instructions" in capsys.readouterr().out


def test_description_file_and_avatar(tmp_path, monkeypatch, capsys):
    transport = setup_cli(monkeypatch)
    file = tmp_path / "instructions.txt"
    file.write_text("new instructions", encoding="utf-8")
    assert (
        cli.main(
            ["bot", "edit", "Alpha", "--description-file", str(file), "--yes", "--json"]
        )
        == 0
    )
    profile = transport.calls[-1][2]["profile"]
    assert isinstance(profile, dict) and profile["description"] == "new instructions"
    capsys.readouterr()
    avatar = tmp_path / "avatar.png"
    avatar.write_bytes(b"\x89PNG\r\n\x1a\n")
    assert (
        cli.main(["bot", "new", "New", "--avatar", str(avatar), "--yes", "--json"]) == 0
    )
    assert transport.calls[-2][2]["avatarPngBase64"] == "iVBORw0KGgo="
    capsys.readouterr()


def test_delete_partial_and_confirmation(monkeypatch, capsys):
    transport = setup_cli(monkeypatch)
    transport.commands["listAgents"] = [
        {"id": "a", "name": "Alpha"},
        {"id": "b", "name": "Beta"},
    ]
    transport.commands["deleteAgents"] = {"failedAgentIds": ["b"]}
    assert cli.main(["bot", "delete", "Alpha", "Beta", "--yes", "--json"]) == 1
    output = capsys.readouterr()
    assert json.loads(output.out)["failed_ids"] == ["b"]
    assert "Alpha (a), Beta (b)" in output.err
    assert "conversation history is removed" in output.err


def test_terminal_confirmation_and_safe_text(monkeypatch, capsys):
    transport = setup_cli(monkeypatch)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "no")
    assert cli.main(["bot", "hide", "Alpha", "--json"]) == 1
    capsys.readouterr()
    assert not any(call[1] == "setAgentHiddenFromSidebar" for call in transport.calls)
    monkeypatch.setattr("builtins.input", lambda prompt: "yes")
    transport.commands["listAgents"] = [{"id": "a", "name": "Alpha\x1b[31m"}]
    assert cli.main(["bot", "hide", "Alpha", "--json"]) == 0
    output = capsys.readouterr()
    assert "\x1b" not in output.err and "\\u001b" in output.err


def test_real_selector_and_context_adapter(monkeypatch, capsys):
    transport = FakeTransport(bots.DEMO_COMMANDS, bots.DEMO_RPCS)
    transport.commands["listAgents"] = [{"id": "a", "name": "Alpha"}]
    monkeypatch.setattr(context, "manager_factory", lambda: transport)
    monkeypatch.setattr(
        context,
        "backend_factory",
        lambda: SimpleNamespace(
            unary=lambda service, method, payload: transport.rpc(method, payload),
        ),
    )
    for selector in ("a", "Alpha", "alpha"):
        assert cli.main(["bot", "hide", selector, "--yes", "--json"]) == 0
        assert json.loads(capsys.readouterr().out)["bot_id"] == "a"
    assert transport.calls[-1] == (
        "command",
        "setAgentHiddenFromSidebar",
        {"id": "a", "isHidden": True},
    )
