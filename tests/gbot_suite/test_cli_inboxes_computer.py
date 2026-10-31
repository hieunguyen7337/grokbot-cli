import json

import pytest

from gbot import cli, context
from gbot.service import computer, inboxes
from gbot.service.transport import FakeTransport

URL = "https://viewer.invalid/?token=private"


def setup_cli(monkeypatch):
    fake = FakeTransport(
        {
            **computer.DEMO_COMMANDS,
            "listAgents": [{"id": "bot", "name": "Alpha", "harness": "box"}],
        },
        {**computer.DEMO_RPCS, **inboxes.DEMO_RPCS},
    )
    fake.commands["getForeverBoxStatus"] = {
        **computer._DEMO,
        "vncUrl": URL,
        "windows": [{"vncUrl": URL}],
    }
    monkeypatch.setattr(context, "manager_factory", lambda: fake)

    class Backend:
        def unary(self, service, name, payload):
            return fake.rpc(name, payload)

    monkeypatch.setattr(context, "backend_factory", Backend)
    return fake


@pytest.mark.parametrize("json_mode", [False, True])
def test_reads(monkeypatch, capsys, json_mode):
    setup_cli(monkeypatch)
    for argv in (["inboxes"], ["computer", "Alpha"]):
        assert cli.main([*argv, *(["--json"] if json_mode else [])]) == 0
        output = capsys.readouterr().out
        assert URL not in output
        if json_mode:
            assert json.loads(output)
        else:
            assert "helper@mail.grokbot.com" in output or "State: running" in output


@pytest.mark.parametrize(
    "argv",
    [
        ["inboxes", "--create", "Alpha"],
        *[
            ["computer", "Alpha", flag]
            for flag in ("--wake", "--update", "--hand-back")
        ],
    ],
)
def test_requires_yes(monkeypatch, capsys, argv):
    fake = setup_cli(monkeypatch)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert cli.main([*argv, "--json"]) == 1
    assert "--yes" in capsys.readouterr().err
    assert not fake.calls


@pytest.mark.parametrize("json_mode", [False, True])
def test_mutations_and_open(monkeypatch, capsys, json_mode):
    fake = setup_cli(monkeypatch)
    opened = []
    monkeypatch.setattr("webbrowser.open", opened.append)
    for argv, name in [
        (["inboxes", "--create", " ALPHA "], "CreateGrokBotEmailInbox"),
        (["computer", "Alpha", "--wake"], "ensureForeverBox"),
        (["computer", "Alpha", "--update"], "updateForeverBox"),
        (["computer", "Alpha", "--hand-back"], "handBackForeverBox"),
        (["computer", "Alpha", "--open"], "getForeverBoxStatus"),
    ]:
        assert cli.main([*argv, "--yes", *(["--json"] if json_mode else [])]) == 0
        output = capsys.readouterr().out
        assert URL not in output
        assert any(call[1] == name for call in fake.calls)
        if json_mode:
            assert json.loads(output)
        elif "--open" in argv:
            assert "Opened the live view." in output
    assert opened == [URL]


def test_missing_handoff_or_view(monkeypatch, capsys):
    fake = setup_cli(monkeypatch)
    fake.commands["getForeverBoxStatus"] = None
    for flag, message in [
        ("--hand-back", "Nothing to hand back"),
        ("--open", "No live view"),
    ]:
        assert cli.main(["computer", "Alpha", flag, "--yes"]) == 1
        assert message in capsys.readouterr().err
    assert not any(call[1] == "handBackForeverBox" for call in fake.calls)
