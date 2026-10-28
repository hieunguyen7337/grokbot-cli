import argparse
import copy
import getpass
import io
import json
import traceback
import warnings
from collections.abc import Callable

import pytest

from gbot import cli, config, context
from gbot.bots import record
from gbot.context import Context
from gbot.pending import classify, discover, is_pending, render, resolve_ref
from groken.client import ConnectError
from groken.gateway import AwaitingUserError

# protocol-0.72.json: $defs.SandSendMessage and its referenced request types.
MESSAGES: dict[str, dict[str, object]] = {
    "email-draft": {
        "draft": {
            "from": "ada@example.com",
            "to": ["bob@example.com", "cat@example.com"],
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
    "meeting-chat-draft": {
        "draft": {
            "meetingId": "meeting-1",
            "meetingTitle": "Planning",
            "body": "Hello",
        },
        "meetingInternal": True,
    },
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
    "meeting-join-consent": {
        "approval": {"requestId": "meeting-request", "status": "pending"},
        "text": "Join the planning meeting",
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
    "widget": {
        "widget": {
            "prompt": "Which colour?",
            "options": [
                {"label": "Blue", "value": "blue"},
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
    "user-form": {
        "formRequest": {
            "title": "Report details",
            "instruction": "Enter the label",
            "reason": "other",
            "fields": [{"id": "label", "label": "Label", "type": "text"}],
        }
    },
    "virtual-card-approval": {
        "approval": {
            "requestId": "card-request",
            "status": "pending",
            "title": "Buy paper",
            "amountCents": 100,
            "context": "Office supplies",
            "currency": "USD",
            "lineItems": [],
            "merchantName": "Paper shop",
            "merchantUrl": "https://example.invalid",
        }
    },
    "publish-approval": {
        "approval": {
            "apex": "example.invalid",
            "bcId": "bc",
            "changeSummary": "New page",
            "createdAtMs": 1000,
            "decidedVia": "bot",
            "kind": "create",
            "note": "Review",
            "previewUrl": "https://example.invalid/preview",
            "projectDir": "/project",
            "proposalId": "proposal",
            "publishId": "publish",
            "slug": "report",
            "status": "pending",
            "targetUrl": "https://example.invalid/report",
            "updatedAtMs": 1000,
            "visibility": "public",
        },
        "text": "Publish the report",
    },
    "cookie-origin-approval": {
        "approval": {
            "requestId": "cookie-request",
            "status": "pending",
            "items": [],
        }
    },
    "connector-grant": {
        "ask": {
            "requestId": "connector-request",
            "serverId": "server",
            "serverName": "Calendar",
            "status": "pending",
        }
    },
    "credential-request": {
        "credentialRequest": {
            "kind": "browser-login",
            "catalogRevision": "revision",
            "connectionId": "connection",
            "credentialId": "credential",
            "expiresAtMs": 9999999999999,
            "purpose": "Read the report",
            "requestedAtMs": 1000,
            "targetSite": "example.invalid",
        }
    },
    "mobile-tool-permission": {
        "permission": {
            "machineId": "phone",
            "machineLabel": "Phone",
            "toolId": "camera",
            "status": "pending",
        },
        "title": "Allow camera",
    },
    "permission-request": {
        "permission": {
            "kind": "camera",
            "reason": "Scan document",
            "title": "Camera access",
        }
    },
    "app-secrets-request": {
        "request": {
            "bcId": "bc",
            "projectDir": "/project",
            "secrets": [{"name": "REPORT_KEY", "state": "requested"}],
        },
        "text": "Configure report secrets",
    },
}


def entry(kind: str, entry_id: str = "abcdef01-entry") -> dict[str, object]:
    return {
        "id": entry_id,
        "kind": "send-message",
        "timestampMs": 1000,
        "message": {"type": kind, **copy.deepcopy(MESSAGES[kind])},
    }


class FakeManager:
    def __init__(self) -> None:
        waiting = {"reason": "Approval", "since": 1000, "tabId": "chat"}
        self.bots: list[dict[str, object]] = [
            {
                "id": "a",
                "name": "Alpha",
                "awaitingUserResponse": waiting,
                "awaitingSessionIds": ["task-1"],
            },
            {"id": "b", "name": "Beta", "awaitingUserResponse": waiting},
            {"id": "c", "name": "Gamma", "awaitingUserResponse": None},
        ]
        self.tails: dict[tuple[str, str | None], list[dict[str, object]]] = {}
        self.pages: dict[tuple[str, str | None, object], dict[str, object]] = {}
        self.calls: list[tuple[str, dict[str, object] | None]] = []
        self.failure: Exception | None = None
        self.reply: dict[str, object] = {"accepted": True, "dispatched": True}
        self.partial = "Work so far"
        self.wait_entry = entry("widget")

    def command(self, method: str, args: dict[str, object] | None = None) -> object:
        assert method in {
            "listAgents",
            "getAgentTranscriptTail",
        }
        self.calls.append((method, copy.deepcopy(args)))
        if method == "listAgents":
            return self.bots
        assert args is not None
        if method == "getAgentTranscriptTail":
            key = (
                str(args["id"]),
                str(args["sessionId"]) if "sessionId" in args else None,
            )
            return self.pages.get(
                (*key, args.get("beforeSeq")), {"entries": self.tails.get(key, [])}
            )
        if self.failure:
            raise self.failure
        return self.reply

    def unary(self, service, method, payload):
        assert service == "aiserver.v1.GrokBotService"
        self.calls.append((method, copy.deepcopy(payload)))
        if self.failure:
            raise self.failure
        return self.reply

    def ask(
        self,
        agent_id: str,
        text: str,
        timeout_s: float = 600,
        idle_s: float = 45,
        *,
        on_entry: Callable[[dict[str, object]], bool] | None = None,
    ) -> str:
        assert (agent_id, text, timeout_s, idle_s) == ("a", "question", 600, 45)
        assert on_entry is not None
        assert not on_entry({"kind": "user", "id": "user", "content": text})
        assert not on_entry({**entry("widget"), "respondedValue": "blue"})
        assert on_entry(self.wait_entry)
        self.tails[("a", "task-1")] = [self.wait_entry]
        raise AwaitingUserError(agent_id, self.wait_entry, self.partial)

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
        if on_chunk and self.partial:
            on_chunk(self.partial)
        return self.ask(agent_id, text, timeout_s, idle_s, on_entry=on_entry)


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    monkeypatch.setattr(
        "httpx.Client", lambda *a, **kw: pytest.fail("network forbidden")
    )
    monkeypatch.setattr("webbrowser.open", lambda *a: pytest.fail("browser forbidden"))
    monkeypatch.setattr("sys.stdin", io.StringIO())


@pytest.fixture
def fake(monkeypatch):
    manager = FakeManager()
    monkeypatch.setattr(context, "manager_factory", lambda: manager)
    monkeypatch.setattr(context, "backend_factory", lambda: manager)
    return manager


def ctx() -> Context:
    return Context(argparse.Namespace(debug=False))


def mutations(fake: FakeManager) -> list[tuple[str, dict[str, object] | None]]:
    return [
        call
        for call in fake.calls
        if call[0] not in {"listAgents", "getAgentTranscriptTail"}
    ]


@pytest.mark.parametrize(
    "selection,expected",
    [
        ([], ["a", "b"]),
        (["--all"], ["a", "b", "c"]),
        (["--bot", "Alpha"], ["a"]),
        (["--bot", "Gamma"], ["c"]),
    ],
)
def test_discovery_selection_default_and_sessions(fake, capsys, selection, expected):
    fake.tails = {
        ("a", None): [entry("auto-review-approval", "review01-entry")],
        ("a", "task-1"): [entry("widget", "widget01-entry")],
        ("b", None): [entry("secret-request", "secret01-entry")],
        ("c", None): [entry("user-form", "form0001-entry")],
    }
    assert cli.main(["approvals", "--json", *selection]) == 2
    items = json.loads(capsys.readouterr().out)
    assert list(dict.fromkeys(item["bot_id"] for item in items)) == expected
    if "a" in expected:
        assert [item["session_id"] for item in items[:2]] == [None, "task-1"]
        assert items[1]["entry_id"] == "widget01-entry"
        assert items[1]["allowed_actions"] == ["respond", "dismiss"]
    config.set_default(("b", "Beta"))
    assert cli.main(["approvals"]) == 2
    output = capsys.readouterr().out
    assert "secret01  Beta  secret-request" in output and "gbot secret REF" in output
    assert "Alpha" not in output
    assert cli.main(["approvals", "--all", "--json"]) == 2
    assert len(json.loads(capsys.readouterr().out)) == 4


@pytest.mark.parametrize("json_mode", [False, True])
def test_empty_and_selection_errors(fake, capsys, json_mode):
    assert cli.main(["approvals", *(["--json"] if json_mode else [])]) == 0
    output = capsys.readouterr().out
    assert json.loads(output) == [] if json_mode else output == "Nothing pending.\n"
    assert cli.main(["approvals", "--all", "--bot", "a"]) == 1
    assert cli.main(["approvals", "--bot", "absent"]) == 1
    config.set_default(("missing", "Deleted"))
    assert cli.main(["approvals"]) == 1


@pytest.mark.parametrize("kind", list(MESSAGES))
def test_every_transcript_pending_type(kind):
    item = classify(entry(kind), "a", "Alpha", "session")
    assert item is not None
    assert (item.type, item.created_at, item.session_id) == (kind, 1000, "session")
    assert item.summary and "\n" not in item.summary


@pytest.mark.parametrize(
    "kind,location,field,value",
    [
        *[
            (kind, nested, "status", state)
            for kind, nested, states in [
                (
                    "auto-review-approval",
                    "approval",
                    ["always", "approved", "denied", "expired"],
                ),
                (
                    "meeting-join-consent",
                    "approval",
                    ["always", "approved", "denied", "expired"],
                ),
                (
                    "local-tool-permission",
                    "ask",
                    ["allowed", "always", "denied", "expired", "never"],
                ),
                (
                    "virtual-card-approval",
                    "approval",
                    ["approved", "denied", "expired", "failed"],
                ),
                (
                    "publish-approval",
                    "approval",
                    ["confirming", "dismissed", "published"],
                ),
                (
                    "cookie-origin-approval",
                    "approval",
                    ["allowed", "always", "approved", "denied", "expired", "failed"],
                ),
                ("connector-grant", "ask", ["allowed", "expired", "skipped"]),
                ("mobile-tool-permission", "permission", ["granted"]),
            ]
            for state in states
        ],
        ("widget", None, "respondedValue", ""),
        ("widget", None, "widgetDismissed", True),
        ("widget", None, "widgetSkipped", True),
        ("secret-request", None, "secretProvided", True),
        *[
            ("user-form", None, "formResolution", value)
            for value in ["submitted", "dismissed", "escalated", "fill_failed"]
        ],
        *[
            ("credential-request", None, "credentialResolution", value)
            for value in ["approved", "denied", "failed", "filling"]
        ],
        (
            "app-secrets-request",
            "request",
            "secrets",
            [{"name": "REPORT_KEY", "state": "set"}],
        ),
    ],
)
def test_answered_entries_are_not_listed(fake, kind, location, field, value):
    resolved = entry(kind)
    target = record(record(resolved["message"])[location]) if location else resolved
    target[field] = value
    fake.tails[("a", None)] = [resolved]
    assert discover(ctx()) == []


def test_malformed_non_pending_and_missing_id():
    for value in [
        {},
        {"kind": "tool-call"},
        {"kind": "send-message", "message": {"type": "text"}},
    ]:
        assert not is_pending(value)
    pending = entry("widget")
    pending.pop("id")
    assert classify(pending, "a", "Alpha") is None


def test_ref_fresh_unique_ambiguous_unknown_short_exact(fake):
    fake.tails[("a", None)] = [entry("widget")]
    assert resolve_ref(ctx(), "abcdef").entry_id == "abcdef01-entry"
    fake.tails[("b", None)] = [entry("widget", "abcdef02-entry")]
    with pytest.raises(ValueError, match="Ambiguous"):
        resolve_ref(ctx(), "abcdef")
    assert resolve_ref(ctx(), "abcdef01-entry").bot_id == "a"
    for ref, error in [("abcde", "at least 6"), ("unknown", "Unknown")]:
        with pytest.raises(ValueError, match=error):
            resolve_ref(ctx(), ref)
    fake.tails[("a", None)][0]["respondedValue"] = "blue"
    with pytest.raises(ValueError, match="Unknown"):
        resolve_ref(ctx(), "abcdef01-entry")
    fake.tails[("a", None)] = [entry("widget", "short")]
    assert resolve_ref(ctx(), "short").entry_id == "short"


def test_ref_from_explicit_bot_listing_without_roster_flag(fake, capsys):
    fake.tails[("c", None)] = [entry("widget")]
    assert cli.main(["approvals", "--bot", "Gamma"]) == 2
    assert "Gamma" in capsys.readouterr().out
    assert cli.main(["respond", "abcdef01", "Blue", "--yes"]) == 0
    assert mutations(fake) == [
        (
            "RespondGrokBotWidget",
            {
                "agentId": "c",
                "entryId": "abcdef01-entry",
                "value": "Blue",
            },
        )
    ]


def test_pagination_and_duplicate_sessions(fake):
    fake.pages[("a", None, None)] = {"entries": [entry("widget")], "nextBeforeSeq": 10}
    fake.pages[("a", None, 10)] = {
        "entries": [entry("secret-request", "secret01-entry")]
    }
    fake.tails[("a", "task-1")] = [entry("widget")]
    items = discover(ctx())
    assert len(items) == 2 and items[0].session_id == "task-1"
    assert (
        "getAgentTranscriptTail",
        {"id": "a", "limit": 100, "beforeSeq": 10},
    ) in fake.calls
    fake.pages[("a", None, 10)]["nextBeforeSeq"] = 10
    with pytest.raises(ValueError, match="did not advance"):
        discover(ctx())
    fake.pages[("a", None, None)] = {"entries": None}
    with pytest.raises(TypeError, match="Invalid transcript"):
        discover(ctx())


@pytest.mark.parametrize("session_id", [None, "task-1"])
@pytest.mark.parametrize(
    "kind,argv,method,extra",
    [
        (
            "auto-review-approval",
            ["approve"],
            "ResolveGrokBotAutoReviewApproval",
            {"requestId": "review-request", "resolution": 1},
        ),
        (
            "auto-review-approval",
            ["approve", "--always"],
            "ResolveGrokBotAutoReviewApproval",
            {"requestId": "review-request", "resolution": 3},
        ),
        (
            "auto-review-approval",
            ["deny"],
            "ResolveGrokBotAutoReviewApproval",
            {"requestId": "review-request", "resolution": 2},
        ),
        (
            "local-tool-permission",
            ["approve"],
            "ResolveGrokBotLocalToolPermission",
            {"requestId": "tool-request", "resolution": 1},
        ),
        (
            "local-tool-permission",
            ["approve", "--always"],
            "ResolveGrokBotLocalToolPermission",
            {"requestId": "tool-request", "resolution": 3},
        ),
        (
            "local-tool-permission",
            ["deny"],
            "ResolveGrokBotLocalToolPermission",
            {"requestId": "tool-request", "resolution": 2},
        ),
        (
            "local-tool-permission",
            ["deny", "--never"],
            "ResolveGrokBotLocalToolPermission",
            {"requestId": "tool-request", "resolution": 4},
        ),
        ("widget", ["respond", "Blue"], "RespondGrokBotWidget", {"value": "Blue"}),
        ("widget", ["dismiss"], "DismissGrokBotWidget", {}),
        (
            "user-form",
            ["respond", "--field", "label=a=b"],
            "SubmitGrokBotUserForm",
            {
                "values": {"label": "a=b"},
                "saveToVault": False,
                "platform": 1,
            },
        ),
        (
            "user-form",
            ["dismiss"],
            "DismissGrokBotUserForm",
            {"mode": 1, "platform": 1},
        ),
    ],
)
def test_exact_answer_contract(fake, capsys, kind, argv, method, extra, session_id):
    fake.tails[("a", session_id)] = [entry(kind)]
    assert cli.main([argv[0], "abcdef01", *argv[1:], "--yes"]) == 0
    args = {"agentId": "a", "entryId": "abcdef01-entry", **extra}
    if method == "ResolveGrokBotAutoReviewApproval":
        args.pop("entryId")
        args["approvalPlatform"] = "desktop"
    if session_id:
        args["sessionId"] = session_id
    assert mutations(fake) == [(method, args)]
    output = capsys.readouterr().out
    assert "Alpha (a)" in output and kind in output and "Summary:" in output
    if kind == "local-tool-permission":
        assert "run-command: python report.py --output report.txt" in output


@pytest.mark.parametrize(
    "kind",
    [
        "meeting-join-consent",
        "virtual-card-approval",
        "publish-approval",
        "cookie-origin-approval",
        "connector-grant",
        "credential-request",
        "mobile-tool-permission",
        "permission-request",
        "app-secrets-request",
    ],
)
@pytest.mark.parametrize("command", ["approve", "deny", "respond", "dismiss", "secret"])
def test_app_only_types(fake, capsys, kind, command):
    fake.tails[("a", None)] = [entry(kind)]
    assert cli.main(["approvals"]) == 2
    assert "answer in the Grok Bot app" in capsys.readouterr().out
    assert cli.main([command, "abcdef01", "--yes"]) == 1
    assert "answer in the Grok Bot app" in capsys.readouterr().err
    assert mutations(fake) == []


@pytest.mark.parametrize(
    "kind,nested,field,value",
    [
        ("user-form", "formRequest", "reason", "checkout"),
        ("user-form", "formRequest", "reason", "auth"),
        ("user-form", "formRequest", "vaultKind", "card"),
        ("user-form", "formRequest", "vaultKind", "login"),
        ("user-form", "formRequest", "saveToVault", "card"),
        ("widget", "widget", "copyKind", "automation_spend_guard_paused"),
        ("widget", "widget", "copyKind", "automation_spend_guard_nudge"),
        (
            "secret-request",
            "secretRequest",
            "target",
            {"kind": "channel-credential", "field": "key", "platform": "slack"},
        ),
    ],
)
def test_payment_and_account_forms_are_app_only(kind, nested, field, value):
    pending = entry(kind)
    record(record(pending["message"])[nested])[field] = value
    item = classify(pending, "a", "Alpha")
    assert item is not None and item.allowed_actions == ()


@pytest.mark.parametrize(
    "kind,argv,hint",
    [
        ("auto-review-approval", ["respond", "blue"], "gbot approve"),
        ("widget", ["approve"], "gbot respond"),
        ("secret-request", ["dismiss"], "gbot secret"),
        ("user-form", ["secret"], "gbot respond"),
        ("auto-review-approval", ["deny", "--never"], "--never applies only"),
        ("widget", ["respond"], "REF VALUE"),
        ("widget", ["respond", "--field", "x=y"], "REF VALUE"),
        ("user-form", ["respond", "x"], "--field NAME=VALUE"),
        ("user-form", ["respond"], "--field NAME=VALUE"),
        ("user-form", ["respond", "--field", "broken"], "unique, nonempty"),
        ("user-form", ["respond", "--field", "=x"], "unique, nonempty"),
        (
            "user-form",
            ["respond", "--field", "x=y", "--field", "x=z"],
            "unique, nonempty",
        ),
    ],
)
def test_wrong_command_and_bad_answers(fake, capsys, kind, argv, hint):
    fake.tails[("a", None)] = [entry(kind)]
    assert cli.main([argv[0], "abcdef01", *argv[1:], "--yes"]) == 1
    assert hint in capsys.readouterr().err
    assert mutations(fake) == []


def test_missing_request_id_refused(fake, capsys):
    pending = entry("auto-review-approval")
    record(record(pending["message"])["approval"]).pop("requestId")
    fake.tails[("a", None)] = [pending]
    assert cli.main(["approve", "abcdef01", "--yes"]) == 1
    assert "requestId" in capsys.readouterr().err
    assert not mutations(fake)


@pytest.mark.parametrize(
    "tty,answer,yes,code",
    [
        (False, "", False, 1),
        (False, "", True, 0),
        (True, "y", False, 0),
        (True, " YES ", False, 0),
        (True, "n", False, 1),
        (True, "", False, 1),
    ],
)
def test_confirmation(fake, monkeypatch, capsys, tty, answer, yes, code):
    fake.tails[("a", None)] = [entry("local-tool-permission")]
    monkeypatch.setattr("sys.stdin.isatty", lambda: tty)

    def confirm(prompt):
        output = capsys.readouterr().out
        assert "Alpha (a)" in output and "run-command: python report.py" in output
        assert prompt == "Confirm [y/N]: " and not mutations(fake)
        return answer

    monkeypatch.setattr("builtins.input", confirm)
    assert cli.main(["approve", "abcdef01", *(["--yes"] if yes else [])]) == code
    assert bool(mutations(fake)) == (code == 0)
    if not tty and not yes:
        assert "Re-run with --yes to confirm" in capsys.readouterr().err


@pytest.mark.parametrize("session_id", [None, "task-1"])
def test_secret_getpass_confirm_exact_args(fake, monkeypatch, capsys, session_id):
    fake.tails[("a", session_id)] = [entry("secret-request")]
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    order = []

    def get_secret(prompt):
        assert "Summary:" in capsys.readouterr().out
        order.append("getpass")
        return "SENSITIVE_TEST_VALUE"

    def confirm(prompt):
        order.append("confirm")
        assert not mutations(fake)
        return "y"

    monkeypatch.setattr(getpass, "getpass", get_secret)
    monkeypatch.setattr("builtins.input", confirm)
    assert cli.main(["secret", "abcdef01"]) == 0
    assert order == ["getpass", "confirm"]
    payload = {
        "agentId": "a",
        "entryId": "abcdef01-entry",
        "value": "SENSITIVE_TEST_VALUE",
    }
    if session_id:
        payload["sessionId"] = session_id
    assert mutations(fake) == [("SubmitGrokBotSecret", payload)]
    captured = capsys.readouterr()
    assert "SENSITIVE_TEST_VALUE" not in captured.out + captured.err


@pytest.mark.parametrize("failure", ["transport", "getpass", "echo-warning", "cancel"])
def test_secret_never_leaks_even_in_debug(fake, monkeypatch, capsys, failure):
    fake.tails[("a", None)] = [entry("secret-request")]
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr(
        "builtins.input", lambda prompt: "n" if failure == "cancel" else "y"
    )

    def get_secret(prompt):
        if failure == "getpass":
            raise ValueError("SENSITIVE_TEST_VALUE")
        if failure == "echo-warning":
            warnings.warn("SENSITIVE_TEST_VALUE", getpass.GetPassWarning, stacklevel=2)
        return "SENSITIVE_TEST_VALUE"

    monkeypatch.setattr(getpass, "getpass", get_secret)
    if failure == "transport":
        fake.failure = RuntimeError("SENSITIVE_TEST_VALUE")
    assert cli.main(["secret", "abcdef01"]) == 1
    captured = capsys.readouterr()
    assert "SENSITIVE_TEST_VALUE" not in captured.out + captured.err
    with pytest.raises(ValueError) as raised:
        cli.main(["--debug", "secret", "abcdef01"])
    assert "SENSITIVE_TEST_VALUE" not in "".join(
        traceback.format_exception(raised.value)
    )
    assert raised.value.__context__ is None
    if failure != "transport":
        assert not mutations(fake)


def test_secret_refuses_non_tty_and_argv_value(fake, monkeypatch, capsys):
    fake.tails[("a", None)] = [entry("secret-request")]
    monkeypatch.setattr(getpass, "getpass", lambda prompt: pytest.fail("must not read"))
    assert cli.main(["secret", "abcdef01"]) == 1
    assert "Re-run with --yes to confirm" in capsys.readouterr().err
    assert cli.main(["secret", "abcdef01", "not-a-supported-argument"]) == 1
    assert "not-a-supported-argument" not in capsys.readouterr().err
    assert not mutations(fake)


def test_secret_yes_still_uses_hidden_prompt(fake, monkeypatch, capsys):
    fake.tails[("a", None)] = [entry("secret-request")]
    prompts = []

    def get_secret(prompt):
        prompts.append(prompt)
        return "SENSITIVE_TEST_VALUE"

    monkeypatch.setattr(getpass, "getpass", get_secret)
    monkeypatch.setattr("builtins.input", lambda prompt: pytest.fail("--yes confirms"))
    assert cli.main(["secret", "abcdef01", "--yes"]) == 0
    assert prompts == ["Secret (hidden): "]
    captured = capsys.readouterr()
    assert "SENSITIVE_TEST_VALUE" not in captured.out + captured.err


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("json_mode", [False, True])
@pytest.mark.parametrize("partial", ["", "Work so far"])
def test_ask_awaiting_partial_and_pending(fake, capsys, stream, json_mode, partial):
    config.set_default(("a", "Alpha"))
    fake.partial = partial
    argv = (
        ["ask", "question"]
        + (["--stream"] if stream else [])
        + (["--json"] if json_mode else [])
    )
    assert cli.main(argv) == 2
    output = capsys.readouterr().out
    if json_mode:
        result = json.loads(output)
        assert result["reply"] == partial and result["bot"] == {
            "id": "a",
            "name": "Alpha",
        }
        assert result["pending"][0]["entry_id"] == "abcdef01-entry"
        assert result["pending"][0]["session_id"] == "task-1"
    else:
        assert "abcdef01  Alpha  widget" in output and "gbot respond REF" in output
        assert output.count("Work so far") == bool(partial)
    assert not mutations(fake)


def test_render_age_and_one_line(monkeypatch):
    monkeypatch.setattr("gbot.pending.time.time", lambda: 62)
    pending = entry("widget")
    record(record(pending["message"])["widget"])["prompt"] = "Choose\ncolour\x1b[2J"
    item = classify(pending, "a", "Alpha\nBeta")
    assert item is not None
    assert "  1m  Choose colour [2J" in render([item])
    pending["timestampMs"] = 61000
    item = classify(pending, "a", "Alpha")
    assert item is not None and "  1s  " in render([item])
    pending.pop("timestampMs")
    item = classify(pending, "a", "Alpha")
    assert item is not None and "  ?  " in render([item])
    item = classify(entry("mobile-tool-permission"), "a", "Alpha")
    assert item is not None and item.summary == "Allow camera"


def test_multiline_command_is_shown_line_by_line(fake, capsys):
    item = entry("auto-review-approval")
    record(record(item["message"])["approval"])["command"] = (
        "Write-Output report # reviewed\nRemove-Item C:\\data -Recurse"
    )
    fake.tails[("a", None)] = [item]
    assert cli.main(["approve", "abcdef01", "--yes"]) == 0
    out = capsys.readouterr().out
    assert "2 lines, all run if approved" in out
    assert " 1| Write-Output report # reviewed\n" in out
    assert " 2| Remove-Item C:\\data -Recurse" in out
    assert "reviewed Remove-Item" not in out


def test_confirmation_escapes_terminal_controls(fake, capsys):
    item = entry("auto-review-approval")
    record(record(item["message"])["approval"])["command"] = (
        "safe\x1b[2K\rrm -rf ~ \u202e"
    )
    fake.tails[("a", None)] = [item]
    fake.bots[0]["name"] = "Alpha\x1b]52;c;ZXZpbA==\x07"
    assert cli.main(["approve", "abcdef01", "--yes"]) == 0
    out = capsys.readouterr().out
    assert not any(c in out for c in "\x1b\x07\r\u202e")
    assert " 1| safe\\u001b[2K\n" in out and " 2| rm -rf ~ \\u202e" in out
    assert "Alpha\\u001b]52;c;ZXZpbA==\\u0007" in out


def test_parser_errors_never_echo_values(fake, capsys):
    fake.tails[("a", None)] = [entry("secret-request")]
    assert cli.main(["secret", "abcdef01", "--value=SYNTHETIC_SECRET"]) == 1
    err = capsys.readouterr().err
    assert "SYNTHETIC_SECRET" not in err and "--value=<hidden>" in err
    assert cli.main(["bots", "POSITIONAL_SECRET"]) == 1
    err = capsys.readouterr().err
    assert "POSITIONAL_SECRET" not in err and "<hidden>" in err
    assert not mutations(fake)


@pytest.mark.parametrize("kind", ["email-draft", "slack-draft", "meeting-chat-draft"])
@pytest.mark.parametrize(
    "state", ["discarded", "draft-created", "sending", "sent", "unconfirmed"]
)
def test_draft_pending_state(kind, state):
    item = entry(kind)
    assert is_pending(item)
    item["draftSendState"] = None
    assert is_pending(item)
    item["draftSendState"] = state
    assert not is_pending(item)


@pytest.mark.parametrize(
    "kind,actions,summary,display",
    [
        (
            "email-draft",
            ("approve", "deny"),
            "From: ada@example.com; To: bob@example.com, cat@example.com; Subject: Report",
            (
                "From: ada@example.com\nTo: bob@example.com, cat@example.com\n"
                "Cc: dee@example.com\nSubject: Report\n\nFirst line\nSecond line"
            ),
        ),
        (
            "slack-draft",
            ("approve", "deny"),
            "To: #reports; Workspace: Example; First line",
            "To: #reports\nThread: thread-1\nWorkspace: Example\n\nFirst line\nSecond line",
        ),
        (
            "meeting-chat-draft",
            ("deny",),
            "Meeting: Planning",
            "Meeting: Planning\n\nHello",
        ),
    ],
)
def test_draft_classification(kind, actions, summary, display):
    row = entry(kind)
    item = classify(row, "a", "Alpha")
    assert item is not None
    assert (item.allowed_actions, item.summary, item.tool_text) == (
        actions,
        summary,
        display,
    )
    draft = record(record(row["message"])["draft"])
    assert item.draft == draft and item.draft is not draft


@pytest.mark.parametrize("session_id", [None, "task-1"])
@pytest.mark.parametrize("kind", ["email-draft", "slack-draft", "meeting-chat-draft"])
def test_discard_draft_payload(fake, capsys, session_id, kind):
    fake.tails[("a", session_id)] = [entry(kind)]
    assert cli.main(["deny", "abcdef01", "--yes"]) == 0
    payload = {"agentId": "a", "entryId": "abcdef01-entry"}
    if session_id:
        payload["sessionId"] = session_id
    assert mutations(fake) == [("DiscardGrokBotDraft", payload)]
    assert "Answer: DiscardGrokBotDraft (discards it)" in capsys.readouterr().out


@pytest.mark.parametrize("session_id", [None, "task-1"])
@pytest.mark.parametrize("kind", ["email-draft", "slack-draft"])
def test_send_draft_payload_and_confirmation(fake, capsys, session_id, kind):
    row = entry(kind)
    draft = record(record(row["message"])["draft"])
    draft["body"] = "First \x1b[2J\nSecond  \n"
    fake.tails[("a", session_id)] = [row]
    assert cli.main(["approve", "abcdef01"]) == 1
    captured = capsys.readouterr()
    assert "Re-run with --yes" in captured.err and not mutations(fake)
    assert (
        "Draft (" in captured.out
        and "sent exactly as shown if approved" in captured.out
    )
    assert "| First \\u001b[2J\n" in captured.out
    assert "| Second  \n" in captured.out and "\x1b" not in captured.out
    assert "Answer: SendGrokBotDraft (sends it now)" in captured.out
    assert cli.main(["approve", "abcdef01", "--yes"]) == 0
    payload = {
        "agentId": "a",
        "entryId": "abcdef01-entry",
        kind.removesuffix("-draft"): draft,
    }
    if session_id:
        payload["sessionId"] = session_id
    assert mutations(fake) == [("SendGrokBotDraft", payload)]


@pytest.mark.parametrize("kind", ["email-draft", "slack-draft", "meeting-chat-draft"])
@pytest.mark.parametrize("action,flag", [("approve", "--always"), ("deny", "--never")])
def test_draft_persistent_flags_refused(fake, capsys, kind, action, flag):
    fake.tails[("a", None)] = [entry(kind)]
    assert cli.main([action, "abcdef01", flag, "--yes"]) == 1
    error = capsys.readouterr().err
    assert (
        "gbot deny REF" in error
        if kind == "meeting-chat-draft" and action == "approve"
        else "do not apply to drafts" in error
    )
    assert not mutations(fake)


def test_meeting_draft_approve_refused(fake, capsys):
    fake.tails[("a", None)] = [entry("meeting-chat-draft")]
    assert cli.main(["approve", "abcdef01", "--yes"]) == 1
    assert "gbot deny REF" in capsys.readouterr().err
    assert not mutations(fake)


@pytest.mark.parametrize("action", ["approve", "deny"])
def test_missing_draft_record_refused(fake, capsys, action):
    row = entry("email-draft")
    record(row["message"]).pop("draft")
    fake.tails[("a", None)] = [row]
    assert cli.main([action, "abcdef01", "--yes"]) == 1
    assert "missing its draft record" in capsys.readouterr().err
    assert not mutations(fake)


@pytest.mark.parametrize("action", ["approve", "deny"])
def test_answer_rejected(fake, capsys, action):
    fake.tails[("a", None)] = [entry("email-draft")]
    fake.reply = {"accepted": False}
    assert cli.main([action, "abcdef01", "--yes"]) == 1
    captured = capsys.readouterr()
    assert "not accepted" in captured.err and "gbot approvals" in captured.err
    assert "Answered." not in captured.out


def test_secret_rejected_without_disclosing_value(fake, monkeypatch, capsys):
    fake.tails[("a", None)] = [entry("secret-request")]
    fake.reply = {"accepted": False}
    monkeypatch.setattr(getpass, "getpass", lambda prompt: "SENSITIVE_TEST_VALUE")
    assert cli.main(["secret", "abcdef01", "--yes"]) == 1
    captured = capsys.readouterr()
    assert "not accepted" in captured.err and "gbot approvals" in captured.err
    assert "Answered." not in captured.out
    assert "SENSITIVE_TEST_VALUE" not in captured.out + captured.err


def test_draft_ask_and_approvals_json(fake, capsys):
    config.set_default(("a", "Alpha"))
    fake.wait_entry = entry("email-draft")
    assert cli.main(["ask", "question"]) == 2
    assert "email-draft" in capsys.readouterr().out
    assert cli.main(["approvals", "--json"]) == 2
    result = json.loads(capsys.readouterr().out)[0]
    assert result["draft"] == MESSAGES["email-draft"]["draft"]
    assert result["tool_text"].endswith("First line\nSecond line")
    assert result["allowed_actions"] == ["approve", "deny"]


def test_draft_optional_fields_and_meeting_id():
    email = entry("email-draft")
    record(record(email["message"])["draft"]).pop("cc")
    item = classify(email, "a", "Alpha")
    assert item is not None and "Cc:" not in item.tool_text
    slack = entry("slack-draft")
    draft = record(record(slack["message"])["draft"])
    draft.pop("thread")
    draft.pop("workspace")
    item = classify(slack, "a", "Alpha")
    assert item is not None and item.summary == "To: #reports; First line"
    assert item.tool_text == "To: #reports\n\nFirst line\nSecond line"
    meeting = entry("meeting-chat-draft")
    record(record(meeting["message"])["draft"]).pop("meetingTitle")
    item = classify(meeting, "a", "Alpha")
    assert item is not None and item.summary == "Meeting: meeting-1"


@pytest.mark.parametrize(
    "kind,action,reply",
    [
        ("widget", ["dismiss"], {}),
        ("auto-review-approval", ["approve"], {}),
        (
            "widget",
            ["dismiss"],
            {"refusal": {"failureCode": "BLOCKED", "message": "No longer available"}},
        ),
    ],
)
def test_backend_rejections(fake, capsys, kind, action, reply):
    fake.tails[("a", None)] = [entry(kind)]
    fake.reply = reply
    assert cli.main([*action, "abcdef01", "--yes"]) == 1
    output = capsys.readouterr()
    assert "Answered." not in output.out
    assert ("BLOCKED" if reply else "not accepted") in output.err


def test_secret_refusal_redacted(fake, monkeypatch, capsys):
    fake.tails[("a", None)] = [entry("secret-request")]
    fake.reply = {"refusal": {"failureCode": "BLOCKED", "message": "PRIVATE_MESSAGE"}}
    monkeypatch.setattr(getpass, "getpass", lambda prompt: "PRIVATE_VALUE")
    assert cli.main(["secret", "abcdef01", "--yes"]) == 1
    output = capsys.readouterr()
    assert "BLOCKED" in output.err
    assert "PRIVATE_MESSAGE" not in output.out + output.err
    assert "PRIVATE_VALUE" not in output.out + output.err


@pytest.mark.parametrize("kind", ["email-draft", "slack-draft"])
def test_draft_optional_fields(fake, kind):
    row = entry(kind)
    draft = record(record(row["message"])["draft"])
    for key in ("cc", "workspace", "thread"):
        draft.pop(key, None)
    fake.tails[("a", None)] = [row]
    assert cli.main(["approve", "abcdef01", "--yes"]) == 0
    payload = mutations(fake)[0][1]
    assert payload is not None
    sent = record(payload[kind.removesuffix("-draft")])
    if kind == "email-draft":
        assert sent["cc"] == []
    else:
        assert "workspace" not in sent and "thread" not in sent


def test_all_scan_failure(fake, monkeypatch, capsys):
    fake.tails[("c", None)] = [entry("widget")]
    original = fake.command

    def command(method, args=None):
        if method == "getAgentTranscriptTail" and args and args["id"] == "b":
            raise RuntimeError("offline")
        return original(method, args)

    monkeypatch.setattr(fake, "command", command)
    assert cli.main(["approvals", "--all", "--json"]) == 2
    output = capsys.readouterr()
    assert json.loads(output.out)[0]["bot_id"] == "c"
    assert output.err == "warning: Beta: offline\n"


def test_all_scan_auth_failure_is_not_a_warning(fake, monkeypatch, capsys):
    fake.tails[("c", None)] = [entry("widget")]
    original = fake.command

    def command(method, args=None):
        if method == "getAgentTranscriptTail" and args and args["id"] == "b":
            raise ConnectError(401, "unauthorized after refresh")
        return original(method, args)

    monkeypatch.setattr(fake, "command", command)
    assert cli.main(["approvals", "--all"]) == 3
    assert "warning:" not in capsys.readouterr().err


@pytest.mark.parametrize(
    "seconds,age", [(59, "59s"), (3599, "59m"), (172799, "47h"), (172800, "2d")]
)
def test_age_ranges(monkeypatch, seconds, age):
    monkeypatch.setattr("gbot.pending.time.time", lambda: seconds + 1)
    item = classify(entry("widget"), "a", "Alpha")
    assert item is not None and f"  {age}  " in render([item])


def test_card_details_and_validation(fake, capsys):
    widget = entry("widget")
    form = entry("user-form", "form0001-entry")
    body = record(record(form["message"])["formRequest"])
    body["fields"] = [
        {"id": "color", "label": "Color", "type": "text", "required": False},
        {"id": "email", "label": "Email", "type": "email", "required": True},
    ]
    fake.tails[("a", None)] = [widget, form]
    assert cli.main(["approvals", "--all"]) == 2
    out = capsys.readouterr().out
    assert (
        "options: Blue" in out
        and "fields: color (text, optional), email (email, required)" in out
    )
    assert (
        "gbot respond REF VALUE" in out and "gbot respond REF --field ID=VALUE" in out
    )
    assert cli.main(["approvals", "--all", "--json"]) == 2
    items = json.loads(capsys.readouterr().out)
    assert items[0]["options"] == ["Blue"] and items[1]["fields"] == body["fields"]
    for args, error in [
        (["respond", "abcdef01", "bad"], "Blue"),
        (["respond", "form0001", "--field", "bad=x"], "color, email"),
        (["respond", "form0001", "--field", "color=x"], "email"),
    ]:
        assert cli.main([*args, "--yes"]) == 1
        assert error in capsys.readouterr().err
        assert not mutations(fake)


@pytest.mark.parametrize(
    "action,kind,extra,rpc,effect",
    [
        ("approve", "email-draft", [], "SendGrokBotDraft", "sends it now"),
        ("deny", "email-draft", [], "DiscardGrokBotDraft", "discards it"),
        ("respond", "widget", ["Blue"], "RespondGrokBotWidget", None),
        ("dismiss", "widget", [], "DismissGrokBotWidget", None),
        ("secret", "secret-request", [], "SubmitGrokBotSecret", None),
    ],
)
def test_answer_json(fake, monkeypatch, capsys, action, kind, extra, rpc, effect):
    fake.tails[("a", None)] = [entry(kind)]
    monkeypatch.setattr(getpass, "getpass", lambda prompt: "PRIVATE_VALUE")
    assert cli.main([action, "abcdef01", *extra, "--yes", "--json"]) == 0
    output = capsys.readouterr()
    assert json.loads(output.out) == {
        "answered": True,
        "bot_id": "a",
        "bot_name": "Alpha",
        "entry_id": "abcdef01-entry",
        "type": kind,
        "rpc": rpc,
        "effect": effect,
    }
    assert (
        "Bot: Alpha" in output.err
        and "Summary:" in output.err
        and "Answer:" in output.err
    )
    assert "PRIVATE_VALUE" not in output.out + output.err


def test_widget_step_options():
    row = entry("widget")
    body = record(record(row["message"])["widget"])
    body["steps"] = [{"options": [{"label": "First"}]}]
    item = classify(row, "a", "Alpha")
    assert item is not None and item.options == ["First"] and not item.validate_options
