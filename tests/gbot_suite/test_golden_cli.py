"""Byte-level CLI contracts backed only by synthetic transport state.

Regenerate deliberately with UPDATE_GOLDEN=1, then review every changed file.
"""

import copy
import difflib
import io
import json
import os
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from gbot import cli, config, context
from gbot.bots import record
from groken import auth
from groken.client import ConnectError

MESSAGES: dict[str, dict[str, object]] = {
    "auto-review-approval": {
        "approval": {
            "requestId": "review-request",
            "status": "pending",
            "summary": "Run report",
            "reason": "Needs approval",
            "surface": "box_shell",
            "command": "python report.py",
        }
    },
    "local-tool-permission": {
        "ask": {
            "requestId": "tool-request",
            "status": "pending",
            "action": "run-command",
            "target": "python report.py --output report.txt",
            "title": "Run local report",
            "description": "Generate the requested report",
        }
    },
    "email-draft": {
        "draft": {
            "from": "ada@example.com",
            "to": ["bob@example.com"],
            "cc": ["dee@example.com"],
            "subject": "Report",
            "body": "First line\nSecond line",
        }
    },
    "slack-draft": {
        "draft": {
            "target": "#reports",
            "thread": "thread-1",
            "workspace": "Example",
            "body": "First line\nSecond line",
        }
    },
    "widget": {
        "widget": {
            "prompt": "Which colour?",
            "options": [
                {"label": "A", "value": "blue"},
                {"label": "B", "value": "red"},
            ],
        }
    },
    "user-form": {
        "formRequest": {
            "title": "Report details",
            "instruction": "Enter the colour",
            "reason": "other",
            "fields": [
                {"id": "color", "label": "Color", "type": "text", "required": True}
            ],
        }
    },
    "secret-request": {
        "secretRequest": {
            "label": "Report API key",
            "description": "Needed for reports",
            "target": {"kind": "box-env", "name": "REPORT_KEY"},
        }
    },
}


