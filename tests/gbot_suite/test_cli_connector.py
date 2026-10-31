import io
import json
from unittest.mock import Mock

import pytest

from gbot import cli, context
from gbot.handoff import run_handoff
from gbot.service import connectors as c
from gbot.service.handoff import HandoffResult
from gbot.service.transport import FakeTransport


def setup_cli(monkeypatch):
    fake = FakeTransport(
        c.DEMO_COMMANDS, {**c.DEMO_RPCS, "GetGrokBotUserRuntimeSettings": {}}
    )
    fake.commands["getMcpState"] = {
        "servers": [
            {
                "id": "s",
                "name": "Mail",
                "accountKey": "Personal",
                "status": "connected",
                "transport": "http",
                "command": "PRIVATE-COMMAND",
                "url": "PRIVATE-URL",
            }
        ]
    }
    monkeypatch.setattr(context, "manager_factory", lambda: fake)

    class Backend:
        def unary(self, service, name, payload):
            return fake.rpc(name, payload)

    monkeypatch.setattr(context, "backend_factory", Backend)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    return fake


@pytest.mark.parametrize("json_mode", [False, True])
def test_detail(monkeypatch, capsys, json_mode):
    setup_cli(monkeypatch)
    assert cli.main(["connector", "Mail", *(["--json"] if json_mode else [])]) == 0
    out = capsys.readouterr().out
    assert "PRIVATE" not in out
    if json_mode:
        data = json.loads(out)
        assert (
            data["account_key"] == "Personal" and data["tools"][0]["name"] == "search"
        )
    else:
        assert (
            "Account: Personal" in out
            and "search: read" in out
            and "Group chats" in out
        )


MUTATIONS = [
    (["--disable-tool", "search"], "toggleMcpToolDisabled"),
    (["--enable-tool", "search"], "listMcpServerTools"),
    (["--permission", "search=block"], "SetGrokBotMcpToolPermissions"),
    (["--reads", "allow"], "SetGrokBotMcpToolPermissions"),
    (["--writes", "ask"], "SetGrokBotMcpToolPermissions"),
    (["--instructions", "Text"], "setMcpCustomInstructions"),
    (["--rename-account", "Personal", "Work"], "renameMcpAccount"),
    (["--remove-account", "Personal"], "removeMcpAccount"),
    (["--remove"], "removeMcpServer"),
    (["--shared-spaces", "on"], "UpdateGrokBotConnectorSharedSpaceAllowlist"),
    (["--shared-spaces", "off"], "UpdateGrokBotConnectorSharedSpaceAllowlist"),
    (["--sign-in"], "authenticateMcpServer"),
]


@pytest.mark.parametrize("options,name", MUTATIONS)
def test_mutation_confirmation(monkeypatch, capsys, options, name):
    fake = setup_cli(monkeypatch)
    assert cli.main(["connector", "s", *options, "--json"]) == 1
    assert "--yes" in capsys.readouterr().err
    assert fake.calls == []
    assert cli.main(["connector", "s", *options, "--json", "--yes"]) == 0
    assert name in [call[1] for call in fake.calls]
    assert "PRIVATE" not in capsys.readouterr().out


def test_clear_and_stdin(monkeypatch, capsys):
    fake = setup_cli(monkeypatch)
    assert cli.main(["connector", "--clear-always-allow", "--json"]) == 1
    capsys.readouterr()
    assert not fake.calls
    assert cli.main(["connector", "--clear-always-allow", "--yes", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"cleared_count": 0}
    monkeypatch.setattr("sys.stdin", io.StringIO("  From stdin \n"))
    assert cli.main(["connector", "s", "--instructions", "-", "--yes"]) == 0
    assert (
        "command",
        "setMcpCustomInstructions",
        {"serverId": "s", "instructions": "From stdin"},
    ) in fake.calls


def test_handoff_url_stderr_only(monkeypatch, capsys):
    fake = setup_cli(monkeypatch)
    fake.commands["authenticateMcpServer"] = {
        "status": "started",
        "url": "https://private.test/sign-in",
    }
    opener = Mock()

    def handoff(url, check, **kwargs):
        return run_handoff(url, lambda: True, opener=opener, **kwargs)

    monkeypatch.setattr("gbot.commands.connector.run_handoff", handoff)
    assert (
        cli.main(["connector", "s", "--sign-in", "--no-browser", "--yes", "--json"])
        == 0
    )
    output = capsys.readouterr()
    assert "https://private.test/sign-in" in output.err
    assert "private.test" not in output.out
    opener.assert_not_called()
    monkeypatch.setattr(
        "gbot.commands.connector.run_handoff", lambda *a, **kw: HandoffResult("timeout")
    )
    assert cli.main(["connector", "s", "--sign-in", "--yes"]) == 0
    assert c.TIMEOUT in capsys.readouterr().out


def test_terminal_confirmation_cancel_and_accept(monkeypatch, capsys):
    fake = setup_cli(monkeypatch)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "no")
    argv = ["connector", "s", "--instructions", "Text", "--json"]
    assert cli.main(argv) == 1
    assert not any(name == "setMcpCustomInstructions" for _, name, _ in fake.calls)
    capsys.readouterr()
    monkeypatch.setattr("builtins.input", lambda _: "yes")
    assert cli.main(argv) == 0
    assert any(name == "setMcpCustomInstructions" for _, name, _ in fake.calls)
