import base64

import pytest

from gbot.protocol import USED_COMMANDS
from gbot.service import attachments as a
from gbot.service import conversation
from gbot.service.broker import CredentialBroker
from gbot.service.client import GbotService
from gbot.service.fake import FakeService
from gbot.service.models import Entry
from gbot.service.transport import FakeTransport
from groken.client import ConnectError


def test_upload_chunks(tmp_path, monkeypatch):
    monkeypatch.setattr(a, "CHUNK", 10)
    file = tmp_path / "data.txt"
    file.write_bytes(b"0123456789")
    progress = []
    transport = FakeTransport({"uploadAttachmentChunk": {"committedPath": "/data"}})
    assert a.upload(
        transport, "bot", file, progress=lambda *p: progress.append(p)
    ) == a.Attachment("/data", "data.txt")
    assert transport.calls[0][2] == {
        "agentId": "bot",
        "uploadId": transport.calls[0][2]["uploadId"],
        "filename": "data.txt",
        "offset": 0,
        "totalSize": 10,
        "bytesBase64": base64.b64encode(file.read_bytes()).decode(),
    }
    assert progress == [(10, 10)]
    file.write_bytes(b"x" * 15)
    transport = FakeTransport(
        {
            "uploadAttachmentChunk": lambda args: {
                "committedPath": "/done" if args["offset"] else None
            }
        }
    )
    assert a.upload(transport, "bot", file).path == "/done"
    assert [c[2]["offset"] for c in transport.calls] == [0, 10]
    assert len({c[2]["uploadId"] for c in transport.calls}) == 1
    assert [
        len(base64.b64decode(str(c[2]["bytesBase64"]))) for c in transport.calls
    ] == [
        10,
        5,
    ]


def test_upload_refusals_and_fallback(tmp_path, monkeypatch):
    file = tmp_path / "data.txt"
    file.touch()
    transport = FakeTransport()
    for path in (file, tmp_path):
        with pytest.raises(ValueError):
            a.upload(transport, "bot", path)
    monkeypatch.setattr(a, "LIMIT", 3)
    file.write_bytes(b"1234")
    with pytest.raises(ValueError, match="limit"):
        a.upload(transport, "bot", file)
    assert not transport.calls
    file.write_bytes(b"123")
    transport.commands["uploadAttachment"] = {"path": "/fallback"}
    assert a.upload(transport, "bot", file).path == "/fallback"
    assert [c[1] for c in transport.calls] == [
        "uploadAttachmentChunk",
        "uploadAttachment",
    ]
    transport.commands["uploadAttachmentChunk"] = {"committedPath": None}
    with pytest.raises(ValueError, match="Upload did not commit"):
        a.upload(transport, "bot", file)
    transport.commands["uploadAttachmentChunk"] = ConnectError(500, "failure")
    with pytest.raises(ConnectError):
        a.upload(transport, "bot", file)


def test_late_404_does_not_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(a, "CHUNK", 2)
    file = tmp_path / "a"
    file.write_bytes(b"abc")

    def chunk(args):
        if args["offset"]:
            raise ConnectError(404, "late")
        return {"committedPath": None}

    transport = FakeTransport({"uploadAttachmentChunk": chunk})
    with pytest.raises(ConnectError):
        a.upload(transport, "bot", file)
    assert all(c[1] == "uploadAttachmentChunk" for c in transport.calls)


def test_video_size_class(tmp_path, monkeypatch):
    monkeypatch.setattr(a, "LIMIT", 2)
    monkeypatch.setattr(a, "VIDEO_LIMIT", 4)
    file = tmp_path / "clip.MP4"
    file.write_bytes(b"1234")
    transport = FakeTransport(a.DEMO_COMMANDS)
    assert a.upload(transport, "bot", file).name == "clip.MP4"
    file.write_bytes(b"12345")
    transport.calls.clear()
    with pytest.raises(ValueError, match="limit"):
        a.upload(transport, "bot", file)
    assert not transport.calls


def test_send_and_fake():
    files = [a.Attachment("/b", "b"), a.Attachment("/a", "a")]
    transport = FakeTransport(
        {"getAgentTranscriptTail": {"entries": []}, "sendPrompt": {"accepted": True}}
    )
    assert conversation.send(transport, "bot", "", attachments=files).accepted
    args = transport.calls[-1][2]
    assert args["attachmentPaths"] == ["/b", "/a"]
    assert args["attachmentNames"] == ["b", "a"]
    with pytest.raises(ValueError, match="Prompt must not be empty"):
        conversation.send(transport, "bot", "")
    fake = FakeService()
    bot = fake.roster()[0].id
    fake.send(bot, "", attachments=files)
    refs = a.entry_files(fake.transcript(bot).entries[-1])
    assert [ref.path for ref in refs] == ["/b", "/a"]
    with pytest.raises(ValueError):
        fake.send(bot, "")
    client = GbotService(CredentialBroker(dict))
    client.transport = transport
    assert client.send("bot", "", attachments=files).accepted
    assert transport.calls[-1][2]["attachmentPaths"] == ["/b", "/a"]