class FakeGateway:
    def __init__(self) -> None:
        self.failure: ConnectError | None = None
        self.bots: list[dict[str, object]] = [
            {
                "id": "bot-inbox",
                "name": "Inbox",
                "awaitingUserResponse": {
                    "reason": "Approval",
                    "since": 1000,
                    "tabId": "chat",
                },
            },
            {
                "id": "bot-research",
                "name": "Research",
                "isRunning": True,
                "awaitingSessionIds": ["task-1"],
            },
            {"id": "bot-ledger", "name": "Ledger"},
            {
                "id": "group-reports",
                "name": "Reports",
                "isGroup": True,
                "memberIds": ["bot-research", "bot-ledger"],
            },
        ]
        self.entries: dict[str, list[dict[str, object]]] = {
            str(bot["id"]): [] for bot in self.bots
        }
        for bot_id in ("bot-inbox", "bot-research"):
            self.entries[bot_id].append(
                {
                    "id": f"{bot_id}-hello",
                    "seq": 1,
                    "kind": "message",
                    "timestampMs": 1000,
                    "message": {"content": "Report requested"},
                }
            )
        for seq, (kind, message) in enumerate(MESSAGES.items(), 2):
            bot_id = "bot-inbox" if seq in (2, 4, 6, 7) else "bot-research"
            self.entries[bot_id].append(
                {
                    "id": f"card{seq:04d}-entry",
                    "seq": seq,
                    "kind": "send-message",
                    "timestampMs": seq * 1000,
                    "sessionId": "task-1" if bot_id == "bot-research" else None,
                    "message": {"type": kind, **copy.deepcopy(message)},
                }
            )
        # A full eight-entry default transcript makes -n 5 actually truncate.
        for seq in (3, 5, 8):
            self.entries["bot-inbox"].append(
                {
                    "id": f"inbox-note-{seq}",
                    "seq": seq,
                    "kind": "message",
                    "timestampMs": seq * 1000,
                    "message": {"content": f"Report update {seq}"},
                }
            )
        self.entries["bot-inbox"].sort(key=lambda row: int(str(row["seq"])))
        self.servers: list[dict[str, object]] = [
            {
                "id": "calendar",
                "serverIdentifier": "user-calendar",
                "name": "Calendar",
                "status": "connected",
                "toolCount": 2,
                "pluginId": "calendar-plugin",
            },
            {
                "id": "notes",
                "serverIdentifier": "user-notes",
                "name": "Notes",
                "status": "needsAuth",
                "toolCount": 0,
            },
        ]

    def command(self, method: str, args: dict[str, object] | None = None) -> object:
        args = args or {}
        if method == "listAgents":
            if self.failure:
                raise self.failure
            return copy.deepcopy(self.bots)
        if method == "getAgentTranscriptTail":
            rows = self.entries[str(args["id"])]
            rows = [
                row
                for row in rows
                if "sessionId" not in args or row.get("sessionId") == args["sessionId"]
            ]
            rows = [
                row
                for row in rows
                if (
                    "beforeSeq" not in args
                    or int(str(row["seq"])) < int(str(args["beforeSeq"]))
                )
                and (
                    "afterSeq" not in args
                    or int(str(row["seq"])) > int(str(args["afterSeq"]))
                )
            ]
            limit = int(str(args.get("limit", 100)))
            return {"entries": copy.deepcopy(rows[-limit:] if limit else [])}
        if method == "sendPrompt":
            rows = self.entries[str(args["agentId"])]
            rows.append(
                {
                    "id": "sent-entry",
                    "seq": max(int(str(row["seq"])) for row in rows) + 1,
                    "kind": "message",
                    "timestampMs": 9000,
                    "message": {"content": args["prompt"]},
                }
            )
            return {"accepted": True}
        responses: dict[str, object] = {
            "getForeverBoxStatus": {"state": "running"},
            "getHostStatus": {
                "hostVersion": "0.77.0",
                "latestHostVersion": "0.78.0",
                "hostUpdateAvailable": True,
                "isBusy": False,
            },
            "getBoxSecretsStatus": {"isApplied": True, "secretNames": ["REPORT_KEY"]},
            "getMcpState": {"servers": self.servers},
            "listBoxMcpServers": {"servers": self.servers},
            "getEffectiveMcpPlugins": [
                {
                    "pluginId": "calendar-plugin",
                    "displayName": "Calendar",
                    "isEnabled": True,
                }
            ],
            "listMcpServerTools": [{"name": "find_event"}, {"name": "create_event"}],
        }
        if method not in responses:
            raise ConnectError(404, f"Unknown synthetic command: {method}")
        return copy.deepcopy(responses[method])

    def transcript_tail(self, agent_id: str) -> list[dict[str, object]]:
        page = record(self.command("getAgentTranscriptTail", {"id": agent_id}))
        rows = page["entries"]
        assert isinstance(rows, list)
        return [record(row) for row in rows]

    def send_prompt(self, agent_id: str, text: str) -> dict[str, object]:
        return record(
            self.command(
                "sendPrompt",
                {"agentId": agent_id, "prompt": text, "clientNonce": "synthetic-nonce"},
            )
        )

    def ask(
        self,
        agent_id: str,
        text: str,
        timeout_s: float = 600,
        idle_s: float = 45,
        *,
        on_entry: Callable[[dict[str, object]], bool] | None = None,
    ) -> str:
        self.send_prompt(agent_id, text)
        for row in self.transcript_tail(agent_id):
            if on_entry and on_entry(row):
                break
        return "Synthetic reply"

    def ask_stream(
        self,
        agent_id: str,
        text: str,
        timeout_s: float = 600,
        idle_s: float = 45,
        on_chunk: Callable[[str], None] | None = None,
        *,
        on_entry: Callable[[dict[str, object]], bool] | None = None,
    ) -> str:
        reply = self.ask(agent_id, text, timeout_s, idle_s, on_entry=on_entry)
        if on_chunk:
            on_chunk(reply)
        return reply

    def events(self, channels: list[str] | None = None) -> Iterator[dict[str, object]]:
        if channels is None or "transcript" in channels:
            for agent_id in self.entries:
                for row in self.transcript_tail(agent_id):
                    yield {
                        "event": "message",
                        "data": {
                            "channel": "transcript",
                            "payload": {
                                "type": "appended",
                                "agentId": agent_id,
                                "entry": row,
                            },
                        },
                    }


class FakeBackend:
    def __init__(self, gateway: FakeGateway) -> None:
        self.gateway = gateway
        self.calls: list[dict[str, object]] = []

    def unary(
        self, service: str, method: str, payload: dict[str, object]
    ) -> dict[str, object]:
        assert service == "aiserver.v1.GrokBotService"
        self.calls.append({"method": method, "payload": copy.deepcopy(payload)})
        return (
            {"dispatched": True}
            if method.startswith("ResolveGrokBot")
            else {"accepted": True}
        )

    def list_sand_mcp_tools(
        self, server_identifiers: list[str] | None = None
    ) -> dict[str, object]:
        return {
            "servers": [
                {
                    **row,
                    "accountLabel": "ada@example.com",
                    "tools": [{"name": "find_event"}, {"name": "create_event"}]
                    if row["id"] == "calendar"
                    else [],
                }
                for row in self.gateway.servers
                if server_identifiers is None
                or row["serverIdentifier"] in server_identifiers
            ]
        }


