import json

import pytest

from gbot import cli, config, context
from groken import auth


@pytest.mark.parametrize(
    "state,label",
    [
        ("absent", "none started (starts when the bot needs one)"),
        ("hibernated", "asleep"),
        ("running", "running"),
        ("future-state", "future-state"),
    ],
)
def test_desktop_computer_states(monkeypatch, tmp_path, capsys, state, label):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    monkeypatch.setattr(auth, "load_tokens", lambda: {"accessToken": "synthetic"})
    monkeypatch.setattr("gbot.commands.status.detect_client_version", lambda: "0.test")
    monkeypatch.setattr(
        "httpx.Client", lambda *a, **kw: pytest.fail("network forbidden")
    )

    class FakeManager:
        def command(self, method, args=None):
            if method == "listAgents":
                return [{"id": "test-bot", "name": "Test Bot"}]
            if method == "getForeverBoxStatus":
                assert args == {"id": "test-bot"}
                return {"state": state}
            assert method in {
                "getHostStatus",
                "getBoxSecretsStatus",
                "listBoxMcpServers",
            }
            return {}

    monkeypatch.setattr(context, "manager_factory", FakeManager)
    config.set_default(("test-bot", "Test Bot"))
    assert cli.main(["status"]) == 0
    assert f"Desktop computer: {label}" in capsys.readouterr().out.splitlines()
    assert cli.main(["status", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["bot"] == {
        "id": "test-bot",
        "name": "Test Bot",
        "state": state,
    }