def test_download_and_collision(tmp_path, monkeypatch):
    monkeypatch.setattr(a, "CHUNK", 3)
    data = b"abcdef"

    def chunk(args):
        offset = args["offset"]
        return {
            "totalSize": 6,
            "resolvedName": "../test.txt",
            "bytesBase64": base64.b64encode(data[offset : offset + 3]).decode(),
        }

    transport = FakeTransport({"readAttachmentChunk": chunk})
    progress = []
    first = a.download(
        transport, "bot", "/file", tmp_path, progress=lambda *p: progress.append(p)
    )
    assert first.name == "test.txt"
    assert first.read_bytes() == data
    assert progress == [(3, 6), (6, 6)]
    second = a.download(transport, "bot", "/file", tmp_path)
    assert second.name == "test (1).txt"
    assert second.read_bytes() == data
    assert [c[2]["offset"] for c in transport.calls] == [0, 3, 0, 3]
    assert all(
        c[2]["agentId"] == "bot" and c[2]["length"] == 3 for c in transport.calls
    )


@pytest.mark.parametrize("failure", ["missing", "large", "midway", "stalled"])
def test_download_cleanup(tmp_path, monkeypatch, failure):
    monkeypatch.setattr(a, "CHUNK", 2)

    def chunk(args):
        if failure == "missing":
            return None
        if args["offset"] and failure == "midway":
            raise ConnectError(500, "failed")
        return {"totalSize": 4, "bytesBase64": "" if failure == "stalled" else "YWI="}

    transport = FakeTransport({"readAttachmentChunk": chunk})
    with pytest.raises((ValueError, FileNotFoundError, ConnectError)):
        a.download(
            transport,
            "bot",
            "/file",
            tmp_path,
            max_bytes=3 if failure == "large" else 100,
        )
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("../../etc/passwd", "passwd"),
        (r"a\b\c.txt", "c.txt"),
        ("CON.txt", "_CON.txt"),
        ("lpt9", "_lpt9"),
        ("", "file"),
        (' .a\x00\n<>:"|?*. ', "a_______"),
        ("invoice\u202etxt.exe", "invoicetxt.exe"),
    ],
)
def test_safe_name(text, expected):
    assert a.safe_name(text) == expected


def test_long_name_and_previews():
    name = a.safe_name("x" * 300 + ".txt")
    assert len(name) == 120 and name.endswith(".txt")
    transport = FakeTransport(a.DEMO_COMMANDS)
    preview = a.read_text(transport, "bot", "/file")
    assert preview is not None and preview.text == "Hello from the bot.\n"
    transport.commands["readAttachmentText"] = {"kind": "binary", "bytes": 4}
    assert a.read_text(transport, "bot", "/file") == a.TextPreview("binary", 4)
    transport.commands["readAttachmentText"] = None
    assert a.read_text(transport, "bot", "/file") is None
    assert set(a.COMMANDS) <= USED_COMMANDS.keys()


def test_entry_files():
    def files(raw):
        return a.entry_files(
            Entry("bot", "id", 1, str(raw.get("kind", "message")), raw=raw)
        )

    assert files(
        {"kind": "user-attachment", "file_path": "/a", "file_name": "A", "byteSize": 3}
    ) == [a.FileRef("/a", "A", 3)]
    assert files(
        {
            "kind": "send-message",
            "message": {
                "type": "attachment",
                "source_path": "/b",
                "url": "https://host/b",
                "file_name": "B",
            },
        }
    ) == [a.FileRef("/b", "B")]
    assert (
        files(
            {
                "kind": "send-message",
                "message": {"type": "attachment", "url": "https://host/b"},
            }
        )[0].remote_url
        == "https://host/b"
    )
    refs = files(
        {
            "attachments": [
                None,
                {},
                {"url": 3},
                {"url": "/c", "byteSize": 9},
                {"url": "http://host/d"},
            ]
        }
    )
    assert refs[0] == a.FileRef("/c", "c", 9)
    assert refs[1].path is None and refs[1].remote_url == "http://host/d"
    assert files({"kind": "user-attachment", "file_path": None}) == []
    assert (
        files({"message": {"attachments": [{"url": "/nested"}]}})[0].path == "/nested"
    )
