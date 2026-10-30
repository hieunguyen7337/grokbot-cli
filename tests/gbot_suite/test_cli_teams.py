import json
from unittest.mock import Mock

import pytest

from gbot import cli, context
from gbot.commands import teams as command
from gbot.handoff import run_handoff
from gbot.service import teams
from gbot.service.handoff import HandoffResult
from gbot.service.transport import FakeTransport


def setup_cli(monkeypatch):
    fake = FakeTransport(
        {"listAgents": [{"id": "gateway", "name": "Alpha"}]}, {**teams.DEMO_RPCS}
    )
    fake.rpcs.update(
        {
            "GetGrokBotTeamsInstallState": {"state": 5, "consentResult": 2},
            "InstallGrokBotTeamsApp": {"state": 5},
            "ReinstallGrokBotTeamsApp": {"state": 5},
            "UninstallGrokBotTeamsApp": {"state": 8},
        }
    )
    monkeypatch.setattr(context, "manager_factory", lambda: fake)

    class Backend:
        def unary(self, service, name, payload):
            return fake.rpc(name, payload)

    monkeypatch.setattr(context, "backend_factory", Backend)
    return fake


MUTATIONS = [
    (["Alpha", "--connect"], "StartGrokBotTeamsConnect"),
    (["Alpha", "--connect", "--admin"], "StartGrokBotTeamsConnect"),
    (
        ["Alpha", "--install", "--team", "a", "b", "--no-personal"],
        "InstallGrokBotTeamsApp",
    ),
    (["Alpha", "--reinstall"], "ReinstallGrokBotTeamsApp"),
    (["Alpha", "--uninstall"], "UninstallGrokBotTeamsApp"),
    (["Alpha", "--add-to-team", "a"], "AddGrokBotTeamsAppToTeam"),
    (["Alpha", "--disconnect", "t"], "DisconnectGrokBotTeamsAccount"),
    (["--account", "--link-account"], "StartMicrosoftTeamsAccountLink"),
    (["--account", "--unlink-account", "t"], "UnlinkMicrosoftTeamsAccount"),
]


@pytest.mark.parametrize("argv,rpc", MUTATIONS)
def test_requires_yes(monkeypatch, capsys, argv, rpc):
    fake = setup_cli(monkeypatch)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    assert cli.main(["teams", *argv]) == 1
    assert "--yes" in capsys.readouterr().err
    assert not fake.calls


@pytest.mark.parametrize("json_mode", [False, True])
@pytest.mark.parametrize(
    "argv,rpc",
    [
        (["Alpha"], "GetGrokBotTeamsInstallState"),
        (["--account"], "GetMicrosoftTeamsAccountLinkStatus"),
        *MUTATIONS,
    ],
)
def test_options(monkeypatch, capsys, argv, rpc, json_mode):
    fake = setup_cli(monkeypatch)
    monkeypatch.setattr(
        command,
        "run_handoff",
        lambda url, check, **kw: HandoffResult("done", teams.TeamsState("connected")),
    )
    assert cli.main(["teams", *argv, "--yes", *(["--json"] if json_mode else [])]) == 0
    output = capsys.readouterr().out
    if json_mode:
        json.loads(output)
    else:
        assert output.strip()
    assert any(name == rpc for _, name, _ in fake.calls)


@pytest.mark.parametrize("admin", [False, True])
@pytest.mark.parametrize("no_browser", [False, True])
def test_connect_handoff(monkeypatch, capsys, admin, no_browser):
    fake = setup_cli(monkeypatch)
    fake.rpcs["GetGrokBotTeamsInstallState"] = {
        "state": 2,
        "connectedAccount": {"tenantId": "tenant"},
    }
    opener = Mock()

    def handoff(url, check, **kwargs):
        return run_handoff(url, check, opener=opener, **kwargs)

    monkeypatch.setattr(command, "run_handoff", handoff)
    argv = ["teams", "Alpha", "--connect", "--yes"]
    assert (
        cli.main(
            [
                *argv,
                *(["--admin"] if admin else []),
                *(["--no-browser"] if no_browser else []),
            ]
        )
        == 0
    )
    expected = (
        "https://example.invalid/teams-admin"
        if admin
        else "https://example.invalid/teams"
    )
    output = capsys.readouterr()
    assert expected in output.err
    assert "--install --yes" in output.out
    assert opener.call_args == (None if no_browser else ((expected,), {}))
    assert fake.calls[-1][2]["consentNonce"] == "demo"


@pytest.mark.parametrize("status,code", [("cancelled", 130), ("timeout", 1)])
def test_cancel(monkeypatch, capsys, status, code):
    fake = setup_cli(monkeypatch)
    monkeypatch.setattr(command, "run_handoff", lambda *a, **kw: HandoffResult(status))
    assert cli.main(["teams", "Alpha", "--connect", "--yes", "--json"]) == code
    assert json.loads(capsys.readouterr().out)["status"] == status
    assert not any(name == "InstallGrokBotTeamsApp" for _, name, _ in fake.calls)


def test_account_handoff_new_tuple(monkeypatch, capsys):
    fake = setup_cli(monkeypatch)
    old = {"tenantId": "tenant", "aadObjectId": "aad", "linkedAtMs": "1"}
    fake.rpcs["GetMicrosoftTeamsAccountLinkStatus"] = {"links": [old]}
    opener = Mock()

    def handoff(url, check, **kwargs):
        assert check() is None
        fake.rpcs["GetMicrosoftTeamsAccountLinkStatus"] = {
            "links": [dict(old, linkedAtMs="2")]
        }
        return run_handoff(url, check, opener=opener, **kwargs)

    monkeypatch.setattr(command, "run_handoff", handoff)
    assert cli.main(["teams", "--link-account", "--yes", "--json"]) == 0
    result = capsys.readouterr()
    assert json.loads(result.out)[0]["linked_at_ms"] == 2
    assert "https://example.invalid/teams-account" in result.err
    opener.assert_called_once_with("https://example.invalid/teams-account")
