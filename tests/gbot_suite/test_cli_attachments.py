import base64
import itertools
import json
from pathlib import Path
from types import SimpleNamespace

from gbot import cli, context
from gbot.commands import ask
from gbot.service import attachments
from gbot.service.fake import FakeService
from gbot.service.transport import FakeTransport
from groken.client import ConnectError


def setup_cli(monkeypatch, entries=(), upload_error=False):
    transport = FakeTransport(
        {
            "listAgents": [{"id": "bot", "name": "Alpha"}],
            "getAgentTranscriptTail": {"entries": list(entries)},
            "uploadAttachmentChunk": ConnectError(500, "upload failed")
            if upload_error
            else {"committedPath": "/uploaded"},
            "sendPrompt": {"accepted": True},
            "readAttachmentChunk": {
                "bytesBase64": base64.b64encode(b"saved text").decode(),
                "totalSize": 10,
                "resolvedName": "saved.txt",
            },
        }
    )
    monkeypatch.setattr(context, "manager_factory", lambda: transport)
    return transport


def test_send_upload_before_send(tmp_path, monkeypatch, capsys):
    transport = setup_cli(monkeypatch)
    file = tmp_path / "file.txt"
    file.write_text("hello", encoding="utf-8")
    assert cli.main(["send", "--bot", "Alpha", "--attach", str(file), "--json"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["attachments"] == [{"name": "file.txt", "path": "/uploaded"}]
    names = [c[1] for c in transport.calls]
    assert names.index("uploadAttachmentChunk") < names.index("sendPrompt")
    assert transport.calls[-1][2]["attachmentPaths"] == ["/uploaded"]
    assert transport.calls[-1][2]["attachmentNames"] == ["file.txt"]
    assert transport.calls[-1][2]["prompt"] == ""


def test_upload_error_never_sends(tmp_path, monkeypatch, capsys):
    transport = setup_cli(monkeypatch, upload_error=True)
    file = tmp_path / "file.txt"
    file.write_bytes(b"hello")
    for command in ("send", "ask"):
        assert (
            cli.main([command, "--bot", "Alpha", "--attach", str(file), "hello"]) == 1
        )
        assert "upload failed" in capsys.readouterr().err
    assert not any(c[1] == "sendPrompt" for c in transport.calls)


def test_later_upload_error_never_sends(tmp_path, monkeypatch, capsys):
    transport = setup_cli(monkeypatch)
    file = tmp_path / "file.txt"
    file.write_bytes(b"hello")
    calls = []

    def upload(args):
        calls.append(args)
        if len(calls) == 2:
            raise ConnectError(401, "upload refused")
        return {"committedPath": "/first"}

    transport.commands["uploadAttachmentChunk"] = upload
    assert (
        cli.main(
            ["send", "--bot", "Alpha", "--attach", str(file), "--attach", str(file)]
        )
        == 1
    )
    assert "upload refused" in capsys.readouterr().err
    assert len(calls) == 2
    assert not any(c[1] == "sendPrompt" for c in transport.calls)


def test_save_local(tmp_path, monkeypatch, capsys):
    transport = setup_cli(
        monkeypatch,
        [
            {
                "id": "entry-123",
                "seq": 1,
                "kind": "user-attachment",
                "file_path": "/file",
                "file_name": "test.txt",
            }
        ],
    )
    dest = tmp_path / "out"
    assert (
        cli.main(
            [
                "save",
                "--bot",
                "Alpha",
                "--session",
                "session",
                "--out",
                str(dest),
                "entry-",
            ]
        )
        == 0
    )
    assert str(dest / "test.txt") in capsys.readouterr().out
    assert (dest / "test.txt").read_bytes() == b"saved text"
    assert transport.calls[1][2]["sessionId"] == "session"


def test_save_default_downloads(tmp_path, monkeypatch, capsys):
    setup_cli(
        monkeypatch,
        [
            {
                "id": "entry-123",
                "seq": 1,
                "kind": "user-attachment",
                "file_path": "/file",
                "file_name": "test.txt",
            }
        ],
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert cli.main(["save", "--bot", "Alpha", "--json", "entry-123"]) == 0
    dest = tmp_path / "Downloads" / "test.txt"
    assert json.loads(capsys.readouterr().out) == {"saved": [str(dest)], "links": []}
    assert dest.read_bytes() == b"saved text"


def test_save_links_and_no_files(tmp_path, monkeypatch, capsys):
    transport = setup_cli(
        monkeypatch,
        [
            {
                "id": "entry-123",
                "seq": 1,
                "kind": "send-message",
                "message": {"type": "attachment", "url": "https://host/file"},
            }
        ],
    )
    argv = ["save", "--bot", "Alpha", "--out", str(tmp_path), "entry-123"]
    assert cli.main(argv) == 0
    assert "link: https://host/file" in capsys.readouterr().out
    assert cli.main(argv + ["--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "saved": [],
        "links": ["https://host/file"],
    }
    assert not any(c[1] == "readAttachmentChunk" for c in transport.calls)
    transport.commands["getAgentTranscriptTail"] = {
        "entries": [{"id": "entry-123", "seq": 1}]
    }
    assert cli.main(argv) == 1
    assert "no files" in capsys.readouterr().err
    assert not list(tmp_path.iterdir())


def test_save_ambiguous_and_short(tmp_path, monkeypatch, capsys):
    setup_cli(
        monkeypatch, [{"id": "entry-123", "seq": 1}, {"id": "entry-456", "seq": 2}]
    )
    for ref, message in (
        ("entry-", "Ambiguous"),
        ("entr", "at least 6"),
        ("unknown", "Unknown"),
    ):
        assert cli.main(["save", "--bot", "Alpha", "--out", str(tmp_path), ref]) == 1
        assert message in capsys.readouterr().err


def test_ask_attached_uses_service_stream(tmp_path, monkeypatch, capsys):
    setup_cli(monkeypatch)
    ticks = itertools.count()
    monkeypatch.setattr(
        ask, "time", SimpleNamespace(monotonic=lambda: next(ticks) * 0.5)
    )

    class ReplyService(FakeService):
        def send(self, bot_id, text, **kwargs):
            assert self._sources and self._sources[0].followed == {(bot_id, None)}
            result = super().send(bot_id, text, **kwargs)
            self.reply(bot_id, "Here is the reply")
            return result

    service = ReplyService()
    bot = service.roster()[0].id
    service.state.rows[0]["id"] = "bot"
    service.state.rows[0].pop("awaitingUserResponse", None)
    service.state.transcripts["bot"] = service.state.transcripts.pop(bot)
    monkeypatch.setattr(context, "service_factory", lambda: service)
    file = tmp_path / "file.txt"
    file.write_bytes(b"hello")
    assert cli.main(["ask", "--bot", "Alpha", "--attach", str(file), "--json"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["reply"] == "Here is the reply"
    assert output["attachments"] == [{"name": "file.txt", "path": "/uploaded"}]
    assert (
        attachments.entry_files(service.transcript("bot").entries[-2])[0].path
        == "/uploaded"
    )
