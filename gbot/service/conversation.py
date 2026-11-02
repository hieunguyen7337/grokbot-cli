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
    "promptAcceptanceStatus": "object",
}
RPCS = ("ListGrokBotAgentSessions",)

_KIND_PREFIX = "GROK_BOT_AGENT_SESSION_KIND_"
_KINDS = {
    "MAIN",
    "SLACK_DM",
    "SLACK_THREAD",
    "DM",
    "GROUP",
    "TEAMS_DM",
    "TEAMS_THREAD",
    "TEAMS_GROUP_CHAT",
}

# Invented placeholders for demos and tests.
DEMO_COMMANDS: dict[str, object] = {
    "promptAcceptanceStatus": lambda args: {
        "accountSlot": "host",
        "clientNonce": args.get("clientNonce"),
        "agentId": args.get("agentId"),
        "inputDigest": "",
        "status": "accepted",
        "acceptedAtMs": 1_800_000_000_000,
        "echoEntryId": "demo-entry",
        "rejectionCode": None,
    },
}
DEMO_RPCS: dict[str, object] = {
    "GetGrokBotSendStatus": {
        "outcome": "GROK_BOT_SEND_STATUS_OUTCOME_FOUND",
        "status": "GROK_BOT_SEND_STATUS_ACCEPTED",
        "acceptedAtMs": "1800000000000",
        "echoEntryId": "demo-entry",
    },
    "ListGrokBotAgentSessions": lambda args: {
        "sessions": [
            {
                "agentId": args.get("agentId"),
                "sessionId": "",
                "kind": _KIND_PREFIX + "MAIN",
                "createdAtMs": "1790000000000",
                "updatedAtMs": "1800000000000",
                "lastActivityAtMs": "1800000000000",
            },
            {
                "agentId": args.get("agentId"),
                "sessionId": "demo-dm-session",
                "kind": _KIND_PREFIX + "DM",
                "createdAtMs": "1795000000000",
                "updatedAtMs": "1799000000000",
            },
        ]
    },
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


def send_status(
    transport: Transport,
    bot_id: str,
    nonce: str,
    *,
    session_id: str | None = None,
    task_id: str | None = None,
) -> dict[str, object]:
    """Whether a send with this client nonce was accepted, without sending anything.

    Box bots use the gateway's promptAcceptanceStatus and return its reply as is; temporal bots use
    GetGrokBotSendStatus through the router, which returns `{"outcome": "not-found"}`,
    `{"outcome": "unknown-durability"}` or the found record (docs/protocol-temporal.md section 1).
    """
    if not nonce.strip():
        raise ValueError("A send status needs the send's nonce.")
    args: dict[str, object] = {"agentId": bot_id, "clientNonce": nonce}
    if session_id is not None:
        args["sessionId"] = session_id
    if task_id is not None:
        args["taskId"] = task_id
    reply = transport.command("promptAcceptanceStatus", args)
    return (
        dict(reply) if isinstance(reply, Mapping) else {"outcome": "unknown-durability"}
    )


def _ms(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return 0


def list_sessions(transport: Transport, bot_id: str) -> list[dict[str, object]]:
    """A bot's sessions (routing contexts) from ListGrokBotAgentSessions, docs/protocol-tui.md section 4."""
    reply = transport.rpc("ListGrokBotAgentSessions", {"agentId": bot_id})
    rows = reply.get("sessions")
    sessions: list[dict[str, object]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, Mapping):
            continue
        kind = row.get("kind")
        short = kind.removeprefix(_KIND_PREFIX) if isinstance(kind, str) else ""
        item: dict[str, object] = {
            "agentId": row.get("agentId") or bot_id,
            "sessionId": row.get("sessionId") or "",
            "kind": short.lower() if short in _KINDS else "unspecified",
            "createdAtMs": _ms(row.get("createdAtMs")),
            "updatedAtMs": _ms(row.get("updatedAtMs")),
        }
        if "lastActivityAtMs" in row:
            item["lastActivityAtMs"] = _ms(row["lastActivityAtMs"])
        sessions.append(item)
    return sessions


def box_state(transport: Transport, bot_id: str) -> str | None:
    reply = transport.command("getForeverBoxStatus", {"id": bot_id})
    state = reply.get("state") if isinstance(reply, Mapping) else None
    return state if isinstance(state, str) else None
