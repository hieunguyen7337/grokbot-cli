import json

import pytest

from gbot import cli, context
from gbot.service import publishing
from gbot.service.transport import FakeTransport
from groken.client import ConnectError

TEMPLATE = {
    "shareId": "share",
    "name": "Helper Template",
    "published": True,
    "activeVersion": 2,
    "visibility": "GROK_BOT_TEMPLATE_TEAM",
}


def setup_cli(monkeypatch, policy="all", **rpcs):
    fake = FakeTransport(
        {"listAgents": [{"id": "gateway", "name": "Alpha", "harness": "temporal"}]},
        {
            **publishing.DEMO_RPCS,
            "GetGrokBotTemplateForSourceAgent": {"template": TEMPLATE},
            "GetGrokBotTemplateExportPolicy": {"exportPolicy": policy},
            **rpcs,
        },
    )
    monkeypatch.setattr(context, "manager_factory", lambda: fake)

    class Backend:
        def unary(self, service, name, payload):
            return fake.rpc(name, payload)

    monkeypatch.setattr(context, "backend_factory", Backend)
    return fake


def sent(fake):
    return [(n, a) for _, n, a in fake.calls if n in publishing.RPCS]


def test_read_text_and_json(monkeypatch, capsys):
    setup_cli(monkeypatch)
    assert cli.main(["publish", "Alpha"]) == 0
    text = capsys.readouterr().out
    assert "Marketplace: unknown" in text
    assert "Template: Helper Template" in text and "Share ID: share" in text
    assert "Active version: 2" in text and "Visibility: team" in text
    assert publishing.policy_sentence("all") in text
    assert cli.main(["publish", "Alpha", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["template"]["share_id"] == "share"
    assert data["export_policy"] == "all"


def test_read_without_template(monkeypatch, capsys):
    setup_cli(monkeypatch, policy="none", GetGrokBotTemplateForSourceAgent={})
    assert cli.main(["publish", "Alpha"]) == 0
    out = capsys.readouterr().out
    assert "Template: none" in out and publishing.policy_sentence("none") in out


CHANGES = [
    (["--listing", "on"], "PublishGrokBotAgent", {"agentId": "gateway"}),
    (["--listing", "off"], "UnpublishGrokBotAgent", {"agentId": "gateway"}),
    (
        ["--template-version", "4"],
        "ActivateGrokBotTemplateVersion",
        {"shareId": "share", "version": 4},
    ),
    (
        ["--template-visibility", "team"],
        "SetGrokBotTemplateVisibility",
        {"shareId": "share", "visibility": "GROK_BOT_TEMPLATE_VISIBILITY_TEAM"},
    ),
    (["--delete-template"], "DeleteGrokBotTemplate", {"shareId": "share"}),
    (
        ["--delete-template", "--share-id", "other"],
        "DeleteGrokBotTemplate",
        {"shareId": "other"},
    ),
]


@pytest.mark.parametrize("argv,rpc,payload", CHANGES)
def test_no_yes_sends_nothing(monkeypatch, capsys, argv, rpc, payload):
    fake = setup_cli(monkeypatch)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert cli.main(["publish", "Alpha", *argv]) == 1
    assert "--yes" in capsys.readouterr().err
    assert not sent(fake)


@pytest.mark.parametrize("json_mode", [False, True])
@pytest.mark.parametrize("argv,rpc,payload", CHANGES)
def test_changes_with_yes(monkeypatch, capsys, argv, rpc, payload, json_mode):
    fake = setup_cli(monkeypatch)
    extra = ["--json"] if json_mode else []
    assert cli.main(["publish", "Alpha", *argv, "--yes", *extra]) == 0
    out = capsys.readouterr().out
    assert out.strip()
    if json_mode:
        json.loads(out)
    assert sent(fake) == [(rpc, payload)]


def test_template_version_payload_omits_nothing_extra(monkeypatch, capsys):
    fake = setup_cli(monkeypatch)
    assert cli.main(["publish", "Alpha", "--template-version", "7", "--yes"]) == 0
    assert "Published version 7" in capsys.readouterr().out
    assert sent(fake)[0][1] == {"shareId": "share", "version": 7}


def test_outcome_sentence_is_printed(monkeypatch, capsys):
    setup_cli(monkeypatch, PublishGrokBotAgent={"outcome": "NOT_SHARED"})
    assert cli.main(["publish", "Alpha", "--listing", "on", "--yes"]) == 0
    assert "Share the bot first" in capsys.readouterr().out


def test_delete_in_terminal_needs_typed_name(monkeypatch, capsys):
    fake = setup_cli(monkeypatch)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": "wrong")
    assert cli.main(["publish", "Alpha", "--delete-template"]) == 1
    assert not sent(fake)
    monkeypatch.setattr("builtins.input", lambda prompt="": "Helper Template")
    assert cli.main(["publish", "Alpha", "--delete-template"]) == 0
    assert sent(fake) == [("DeleteGrokBotTemplate", {"shareId": "share"})]
    assert "Template deleted." in capsys.readouterr().out


def test_policy_gates(monkeypatch, capsys):
    fake = setup_cli(monkeypatch, policy="none")
    assert cli.main(["publish", "Alpha", "--template-version", "1", "--yes"]) == 1
    assert "turned off" in capsys.readouterr().err
    fake = setup_cli(monkeypatch, policy="team_only")
    assert (
        cli.main(["publish", "Alpha", "--template-visibility", "public", "--yes"]) == 1
    )
    assert "team only" in capsys.readouterr().err
    assert not sent(fake)


def test_no_template_to_change(monkeypatch, capsys):
    setup_cli(monkeypatch, GetGrokBotTemplateForSourceAgent={})
    assert cli.main(["publish", "Alpha", "--template-version", "1", "--yes"]) == 1
    assert "no template" in capsys.readouterr().err


def test_refusal_exits_1_with_server_message(monkeypatch, capsys):
    setup_cli(
        monkeypatch,
        PublishGrokBotAgent=ConnectError(
            403, '{"code": "failed_precondition", "message": "Sharing is disabled."}'
        ),
    )
    assert cli.main(["publish", "Alpha", "--listing", "on", "--yes", "--json"]) == 1
    err = json.loads(capsys.readouterr().err)
    assert err["error"]["message"] == "Sharing is disabled."


def test_bad_flag_combinations(monkeypatch, capsys):
    fake = setup_cli(monkeypatch)
    for argv in (
        ["--share-id", "x"],
        ["--template-version", "0", "--yes"],
        ["--delete-template", "--template-version", "1", "--yes"],
    ):
        assert cli.main(["publish", "Alpha", *argv]) == 1
    assert not sent(fake)
