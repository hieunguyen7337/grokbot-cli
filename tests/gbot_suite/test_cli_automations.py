import io
import json

import pytest

from gbot import cli, context
from gbot.service import automations as a
from gbot.service.transport import FakeTransport
from groken.client import ConnectError


def setup_cli(monkeypatch):
    fake = FakeTransport(
        {**a.DEMO_COMMANDS, "listAgents": [{"id": "demo-helper", "name": "Helper"}]},
        a.DEMO_RPCS,
    )
    monkeypatch.setattr(context, "manager_factory", lambda: fake)

    class Backend:
        def unary(self, service, name, payload):
            return fake.rpc(name, payload)

    monkeypatch.setattr(context, "backend_factory", Backend)
    return fake


def test_agent_routines_list_toggle_and_unsupported(monkeypatch, capsys):
    fake = setup_cli(monkeypatch)
    routine = {
        "automationId": "routine-a",
        "routineId": "routine-r",
        "name": "Daily brief",
        "triggerDescription": "Daily",
        "schedule": "@daily",
        "isEnabled": True,
        "createdAtMs": "1800000000000",
        "runAsDisplayName": "Demo user",
    }
    fake.rpcs["ListGrokBotAgentRoutines"] = {
        "routines": [routine],
        "routinePolicy": {"futurePolicy": True},
    }
    assert (
        cli.main(
            ["automations", "Helper", "--routines", "--time-zone", "UTC", "--json"]
        )
        == 0
    )
    listed = json.loads(capsys.readouterr().out)
    assert listed["routines"][0]["automation_id"] == "routine-a"
    assert listed["routine_policy"] == {"futurePolicy": True}
    fake.rpcs["SetGrokBotAgentRoutineEnabled"] = {
        "routine": {**routine, "isEnabled": False}
    }
    assert (
        cli.main(
            [
                "automations",
                "Helper",
                "--routine-off",
                "routine-a",
                "--time-zone",
                "UTC",
                "--yes",
                "--json",
            ]
        )
        == 0
    )
    changed = json.loads(capsys.readouterr().out)
    assert changed["routine"]["is_enabled"] is False
    assert fake.calls[-1] == (
        "rpc",
        "SetGrokBotAgentRoutineEnabled",
        {
            "agentId": "demo-helper",
            "automationId": "routine-a",
            "isEnabled": False,
            "timeZone": "UTC",
        },
    )
    fake.rpcs["ListGrokBotAgentRoutines"] = ConnectError(404, '{"code":"not_found"}')
    assert cli.main(["automations", "Helper", "--routines", "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["supported"] is False


@pytest.mark.parametrize("argv", [[], ["Helper"], ["Helper", "--show", "demo-a"]])
@pytest.mark.parametrize("json_mode", [False, True])
def test_list_show(monkeypatch, capsys, argv, json_mode):
    setup_cli(monkeypatch)
    assert cli.main(["automations", *argv, *(["--json"] if json_mode else [])]) == 0
    output = capsys.readouterr().out
    assert "Morning briefing" in output
    if json_mode:
        assert json.loads(output)
    if "--show" in argv:
        assert "Summarize today's priorities." in output


MUTATIONS = [
    ["--new", "--name", "New", "--prompt", "Prompt", "--schedule", "@daily", "--off"],
    ["--edit", "demo-a", "--name", "Changed"],
    ["--on", "demo-a"],
    ["--off", "demo-a"],
    ["--delete", "demo-a"],
    ["--run", "demo-a", "--no-wait"],
    ["--run", "demo-a"],
]


@pytest.mark.parametrize("argv", MUTATIONS)
def test_requires_yes(monkeypatch, capsys, argv):
    fake = setup_cli(monkeypatch)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert cli.main(["automations", "Helper", *argv, "--json"]) == 1
    assert "--yes" in capsys.readouterr().err
    assert not fake.calls


@pytest.mark.parametrize("argv", MUTATIONS)
@pytest.mark.parametrize("json_mode", [False, True])
def test_mutations(monkeypatch, capsys, argv, json_mode):
    fake = setup_cli(monkeypatch)

    def start(args):
        fake.commands["getAgentAutomations"] = [
            {**a._DEMO, "runs": [{"id": "new", "status": "running", "startedAt": 9}]}
        ]

    fake.commands["runAgentAutomationNow"] = start
    assert (
        cli.main(
            [
                "automations",
                "Helper",
                *argv,
                "--yes",
                *(["--json"] if json_mode else []),
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    if json_mode:
        assert isinstance(json.loads(output), dict)
    if "--no-wait" in argv:
        assert "requested" in output
        assert sum(name == "getAgentAutomations" for _, name, _ in fake.calls) == 1
    elif "--run" in argv:
        assert "running" in output
    assert any(
        name
        in {
            "createAgentAutomation",
            "updateAgentAutomation",
            "setAgentAutomationEnabled",
            "deleteAgentAutomation",
            "runAgentAutomationNow",
        }
        for _, name, _ in fake.calls
    )


def test_stdin_and_confirmation(monkeypatch, capsys):
    fake = setup_cli(monkeypatch)
    monkeypatch.setattr("sys.stdin", io.StringIO("Read this\nexactly"))
    assert (
        cli.main(
            ["automations", "Helper", "--edit", "demo-a", "--prompt", "-", "--yes"]
        )
        == 0
    )
    capsys.readouterr()
    spec = fake.calls[-1][2]["spec"]
    assert isinstance(spec, dict)
    assert spec["prompt"] == "Read this\nexactly"
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "no")
    before = len(fake.calls)
    assert cli.main(["automations", "Helper", "--delete", "demo-a"]) == 1
    assert not any(
        name == "deleteAgentAutomation" for _, name, _ in fake.calls[before:]
    )


@pytest.mark.parametrize(
    "argv",
    [
        ["--off"],
        ["--new"],
        ["--name", "X"],
        ["--no-wait"],
        ["--on", "demo-a", "--off", "demo-a"],
    ],
)
def test_invalid_options(monkeypatch, capsys, argv):
    fake = setup_cli(monkeypatch)
    assert cli.main(["automations", "Helper", *argv, "--yes", "--json"]) == 1
    assert capsys.readouterr().err
    assert not fake.calls


@pytest.mark.parametrize(
    "argv",
    [
        ["--routine-on", ""],
        ["--routine-off", ""],
        ["--routine-on", "demo-routine", "--off", "other"],
        ["--routines", "--off", "other"],
        ["--routines", "--time-zone", ""],
        ["--routine-on", "demo-routine", "--time-zone", "Not a zone!"],
    ],
)
def test_bad_routine_arguments_send_nothing(monkeypatch, capsys, argv):
    fake = setup_cli(monkeypatch)
    assert cli.main(["automations", "Helper", *argv, "--yes", "--json"]) != 0
    assert "Routine" not in json.dumps(fake.calls)
    captured = capsys.readouterr()
    assert json.loads(captured.out or captured.err)["error"]["message"]
