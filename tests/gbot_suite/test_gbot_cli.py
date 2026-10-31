import argparse
import io
import json
import webbrowser
from collections.abc import Callable, Iterator
from queue import SimpleQueue

import httpx
import pytest

from gbot import cli, config, context
from gbot.bots import resolve_bot
from gbot.commands import tail
from gbot.context import Context
from gbot.service.errors import SignedOutError
from gbot.service.events import ConnectionChanged, EntryAdded
from gbot.service.models import ConnectionStatus, Entry, TranscriptPage
from groken import auth
from groken.client import ConnectError
from groken.gateway import ReplyIncompleteError


class FakeManager:
    def __init__(self) -> None:
        self.bots: list[dict[str, object]] = [
            {"id": "a", "name": "Alpha", "isComposingMessage": True},
            {"id": "b", "name": "Beta", "isRunning": True},
            {"id": "c", "name": "Gamma"},
        ]
        self.entries: list[dict[str, object]] = [
            {
                "id": "1",
                "seq": 1,
                "timestampMs": 0,
                "kind": "user",
                "message": {"content": "hello"},
            },
            {
                "id": "2",
                "seq": 2,
                "timestampMs": 1000,
                "kind": "assistant",
                "content": "x" * 180,
            },
        ]
        self.calls: list[object] = []
        self.failure: Exception | None = None
        self.streams = 0

    def own_agent_id(self):
        pytest.fail("own_agent_id is forbidden")

    def create_bot(self, *args):
        pytest.fail("create_bot is forbidden")

    def duplicate_bot(self, *args):
        pytest.fail("duplicate_bot is forbidden")

    def resolve_agent(self, *args):
        pytest.fail("resolve_agent is forbidden")

    def command(self, method: str, args: dict[str, object] | None = None) -> object:
        assert method not in {
            "createAgent",
            "updateAgent",
            "duplicateAgent",
            "deleteAgent",
        }
        self.calls.append((method, args))
        if self.failure:
            raise self.failure
        return {
            "listAgents": self.bots,
            "getAgentTranscriptTail": {"entries": self.entries},
            "sendPrompt": {"ok": True},
            "getForeverBoxStatus": {"state": "running"},
            "getHostStatus": {
                "hostVersion": "0.30",
                "latestHostVersion": "0.31",
                "hostUpdateAvailable": True,
                "isBusy": True,
            },
            "getBoxSecretsStatus": {"isApplied": True, "secretNames": ["DO_NOT_PRINT"]},
            "listBoxMcpServers": {
                "servers": [
                    {"serverIdentifier": "mcp1", "status": "connected", "toolCount": 2}
                ]
            },
        }[method]

    def send_prompt(self, agent_id: str, text: str) -> dict[str, object]:
        self.calls.append(("send", agent_id, text))
        return {"ok": True}

    def ask(
        self,
        agent_id: str,
        text: str,
        timeout_s: float = 600,
        idle_s: float = 45,
        *,
        on_entry: Callable[[dict[str, object]], bool] | None = None,
    ) -> str:
        self.calls.append(("ask", agent_id, text, timeout_s, idle_s))
        return "reply ?"

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
        self.calls.append(("stream", agent_id, text, timeout_s, idle_s))
        if on_chunk:
            on_chunk("reply ")
            on_chunk("?")
        return "reply ?"

    def transcript_tail(self, agent_id: str) -> list[dict[str, object]]:
        assert agent_id == "a"
        return self.entries

    def events(self, channels: list[str] | None = None) -> Iterator[dict[str, object]]:
        assert channels == ["transcript"]
        self.streams += 1
        if self.streams == 1:
            # Appended while the stream is down: only the backfill can show it.
            self.entries.append({"id": "6", "kind": "assistant", "content": "gap"})
            raise httpx.ReadError("dropped")
        if self.streams == 3:
            raise KeyboardInterrupt
        # The real gateway wraps each frame as {"event", "data": {"channel", "payload"}}.
        yield {
            "event": "message",
            "data": {
                "channel": "agent-upserted",
                "payload": {
                    "type": "appended",
                    "agentId": "a",
                    "entry": {"id": "7", "content": "wrong channel"},
                },
            },
        }
        for bot, kind, entry in [
            ("b", "appended", {"id": "3", "content": "wrong bot"}),
            ("a", "updated", {"id": "4", "content": "wrong type"}),
            ("a", "appended", self.entries[0]),
            ("a", "appended", {"id": "5", "kind": "assistant", "content": "fresh"}),
        ]:
            yield {
                "event": "message",
                "data": {
                    "channel": "transcript",
                    "payload": {"type": kind, "agentId": bot, "entry": entry},
                },
            }


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    monkeypatch.setattr(auth, "TOKEN_FILE", tmp_path / "tokens.json")
    monkeypatch.setattr(auth, "load_tokens", lambda: {"accessToken": "fake"})
    monkeypatch.setattr(auth, "save_tokens", lambda tokens: None)
    monkeypatch.setattr(
        "webbrowser.open", lambda url: pytest.fail("unexpected browser")
    )
    monkeypatch.setattr(
        "httpx.Client", lambda *a, **kw: pytest.fail("network forbidden")
    )
    monkeypatch.setattr("gbot.commands.status.detect_client_version", lambda: "0.30")


