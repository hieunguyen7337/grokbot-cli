import io
import json

import pytest

from gbot import cli, context
from gbot.service import cloud_agents
from gbot.service.transport import FakeTransport
from groken.client import ConnectError

SECRET = "sk-test-value-5f1e"
REFUSED = ConnectError(
    403,
    json.dumps({"code": "permission_denied", "message": "Apps are off for you."}),
)


def setup_cli(monkeypatch):
    fake = FakeTransport(
        {
            "listAgents": [{"id": "gateway", "name": "Alpha"}],
            **cloud_agents.DEMO_COMMANDS,
            "getCloudAgentAppSecrets": {
                "secrets": [{"name": "API_KEY", "value": SECRET}]
            },
        }
    )
    monkeypatch.setattr(context, "manager_factory", lambda: fake)

    class Backend:
        def unary(self, service, name, payload):
            return fake.rpc(name, payload)

    monkeypatch.setattr(context, "backend_factory", Backend)
    return fake


def sent(fake, name):
    return [args for kind, called, args in fake.calls if called == name]


MUTATIONS = [
    (
        ["apps", "--update", "bc", "--slug", "s", "--apex", "a", "--visibility", "team"],
        "updateCloudAgentPublishApp",
    ),
    (["apps", "--unpublish", "bc", "--slug", "s", "--apex", "a"], "unpublishCloudAgentPublishApp"),
    (["cloud-agent", "bc", "--stop"], "stopCloudAgent"),
    (
        ["cloud-agent", "bc", "--confirm-proposal", "p", "--bot", "Alpha", "--slug", "s", "--visibility", "public"],
        "confirmCloudAgentPublishProposal",
    ),
    (["cloud-agent", "bc", "--dismiss-proposal", "p"], "dismissCloudAgentPublishProposal"),
    (["cloud-agent", "bc", "--set-secret", "API_KEY", "--project-dir", "/app"], "setCloudAgentAppSecrets"),
]  # fmt: skip
READS = [
    (["apps"], "listCloudAgentPublishedApps"),
    (["cloud-agent", "bc"], "getCloudAgentInfo"),
    (["cloud-agent", "bc", "--files", "--artifacts"], "getCloudAgentInfo"),
    (["cloud-agent", "bc", "--conversation"], "getCloudAgentConversation"),
    (["cloud-agent", "bc", "--proposals"], "getCloudAgentPublishProposals"),
    (["cloud-agent", "bc", "--secrets", "/app"], "getCloudAgentAppSecrets"),
]


@pytest.mark.parametrize("tty", [False, True])
@pytest.mark.parametrize("argv,command", MUTATIONS)
def test_changes_need_yes(monkeypatch, capsys, argv, command, tty):
    fake = setup_cli(monkeypatch)
    monkeypatch.setattr("sys.stdin", io.StringIO(SECRET + "\n"))
    monkeypatch.setattr("sys.stdin.isatty", lambda: tty)
    assert cli.main(argv) == 1
    assert "--yes" in capsys.readouterr().err
    assert not sent(fake, command)


@pytest.mark.parametrize("json_mode", [False, True])
@pytest.mark.parametrize("argv,command", [*READS, *MUTATIONS])
def test_options_text_and_json(monkeypatch, capsys, argv, command, json_mode):
    fake = setup_cli(monkeypatch)
    monkeypatch.setattr("sys.stdin", io.StringIO(SECRET + "\n"))
    flags = ["--yes"] if (argv, command) in MUTATIONS else []
    assert cli.main([*argv, *flags, *(["--json"] if json_mode else [])]) == 0
    output = capsys.readouterr()
    if json_mode:
        json.loads(output.out)
    else:
        assert output.out.strip()
    assert sent(fake, command)
    assert SECRET not in output.out + output.err


