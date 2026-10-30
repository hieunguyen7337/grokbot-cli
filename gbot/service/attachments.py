"""Gateway attachment uploads, previews and downloads shared by terminal clients."""

import base64
import re
import sys
import tempfile
import unicodedata
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from groken.client import ConnectError

from .models import Entry
from .transport import Transport

CHUNK = 4 * 1024 * 1024
LIMIT = 25 * 1024 * 1024
VIDEO_LIMIT = 200 * 1024 * 1024
_VIDEO = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}
COMMANDS = dict.fromkeys(
    (
        "uploadAttachmentChunk",
        "uploadAttachment",
        "readAttachmentText",
        "readAttachmentChunk",
    ),
    "object",
)
_DEMO = b"Hello from the bot.\n"
DEMO_COMMANDS = {
    "uploadAttachmentChunk": {"committedPath": "/attachments/example.txt"},
    "uploadAttachment": {"path": "/attachments/example.txt"},
    "readAttachmentText": {
        "kind": "text",
        "bytes": len(_DEMO),
        "text": _DEMO.decode(),
        "truncated": False,
    },
    "readAttachmentChunk": {
        "bytesBase64": base64.b64encode(_DEMO).decode(),
        "mime": "text/plain",
        "totalSize": len(_DEMO),
        "resolvedName": "example.txt",
    },
}


@dataclass(frozen=True)
class Attachment:
    path: str
    name: str


@dataclass(frozen=True)
class TextPreview:
    kind: str
    bytes: int
    text: str = ""
    truncated: bool = False


@dataclass(frozen=True)
class FileRef:
    path: str | None
    name: str
    size: int | None = None
    remote_url: str | None = None


def upload(
    transport: Transport,
    bot_id: str,
    file: Path,
    *,
    progress: Callable[[int, int], None] | None = None,
) -> Attachment:
    if not file.is_file():
        raise ValueError(f"Not a file: {file}")
    total = file.stat().st_size
    limit = VIDEO_LIMIT if file.suffix.lower() in _VIDEO else LIMIT
    if total == 0:
        raise ValueError("Cannot upload an empty file.")
    if total > limit:
        raise ValueError(f"File exceeds the {limit // (1024 * 1024)} MiB upload limit.")
    upload_id = str(uuid.uuid4())
    with file.open("rb") as source:
        offset = 0
        while offset < total:
            chunk = source.read(min(CHUNK, total - offset))
            if not chunk:
                raise ValueError("File changed during upload.")
            try:
                reply = transport.command(
                    "uploadAttachmentChunk",
                    {
                        "agentId": bot_id,
                        "uploadId": upload_id,
                        "filename": file.name,
                        "offset": offset,
                        "totalSize": total,
                        "bytesBase64": base64.b64encode(chunk).decode(),
                    },
                )
            except ConnectError as exc:
                if offset != 0 or exc.status != 404:
                    raise
                source.seek(0)
                reply = transport.command(
                    "uploadAttachment",
                    {
                        "agentId": bot_id,
                        "filename": file.name,
                        "bytesBase64": base64.b64encode(source.read()).decode(),
                    },
                )
                path = reply.get("path") if isinstance(reply, Mapping) else None
                if not isinstance(path, str) or not path:
                    raise ValueError("Upload did not commit")
                if progress:
                    progress(total, total)
                return Attachment(path, file.name)
            offset += len(chunk)
            if progress:
                progress(offset, total)
            path = reply.get("committedPath") if isinstance(reply, Mapping) else None
            if isinstance(path, str) and path:
                return Attachment(path, file.name)
    raise ValueError("Upload did not commit")


def read_text(transport: Transport, bot_id: str, path: str) -> TextPreview | None:
    reply = transport.command("readAttachmentText", {"agentId": bot_id, "path": path})
    if reply is None:
        return None
    if not isinstance(reply, Mapping) or reply.get("kind") not in ("text", "binary"):
        raise ValueError("Invalid attachment preview.")
    size = reply.get("bytes")
    if type(size) is not int or size < 0:
        raise ValueError("Invalid attachment size.")
    return TextPreview(
        str(reply["kind"]),
        size,
        str(reply.get("text", "")),
        reply.get("truncated") is True,
    )


