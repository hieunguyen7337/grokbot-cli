import json
from unittest.mock import Mock

import pytest

from gbot import cli, context
from gbot.service import channels as c
from gbot.service.handoff import HandoffResult
from gbot.service.transport import FakeTransport


def setup(monkeypatch, tmp_path):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    fake = FakeTransport(
        {**c.DEMO_COMMANDS, "listAgents": [{"id": "b", "name": "Alpha"}]}, c.DEMO_RPCS
    )
    monkeypatch.setattr(context, "manager_factory", lambda: fake)

    class Backend:
        def unary(self, service, name, payload):
            return fake.rpc(name, payload)

    monkeypatch.setattr(context, "backend_factory", Backend)
    return fake


@pytest.mark.parametrize(
    "argv,key",
    [
        (["slack", "Alpha"], "status"),
        (["sms"], "available"),
        (["listeners"], "integrations"),
    ],
)
@pytest.mark.parametrize("json_mode", [False, True])
def test_reads(monkeypatch, tmp_path, capsys, argv, key, json_mode):
    setup(monkeypatch, tmp_path)
    assert cli.main(["channels", *argv, *(["--json"] if json_mode else [])]) == 0
    out = capsys.readouterr().out
    assert key in json.loads(out) if json_mode else out.strip()


@pytest.mark.parametrize(
    "argv",
    [
        ["slack", "Alpha", "--" + verb]
        for verb in ("connect", "install", "reinstall", "uninstall")
    ]
    + [
        ["sms", "--link"],
        ["sms", "--unlink", "h"],
        ["listeners", "--connect", "github"],
    ],
)
def test_yes_required(monkeypatch, tmp_path, capsys, argv):
    fake = setup(monkeypatch, tmp_path)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    assert cli.main(["channels", *argv]) == 1
    assert "--yes" in capsys.readouterr().err
    assert not fake.calls


@pytest.mark.parametrize("json_mode", [False, True])
def test_mutations(monkeypatch, tmp_path, capsys, json_mode):
    fake = setup(monkeypatch, tmp_path)
    for argv in (
        ["slack", "Alpha", "--connect"],
        ["slack", "Alpha", "--install", "--workspace", "team"],
        ["slack", "Alpha", "--reinstall"],
        ["slack", "Alpha", "--uninstall"],
        ["sms", "--link"],
        ["sms", "--unlink", "h"],
    ):
        assert (
            cli.main(["channels", *argv, "--yes", *(["--json"] if json_mode else [])])
            == 0
        )
        out = capsys.readouterr().out
        assert isinstance(json.loads(out), dict) if json_mode else out.strip()
    assert any(p.get("slackTeamId") == "team" for _, _, p in fake.calls)


@pytest.mark.parametrize("channel", ["slack", "listeners"])
def test_no_browser_and_wait(monkeypatch, tmp_path, capsys, channel):
    fake = setup(monkeypatch, tmp_path)
    opener = Mock()
    from gbot.handoff import run_handoff

    def handoff(url, check, **kwargs):
        if channel == "slack":
            fake.rpcs[c.RPCS[0]] = {"status": "connected"}
        else:
            fake.commands["getListenerIntegrations"] = {
                "integrations": [{"platform": "github", "isConnected": True}]
            }
        return run_handoff(url, check, opener=opener, **kwargs)

    monkeypatch.setattr("gbot.commands.channels.run_handoff", handoff)
    fake.rpcs[c.RPCS[1]] = {"outcome": "started", "url": "https://example.test/connect"}
    argv = (
        ["slack", "Alpha", "--connect"]
        if channel == "slack"
        else ["listeners", "--connect", "github"]
    )
    assert cli.main(["channels", *argv, "--yes", "--no-browser", "--json"]) == 0
    output = capsys.readouterr()
    assert "https://example.test/" in output.err
    assert "connected" in output.out
    opener.assert_not_called()
    monkeypatch.setattr(
        "gbot.commands.channels.run_handoff",
        lambda *a, **kw: HandoffResult("cancelled"),
    )
    assert cli.main(["channels", *argv, "--yes"]) == 130
    capsys.readouterr()
    if channel == "listeners":
        monkeypatch.setattr(
            "gbot.commands.channels.run_handoff",
            lambda *a, **kw: HandoffResult("timeout"),
        )
        assert cli.main(["channels", *argv, "--yes"]) == 0
        assert c.CALLBACK_HINT in capsys.readouterr().out
