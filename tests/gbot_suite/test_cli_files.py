import json

import pytest

from gbot import cli, context
from gbot.service import bot_files, library
from gbot.service.transport import FakeTransport
from groken.client import ConnectError

URL = "https://storage.invalid/put?signature=SECRET-URL"
TOKEN = "SECRET-TOKEN"
HEADER = "SECRET-HEADER"
SECRETS = ("SECRET-URL", TOKEN, HEADER)
REFUSED = ConnectError(
    403, json.dumps({"code": "permission_denied", "message": "Files need a team."})
)
FILE = {
    "name": "a.txt",
    "path": "/f/a.txt",
    "sizeBytes": "2048",
    "contentType": "text/plain",
    "updatedAtMs": "1700000000000",
    "etag": "e",
}
DOC = {
    "key": "k1",
    "provider": "notion",
    "externalId": "ext",
    "url": "https://example.invalid/d",
    "title": "Plan",
    "kind": "page",
    "lastTouchedAtMs": "1700000000000",
}


def setup_cli(monkeypatch):
    fake = FakeTransport(
        {"listAgents": [{"id": "gateway", "name": "Alpha"}]},
        {**bot_files.DEMO_RPCS, **library.DEMO_RPCS},
    )
    fake.rpcs.update(
        {
            "ListGrokBotAgentFiles": {
                "files": [FILE],
                "totalBytes": "2048",
                "canEdit": True,
            },
            "ListGrokBotUserStoreFiles": {
                "files": [{"name": "u", "path": "/u", "sizeBytes": "5"}]
            },
            "BeginGrokBotAgentFileUpload": {
                "uploadToken": TOKEN,
                "url": URL,
                "headers": {"h": HEADER},
            },
            "FinishGrokBotAgentFileUpload": {"file": FILE},
            "ListGrokBotLibraryDocs": {"docs": [DOC]},
            "ListGrokBotLibraryPins": {
                "pins": [{"externalDocKey": "k1"}, {"appKey": "app"}]
            },
            "SetGrokBotLibraryPin": {"pins": [{"externalDocKey": "k1"}]},
            "MergeGrokBotLibraryPins": {"pins": [{"appKey": "app"}]},
        }
    )
    monkeypatch.setattr(context, "manager_factory", lambda: fake)

    class Backend:
        def unary(self, service, name, payload):
            return fake.rpc(name, payload)

    monkeypatch.setattr(context, "backend_factory", Backend)
    monkeypatch.setattr(
        bot_files, "_storage_put", lambda url, headers, body: 200, raising=True
    )
    return fake


def sent(fake, rpc):
    return [p for _, n, p in fake.calls if n == rpc]