def test_payloads(monkeypatch, capsys):
    fake = setup_cli(monkeypatch)
    for argv, _ in MUTATIONS:
        monkeypatch.setattr("sys.stdin", io.StringIO(SECRET + "\n"))
        assert cli.main([*argv, "--yes"]) == 0
    assert cli.main(["cloud-agent", "bc", "--files"]) == 0
    assert cli.main(["cloud-agent", "bc", "--dismiss-proposal", "p", "--bot", "Alpha", "--yes"]) == 0  # fmt: skip
    assert sent(fake, "updateCloudAgentPublishApp") == [
        {
            "bcId": "bc",
            "slug": "s",
            "apex": "a",
            "visibility": "team",
            "muteRedeployPrompts": False,
            "requireConfirmationForUpdates": False,
        }
    ]
    assert sent(fake, "confirmCloudAgentPublishProposal") == [
        {
            "agentId": "gateway",
            "bcId": "bc",
            "proposalId": "p",
            "slug": "s",
            "visibility": "public",
            "requireConfirmationForUpdates": False,
        }
    ]
    assert sent(fake, "dismissCloudAgentPublishProposal") == [
        {"bcId": "bc", "proposalId": "p"},
        {"bcId": "bc", "proposalId": "p", "agentId": "gateway"},
    ]
    assert sent(fake, "getCloudAgentInfo") == [
        {"bcId": "bc", "includeFiles": True, "includeArtifacts": False}
    ]
    assert sent(fake, "tellCloudAgentAppSecretsSet") == [
        {
            "bcId": "bc",
            "projectDir": "/app",
            "names": ["API_KEY"],
            "refused": [],
            "applyNeeded": False,
        }
    ]
    assert SECRET not in capsys.readouterr().out


def test_update_flags(monkeypatch, capsys):
    fake = setup_cli(monkeypatch)
    argv = [
        "apps", "--update", "bc", "--slug", "s", "--apex", "a", "--visibility", "private",
        "--mute-redeploy-prompts", "--require-confirmation", "--yes",
    ]  # fmt: skip
    assert cli.main(argv) == 0
    payload = sent(fake, "updateCloudAgentPublishApp")[0]
    assert payload["muteRedeployPrompts"] and payload["requireConfirmationForUpdates"]
    assert capsys.readouterr().out.strip() == "Updated app s."


