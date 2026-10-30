import getpass
import io
import json
import warnings

import pytest

from gbot import cli, context
from gbot.service import secrets
from gbot.service.transport import FakeTransport


def setup_cli(monkeypatch, tmp_path):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    fake = FakeTransport(
        {**secrets.DEMO_COMMANDS, "listAgents": [{"id": "bot", "name": "Alpha"}]},
        {
            **secrets.DEMO_RPCS,
            "ListGrokBotAgents": {"agents": [{"agentId": "bot", "id": "backend"}]},
        },
    )
    monkeypatch.setattr(context, "manager_factory", lambda: fake)

    class Backend:
        def unary(self, service, name, payload):
            return fake.rpc(name, payload)

    monkeypatch.setattr(context, "backend_factory", Backend)
    return fake


@pytest.mark.parametrize("json_mode", [False, True])
def test_reads(monkeypatch, tmp_path, capsys, json_mode):
    setup_cli(monkeypatch, tmp_path)
    suffix = ["--json"] if json_mode else []
    assert cli.main(["secrets", "Alpha", *suffix]) == 0
    output = capsys.readouterr().out
    assert "DEMO_TOKEN" in output and "Demo integration" in output
    if json_mode:
        assert json.loads(output)[0]["updated_at_ms"] == 1800000000000
    assert cli.main(["secrets", "--computer", *suffix]) == 0
    assert "DEMO_KEY" in capsys.readouterr().out


@pytest.mark.parametrize("tty", [False, True])
def test_set(monkeypatch, tmp_path, capsys, tty):
    fake = setup_cli(monkeypatch, tmp_path)
    value = "private-test-value"
    stream = io.StringIO(value + "\nsecond-line\n")
    monkeypatch.setattr(stream, "isatty", lambda: tty)
    monkeypatch.setattr("sys.stdin", stream)
    prompts = []
    monkeypatch.setattr(
        getpass, "getpass", lambda prompt: prompts.append(prompt) or value
    )
    assert (
        cli.main(
            [
                "secrets",
                "Alpha",
                "--set",
                "token",
                "--description",
                "test",
                "--yes",
                "--json",
            ]
        )
        == 0
    )
    assert prompts == (["Value for TOKEN (hidden): "] if tty else [])
    assert fake.calls[-1][2]["value"] == value
    output = capsys.readouterr()
    assert value not in output.out + output.err
    if not tty:
        assert stream.readline() == "second-line\n"


def test_confirmation_delete_copy_and_errors(monkeypatch, tmp_path, capsys):
    fake = setup_cli(monkeypatch, tmp_path)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    for action in (
        ["--set", "TOKEN"],
        ["--delete", "TOKEN"],
        ["--copy-from-computer", "TOKEN"],
    ):
        assert cli.main(["secrets", "Alpha", *action]) == 1
        assert "--yes" in capsys.readouterr().err
        assert not fake.calls
    assert cli.main(["secrets", "Alpha", "--delete", "token", "--yes"]) == 0
    assert fake.calls[-1][1] == "DeleteGrokBotSecret"
    assert (
        cli.main(["secrets", "Alpha", "--copy-from-computer", "TOKEN", "KEY", "--yes"])
        == 0
    )
    assert "TOKEN: copied" in capsys.readouterr().out

    def warning(prompt):
        warnings.warn("echo unsafe", getpass.GetPassWarning)
        return "private-test-value"

    monkeypatch.setattr(getpass, "getpass", warning)
    assert cli.main(["secrets", "Alpha", "--set", "TOKEN", "--yes"]) == 1
    assert not any(call[1] == "PutGrokBotSecret" for call in fake.calls)
    monkeypatch.setattr(getpass, "getpass", lambda _: "private-test-value")
    fake.rpcs["PutGrokBotSecret"] = RuntimeError("private-test-value")
    assert cli.main(["secrets", "Alpha", "--set", "TOKEN", "--yes", "--json"]) == 1
    output = capsys.readouterr()
    assert "private-test-value" not in output.out + output.err
