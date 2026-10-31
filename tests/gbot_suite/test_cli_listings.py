import json

import pytest

from gbot import cli, context
from gbot.service import listings, plugins
from gbot.service import workflows as w
from gbot.service.transport import FakeTransport
from groken.client import ConnectError

TEMPORAL = '{"error":"publishSkill is not supported for Temporal agents"}'
CHANGES = [
    (["publish-skill", "Alpha", "Meeting notes"], "publishSkill"),
    (["publish-skill", "Alpha", "demo-notes", "--team", "t1"], "publishSkill"),
    (["resync-skill", "Alpha", "demo-notes"], "resyncPublishedSkill"),
    (["unpublish-skill", "Alpha", "demo-notes"], "unpublishSkill"),
    (["unpublish-plugin", "Alpha", "Notes"], "unpublishPluginListing"),
    (["unpublish-plugin", "Alpha", "12", "--team", "t1"], "unpublishPluginListing"),
]


def setup_cli(monkeypatch, tmp_path):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    fake = FakeTransport(
        {
            **w.DEMO_COMMANDS,
            **plugins.DEMO_COMMANDS,
            **listings.DEMO_COMMANDS,
            "listAgents": [{"id": "bot", "name": "Alpha"}],
        },
        {**w.DEMO_RPCS, **plugins.DEMO_RPCS},
    )
    monkeypatch.setattr(context, "manager_factory", lambda: fake)

    class Backend:
        def unary(self, service, name, payload):
            return fake.rpc(name, payload)

    monkeypatch.setattr(context, "backend_factory", Backend)
    return fake


def sent(fake, name):
    return [args for kind, call, args in fake.calls if call == name]


@pytest.mark.parametrize("json_mode", [False, True])
def test_targets(monkeypatch, tmp_path, capsys, json_mode):
    fake = setup_cli(monkeypatch, tmp_path)
    assert cli.main(["listings", "targets", *(["--json"] if json_mode else [])]) == 0
    output = capsys.readouterr().out
    assert "demo-team" in output and "Demo team" in output
    if json_mode:
        assert json.loads(output)["teams"] == [
            {"team_id": "demo-team", "name": "Demo team"}
        ]
    fake.commands["getSkillPublishTargets"] = {
        "teams": [],
        "unavailableReason": "Join a team to publish skills.",
        "unavailableReasonKind": "no_team",
    }
    assert cli.main(["listings", "targets", *(["--json"] if json_mode else [])]) == 0
    output = capsys.readouterr().out
    assert "Join a team to publish skills." in output
    if json_mode:
        assert json.loads(output)["unavailable_kind"] == "no_team"


@pytest.mark.parametrize("restorable", [True, False])
@pytest.mark.parametrize("json_mode", [False, True])
def test_plugin_read(monkeypatch, tmp_path, capsys, restorable, json_mode):
    fake = setup_cli(monkeypatch, tmp_path)
    fake.commands["hasRestorablePluginListingCopy"] = restorable
    argv = ["listings", "plugin", "Alpha", "notes", *(["--json"] if json_mode else [])]
    assert cli.main(argv) == 0
    output = capsys.readouterr().out
    if json_mode:
        assert json.loads(output)["restorable_copy"] is restorable
    else:
        assert ("a private copy stays" in output) is restorable
    assert sent(fake, "hasRestorablePluginListingCopy") == [{"pluginId": "12"}]
    assert not sent(fake, "unpublishPluginListing")


@pytest.mark.parametrize("argv,name", CHANGES)
def test_changes_need_yes(monkeypatch, tmp_path, capsys, argv, name):
    fake = setup_cli(monkeypatch, tmp_path)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert cli.main(["listings", *argv]) == 1
    assert "--yes" in capsys.readouterr().err
    assert not fake.calls


@pytest.mark.parametrize("json_mode", [False, True])
@pytest.mark.parametrize("argv,name", CHANGES)
def test_changes_send_exact_payloads(
    monkeypatch, tmp_path, capsys, argv, name, json_mode
):
    fake = setup_cli(monkeypatch, tmp_path)
    suffix = ["--json"] if json_mode else []
    assert cli.main(["listings", *argv, "--yes", *suffix]) == 0
    output = capsys.readouterr().out
    if json_mode:
        assert json.loads(output)["ok"] is True
    else:
        assert output.strip()
    team = {"teamId": "t1"} if "--team" in argv else {}
    key = "pluginId" if "plugin" in argv[0] else "workflowId"
    value = "12" if key == "pluginId" else "demo-notes"
    assert sent(fake, name) == [{key: value, **team}]


def test_unknown_names_send_nothing(monkeypatch, tmp_path, capsys):
    fake = setup_cli(monkeypatch, tmp_path)
    assert cli.main(["listings", "publish-skill", "Alpha", "nope", "--yes"]) == 1
    assert "Unknown or ambiguous skill" in capsys.readouterr().err
    assert cli.main(["listings", "unpublish-plugin", "Alpha", "nope", "--yes"]) == 1
    assert "Choose a plugin" in capsys.readouterr().err
    assert not sent(fake, "publishSkill") and not sent(fake, "unpublishPluginListing")


@pytest.mark.parametrize("argv,name", CHANGES)
def test_refusal_exits_1_with_the_message(monkeypatch, tmp_path, capsys, argv, name):
    fake = setup_cli(monkeypatch, tmp_path)
    fake.commands[name] = ConnectError(400, TEMPORAL)
    assert cli.main(["listings", *argv, "--yes"]) == 1
    error = capsys.readouterr().err
    assert "not supported for Temporal agents" in error
    assert "Traceback" not in error


def test_refusal_message_in_json(monkeypatch, tmp_path, capsys):
    fake = setup_cli(monkeypatch, tmp_path)
    fake.commands["getSkillPublishTargets"] = ConnectError(
        403, '{"code":"permission_denied","message":"Teams only."}'
    )
    assert cli.main(["listings", "targets", "--json"]) == 1
    error = json.loads(capsys.readouterr().err)["error"]
    assert error["message"] == "Teams only." and error["exit_code"] == 1


def test_not_ok_reply_exits_1(monkeypatch, tmp_path, capsys):
    fake = setup_cli(monkeypatch, tmp_path)
    fake.commands["publishSkill"] = {"error": "Skill has no description."}
    assert cli.main(["listings", "publish-skill", "Alpha", "demo-notes", "--yes"]) == 1
    assert "Skill has no description." in capsys.readouterr().err


def test_odd_reply_is_a_plain_success(monkeypatch, tmp_path, capsys):
    fake = setup_cli(monkeypatch, tmp_path)
    fake.commands["resyncPublishedSkill"] = None
    assert cli.main(["listings", "resync-skill", "Alpha", "demo-notes", "--yes"]) == 0
    assert "Resynced Meeting notes" in capsys.readouterr().out


def test_interactive_cancel_sends_nothing(monkeypatch, tmp_path, capsys):
    fake = setup_cli(monkeypatch, tmp_path)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    assert cli.main(["listings", "unpublish-skill", "Alpha", "demo-notes"]) == 1
    assert "Cancelled" in capsys.readouterr().err
    assert not sent(fake, "unpublishSkill")
