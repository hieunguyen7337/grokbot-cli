import getpass
import io
import json
import warnings

import pytest

from gbot import cli, context
from gbot.service import plugins
from gbot.service.transport import FakeTransport


def setup_cli(monkeypatch, tmp_path):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    transport = FakeTransport(
        {**plugins.DEMO_COMMANDS, "listAgents": [{"id": "bot", "name": "Alpha"}]},
        plugins.DEMO_RPCS,
    )
    monkeypatch.setattr(context, "manager_factory", lambda: transport)

    class Backend:
        def unary(self, service, name, payload):
            return transport.rpc(name, payload)

    monkeypatch.setattr(context, "backend_factory", Backend)
    return transport


@pytest.mark.parametrize("json_mode", [False, True])
def test_reads(monkeypatch, tmp_path, capsys, json_mode):
    setup_cli(monkeypatch, tmp_path)
    suffix = ["--json"] if json_mode else []
    for command in (["catalog"], ["catalog", "show", "notes"], ["plugins", "Alpha"]):
        assert cli.main([*command, *suffix]) == 0
        output = capsys.readouterr().out
        assert "Notes" in output
        if json_mode:
            json.loads(output)
    assert cli.main(["catalog", "--category", "utilities", "--search", "weather"]) == 0
    output = capsys.readouterr().out
    assert "Weather" in output and "Notes" not in output


@pytest.mark.parametrize("tty", [False, True])
def test_hidden_value(monkeypatch, tmp_path, capsys, tty):
    transport = setup_cli(monkeypatch, tmp_path)
    stream = io.StringIO("private-test\nsecond\n")
    monkeypatch.setattr(stream, "isatty", lambda: tty)
    monkeypatch.setattr("sys.stdin", stream)
    prompts = []
    monkeypatch.setattr(
        getpass, "getpass", lambda prompt: prompts.append(prompt) or "private-test"
    )
    command = ["plugins", "Alpha", "--set-var", "Notes", "api_token", "--yes"]
    assert cli.main(command) == 0
    assert prompts == (["Value for api_token (hidden): "] if tty else [])
    assert transport.calls[-1][2]["variables"] == {"api_token": "private-test"}
    output = capsys.readouterr()
    assert "private-test" not in output.out + output.err
    if not tty:
        assert stream.readline() == "second\n"
    transport.rpcs["SetGrokBotAgentPluginVariables"] = RuntimeError("private-test")
    stream.seek(0)
    assert cli.main(command) == 1
    output = capsys.readouterr()
    assert "private-test" not in output.out + output.err


def test_confirmation_and_mutations(monkeypatch, tmp_path, capsys):
    transport = setup_cli(monkeypatch, tmp_path)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    for args in (
        ["--add", "weather"],
        ["--remove", "Notes"],
        ["--set-var", "Notes", "token"],
    ):
        assert cli.main(["plugins", "Alpha", *args]) == 1
        assert not transport.calls
    capsys.readouterr()
    assert cli.main(["plugins", "Alpha", "--remove", "Notes", "--yes"]) == 0
    assert transport.calls[-1][2]["plugins"] == []
    transport.rpcs["GetGrokBotAgentPlugins"] = {}
    assert cli.main(["plugins", "Alpha", "--add", "Notes", "--yes"]) == 0
    assert "Fill in its settings" in capsys.readouterr().out
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "n")
    transport.calls.clear()
    assert cli.main(["plugins", "Alpha", "--add", "Notes"]) == 1
    assert not transport.calls
    monkeypatch.setattr("builtins.input", lambda _: "y")
    transport.rpcs["GetGrokBotAgentPlugins"] = plugins.DEMO_RPCS[
        "GetGrokBotAgentPlugins"
    ]

    def warning(prompt):
        warnings.warn("unsafe", getpass.GetPassWarning)
        return "private-test"

    monkeypatch.setattr(getpass, "getpass", warning)
    assert cli.main(["plugins", "Alpha", "--set-var", "Notes", "token", "--yes"]) == 1
    assert "cannot hide input" in capsys.readouterr().err
