"""Shared conversation commands for the CLI and service."""

import uuid
from collections.abc import Mapping, Sequence

from .attachments import Attachment
from .models import Bot, Entry, SendResult, TranscriptPage
from .transport import Transport

COMMANDS = {
    "listAgents": "none",
    "openAgentTail": "object",
    "getAgentTranscriptTail": "object",
    "sendPrompt": "object",
    "getForeverBoxStatus": "object",
}


def roster(transport: Transport) -> list[Bot]:
    reply = transport.command("listAgents")
    rows = reply.get("agents") if isinstance(reply, Mapping) else reply
    if not isinstance(rows, list):
        raise TypeError("Invalid bot list from gateway.")
    return [bot for row in rows if (bot := Bot.from_row(row)) is not None]


def _page(reply: object, bot_id: str, session_id: str | None) -> TranscriptPage:
    data = reply if isinstance(reply, Mapping) else {}
    rows = data.get("entries", [])
    if not isinstance(rows, list):
        raise TypeError("Invalid transcript page from gateway.")
    entries = [
        entry
        for row in rows
        if (entry := Entry.from_raw(bot_id, row, session_id)) is not None
    ]
    cursor = data.get("nextBeforeSeq")
    return TranscriptPage(
        tuple(sorted(entries, key=lambda entry: entry.seq)),
        cursor if type(cursor) is int else None,
    )


def open_chat(
    transport: Transport,
    bot_id: str,
    *,
    session_id: str | None = None,
    limit: int = 200,
) -> TranscriptPage:
    args: dict[str, object] = {"id": bot_id, "limit": limit}
    if session_id is not None:
        args["sessionId"] = session_id
    return _page(transport.command("openAgentTail", args), bot_id, session_id)


def transcript(
    transport: Transport,
    bot_id: str,
    *,
    before_seq: int | None = None,
    limit: int = 50,
    session_id: str | None = None,
) -> TranscriptPage:
    args: dict[str, object] = {"id": bot_id, "limit": limit}
    if before_seq is not None:
        args["beforeSeq"] = before_seq
    if session_id is not None:
        args["sessionId"] = session_id
    return _page(transport.command("getAgentTranscriptTail", args), bot_id, session_id)


def send(
    transport: Transport,
    bot_id: str,
    text: str,
    *,
    session_id: str | None = None,
    nonce: str | None = None,
    attachments: Sequence[Attachment] = (),
) -> SendResult:
    if not text.strip() and not attachments:
        raise ValueError("Prompt must not be empty.")
    nonce = nonce if nonce is not None else str(uuid.uuid4())
    page = transcript(transport, bot_id, limit=1, session_id=session_id)
    args: dict[str, object] = {
        "agentId": bot_id,
        "prompt": text,
        "clientNonce": nonce,
    }
    if session_id is not None:
        args["sessionId"] = session_id
    if attachments:
        args["attachmentPaths"] = [item.path for item in attachments]
        args["attachmentNames"] = [item.name for item in attachments]
    reply = transport.command("sendPrompt", args)
    accepted = (
        bool(reply.get("accepted", False)) if isinstance(reply, Mapping) else False
    )
    return SendResult(accepted, nonce, max((e.seq for e in page.entries), default=None))


def box_state(transport: Transport, bot_id: str) -> str | None:
    reply = transport.command("getForeverBoxStatus", {"id": bot_id})
    state = reply.get("state") if isinstance(reply, Mapping) else None
    return state if isinstance(state, str) else None
