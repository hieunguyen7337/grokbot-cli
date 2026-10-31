import hashlib
import json

import httpx
import pytest

from gbot.service import bot_files
from gbot.service.errors import ServiceError
from gbot.service.fake import load_fake
from gbot.service.transport import FakeTransport
from groken.client import ConnectError

URL = "https://storage.invalid/put?signature=SECRET-URL"
TOKEN = "SECRET-TOKEN"
HEADER = "SECRET-HEADER"


def file_row(name="a.txt", **extra):
    return {
        "name": name,
        "path": "/files/" + name,
        "sizeBytes": "12",
        "contentType": "text/plain",
        "updatedAtMs": "1700000000000",
        "etag": "e",
        **extra,
    }


def test_pagination_three_pages_and_payloads():
    pages = {
        "": {"files": [file_row("a")], "nextPageToken": "p2", "totalBytes": "5"},
        "p2": {"files": [file_row("b")], "nextPageToken": "p3"},
        "p3": {"files": [file_row("c")], "totalBytes": "36", "canEdit": True},
    }
    fake = FakeTransport(
        rpcs={"ListGrokBotAgentFiles": lambda a: pages[str(a["pageToken"])]}
    )
    result = bot_files.agent_files(fake, "bot")
    assert [f.name for f in result.files] == ["a", "b", "c"]
    assert result.total_bytes == 36 and result.can_edit
    assert result.files[0].size_bytes == 12
    assert [c[2] for c in fake.calls] == [
        {"agentId": "bot", "pageToken": t} for t in ("", "p2", "p3")
    ]


def test_repeated_token_and_page_cap_stop():
    fake = FakeTransport(
        rpcs={"ListGrokBotAgentFiles": {"files": [file_row()], "nextPageToken": "x"}}
    )
    assert len(bot_files.agent_files(fake, "bot").files) == 2
    count = iter(range(1000))
    endless = FakeTransport(
        rpcs={
            "ListGrokBotAgentFiles": lambda a: {
                "files": [file_row()],
                "nextPageToken": f"t{next(count)}",
            }
        }
    )
    assert len(bot_files.agent_files(endless, "bot").files) == bot_files.MAX_PAGES


@pytest.mark.parametrize("reply", [{}, {"files": "x"}, {"files": [1, {}]}])
def test_odd_lists(reply):
    fake = FakeTransport(rpcs={"ListGrokBotAgentFiles": reply})
    result = bot_files.agent_files(fake, "bot")
    assert result.total_bytes == 0 and not result.can_edit
    assert len(result.files) == (1 if reply.get("files") == [1, {}] else 0)


def begin_fake(finish):
    return FakeTransport(
        rpcs={
            "BeginGrokBotAgentFileUpload": {
                "uploadToken": TOKEN,
                "finalName": "n.txt",
                "url": URL,
                "headers": {"x-amz-meta": HEADER, "Content-Type": "text/plain"},
            },
            "FinishGrokBotAgentFileUpload": finish,
        }
    )


def test_upload_hash_size_type_and_put(tmp_path):
    path = tmp_path / "n.txt"
    path.write_bytes(b"hello world\n")
    fake = begin_fake({"file": file_row("n.txt")})
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)

    def put(url, headers, body):
        with httpx.Client(transport=transport) as client:
            return client.put(url, headers=headers, content=body).status_code

    result = bot_files.upload_file(fake, "bot", path, put=put)
    assert result.name == "n.txt"
    begin, finish = fake.calls[0][2], fake.calls[1][2]
    assert begin == {
        "agentId": "bot",
        "fileName": "n.txt",
        "sizeBytes": "12",
        "sha256Hex": hashlib.sha256(b"hello world\n").hexdigest(),
        "contentType": "text/plain",
    }
    assert finish == {"agentId": "bot", "uploadToken": TOKEN}
    assert len(seen) == 1
    assert str(seen[0].url) == URL and seen[0].method == "PUT"
    assert seen[0].headers["x-amz-meta"] == HEADER
    assert seen[0].content == b"hello world\n"