def test_files_text_and_json(monkeypatch, capsys):
    fake = setup_cli(monkeypatch)
    assert cli.main(["files", "Alpha"]) == 0
    out = capsys.readouterr().out
    assert "a.txt" in out and "2.0 KB" in out and "you can edit" in out
    assert "User-store files:" in out and "/u" in out
    assert cli.main(["files", "Alpha", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["can_edit"] and data["files"][0]["name"] == "a.txt"
    assert data["user_store_files"][0]["path"] == "/u"
    assert sent(fake, "ListGrokBotAgentFiles")[0] == {
        "agentId": "gateway",
        "pageToken": "",
    }


def test_files_refused_part_still_succeeds(monkeypatch, capsys):
    fake = setup_cli(monkeypatch)
    fake.rpcs["ListGrokBotAgentFiles"] = REFUSED
    assert cli.main(["files", "Alpha"]) == 0
    out = capsys.readouterr().out
    assert "Files need a team." in out and "/u" in out


CHANGES = [
    (["--delete", "a.txt"], "DeleteGrokBotAgentFile"),
    (["--delete-user-file", "/u"], "DeleteGrokBotUserStoreFile"),
    (["--upload", "UP"], "BeginGrokBotAgentFileUpload"),
]


@pytest.mark.parametrize("argv,rpc", CHANGES)
def test_files_changes_need_yes(monkeypatch, capsys, tmp_path, argv, rpc):
    fake = setup_cli(monkeypatch)
    upload = tmp_path / "up.txt"
    upload.write_text("hi")
    argv = [str(upload) if a == "UP" else a for a in argv]
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert cli.main(["files", "Alpha", *argv]) == 1
    assert "--yes" in capsys.readouterr().err
    assert not sent(fake, rpc)
    for json_mode in (False, True):
        assert (
            cli.main(
                ["files", "Alpha", *argv, "--yes", *(["--json"] if json_mode else [])]
            )
            == 0
        )
        out = capsys.readouterr()
        if json_mode:
            json.loads(out.out)
        assert out.out.strip()
        assert not any(s in out.out + out.err for s in SECRETS)
    assert len(sent(fake, rpc)) == 2


def test_upload_missing_file_and_refusal(monkeypatch, capsys, tmp_path):
    fake = setup_cli(monkeypatch)
    assert cli.main(["files", "Alpha", "--upload", str(tmp_path / "no"), "--yes"]) == 1
    assert not fake.calls[1:]
    upload = tmp_path / "up.txt"
    upload.write_text("hi")
    fake.rpcs["BeginGrokBotAgentFileUpload"] = REFUSED
    assert cli.main(["files", "Alpha", "--upload", str(upload), "--yes"]) == 1
    assert "Files need a team." in capsys.readouterr().err


def test_library_text_and_json(monkeypatch, capsys):
    fake = setup_cli(monkeypatch)
    assert cli.main(["library", "Alpha"]) == 0
    out = capsys.readouterr().out
    assert "* Plan" in out and "key k1" in out and "Pins:" in out and "app" in out
    assert cli.main(["library", "Alpha", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["docs"][0]["pinned"] is True
    assert [p["kind"] for p in data["pins"]] == ["doc", "app"]
    assert sent(fake, "ListGrokBotLibraryDocs")[0] == {"agentId": "gateway"}


def test_library_refused_part(monkeypatch, capsys):
    fake = setup_cli(monkeypatch)
    fake.rpcs["ListGrokBotLibraryDocs"] = REFUSED
    assert cli.main(["library", "Alpha"]) == 0
    assert "Files need a team." in capsys.readouterr().out


@pytest.mark.parametrize(
    "argv,rpc",
    [
        (["--pin", "k1"], "SetGrokBotLibraryPin"),
        (["--unpin", "k1"], "SetGrokBotLibraryPin"),
        (["--merge-pins", "PINS"], "MergeGrokBotLibraryPins"),
    ],
)
def test_library_changes(monkeypatch, capsys, tmp_path, argv, rpc):
    fake = setup_cli(monkeypatch)
    pins = tmp_path / "pins.json"
    pins.write_text(
        json.dumps([{"kind": "doc", "key": "k1", "pinned_at_ms": 4, "extra": 1}])
    )
    argv = [str(pins) if a == "PINS" else a for a in argv]
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert cli.main(["library", "Alpha", *argv]) == 1
    assert "--yes" in capsys.readouterr().err
    assert not sent(fake, rpc)
    assert cli.main(["library", "Alpha", *argv, "--yes", "--json"]) == 0
    json.loads(capsys.readouterr().out)
    (payload,) = sent(fake, rpc)
    if rpc == "SetGrokBotLibraryPin":
        assert payload["isPinned"] is (argv[0] == "--pin")
        pin = json.loads(json.dumps(payload["pin"]))
        assert pin.pop("pinnedAtMs") is not None
        assert pin == {"externalDocKey": "k1"}
    else:
        assert payload["pins"] == [{"externalDocKey": "k1", "pinnedAtMs": "4"}]


def test_merge_pins_bad_file_and_refusal(monkeypatch, capsys, tmp_path):
    fake = setup_cli(monkeypatch)
    bad = tmp_path / "bad.json"
    bad.write_text('{"x": 1}')
    assert cli.main(["library", "Alpha", "--merge-pins", str(bad), "--yes"]) == 1
    bad.write_text('[{"kind": "nope"}]')
    assert cli.main(["library", "Alpha", "--merge-pins", str(bad), "--yes"]) == 1
    assert not sent(fake, "MergeGrokBotLibraryPins")
    bad.write_text('[{"key": "k1"}]')
    assert cli.main(["library", "Alpha", "--merge-pins", str(bad), "--yes"]) == 1
    assert "each pin needs a kind" in capsys.readouterr().err.lower()
    assert not sent(fake, "MergeGrokBotLibraryPins")
    bad.write_text("[]")
    fake.rpcs["MergeGrokBotLibraryPins"] = REFUSED
    assert cli.main(["library", "Alpha", "--merge-pins", str(bad), "--yes"]) == 1
    assert "Files need a team." in capsys.readouterr().err
    fake.rpcs["MergeGrokBotLibraryPins"] = ConnectError(
        404, json.dumps({"code": "not_found"})
    )
    assert cli.main(["library", "Alpha", "--merge-pins", str(bad), "--yes"]) == 1
    assert "Merged" not in capsys.readouterr().out