class FixedDatetime(datetime):
    def astimezone(self, tz=None):
        return super().astimezone(UTC)


@pytest.fixture
def transport(monkeypatch, tmp_path):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    monkeypatch.setattr(auth, "TOKEN_FILE", tmp_path / "tokens.json")
    monkeypatch.setattr(auth, "load_tokens", lambda: {"accessToken": "synthetic"})
    monkeypatch.setattr(
        "httpx.Client", lambda *a, **kw: pytest.fail("network forbidden")
    )
    monkeypatch.setattr("webbrowser.open", lambda *a: pytest.fail("browser forbidden"))
    monkeypatch.setattr("sys.stdin", io.StringIO())
    monkeypatch.setattr("gbot.pending.time.time", lambda: 125)
    monkeypatch.setattr("gbot.commands.tail.datetime", FixedDatetime)
    monkeypatch.setattr("gbot.commands.status.detect_client_version", lambda: "0.77.0")
    gateway = FakeGateway()
    backend = FakeBackend(gateway)
    monkeypatch.setattr(context, "manager_factory", lambda: gateway)
    monkeypatch.setattr(context, "backend_factory", lambda: backend)
    config.set_default(("bot-inbox", "Inbox"))
    return gateway, backend


CASES = [
    ("bots", ["bots"]),
    ("send", ["send", "hi"]),
    ("tail-five", ["tail", "-n", "5"]),
    ("tail-after", ["tail", "--after", "4"]),
    ("approvals", ["approvals"]),
    ("approvals-all", ["approvals", "--all"]),
    ("approve", ["approve", "card0002", "--yes"]),
    ("deny", ["deny", "card0004", "--yes"]),
    ("respond-widget", ["respond", "card0006", "A", "--yes"]),
    ("respond-form", ["respond", "card0007", "--field", "color=blue", "--yes"]),
    ("dismiss", ["dismiss", "card0006", "--yes"]),
    ("status", ["status"]),
    ("connectors", ["connectors"]),
    ("unknown-bot", ["send", "--bot", "Nope", "hi"]),
]
GOLDEN_CASES = [
    (f"{name}-{mode}", [*argv, *(["--json"] if mode == "json" else [])])
    for name, argv in CASES
    for mode in ("text", "json")
]
GOLDEN_CASES += [
    ("use-text", ["use", "Research"]),
    ("unauthorized-json", ["bots", "--json"]),
]


def trim_lines(value: str) -> str:
    return "".join(
        line.rstrip(" \t\r\n") + ("\n" if line.endswith("\n") else "")
        for line in value.splitlines(keepends=True)
    )


@pytest.mark.parametrize(
    "name,argv", GOLDEN_CASES, ids=[case[0] for case in GOLDEN_CASES]
)
def test_golden_cli(transport, capsys, name, argv):
    gateway, backend = transport
    if name == "unauthorized-json":
        gateway.failure = ConnectError(401, "unauthorized after refresh")
    exit_code = cli.main(argv)
    captured = capsys.readouterr()
    actual = f"{captured.out}--- stderr ---\n{captured.err}--- exit {exit_code} ---\n"
    if argv[0] in {"approve", "deny", "respond", "dismiss"}:
        assert len(backend.calls) == 1
        actual += (
            "--- rpc ---\n"
            + json.dumps(backend.calls, indent=2, ensure_ascii=False)
            + "\n"
        )
    if name == "unauthorized-json":
        assert exit_code == 3
    path = Path(__file__).with_name("golden") / f"{name}.txt"
    actual = trim_lines(actual)
    if os.environ.get("UPDATE_GOLDEN") == "1":
        path.parent.mkdir(exist_ok=True)
        path.write_text(actual, encoding="utf-8", newline="\n")
    expected = trim_lines(path.read_text(encoding="utf-8"))
    assert actual == expected, "".join(
        difflib.unified_diff(
            expected.splitlines(keepends=True),
            actual.splitlines(keepends=True),
            fromfile=str(path),
            tofile="actual",
        )
    )
