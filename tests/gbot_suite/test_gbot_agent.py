import json
import subprocess
import sys
from types import SimpleNamespace

import httpx
import pytest

from gbot import cli, context
from groken.client import ConnectError
from groken.errors import explain_error
from groken.gateway import ReplyIncompleteError


@pytest.mark.parametrize(
    "exc,kind,code",
    [
        (ConnectError(401, "expired"), "auth", 3),
        (ReplyIncompleteError("a", 3), "still_working", 4),
        (httpx.ReadTimeout("late"), "timeout", 1),
        (httpx.ConnectError("offline"), "network", 1),
        (ConnectError(0, "offline"), "network", 1),
        (ConnectError(500, "failed"), "gateway", 1),
        (ValueError("bad"), "invalid", 1),
        (RuntimeError("failed"), "error", 1),
    ],
)
def test_json_errors(monkeypatch, capsys, exc, kind, code):
    def fail():
        raise exc

    monkeypatch.setattr(context, "manager_factory", fail)
    assert cli.main(["bots", "--json"]) == code
    output = capsys.readouterr()
    assert output.out == ""
    assert len(output.err.splitlines()) == 1
    assert json.loads(output.err) == {
        "error": {
            "type": kind,
            "message": " ".join(explain_error(exc, cli="gbot").splitlines()),
            "exit_code": code,
        }
    }


def test_json_parse_error_redacts(capsys):
    assert cli.main(["bots", "--json", "--bad=secret", "private"]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert "secret" not in output.err and "private" not in output.err
    assert json.loads(output.err)["error"]["type"] == "invalid"


@pytest.mark.parametrize("size", [1, 100000])
@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_broken_pipe_subprocess(size, stream):
    script = f"""import os, sys
from gbot import cli
read_fd, write_fd = os.pipe()
os.close(read_fd)
os.dup2(write_fd, sys.{stream}.fileno())
os.close(write_fd)
cli._main = lambda argv: (print("x" * {size}, file=sys.{stream}), 0)[1]
raise SystemExit(cli.main([]))
"""
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, timeout=30, check=False
    )
    assert result.returncode == 0
    assert result.stderr == b""


def test_send_cursor(monkeypatch, capsys):
    class Manager:
        def __init__(self):
            self.entries = []
            self.calls = []

        def command(self, method, args=None):
            if method == "listAgents":
                return [{"id": "a", "name": "Alpha"}]
            self.calls.append((method, args))
            if method == "getAgentTranscriptTail":
                # The gateway returns the newest `limit` entries.
                return {"entries": self.entries[-(args or {})["limit"] :]}
            return {"accepted": True}

    manager = Manager()
    monkeypatch.setattr(context, "manager_factory", lambda: manager)
    for entries, expected in [
        ([], None),
        (
            [
                {"id": "t1u", "seq": 2},
                {"id": "t1s0", "seq": True},
                {"id": "t2u", "seq": 8},
            ],
            8,
        ),
    ]:
        manager.entries = entries
        assert cli.main(["send", "--bot", "Alpha", "--json", "hello"]) == 0
        assert json.loads(capsys.readouterr().out) == {
            "accepted": True,
            "bot": {"id": "a", "name": "Alpha"},
            "last_seq": expected,
        }
        (read, read_args), (send, send_args) = manager.calls[-2:]
        assert (read, read_args) == ("getAgentTranscriptTail", {"id": "a", "limit": 1})
        assert send == "sendPrompt" and send_args["prompt"] == "hello"
        assert send_args["agentId"] == "a" and send_args["clientNonce"]


def test_exit_codes_and_help(monkeypatch, capsys):
    def register(subparsers):
        parser = subparsers.add_parser("attention")
        parser.set_defaults(func=lambda args, ctx: 2)

    monkeypatch.setattr(
        cli.pkgutil, "iter_modules", lambda path: [SimpleNamespace(name="test")]
    )
    monkeypatch.setattr(
        cli.importlib, "import_module", lambda name: SimpleNamespace(register=register)
    )
    assert cli.main(["attention"]) == 2
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    help_text = capsys.readouterr().out
    for code in ("0", "1", "2", "3", "4", "130"):
        assert f"{code} " in help_text