def safe_name(text: str) -> str:
    name = re.split(r"[/\\]", text)[-1]
    name = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", name)
    # Invisible format characters (such as a right-to-left override) could disguise the extension.
    name = "".join(c for c in name if unicodedata.category(c) != "Cf")
    name = re.sub(r'[<>:"/\\|?*]', "_", name).strip(" .") or "file"
    if re.fullmatch(
        r"CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]", name.split(".")[0], re.IGNORECASE
    ):
        name = "_" + name
    if len(name) > 120:
        suffix = Path(name).suffix[:119]
        name = name[: 120 - len(suffix)] + suffix
    return name


def download(
    transport: Transport,
    bot_id: str,
    path: str,
    dest_dir: Path,
    *,
    name: str | None = None,
    max_bytes: int = 1024**3,
    progress: Callable[[int, int], None] | None = None,
) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        offset = 0
        total: int | None = None
        filename = ""
        with tempfile.NamedTemporaryFile(dir=dest_dir, delete=False) as target:
            temporary = Path(target.name)
            while total is None or offset < total:
                reply = transport.command(
                    "readAttachmentChunk",
                    {
                        "agentId": bot_id,
                        "path": path,
                        "offset": offset,
                        "length": CHUNK,
                    },
                )
                if reply is None:
                    raise FileNotFoundError(path)
                if not isinstance(reply, Mapping):
                    raise TypeError("Invalid attachment chunk.")
                size = reply.get("totalSize")
                if (
                    type(size) is not int
                    or size < 0
                    or (total is not None and total != size)
                ):
                    raise ValueError("Invalid attachment size.")
                if size > max_bytes:
                    raise ValueError("Attachment exceeds maximum download size.")
                if total is None:
                    resolved = reply.get("resolvedName")
                    filename = safe_name(
                        name or (resolved if isinstance(resolved, str) else "") or path
                    )
                total = size
                encoded = reply.get("bytesBase64")
                if not isinstance(encoded, str):
                    raise TypeError("Invalid attachment chunk.")
                data = base64.b64decode(encoded, validate=True)
                if (
                    len(data) > CHUNK
                    or offset + len(data) > total
                    or (not data and offset < total)
                ):
                    raise ValueError("Invalid attachment chunk length.")
                target.write(data)
                offset += len(data)
                if progress:
                    progress(offset, total)
        destination = dest_dir / filename
        index = 0
        while True:
            try:
                if sys.platform == "win32":
                    temporary.rename(destination)
                    temporary = None
                else:
                    # POSIX rename replaces existing files; publish without overwriting.
                    destination.hardlink_to(temporary)
                break
            except FileExistsError:
                index += 1
                original = Path(filename)
                destination = dest_dir / f"{original.stem} ({index}){original.suffix}"
        return destination
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def entry_files(entry: Entry) -> list[FileRef]:
    raw = entry.raw
    result: list[FileRef] = []

    def add(url: object, name: object = None, size: object = None) -> None:
        if not isinstance(url, str) or not url.strip():
            return
        remote = url.startswith(("http://", "https://"))
        result.append(
            FileRef(
                None if remote else url,
                name if isinstance(name, str) and name else safe_name(url),
                size if type(size) is int and size >= 0 else None,
                url if remote else None,
            )
        )

    if raw.get("kind") == "user-attachment":
        add(raw.get("file_path"), raw.get("file_name"), raw.get("byteSize"))
    message = raw.get("message")
    if (
        isinstance(message, Mapping)
        and raw.get("kind") == "send-message"
        and message.get("type") == "attachment"
    ):
        source = message.get("source_path")
        add(
            source if isinstance(source, str) and source else message.get("url"),
            message.get("file_name"),
            message.get("byteSize"),
        )
    for container in (raw, message):
        items = container.get("attachments") if isinstance(container, Mapping) else None
        if isinstance(items, list):
            for item in items:
                if isinstance(item, Mapping):
                    add(item.get("url"), item.get("file_name"), item.get("byteSize"))
    return result
