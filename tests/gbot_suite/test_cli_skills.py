import io
import json

import pytest

from gbot import cli, context
from gbot.service import workflows as w
from gbot.service.models import _record
from gbot.service.transport import FakeTransport


def setup_cli(monkeypatch):
    transport = FakeTransport(
        {
            **w.DEMO_COMMANDS,
            "listAgents": [{"id": "bot", "name": "Alpha", "harness": "temporal"}],
        },
        w.DEMO_RPCS,
    )
    monkeypatch.setattr(context, "manager_factory", lambda: transport)

    class Backend:
        def unary(self, service, name, payload):
            return transport.rpc(name, payload)

    monkeypatch.setattr(context, "backend_factory", Backend)
    return transport


@pytest.mark.parametrize("json_mode", [False, True])
def test_list_show_catalog(monkeypatch, capsys, json_mode):
    setup_cli(monkeypatch)
    suffix = ["--json"] if json_mode else []
    assert cli.main(["skills", "Alpha", *suffix]) == 0
    out = capsys.readouterr().out
    assert "Research" not in out and "Morning brief" in out
    assert cli.main(["skills", "Alpha", "--all", *suffix]) == 0
    assert "Research" in capsys.readouterr().out
    assert cli.main(["skills", "Alpha", "--show", "meeting notes", *suffix]) == 0
    assert "Collect decisions and next steps." in capsys.readouterr().out
    assert cli.main(["skills", "--catalog", "--search", "weekly", *suffix]) == 0
    assert "Weekly review" in capsys.readouterr().out
    assert cli.main(["skills", "--catalog", "--search", "missing", *suffix]) == 0
    assert "Weekly review" not in capsys.readouterr().out


MUTATIONS = [
    [
        "--new",
        "--name",
        "New",
        "--description",
        "Description",
        "--body",
        "-",
        "--schedule",
        "daily",
    ],
    ["--edit", "demo-notes", "--name", "Changed"],
    ["--edit", "demo-brief", "--pause"],
    ["--edit", "demo-brief", "--resume"],
    ["--edit", "demo-brief", "--unschedule"],
    ["--delete", "demo-notes"],
    ["--run", "demo-brief"],
    ["--import-url", "https://example.test/skill", "--name", "Imported"],
    ["--install", "demo-catalog"],
]


@pytest.mark.parametrize("argv", MUTATIONS)
@pytest.mark.parametrize("json_mode", [False, True])
def test_mutations(monkeypatch, capsys, argv, json_mode):
    transport = setup_cli(monkeypatch)
    monkeypatch.setattr("sys.stdin", io.StringIO("# Body from stdin"))
    suffix = ["--json"] if json_mode else []
    assert cli.main(["skills", "Alpha", *argv, "--yes", *suffix]) == 0
    out = capsys.readouterr().out
    if json_mode:
        assert isinstance(json.loads(out), (dict, list))
    else:
        assert out
    commands = [name for _, name, _ in transport.calls]
    assert any(
        name in commands
        for name in (
            "createAgentWorkflow",
            "updateAgentWorkflow",
            "deleteAgentWorkflow",
            "runAgentWorkflowNow",
            "importAgentWorkflowText",
            "importAgentWorkflowUrl",
        )
    )
    if "--new" in argv:
        assert _record(transport.calls[-1][2]["spec"])["body"] == "# Body from stdin"


@pytest.mark.parametrize("argv", [*MUTATIONS, ["--import-file", "not-read.md"]])
def test_requires_yes(monkeypatch, capsys, argv):
    transport = setup_cli(monkeypatch)
    monkeypatch.setattr("sys.stdin", io.StringIO())
    assert cli.main(["skills", "Alpha", *argv, "--json"]) == 1
    assert "--yes" in capsys.readouterr().err
    assert not transport.calls


@pytest.mark.parametrize("json_mode", [False, True])
def test_file_and_terminal_confirmation(monkeypatch, capsys, tmp_path, json_mode):
    transport = setup_cli(monkeypatch)
    path = tmp_path / "skill.md"
    path.write_text("# Local body", encoding="utf-8")
    suffix = ["--json"] if json_mode else []
    assert (
        cli.main(["skills", "Alpha", "--import-file", str(path), "--yes", *suffix]) == 0
    )
    capsys.readouterr()
    assert transport.calls[-1][2]["markdown"] == "# Local body"
    transport.calls.clear()
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "no")
    assert cli.main(["skills", "Alpha", "--delete", "demo-notes", *suffix]) == 1
    capsys.readouterr()
    assert not transport.calls
    monkeypatch.setattr("builtins.input", lambda _: "yes")
    assert cli.main(["skills", "Alpha", "--delete", "demo-notes", *suffix]) == 0
    capsys.readouterr()
    assert transport.calls[-1][1] == "deleteAgentWorkflow"


def test_mutation_output_hides_managed_skills(monkeypatch, capsys):
    setup_cli(monkeypatch)
    argv = ["skills", "Alpha", "--edit", "demo-notes", "--name", "Changed", "--yes"]
    assert cli.main(argv) == 0
    out = capsys.readouterr().out
    assert "Meeting notes" in out and "Research" not in out


def test_edit_without_changes_sends_nothing(monkeypatch, capsys):
    transport = setup_cli(monkeypatch)
    assert cli.main(["skills", "Alpha", "--edit", "demo-notes", "--yes"]) != 0
    assert "Nothing to change" in capsys.readouterr().err
    assert transport.calls == []
