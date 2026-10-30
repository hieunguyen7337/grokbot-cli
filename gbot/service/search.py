"""Search gateway messages and media."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from .transport import Transport

COMMANDS = dict.fromkeys(
    ("searchAgents", "searchMedia", "searchConversation"), "object"
)
DEMO_COMMANDS = {
    "searchAgents": [
        {
            "agentId": "demo-helper",
            "entryId": "demo",
            "role": "assistant",
            "snippet": "A helpful answer",
            "timestampMs": 0,
        }
    ],
    "searchMedia": [
        {
            "agentId": "demo-helper",
            "entryId": "demo",
            "ext": "pdf",
            "fileName": "report.pdf",
            "kind": "pdf",
            "mime": "application/pdf",
            "width": None,
            "height": None,
            "timestampMs": 0,
        }
    ],
    "searchConversation": {"matches": [], "isComplete": True},
}


@dataclass(frozen=True)
class MessageMatch:
    agent_id: str
    entry_id: str
    role: str
    snippet: str
    timestamp_ms: int


@dataclass(frozen=True)
class MediaMatch:
    agent_id: str
    entry_id: str
    ext: str
    file_name: str
    kind: str
    mime: str | None
    width: int | None
    height: int | None
    timestamp_ms: int


@dataclass(frozen=True)
class ConversationMatch:
    entry_id: str
    role: str
    seq: int
    snippet: str
    timestamp_ms: int


@dataclass(frozen=True)
class ConversationSearch:
    matches: list[ConversationMatch]
    complete: bool


def _number(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _parse(
    rows: list[object], fields: tuple[str, ...], numbers: tuple[str, ...], cls: type
) -> list:
    result = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        if not all(isinstance(row.get(f), str) for f in fields) or not all(
            _number(row.get(f)) for f in numbers
        ):
            continue
        if cls is MediaMatch:
            if any(
                row.get(f) is not None and not _number(row.get(f))
                for f in ("width", "height")
            ) or (row.get("mime") is not None and not isinstance(row.get("mime"), str)):
                continue
            result.append(
                cast(Any, cls)(
                    *(row[f] for f in fields),
                    row.get("mime"),
                    row.get("width"),
                    row.get("height"),
                    row["timestampMs"],
                )
            )
        else:
            result.append(cls(*(row[f] for f in fields), *(row[f] for f in numbers)))
    return result


def messages(transport: Transport, query: str, limit: int = 50) -> list[MessageMatch]:
    reply = transport.command("searchAgents", {"query": query, "limit": limit})
    if not isinstance(reply, list):
        raise ValueError("Unexpected reply to searchAgents")  # noqa: TRY004 - protocol contract
    return _parse(
        reply, ("agentId", "entryId", "role", "snippet"), ("timestampMs",), MessageMatch
    )


def media(transport: Transport, query: str, limit: int = 50) -> list[MediaMatch]:
    reply = transport.command("searchMedia", {"query": query, "limit": limit})
    if not isinstance(reply, list):
        raise ValueError("Unexpected reply to searchMedia")  # noqa: TRY004 - protocol contract
    return _parse(
        reply,
        ("agentId", "entryId", "ext", "fileName", "kind"),
        ("timestampMs",),
        MediaMatch,
    )


def conversation(
    transport: Transport,
    bot_id: str,
    query: str,
    before_seq: int | None = None,
    limit: int = 50,
) -> ConversationSearch:
    args: dict[str, object] = {"agentId": bot_id, "query": query, "limit": limit}
    if before_seq is not None:
        args["beforeSeq"] = before_seq
    reply = transport.command("searchConversation", args)
    if (
        not isinstance(reply, Mapping)
        or not isinstance(reply.get("matches"), list)
        or not isinstance(reply.get("isComplete"), bool)
    ):
        raise ValueError("Unexpected reply to searchConversation")  # noqa: TRY004 - protocol contract
    # ConversationMatch places seq before snippet.
    matches = []
    for row in reply["matches"]:
        if (
            isinstance(row, Mapping)
            and all(isinstance(row.get(f), str) for f in ("entryId", "role", "snippet"))
            and all(_number(row.get(f)) for f in ("seq", "timestampMs"))
        ):
            matches.append(
                ConversationMatch(
                    row["entryId"],
                    row["role"],
                    row["seq"],
                    row["snippet"],
                    row["timestampMs"],
                )
            )
    return ConversationSearch(matches, reply["isComplete"])