def test_default_put_uses_httpx_with_long_timeout(tmp_path, monkeypatch):
    path = tmp_path / "blob.unknownext"
    path.write_bytes(b"x")
    calls = []

    def fake_put(url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(204)

    monkeypatch.setattr(httpx, "put", fake_put)
    fake = begin_fake({"file": file_row("blob")})
    bot_files.upload_file(fake, "bot", path)
    assert fake.calls[0][2]["contentType"] == "application/octet-stream"
    assert calls[0][1]["timeout"] == 300
    assert calls[0][1]["content"] == b"x"
    assert calls[0][1]["headers"] == {
        "x-amz-meta": HEADER,
        "Content-Type": "text/plain",
    }


def test_put_refusal_hides_secrets(tmp_path):
    path = tmp_path / "n.txt"
    path.write_bytes(b"x")
    fake = begin_fake({"file": file_row()})
    with pytest.raises(ServiceError) as caught:
        bot_files.upload_file(fake, "bot", path, put=lambda u, h, b: 403)
    assert str(caught.value) == "Storage refused the upload (HTTP 403)."
    for secret in (URL, "SECRET-URL", TOKEN, HEADER):
        assert secret not in str(caught.value)
    assert not any(c[1] == "FinishGrokBotAgentFileUpload" for c in fake.calls)


def test_put_network_error_hides_url(tmp_path):
    path = tmp_path / "n.txt"
    path.write_bytes(b"x")

    def put(url, headers, body):
        raise httpx.ConnectError("failed " + url)

    with pytest.raises(ServiceError) as caught:
        bot_files.upload_file(begin_fake({}), "bot", path, put=put)
    assert "SECRET" not in str(caught.value) and caught.value.__cause__ is None


def test_finish_without_file_is_error(tmp_path):
    path = tmp_path / "n.txt"
    path.write_bytes(b"x")
    with pytest.raises(ServiceError):
        bot_files.upload_file(begin_fake({}), "bot", path, put=lambda u, h, b: 200)


def test_begin_without_target_is_error(tmp_path):
    path = tmp_path / "n.txt"
    path.write_bytes(b"x")
    fake = FakeTransport(rpcs={"BeginGrokBotAgentFileUpload": {}})
    with pytest.raises(ServiceError):
        bot_files.upload_file(fake, "bot", path, put=lambda u, h, b: 200)


def test_secrets_not_in_repr_or_demo():
    fake = load_fake()
    assert bot_files.agent_files(fake.transport, "demo-helper").files == ()
    assert bot_files.user_store_files(fake.transport, "demo-helper") == ()
    assert "SECRET" not in repr(bot_files.AgentFile("n", "p", 1, "t", 2, "e"))


def test_deletes_and_user_store():
    fake = FakeTransport(
        rpcs={
            "DeleteGrokBotAgentFile": {},
            "DeleteGrokBotUserStoreFile": {},
            "ListGrokBotUserStoreFiles": {
                "files": [
                    {"name": "u", "path": "/u", "sizeBytes": "3", "updatedAtMs": "9"},
                    "odd",
                ]
            },
        }
    )
    bot_files.delete_agent_file(fake, "bot", "a.txt")
    bot_files.delete_user_store_file(fake, "bot", "/u")
    (item,) = bot_files.user_store_files(fake, "bot")
    assert (item.name, item.path, item.size_bytes, item.updated_at_ms) == (
        "u",
        "/u",
        3,
        9,
    )
    assert [c[2] for c in fake.calls[:2]] == [
        {"agentId": "bot", "name": "a.txt"},
        {"agentId": "bot", "path": "/u"},
    ]


def test_connect_error_propagates():
    fake = FakeTransport(
        rpcs={"ListGrokBotAgentFiles": ConnectError(500, json.dumps({"code": "x"}))}
    )
    with pytest.raises(ConnectError):
        bot_files.agent_files(fake, "bot")
