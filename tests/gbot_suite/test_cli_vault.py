import getpass
import io
import json

import pytest

from gbot import cli, context
from gbot.service import vault as v
from gbot.service.transport import FakeTransport


def setup_cli(monkeypatch):
    t = FakeTransport(rpcs=v.DEMO_RPCS)

    class Backend:
        def unary(self, service, name, payload):
            return t.rpc(name, payload)

    monkeypatch.setattr(context, "backend_factory", Backend)
    return t


@pytest.mark.parametrize(
    "option", [[], ["--payment-methods"], ["--passkeys"], ["--onepassword"]]
)
@pytest.mark.parametrize("json_mode", [False, True])
def test_list(monkeypatch, capsys, option, json_mode):
    t = setup_cli(monkeypatch)
    assert cli.main(["vault", *option, *(["--json"] if json_mode else [])]) == 0
    out = capsys.readouterr()
    assert out.out and not out.err and len(t.calls) == 1
    if json_mode:
        assert json.loads(out.out)


@pytest.mark.parametrize(
    "option",
    [
        ["--add-login"],
        ["--update-login", "id"],
        ["--delete", "id"],
        ["--revoke-passkey", "id"],
        ["--onepassword-sync"],
        ["--onepassword-disconnect", "id"],
    ],
)
def test_yes_required(monkeypatch, capsys, option):
    t = setup_cli(monkeypatch)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    assert cli.main(["vault", *option]) == 1
    assert "--yes" in capsys.readouterr().err
    assert not t.calls
    if option[0] not in ("--add-login", "--update-login"):
        assert cli.main(["vault", *option, "--yes"]) == 0
        assert len(t.calls) == 1


@pytest.mark.parametrize("update", [False, True])
@pytest.mark.parametrize("tty", [False, True])
def test_password(monkeypatch, capsys, update, tty):
    t = setup_cli(monkeypatch)
    password = "unique-test-password"
    monkeypatch.setattr("sys.stdin", io.StringIO(password + "\n"))
    monkeypatch.setattr("sys.stdin.isatty", lambda: tty)
    prompts = []
    monkeypatch.setattr(
        getpass, "getpass", lambda prompt: prompts.append(prompt) or password
    )
    argv = [
        "vault",
        *(["--update-login", "demo-login"] if update else ["--add-login"]),
        "--title",
        "Title",
        "--username",
        "User",
        "--yes",
    ]
    assert cli.main(argv) == 0
    assert prompts == (["Password (hidden): "] if tty else [])
    assert t.calls[-1][2]["password"] == password
    assert password not in str(capsys.readouterr())
    t.rpcs[v.RPCS[1]] = RuntimeError(password)
    monkeypatch.setattr("sys.stdin", io.StringIO(password + "\n"))
    assert cli.main(argv) == 1
    assert password not in str(capsys.readouterr())


def test_update_keeps_fields_not_given(monkeypatch):
    t = setup_cli(monkeypatch)
    monkeypatch.setattr("sys.stdin", io.StringIO("new-password" + chr(10)))
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    before = v.list_items(t)[0]
    argv = ["vault", "--update-login", "demo-login", "--title", "Renamed", "--yes"]
    assert cli.main(argv) == 0
    sent = t.calls[-1][2]
    assert sent["id"] == "demo-login" and sent["title"] == "Renamed"
    assert sent["username"] == before.username and sent["notes"] == before.notes
    assert sent["sites"] == list(before.sites)


def test_update_unknown_login_sends_nothing(monkeypatch):
    t = setup_cli(monkeypatch)
    monkeypatch.setattr("sys.stdin", io.StringIO("pw" + chr(10)))
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert cli.main(["vault", "--update-login", "missing", "--yes"]) == 1
    assert v.RPCS[1] not in [call[1] for call in t.calls]


def test_getpass_warning(monkeypatch, capsys):
    setup_cli(monkeypatch)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    def unsafe(prompt):
        import warnings

        warnings.warn("cannot hide input", getpass.GetPassWarning)
        raise AssertionError("must not reach fallback")

    monkeypatch.setattr(getpass, "getpass", unsafe)
    assert cli.main(["vault", "--add-login", "--title", "T", "--yes"]) == 1
    assert "cannot hide input" in capsys.readouterr().err
