import json
import re
from pathlib import Path

import pytest

from gbot import cli, context
from gbot.protocol import USED_COMMANDS
from groken.client import ConnectError


class FakeManager:
    def __init__(self):
        self.calls = []
        self.responses = {
            "getMcpState": {
                "servers": [
                    {
                        "id": "gmail-id",
                        "serverIdentifier": "gmail",
                        "name": "Gmail",
                        "status": "needsAuth",
                        "pluginId": "p",
                    },
                    {
                        "id": "drive-id",
                        "name": "Drive",
                        "status": "connected",
                        "toolCount": 0,
                    },
                    {},
                ]
            },
            "listBoxMcpServers": {
                "servers": [
                    {
                        "serverIdentifier": "gmail",
                        "pendingSignIn": True,
                        "toolCount": 2,
                    },
                    {"serverIdentifier": "calendar", "status": "initializing"},
                ]
            },
            "getEffectiveMcpPlugins": [
                {"pluginId": "p", "isEnabled": True, "mcpServerNames": ["Gmail"]},
                {"isEnabled": False, "mcpServerNames": ["Extra"]},
            ],
        }

    def command(self, method, args=None):
        assert method in {
            "getMcpState",
            "listBoxMcpServers",
            "getEffectiveMcpPlugins",
            "listMcpServerTools",
        }
        self.calls.append((method, args))
        if method == "listMcpServerTools":
            assert args is not None
            if args["serverId"] == "gmail-id":
                raise RuntimeError("tool listing failed")
            return [{"name": "search"}, {}]
        return self.responses[method]


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    monkeypatch.setattr(
        "httpx.Client", lambda *a, **kw: pytest.fail("network forbidden")
    )


@pytest.fixture
def fake(monkeypatch):
    manager = FakeManager()
    monkeypatch.setattr(context, "manager_factory", lambda: manager)
    return manager


@pytest.mark.parametrize("json_mode", [False, True])
def test_merge(fake, capsys, json_mode):
    assert cli.main(["connectors"] + (["--json"] if json_mode else [])) == 0
    output = capsys.readouterr().out
    assert fake.calls == [
        ("getMcpState", None),
        ("listBoxMcpServers", {"serverIdentifiers": []}),
        ("getEffectiveMcpPlugins", None),
    ]
    if json_mode:
        rows = json.loads(output)
        assert len(rows) == 5
        assert rows[0] == {
            "id": "gmail-id",
            "name": "Gmail",
            "status": "needsAuth",
            "auth": "needs sign-in",
            "tool_count": 2,
            "enabled": True,
        }
        assert rows[1]["tool_count"] == 0
        assert rows[2] == dict.fromkeys(
            ["id", "name", "status", "auth", "tool_count", "enabled"]
        )
        assert rows[-1]["enabled"] is False
        assert rows[-1]["id"] is None
        assert all("tools" not in row for row in rows)
    else:
        assert "needs sign-in" in output and "connect it in the Grok Bot app" in output
        assert "tools=-" in output and "enabled=False" in output


@pytest.mark.parametrize("json_mode", [False, True])
def test_tools_failure_is_local(fake, capsys, json_mode):
    assert cli.main(["connectors", "--tools"] + (["--json"] if json_mode else [])) == 0
    output = capsys.readouterr().out
    calls = [
        args["serverId"]
        for method, args in fake.calls
        if method == "listMcpServerTools"
    ]
    assert calls == ["gmail-id", "drive-id", "calendar"]
    if json_mode:
        rows = json.loads(output)
        assert rows[0]["tools"] == [] and "tool listing failed" in rows[0]["error"]
        assert rows[1]["tools"] == [{"name": "search"}, {"name": None}]
        assert "missing server id" in rows[2]["error"]
    else:
        assert "tool listing failed" in output and "search" in output


def test_no_connectors(fake, capsys):
    fake.responses = dict.fromkeys(fake.responses)
    assert cli.main(["connectors", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == []
    assert cli.main(["connectors"]) == 0
    assert "No connectors" in capsys.readouterr().out


def test_not_signed_in(monkeypatch, capsys):
    def missing():
        raise SystemExit("no tokens")

    monkeypatch.setattr(context, "manager_factory", missing)
    assert cli.main(["connectors"]) == 3
    assert "gbot login" in capsys.readouterr().err


def test_no_bot_option(fake, capsys):
    assert cli.main(["connectors", "--bot", "a"]) == 1
    assert not fake.calls


def test_used_command_source_scan():
    names = set()
    for path in Path("gbot").rglob("*.py"):
        names.update(
            re.findall(
                r'\bcommand\(\s*["\']([^"\']+)["\']', path.read_text(encoding="utf-8")
            )
        )
    assert names <= USED_COMMANDS.keys()
    assert set(USED_COMMANDS.values()) <= {"none", "object", "unknown"}
    assert {
        "sendPrompt",
        "getAgentTranscriptTail",
        "listAgents",
    } <= USED_COMMANDS.keys()


def test_gateway_auth_error(fake, capsys):
    def expired(method, args=None):
        raise ConnectError(401, "expired")

    fake.command = expired
    assert cli.main(["connectors"]) == 3


@pytest.mark.parametrize(
    "status,detail",
    [
        ("needsAuth", None),
        ("needsGrant", None),
        ("error", {"kind": "authentication_required"}),
        ("disconnected", {"kind": "sign_in_pending"}),
    ],
)
def test_auth_state_survives_box_status(fake, capsys, status, detail):
    fake.responses["getMcpState"] = {
        "servers": [
            {
                "id": "s",
                "serverIdentifier": "box-s",
                "status": status,
                "statusDetail": detail,
            }
        ]
    }
    fake.responses["listBoxMcpServers"] = {
        "servers": [
            {
                "serverIdentifier": "box-s",
                "status": "disconnected",
            }
        ]
    }
    fake.responses["getEffectiveMcpPlugins"] = []
    assert cli.main(["connectors", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert len(rows) == 1 and rows[0]["auth"] == "needs sign-in"
