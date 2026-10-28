import argparse
import json
import re
from pathlib import Path

import httpx
import pytest

from gbot import cli, context
from gbot.context import Context
from gbot.protocol import USED_COMMANDS
from groken.client import ConnectError


class FakeBackend:
    def __init__(self):
        self.response = {
            "servers": [
                {
                    "serverIdentifier": "user-Gmail",
                    "accountLabel": "first@example.test",
                    "status": "connected",
                    "servedBy": "MCP_SERVED_BY_GROK",
                    "tools": [{"name": "search"}, {"name": "read"}],
                },
                {
                    "serverIdentifier": "user-Gmail--second",
                    "accountLabel": "second@example.test",
                    "status": "needsAuth",
                },
                {
                    "serverIdentifier": "user-BackendOnly",
                    "status": "connected",
                    "servedBy": "MCP_SERVED_BY_CURSOR",
                    "tools": [],
                },
            ]
        }
        self.failure = None

    def list_sand_mcp_tools(self, server_identifiers=None):
        assert server_identifiers is None
        if self.failure:
            raise self.failure
        return self.response


class FakeManager:
    def __init__(self):
        self.calls = []
        self.failures = {}
        self.responses = {
            "getMcpState": {
                "servers": [
                    {
                        "id": "first",
                        "serverIdentifier": "user-Gmail",
                        "name": "Gmail",
                        "status": "error",
                        "toolCount": 99,
                        "pluginId": "gmail",
                    },
                    {
                        "id": "second",
                        "serverIdentifier": "user-Gmail--second",
                        "name": "Gmail",
                        "status": "connected",
                        "toolCount": 4,
                        "pluginId": "gmail",
                    },
                    {
                        "id": "only",
                        "serverIdentifier": "cursor-only",
                        "pluginDisplayName": "Gateway Only",
                        "status": "connected",
                        "toolCount": 1,
                    },
                ]
            },
            "listBoxMcpServers": {
                "servers": [
                    {
                        "serverIdentifier": "user-Gmail",
                        "status": "disconnected",
                        "toolCount": 42,
                    }
                ]
            },
            "getEffectiveMcpPlugins": [
                {
                    "pluginId": "gmail",
                    "displayName": "Gmail Plugin",
                    "isEnabled": True,
                    "mcpServerNames": None,
                },
                {
                    "pluginId": "extra",
                    "displayName": "Extra Plugin",
                    "isEnabled": False,
                },
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
        if method in self.failures:
            raise self.failures[method]
        if method == "listMcpServerTools":
            assert args is not None
            if args["serverId"] == "second":
                raise RuntimeError("tool listing failed")
            return [{"name": "fallback"}]
        return self.responses[method]


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    monkeypatch.setattr(
        "httpx.Client", lambda *a, **kw: pytest.fail("network forbidden")
    )


@pytest.fixture
def fake(monkeypatch):
    manager, backend = FakeManager(), FakeBackend()
    monkeypatch.setattr(context, "manager_factory", lambda: manager)
    monkeypatch.setattr(context, "backend_factory", lambda: backend)
    return manager, backend


def test_merge_json(fake, capsys):
    manager, _ = fake
    assert cli.main(["connectors", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    rows = {row["server_identifier"]: row for row in result["connectors"]}
    assert list(rows) == [
        "user-BackendOnly",
        "cursor-only",
        "user-Gmail",
        "user-Gmail--second",
    ]
    assert rows["user-Gmail"] == {
        "name": "Gmail",
        "server_identifier": "user-Gmail",
        "account": "first@example.test",
        "status": "connected",
        "auth": "connected",
        "tool_count": 2,
        "plugin": "on",
        "served_by": "grok",
        "sources": [
            "backend",
            "getMcpState",
            "listBoxMcpServers",
            "getEffectiveMcpPlugins",
        ],
    }
    assert rows["user-Gmail--second"]["account"] == "second@example.test"
    assert rows["user-Gmail--second"]["auth"] == "needs sign-in"
    assert rows["user-Gmail--second"]["tool_count"] == 4
    assert rows["cursor-only"]["name"] == "Gateway Only"
    assert rows["user-BackendOnly"]["served_by"] == "cursor"
    assert result["plugins_without_connector"] == ["Extra Plugin"]
    assert result["warnings"] == []
    assert manager.calls == [
        ("getMcpState", None),
        ("getEffectiveMcpPlugins", None),
        ("listBoxMcpServers", {"serverIdentifiers": []}),
    ]


def test_table_alignment_and_ascii(fake, capsys):
    assert cli.main(["connectors"]) == 0
    output = capsys.readouterr().out
    assert output.isascii()
    lines = output.splitlines()
    starts = [
        lines[0].index(title)
        for title in ("NAME", "ACCOUNT", "STATUS", "TOOLS", "PLUGIN")
    ]
    for line, values in zip(
        lines[1:5],
        [
            ("BackendOnly", "-", "connected", "0", "-"),
            ("Gateway Only", "-", "connected", "1", "-"),
            ("Gmail", "first@example.test", "connected", "2", "on"),
            ("Gmail", "second@example.test", "needsAuth", "4", "on"),
        ],
    ):
        for start, value in zip(starts, values):
            assert line[start:].startswith(value)
    assert lines[4].endswith("- connect it in the Grok Bot app")
    assert lines[5] == "Plugins without a connector: Extra Plugin"


@pytest.mark.parametrize(
    "source", ["backend", "getMcpState", "getEffectiveMcpPlugins", "listBoxMcpServers"]
)
@pytest.mark.parametrize(
    "failure", [ConnectError(500, "waking"), httpx.ReadTimeout("timeout")]
)
def test_each_source_failure(fake, capsys, source, failure):
    manager, backend = fake
    if source == "backend":
        backend.failure = failure
    else:
        manager.failures[source] = failure
    assert cli.main(["connectors", "--json"]) == 0
    output = capsys.readouterr()
    result = json.loads(output.out)
    assert result["connectors"]
    assert len(result["warnings"]) == 1
    assert output.err.strip() == result["warnings"][0]
    assert output.err.startswith(f"warning: {source} unavailable: ")


@pytest.mark.parametrize("auth,code", [(False, 1), (True, 3)])
def test_all_fail(fake, capsys, auth, code):
    manager, backend = fake
    backend.failure = ConnectError(401 if auth else 500, "failure")
    manager.failures = {
        name: httpx.ReadTimeout("timeout") for name in manager.responses
    }
    assert cli.main(["connectors"]) == code
    output = capsys.readouterr()
    assert output.err.count("warning:") == 4
    assert not output.out


def test_backend_auth_failure_keeps_gateway(fake, capsys):
    fake[1].failure = ConnectError(401, "expired")
    assert cli.main(["connectors", "--json"]) == 0
    output = capsys.readouterr()
    assert json.loads(output.out)["connectors"]
    assert "gbot login" in output.err


def test_tools_and_local_failure(fake, capsys):
    manager, _ = fake
    assert cli.main(["connectors", "--tools", "--json"]) == 0
    rows = {
        r["server_identifier"]: r
        for r in json.loads(capsys.readouterr().out)["connectors"]
    }
    assert rows["user-Gmail"]["tools"] == ["search", "read"]
    assert rows["user-BackendOnly"]["tools"] == []
    assert rows["cursor-only"]["tools"] == ["fallback"]
    assert rows["user-Gmail--second"]["tools"] == []
    assert "tool listing failed" in rows["user-Gmail--second"]["error"]
    assert [
        (method, args)
        for method, args in manager.calls
        if method == "listMcpServerTools"
    ] == [
        ("listMcpServerTools", {"serverId": "only"}),
        ("listMcpServerTools", {"serverId": "second"}),
    ]
    assert cli.main(["connectors", "--tools"]) == 0
    text = capsys.readouterr().out
    assert "  search" in text and "  fallback" in text and "tool listing failed" in text


@pytest.mark.parametrize(
    "status,kind",
    [
        ("needsGrant", None),
        ("error", "authentication_required"),
        ("error", "grant_required"),
        ("error", "sign_in_pending"),
    ],
)
def test_auth_detail(fake, capsys, status, kind):
    fake[1].response = {"servers": []}
    fake[0].responses["getMcpState"] = {
        "servers": [
            {"serverIdentifier": "x", "status": status, "statusDetail": {"kind": kind}}
        ]
    }
    assert cli.main(["connectors", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)["connectors"]
    assert (
        next(row for row in rows if row["server_identifier"] == "x")["auth"]
        == "needs sign-in"
    )


def test_context_backend_lazy_and_auth(monkeypatch):
    calls = []
    backend = FakeBackend()
    monkeypatch.setattr(context, "backend_factory", lambda: calls.append(1) or backend)
    ctx = Context(argparse.Namespace(debug=False))
    assert not calls
    assert ctx.backend() is ctx.backend() is backend
    assert calls == [1]

    def missing():
        raise SystemExit("missing")

    monkeypatch.setattr(context, "backend_factory", missing)
    with pytest.raises(ConnectError) as exc:
        Context(argparse.Namespace(debug=False)).backend()
    assert exc.value.status == 401


def test_no_bot_option(fake, capsys):
    assert cli.main(["connectors", "--bot", "a"]) == 1
    assert not fake[0].calls


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