def test_apps_text(monkeypatch, capsys):
    fake = setup_cli(monkeypatch)
    assert cli.main(["apps"]) == 0
    out = capsys.readouterr().out
    assert "landing  demo.example  public  bc-demo-1" in out
    fake.commands["listCloudAgentPublishedApps"] = {
        "kind": "off",
        "apps": [{"slug": "x", "url": "https://x.invalid/?ticket=t"}],
    }
    assert cli.main(["apps"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("x  ") and "ticket" not in out
    assert cli.main(["apps", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["kind"] == "off" and "url" not in data["apps"][0]
    fake.commands["listCloudAgentPublishedApps"] = {"kind": "off"}
    assert cli.main(["apps"]) == 0
    assert (
        capsys.readouterr().out.strip() == "Cloud-agent apps are off for this account."
    )


def test_info_null_and_conversation(monkeypatch, capsys):
    fake = setup_cli(monkeypatch)
    assert cli.main(["cloud-agent", "bc"]) == 0
    out = capsys.readouterr().out
    assert "Status: RUNNING" in out and "Repository: github.com/demo/site" in out
    fake.commands["getCloudAgentInfo"] = None
    assert cli.main(["cloud-agent", "bc"]) == 0
    assert capsys.readouterr().out.strip() == "No cloud agent with that id."
    assert cli.main(["cloud-agent", "bc", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) is None
    assert cli.main(["cloud-agent", "bc", "--conversation"]) == 0
    assert "assistant: The page is ready to publish." in capsys.readouterr().out


def test_refusals(monkeypatch, capsys):
    fake = setup_cli(monkeypatch)
    fake.commands["listCloudAgentPublishedApps"] = REFUSED
    assert cli.main(["apps"]) == 0
    assert capsys.readouterr().out.strip() == "Apps are off for you."
    fake.commands["stopCloudAgent"] = REFUSED
    assert cli.main(["cloud-agent", "bc", "--stop", "--yes"]) == 1
    result = capsys.readouterr()
    assert (
        result.err.strip() == "Apps are off for you." and "Traceback" not in result.err
    )
    assert cli.main(["cloud-agent", "bc", "--stop", "--yes", "--json"]) == 1
    error = json.loads(capsys.readouterr().err)["error"]
    assert error["message"] == "Apps are off for you."
    fake.commands["unpublishCloudAgentPublishApp"] = {"ok": False, "message": "Busy"}
    argv = ["apps", "--unpublish", "bc", "--slug", "s", "--apex", "a", "--yes"]
    assert cli.main(argv) == 1
    assert capsys.readouterr().out.strip() == "Busy"


def test_set_secrets_hidden_with_refusals(monkeypatch, capsys):
    fake = setup_cli(monkeypatch)
    fake.commands["setCloudAgentAppSecrets"] = {
        "refused": [{"name": "B", "kind": "not_sensitive", "message": "Not sensitive " + SECRET}],
        "applyNeeded": True,
    }  # fmt: skip
    prompts = []

    def getpass(prompt):
        prompts.append(prompt)
        return SECRET

    monkeypatch.setattr("getpass.getpass", getpass)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    argv = ["cloud-agent", "bc", "--set-secret", "A", "--set-secret", "B"]
    assert cli.main([*argv, "--project-dir", "/app", "--yes"]) == 1
    output = capsys.readouterr()
    assert prompts == ["Value for A (hidden): ", "Value for B (hidden): "]
    assert "Saved A." in output.out and "B: Not sensitive" in output.out
    tell = sent(fake, "tellCloudAgentAppSecretsSet")[0]
    assert tell["names"] == ["A"] and tell["applyNeeded"] is True
    assert tell["refused"] == [
        {
            "name": "B",
            "kind": "not_sensitive",
            "message": "Not sensitive [redacted]",
            "permanent": False,
        }
    ]
    # A secret value echoed in a refusal message still never reaches the output.
    assert SECRET not in output.out + output.err
    assert "Not sensitive [redacted]" in output.out
    fake.commands["setCloudAgentAppSecrets"] = ConnectError(500, "echo " + SECRET)
    assert cli.main([*argv, "--project-dir", "/app", "--yes", "--json"]) == 1
    output = capsys.readouterr()
    assert SECRET not in output.out + output.err
    assert len(sent(fake, "tellCloudAgentAppSecretsSet")) == 1


def test_secret_names_only(monkeypatch, capsys):
    setup_cli(monkeypatch)
    for flags in ([], ["--json"]):
        assert cli.main(["cloud-agent", "bc", "--secrets", "/app", *flags]) == 0
        output = capsys.readouterr()
        assert "API_KEY" in output.out and SECRET not in output.out + output.err


@pytest.mark.parametrize(
    "argv",
    [
        ["apps", "--update", "bc", "--slug", "s", "--apex", "a", "--yes"],
        ["apps", "--unpublish", "bc", "--slug", "s", "--yes"],
        ["apps", "--slug", "s"],
        ["apps", "--visibility", "team"],
        ["cloud-agent", "bc", "--confirm-proposal", "p", "--yes"],
        ["cloud-agent", "bc", "--bot", "Alpha"],
        ["cloud-agent", "bc", "--slug", "s"],
        ["cloud-agent", "bc", "--set-secret", "A", "--yes"],
        ["cloud-agent", "bc", "--project-dir", "/app"],
        ["cloud-agent", "bc", "--conversation", "--files"],
    ],
)
def test_option_errors_send_nothing(monkeypatch, capsys, argv):
    fake = setup_cli(monkeypatch)
    assert cli.main(argv) == 1
    assert capsys.readouterr().err.strip()
    assert not [call for call in fake.calls if call[1] != "listAgents"]
