"""Bot files (uploaded by the person) and user-store files of one bot."""

import hashlib
import mimetypes
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

import httpx

from .errors import ServiceError
from .transport import Transport

RPCS = frozenset(
    (
        "ListGrokBotAgentFiles",
        "BeginGrokBotAgentFileUpload",
        "FinishGrokBotAgentFileUpload",
        "DeleteGrokBotAgentFile",
        "ListGrokBotUserStoreFiles",
        "DeleteGrokBotUserStoreFile",
    )
)
MAX_PAGES = 100
Put = Callable[[str, Mapping[str, str], bytes], int]


@dataclass(frozen=True)
class AgentFile:
    name: str
    path: str
    size_bytes: int
    content_type: str
    updated_at_ms: int
    etag: str


@dataclass(frozen=True)
class AgentFiles:
    files: tuple[AgentFile, ...]
    total_bytes: int
    can_edit: bool


@dataclass(frozen=True)
class UserStoreFile:
    name: str
    path: str
    size_bytes: int
    updated_at_ms: int


def _int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return int(str(value))
    except ValueError:
        return 0


def _rows(value: object) -> tuple[dict[str, object], ...]:
    return (
        tuple(dict(row) for row in value if isinstance(row, dict))
        if isinstance(value, list)
        else ()
    )


def _file(row: Mapping[str, object]) -> AgentFile:
    return AgentFile(
        str(row.get("name") or ""),
        str(row.get("path") or ""),
        _int(row.get("sizeBytes")),
        str(row.get("contentType") or ""),
        _int(row.get("updatedAtMs")),
        str(row.get("etag") or ""),
    )


def agent_files(transport: Transport, bot_id: str) -> AgentFiles:
    """Every page of the bot's files; stops on a repeated token or after MAX_PAGES pages."""
    files: list[AgentFile] = []
    total = 0
    can_edit = False
    token = ""
    seen: set[str] = set()
    for _ in range(MAX_PAGES):
        reply = transport.rpc(
            "ListGrokBotAgentFiles", {"agentId": bot_id, "pageToken": token}
        )
        files.extend(_file(row) for row in _rows(reply.get("files")))
        total = _int(reply.get("totalBytes"))
        can_edit = bool(reply.get("canEdit"))
        seen.add(token)
        token = str(reply.get("nextPageToken") or "")
        if not token or token in seen:
            break
    return AgentFiles(tuple(files), total, can_edit)


def _storage_put(url: str, headers: Mapping[str, str], body: bytes) -> int:
    return httpx.put(url, headers=dict(headers), content=body, timeout=300).status_code


def upload_file(
    transport: Transport,
    bot_id: str,
    path: Path,
    *,
    content_type: str | None = None,
    put: Put | None = None,
) -> AgentFile:
    data = path.read_bytes()
    kind = (
        content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    )
    begin = transport.rpc(
        "BeginGrokBotAgentFileUpload",
        {
            "agentId": bot_id,
            "fileName": path.name,
            "sizeBytes": str(len(data)),
            "sha256Hex": hashlib.sha256(data).hexdigest(),
            "contentType": kind,
        },
    )
    url = begin.get("url")
    token = begin.get("uploadToken")
    if not isinstance(url, str) or not url or not isinstance(token, str) or not token:
        raise ServiceError("The server did not return an upload target.")
    raw = begin.get("headers")
    headers = (
        {str(key): str(value) for key, value in raw.items()}
        if isinstance(raw, dict)
        else {}
    )
    try:
        status = (put or _storage_put)(url, headers, data)
    except httpx.HTTPError:
        # The error text can carry the signed URL.
        raise ServiceError("Storage could not be reached for the upload.") from None
    if not 200 <= status < 300:
        raise ServiceError(f"Storage refused the upload (HTTP {status}).")
    reply = transport.rpc(
        "FinishGrokBotAgentFileUpload", {"agentId": bot_id, "uploadToken": token}
    )
    row = reply.get("file")
    if not isinstance(row, dict):
        raise ServiceError("The server did not confirm the upload.")
    return _file(row)


def delete_agent_file(transport: Transport, bot_id: str, name: str) -> None:
    transport.rpc("DeleteGrokBotAgentFile", {"agentId": bot_id, "name": name})


def user_store_files(transport: Transport, bot_id: str) -> tuple[UserStoreFile, ...]:
    reply = transport.rpc("ListGrokBotUserStoreFiles", {"agentId": bot_id})
    return tuple(
        UserStoreFile(
            str(row.get("name") or ""),
            str(row.get("path") or ""),
            _int(row.get("sizeBytes")),
            _int(row.get("updatedAtMs")),
        )
        for row in _rows(reply.get("files"))
    )


def delete_user_store_file(transport: Transport, bot_id: str, path: str) -> None:
    transport.rpc("DeleteGrokBotUserStoreFile", {"agentId": bot_id, "path": path})


DEMO_RPCS: dict[str, object] = {name: {} for name in RPCS}