@pytest.fixture
def fake(monkeypatch):
    manager = FakeManager()
    monkeypatch.setattr(context, "manager_factory", lambda: manager)
    config.set_default(("a", "Alpha"))
    return manager


@pytest.mark.parametrize("requested", ["a", "Alpha", "ALPHA"])
def test_resolve(fake, requested):
    assert resolve_bot(Context(argparse.Namespace(debug=False)), requested) == (
        "a",
        "Alpha",
    )


def test_list_bots_accepts_bare_array_and_wrapped(fake, monkeypatch):
    ctx = Context(argparse.Namespace(debug=False))
    assert resolve_bot(ctx, "Beta") == ("b", "Beta")
    original = fake.command
    monkeypatch.setattr(
        fake,
        "command",
        lambda method, args=None: (
            {"agents": fake.bots} if method == "listAgents" else original(method, args)
        ),
    )
    assert resolve_bot(ctx, "Beta") == ("b", "Beta")


def test_resolve_default_renamed_deleted_none(fake):
    ctx = Context(argparse.Namespace(debug=False))
    fake.bots[0]["name"] = "Renamed"
    assert resolve_bot(ctx, None) == ("a", "Renamed")
    assert config.default_bot() == {"id": "a", "name": "Renamed"}
    fake.bots.pop(0)
    with pytest.raises(
        ValueError, match=r"Default bot Renamed \(a\) no longer exists.*Beta, Gamma"
    ):
        resolve_bot(ctx, None)
    config.set_default(None)
    with pytest.raises(ValueError, match="No bot selected.*Beta, Gamma"):
        resolve_bot(ctx, None)


def test_ambiguous_and_exact_priority(fake):
    fake.bots.append({"id": "d", "name": "ALPHA"})
    ctx = Context(argparse.Namespace(debug=False))
    assert resolve_bot(ctx, "Alpha") == ("a", "Alpha")
    with pytest.raises(ValueError, match=r"Ambiguous.*Alpha \[a\].*ALPHA \[d\]"):
        resolve_bot(ctx, "alpha")
    fake.bots.append({"id": "Alpha", "name": "ID wins"})
    assert resolve_bot(ctx, "Alpha") == ("Alpha", "ID wins")


@pytest.mark.parametrize("json_mode", [False, True])
@pytest.mark.parametrize("command", ["bots", "use", "ask", "send", "tail", "status"])
def test_command_outputs(fake, capsys, command, json_mode):
    args = [command] + (["--json"] if json_mode else [])
    if command in {"ask", "send"}:
        args += ["hello", "world"]
    assert cli.main(args) == 0
    output = capsys.readouterr().out
    assert "DO_NOT_PRINT" not in output
    if json_mode:
        value = json.loads(output)
        if command == "bots":
            assert [row["state"] for row in value] == ["composing", "running", "idle"]
            assert value[0]["default"] is True
        elif command == "use":
            assert value["default_bot"]["id"] == "a"
        elif command == "ask":
            assert value == {"bot": {"id": "a", "name": "Alpha"}, "reply": "reply ?"}
        elif command == "send":
            assert value == {
                "accepted": False,
                "bot": {"id": "a", "name": "Alpha"},
                "last_seq": 2,
            }
        elif command == "tail":
            assert [row["id"] for row in value] == ["1", "2"]
        else:
            assert value["host"] == {
                "version": "0.30",
                "latest_version": "0.31",
                "update_available": True,
                "busy": True,
            }
            assert value["mcp"]["servers"] == [
                {"id": "mcp1", "status": "connected", "tool_count": 2}
            ]
            assert value["secrets"] == {"is_applied": True}
    else:
        assert {
            "bots": "*  Alpha  composing  a",
            "use": "Default bot: Alpha (a)",
            "ask": "reply ?",
            "send": "Sent to Alpha.",
            "tail": "user: hello",
            "status": "Desktop computer: running",
        }[command] in output
    if command == "status":
        assert ("getForeverBoxStatus", {"id": "a"}) in fake.calls
        assert ("listBoxMcpServers", {"serverIdentifiers": []}) in fake.calls


