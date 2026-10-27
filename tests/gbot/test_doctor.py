import json
import struct
import sys
from pathlib import Path

import pytest

from gbot import cli, config, context
from gbot.commands import doctor
from gbot.protocol import USED_COMMANDS
from groken import app_archive, auth, client, winplat
from groken.client import ConnectError


def build_app(
    root: Path, commands: dict[str, str] | None = None, source: bytes | None = None
) -> Path:
    root.mkdir(exist_ok=True)
    if source is None:
        commands = USED_COMMANDS if commands is None else commands
        source = (
            "var table={"
            + ",".join(
                f"{name}:v().noArgs"
                if kind == "none"
                else f"{name}:v().args({{id:s()}})"
                for name, kind in commands.items()
            )
            + "};"
        ).encode()
    tree = {
        "files": {
            "dist": {
                "files": {
                    "node-agent-coordinator": {
                        "files": {"main.cjs": {"offset": "0", "size": len(source)}}
                    }
                }
            }
        }
    }
    payload = json.dumps(tree).encode()
    padding = (4 - len(payload) % 4) % 4
    str_size = len(payload) + 4 + padding
    (root / "app.asar").write_bytes(
        struct.pack("<4I", 4, str_size + 4, str_size, len(payload))
        + payload
        + b"\0" * padding
        + source
    )
    return root


class FakeManager:
    def __init__(self):
        self.calls = []
        self.failure = None
        self.host_failure = None
        self.bots = [{"id": "a", "name": "Alpha"}]
        self.host = {"hostVersion": "0.72", "hostUpdateAvailable": False}

    def command(self, method, args=None):
        assert method in {"listAgents", "getHostStatus"} and args is None
        self.calls.append(method)
        if self.failure:
            raise self.failure
        if method == "listAgents":
            return self.bots
        if self.host_failure:
            raise self.host_failure
        return self.host


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("GBOT_HOME", str(tmp_path))
    monkeypatch.setattr(auth, "TOKEN_FILE", tmp_path / "tokens.json")
    monkeypatch.setattr(auth, "load_tokens", lambda: {"accessToken": "NEVER_PRINT"})
    monkeypatch.setattr(
        "httpx.Client", lambda *a, **kw: pytest.fail("network forbidden")
    )
    monkeypatch.setattr(client, "detect_client_version", lambda: "0.72")
    monkeypatch.delenv("SAND_CLIENT_VERSION", raising=False)
    monkeypatch.setattr(app_archive, "read_bundle_version", lambda app: "0.72")
    app = build_app(tmp_path / "app")
    monkeypatch.setenv("GBOT_APP_DIR", str(app))
    config.set_default(("a", "Alpha"))


@pytest.fixture
def fake(monkeypatch):
    manager = FakeManager()
    monkeypatch.setattr(context, "manager_factory", lambda: manager)
    return manager


def result(capsys):
    output = capsys.readouterr().out
    assert "NEVER_PRINT" not in output
    rows = json.loads(output)
    assert [r["check"] for r in rows] == [
        "app",
        "client_version",
        "token",
        "gateway",
        "default_bot",
        "host",
        "protocol",
    ]
    assert all(set(row) == {"check", "status", "detail"} for row in rows)
    return {row["check"]: row for row in rows}


@pytest.mark.parametrize("json_mode", [False, True])
def test_pass(fake, capsys, json_mode):
    assert cli.main(["doctor"] + (["--json"] if json_mode else [])) == 0
    if json_mode:
        rows = result(capsys)
        assert all(row["status"] == "pass" for row in rows.values())
        assert (
            rows["protocol"]["detail"]
            == f"{len(USED_COMMANDS)} commands; all {len(USED_COMMANDS)} used commands present"
        )
    else:
        output = capsys.readouterr().out
        assert "[PASS] app" in output and "version 0.72" in output
        assert "[PASS] gateway  1 bots" in output
    assert fake.calls == ["listAgents", "getHostStatus"]


@pytest.mark.parametrize("signed_in", [True, False])
def test_offline(fake, monkeypatch, capsys, signed_in):
    monkeypatch.setattr(
        auth, "load_tokens", lambda: {"accessToken": "fake"} if signed_in else None
    )
    assert cli.main(["doctor", "--offline", "--json"]) == (0 if signed_in else 3)
    rows = result(capsys)
    assert [rows[key]["status"] for key in ["gateway", "default_bot", "host"]] == [
        "skip"
    ] * 3
    assert rows["protocol"]["status"] == "pass"
    assert not fake.calls


def test_missing_token_online(fake, monkeypatch, capsys):
    monkeypatch.setattr(auth, "load_tokens", dict)
    assert cli.main(["doctor", "--json"]) == 3
    rows = result(capsys)
    assert rows["token"]["detail"] == "Not signed in. Run: gbot login"
    assert not fake.calls


@pytest.mark.parametrize(
    "failure,code", [(ConnectError(401, "expired"), 3), (RuntimeError("broken"), 1)]
)
def test_gateway_failure(fake, capsys, failure, code):
    fake.failure = failure
    assert cli.main(["doctor", "--json"]) == code
    rows = result(capsys)
    assert rows["gateway"]["status"] == "fail"
    assert rows["default_bot"]["status"] == rows["host"]["status"] == "skip"
    assert rows["protocol"]["status"] == "pass"


@pytest.mark.parametrize("default", [None, ("gone", "Gone")])
def test_default_warning(fake, capsys, default):
    config.set_default(default)
    assert cli.main(["doctor", "--json"]) == 2
    row = result(capsys)["default_bot"]
    assert row["status"] == "warn" and "gbot use <name>" in row["detail"]


def test_host_update(fake, capsys):
    fake.host["hostUpdateAvailable"] = True
    assert cli.main(["doctor", "--json"]) == 2
    assert "update available" in result(capsys)["host"]["detail"]


@pytest.mark.parametrize(
    "failure,code",
    [(RuntimeError("host failed"), 1), (ConnectError(401, "expired"), 3)],
)
def test_host_failure(fake, capsys, failure, code):
    fake.host_failure = failure
    assert cli.main(["doctor", "--json"]) == code
    assert result(capsys)["host"]["status"] == "fail"


def test_missing_app(fake, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("GBOT_APP_DIR", str(tmp_path / "missing"))
    assert cli.main(["doctor", "--json"]) == 2
    rows = result(capsys)
    assert rows["app"]["detail"] == "not found; set GBOT_APP_DIR"
    assert rows["protocol"]["status"] == "skip"


@pytest.mark.parametrize("mode", ["missing", "changed", "empty", "broken"])
def test_protocol_drift(fake, monkeypatch, tmp_path, capsys, mode):
    commands = dict(USED_COMMANDS)
    commands.pop("sendPrompt")
    if mode == "changed":
        commands["listAgents"] = "object"
    app = build_app(
        tmp_path / "drift", commands, b"nothing here" if mode == "empty" else None
    )
    if mode == "broken":
        (app / "app.asar").write_bytes(b"bad")
    monkeypatch.setenv("GBOT_APP_DIR", str(app))
    assert cli.main(["doctor", "--json"]) == 2
    row = result(capsys)["protocol"]
    assert row["status"] == "warn"
    if mode in {"empty", "broken"}:
        assert row["detail"] == "could not read the command table"
    else:
        assert "sendPrompt: missing" in row["detail"]
        if mode == "changed":
            assert "listAgents: args none -> object" in row["detail"]


def test_env_version_source(fake, monkeypatch, capsys):
    monkeypatch.setenv("SAND_CLIENT_VERSION", "0.72")
    assert cli.main(["doctor", "--json"]) == 0
    assert "env override" in result(capsys)["client_version"]["detail"]


def test_local_failures(fake, monkeypatch, capsys):
    def broken():
        raise ValueError("bad local state")

    monkeypatch.setattr(client, "detect_client_version", broken)
    assert cli.main(["doctor", "--json"]) == 1
    assert result(capsys)["client_version"]["status"] == "fail"
    monkeypatch.setattr(auth, "load_tokens", broken)
    assert cli.main(["doctor", "--json"]) == 3
    assert result(capsys)["token"]["status"] == "fail"


def test_unknown_app_version(fake, monkeypatch, capsys):
    monkeypatch.setattr(app_archive, "read_bundle_version", lambda app: None)
    assert cli.main(["doctor", "--json"]) == 2
    assert result(capsys)["app"]["status"] == "warn"


def test_find_app_platform_defaults(monkeypatch, tmp_path):
    monkeypatch.delenv("GBOT_APP_DIR")
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        winplat, "app_install_dirs", lambda: [tmp_path / "missing", tmp_path]
    )
    assert doctor.find_app() == tmp_path
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(app_archive, "DEFAULT_APP_PATH", tmp_path)
    assert doctor.find_app() == tmp_path