def test_bots_columns_align_and_json_unchanged(fake, capsys):
    fake.bots[1]["name"] = "A much longer name"
    assert cli.main(["bots"]) == 0
    lines = capsys.readouterr().out.splitlines()
    starts = [lines[0].index(label) for label in ("NAME", "STATE", "ID")]
    assert lines[0].startswith("   NAME")
    for line, values in zip(
        lines[1:],
        [
            ("Alpha", "composing", "a"),
            ("A much longer name", "running", "b"),
            ("Gamma", "idle", "c"),
        ],
    ):
        for start, value in zip(starts, values):
            assert line[start:].startswith(value)
    assert lines[1].startswith("*") and all(line.startswith(" ") for line in lines[2:])
    assert cli.main(["bots", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == [
        {"id": "a", "name": "Alpha", "state": "composing", "default": True},
        {"id": "b", "name": "A much longer name", "state": "running", "default": False},
        {"id": "c", "name": "Gamma", "state": "idle", "default": False},
    ]


@pytest.mark.parametrize("json_mode", [False, True])
def test_login(fake, monkeypatch, capsys, json_mode):
    saved = []
    opened = []
    monkeypatch.setattr(
        auth,
        "start_login",
        lambda: {
            "login_url": "https://example.invalid/login",
            "uuid": "uid",
            "verifier": "proof",
        },
    )

    def poll(uid, verifier, timeout_s):
        assert (uid, verifier, timeout_s) == ("uid", "proof", 42)
        return {"accessToken": "TOP_SECRET"}

    monkeypatch.setattr(auth, "poll_for_tokens", poll)
    monkeypatch.setattr(auth, "save_tokens", saved.append)
    monkeypatch.setattr("webbrowser.open", opened.append)
    assert (
        cli.main(["login", "--timeout", "42"] + (["--json"] if json_mode else [])) == 0
    )
    output = capsys.readouterr().out
    assert "TOP_SECRET" not in output
    assert "https://example.invalid/login" in output
    assert ('"signed_in": true' if json_mode else "Signed in.") in output
    assert opened == ["https://example.invalid/login"]
    assert saved == [{"accessToken": "TOP_SECRET"}]


def test_login_timeout_no_browser(monkeypatch, capsys):
    monkeypatch.setattr(auth, "poll_for_tokens", lambda *a, **kw: None)
    assert cli.main(["login", "--no-browser"]) == 3
    assert "gbot login" in capsys.readouterr().err


@pytest.mark.parametrize("json_mode", [False, True])
@pytest.mark.parametrize("removed", [False, True])
def test_logout(monkeypatch, capsys, removed, json_mode):
    monkeypatch.setattr(auth, "clear_tokens", lambda: removed)
    assert cli.main(["logout"] + (["--json"] if json_mode else [])) == 0
    output = capsys.readouterr().out
    if json_mode:
        assert json.loads(output) == {"removed": removed}
    else:
        assert output.strip() == (
            "Session removed." if removed else "No saved session."
        )


def test_use_set_clear(fake, capsys):
    assert cli.main(["use", "Beta"]) == 0
    assert config.default_bot() == {"id": "b", "name": "Beta"}
    assert cli.main(["use", "--clear", "--json"]) == 0
    assert config.default_bot() is None
    assert "Default bot: Beta" in capsys.readouterr().out
    assert cli.main(["use", "--clear"]) == 0
    assert "cleared" in capsys.readouterr().out


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("json_mode", [False, True])
def test_ask_stdin_stream(fake, monkeypatch, capsys, stream, json_mode):
    monkeypatch.setattr("sys.stdin", io.StringIO("from stdin"))
    args = ["ask", "--bot", "b", "--timeout", "17", "--idle", "3"]
    args += (["--stream"] if stream else []) + (["--json"] if json_mode else []) + ["-"]
    assert cli.main(args) == 0
    assert ("stream" if stream else "ask", "b", "from stdin", 17, 3) in fake.calls
    output = capsys.readouterr().out
    if json_mode:
        assert json.loads(output)["reply"] == "reply ?"
    else:
        assert output == "reply ?\n"


@pytest.mark.parametrize(
    "failure,code,hint",
    [
        (ConnectError(401, "expired"), 3, "gbot login"),
        (ReplyIncompleteError("a", 600), 4, "longer --timeout"),
        (RuntimeError("one\ntwo"), 1, "one two"),
    ],
)
def test_error_codes(fake, capsys, failure, code, hint):
    fake.failure = failure
    assert cli.main(["bots"]) == code
    output = capsys.readouterr()
    assert not output.out
    assert hint in output.err
    assert output.err.count("\n") == 1
    assert "Traceback" not in output.err


def test_missing_auth(monkeypatch, capsys):
    def missing():
        raise SystemExit("No tokens. Run: groken login")

    monkeypatch.setattr(context, "manager_factory", missing)
    assert cli.main(["bots"]) == 3
    assert "gbot login" in capsys.readouterr().err


def test_unknown_bot(fake, capsys):
    assert cli.main(["use", "missing"]) == 1
    assert "available: Alpha, Beta, Gamma" in capsys.readouterr().err


@pytest.mark.parametrize("json_mode", [False, True])
def test_unsigned_status_lazy(monkeypatch, capsys, json_mode):
    monkeypatch.setattr(auth, "load_tokens", lambda: None)
    monkeypatch.setattr(
        context, "manager_factory", lambda: pytest.fail("manager must stay lazy")
    )
    assert cli.main(["status"] + (["--json"] if json_mode else [])) == 3
    output = capsys.readouterr().out
    assert (
        (json.loads(output)["signed_in"] is False)
        if json_mode
        else "Not signed in" in output
    )


def test_signed_in_without_selection_lazy(monkeypatch, capsys):
    monkeypatch.setattr(
        context, "manager_factory", lambda: pytest.fail("manager must stay lazy")
    )
    assert cli.main(["status", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["default_bot"] is None


def test_tail_options(fake, capsys):
    assert cli.main(["tail", "--since", "1", "-n", "1", "--full"]) == 0
    output = capsys.readouterr().out
    assert "x" * 180 in output and "hello" not in output
    assert cli.main(["tail"]) == 0
    output = capsys.readouterr().out
    assert "x" * 160 in output and "x" * 161 not in output
    assert cli.main(["tail", "-n", "0", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == []
    assert cli.main(["tail", "--since", "missing"]) == 1
    assert "not found" in capsys.readouterr().err
    assert cli.main(["tail", "-n", "-1"]) == 1


def test_debug_and_interrupt(fake, monkeypatch):
    fake.failure = RuntimeError("broken")
    with pytest.raises(RuntimeError, match="broken"):
        cli.main(["--debug", "bots"])

    def interrupt():
        raise KeyboardInterrupt

    monkeypatch.setattr(context, "manager_factory", interrupt)
    assert cli.main(["bots"]) == 130


def test_config_corrupt_warn_once(tmp_path, capsys):
    path = tmp_path / "gbot.json"
    assert config.load() == {}
    for content in ["{", "[]", '{"default_bot": {"id": 2}}']:
        path.write_text(content)
        assert config.load() == {}
    assert capsys.readouterr().err.count("Ignoring corrupt") == 1
    config.set_default(("a", "?"))
    assert config.default_bot() == {"id": "a", "name": "?"}


def test_private_config_writer(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        config,
        "write_private_text",
        lambda path, content: calls.append((path, content)),
    )
    config.set_default(("a", "Alpha"))
    assert calls[0][0] == tmp_path / "gbot.json"
    assert json.loads(calls[0][1])["default_bot"]["id"] == "a"


def test_discovery_help_version(monkeypatch, capsys):
    registered = []
    real_import = cli.importlib.import_module

    def importing(name):
        module = real_import(name)
        registered.append(name)
        return module

    monkeypatch.setattr(cli.importlib, "import_module", importing)
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    for name in ["login", "logout", "status", "bots", "use", "ask", "send", "tail"]:
        assert "gbot.commands." + name in registered
        assert name in output
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert "0.3.0" in capsys.readouterr().out
    assert cli.main([]) == 0


def test_context_cached_factory(fake):
    count = []

    def factory():
        count.append(1)
        return fake

    ctx = Context(argparse.Namespace(debug=False), factory)
    assert not count
    assert ctx.manager() is ctx.manager() is fake
    assert count == [1]


def test_empty_prompt(fake, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert cli.main(["ask", "-"]) == 1
    assert "empty" in capsys.readouterr().err
    assert not fake.calls


def test_console_reconfigure(monkeypatch):
    from gbot.output import Output

    calls = []

    class Console(io.StringIO):
        def reconfigure(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr("sys.stdout", Console())
    monkeypatch.setattr("sys.stderr", Console())
    Output().write({"name": "?"}, "?")
    assert calls == [{"encoding": "utf-8", "errors": "replace"}] * 2


def test_redirected_output_is_utf8(monkeypatch):
    # Windows gives a redirected stdout the ANSI code page; --json must still be UTF-8.
    from gbot.output import Output

    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp1252", newline="\n")
    monkeypatch.setattr("sys.stdout", stream)
    Output(json_mode=True).write({"note": "Inbox → Outbox — 알림"}, "")
    stream.flush()
    assert json.loads(raw.getvalue().decode("utf-8")) == {
        "note": "Inbox → Outbox — 알림"
    }


def test_new_command_is_discovered(monkeypatch, capsys):
    from types import SimpleNamespace

    def register(subparsers):
        parser = subparsers.add_parser("future-command")
        parser.set_defaults(func=lambda args, ctx: 0)

    monkeypatch.setattr(
        cli.pkgutil, "iter_modules", lambda path: [SimpleNamespace(name="future")]
    )
    monkeypatch.setattr(
        cli.importlib, "import_module", lambda name: SimpleNamespace(register=register)
    )
    assert cli.main(["future-command"]) == 0
    assert not capsys.readouterr().out


class FollowService:
    """A scripted service for `tail --follow`: one page, then the given events."""

    def __init__(self, events):
        self.events = events
        self.followed = []
        self.closed = False

    def transcript(self, bot_id, limit):
        return TranscriptPage((added(bot_id, "1", "fresh").entry,))

    def event_source(self):
        return self

    def follow(self, bot_id):
        self.followed.append(bot_id)

    def start(self, sink):
        for event in self.events:
            sink(event)

    def close(self):
        self.closed = True


def added(bot_id, entry_id, content, session_id=None):
    raw = {"id": entry_id, "seq": int(entry_id), "kind": "message", "content": content}
    entry = Entry.from_raw(bot_id, raw, session_id)
    assert entry is not None
    return EntryAdded(entry)


class Interrupting(SimpleQueue):
    """Ends the follow loop with Ctrl+C once the scripted events are used up."""

    def get(self, block=True, timeout=None):
        if self.empty():
            raise KeyboardInterrupt
        return super().get(block, timeout)


@pytest.mark.parametrize("json_mode", [False, True])
def test_follow_stream(fake, monkeypatch, capsys, json_mode):
    dropped = ConnectionChanged(ConnectionStatus.RECONNECTING, 1, "dropped")
    service = FollowService(
        [
            added("a", "1", "fresh"),
            dropped,
            dropped,
            added("b", "2", "wrong bot"),
            added("a", "3", "other session", "s1"),
            added("a", "4", "hello"),
        ]
    )
    monkeypatch.setattr(context, "service_factory", lambda: service)
    monkeypatch.setattr(tail, "SimpleQueue", Interrupting)
    assert cli.main(["tail", "--follow"] + (["--json"] if json_mode else [])) == 0
    output = capsys.readouterr()
    assert output.out.count("fresh") == 1
    assert output.out.count("hello") == 1
    for noise in ("wrong bot", "other session"):
        assert noise not in output.out
    if json_mode:
        lines = output.out.splitlines()
        assert [json.loads(line)["id"] for line in lines] == ["1", "4"]
    assert output.err.count("dropped") == 1
    assert service.followed == ["a"]
    assert service.closed


def test_follow_auth_expired(fake, monkeypatch, capsys):
    def signed_out():
        raise SignedOutError()

    monkeypatch.setattr(context, "service_factory", signed_out)
    assert cli.main(["tail", "--follow"]) == 3
    assert "gbot login" in capsys.readouterr().err
    service = FollowService([ConnectionChanged(ConnectionStatus.SIGNED_OUT)])
    monkeypatch.setattr(context, "service_factory", lambda: service)
    monkeypatch.setattr(tail, "SimpleQueue", Interrupting)
    assert cli.main(["tail", "--follow"]) == 3
    assert "gbot login" in capsys.readouterr().err
    assert service.closed


def test_untrusted_text_cannot_drive_the_terminal(fake, monkeypatch, capsys):
    hostile = "hi\x1b[2J\x1b]52;c;ZXZpbA==\x07\r\nok\u202e"
    monkeypatch.setattr(fake, "ask", lambda *a, **kw: hostile)
    assert cli.main(["ask", "--bot", "Alpha", "x"]) == 0
    out = capsys.readouterr().out
    assert not any(c in out for c in "\x1b\x07\r\u202e")
    assert "hi\\u001b[2J\\u001b]52;c;ZXZpbA==\\u0007\nok\\u202e" in out
    assert cli.main(["ask", "--bot", "Alpha", "--json", "x"]) == 0
    assert json.loads(capsys.readouterr().out)["reply"] == hostile

    def ask_stream(*args, on_chunk=None, **kwargs):
        assert on_chunk is not None
        for part in ("a\x1b", "[2Jb"):
            on_chunk(part)
        return "a\x1b[2Jb"

    monkeypatch.setattr(fake, "ask_stream", ask_stream)
    assert cli.main(["ask", "--bot", "Alpha", "--stream", "x"]) == 0
    out = capsys.readouterr().out
    assert "\x1b" not in out and "a\\u001b[2Jb" in out

    fake.failure = ConnectError(500, "\x1b[31mboom")
    assert cli.main(["bots"]) == 1
    err = capsys.readouterr().err
    assert "\x1b" not in err and "\\u001b[31mboom" in err


def test_send_session(fake, capsys):
    assert cli.main(["send", "--session", "task-1", "hello"]) == 0
    sent = [args for name, args in fake.calls if name == "sendPrompt"]
    assert sent[0]["sessionId"] == "task-1"
    assert sent[0]["clientNonce"]
    assert (
        "getAgentTranscriptTail",
        {"id": "a", "limit": 1, "sessionId": "task-1"},
    ) in fake.calls


def test_bots_awaiting_priority(fake, capsys):
    fake.bots[0]["awaitingUserResponse"] = {"reason": "approval"}
    assert cli.main(["bots", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["state"] == "awaiting"


def test_interrupt_cli(fake, monkeypatch, capsys):
    original = fake.command

    def command(method, args=None):
        if method == "interruptAgentRun":
            fake.calls.append((method, args))
            return {"hadActiveRun": True}
        return original(method, args)

    monkeypatch.setattr(fake, "command", command)
    assert cli.main(["interrupt", "--bot", "Alpha", "--yes", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "interrupted": True,
        "bot": {"id": "a", "name": "Alpha"},
        "session_id": None,
    }
    assert ("interruptAgentRun", {"id": "a"}) in fake.calls
    monkeypatch.setattr("sys.stdin", io.StringIO())
    assert cli.main(["interrupt", "--bot", "Alpha"]) == 1
    assert "Re-run with --yes to confirm" in capsys.readouterr().err


@pytest.mark.parametrize("outcome", ["false", "raises", "raises-other", "opens"])
@pytest.mark.parametrize("json_mode", [False, True])
def test_login_reports_browser_failure(fake, monkeypatch, capsys, outcome, json_mode):
    saved = []
    url = "https://example.invalid/login"
    monkeypatch.setattr(
        auth,
        "start_login",
        lambda: {"login_url": url, "uuid": "uid", "verifier": "proof"},
    )
    monkeypatch.setattr(
        auth, "poll_for_tokens", lambda *a, **kw: {"accessToken": "TOP_SECRET"}
    )
    monkeypatch.setattr(auth, "save_tokens", saved.append)

    def fail(target):
        if outcome == "raises":
            raise webbrowser.Error(f"no browser for {target}")
        if outcome == "raises-other":
            raise ValueError(f"no browser for {target}")
        return outcome == "opens"

    monkeypatch.setattr("gbot.commands.login.webbrowser.open", fail)
    assert (
        cli.main(["login", "--timeout", "42"] + (["--json"] if json_mode else [])) == 0
    )
    captured = capsys.readouterr()
    note = "Could not open a browser. Open the link shown above to sign in."
    if outcome == "opens":
        assert note not in captured.err
    else:
        assert note in captured.err
    # A note, not an error object: login still succeeds and exits 0.
    assert '"error"' not in captured.err
    assert url not in captured.err and "no browser" not in captured.err
    assert "TOP_SECRET" not in captured.out + captured.err
    assert ('"signed_in": true' if json_mode else "Signed in.") in captured.out
    assert saved == [{"accessToken": "TOP_SECRET"}]
