"""Account email address management."""

from dataclasses import dataclass

from .models import _record
from .transport import Transport

COMMANDS: dict[str, str] = {}
RPCS = ("ListGrokBotEmailInboxes", "CreateGrokBotEmailInbox")
DEMO_COMMANDS: dict[str, object] = {}
_DEMO = {
    "email": "helper@mail.grokbot.com",
    "domain": "mail.grokbot.com",
    "assigned": True,
}
DEMO_RPCS = {
    "ListGrokBotEmailInboxes": {"inboxes": [_DEMO]},
    "CreateGrokBotEmailInbox": {"inbox": _DEMO},
}


@dataclass(frozen=True)
class Inbox:
    email: str
    domain: str
    created_at_ms: int
    assigned: bool


def _parse(value: object) -> Inbox:
    row = _record(value)
    return Inbox(
        str(row.get("email", "")),
        str(row.get("domain", "")),
        int(str(row.get("createdAtMs", 0))),
        row.get("assigned") is True,
    )


def list_inboxes(transport: Transport) -> list[Inbox]:
    reply = transport.rpc("ListGrokBotEmailInboxes", {"showsAssigned": True})
    rows = reply.get("inboxes", [])
    return [_parse(row) for row in rows] if isinstance(rows, list) else []


def normalize_username(username: str) -> str:
    username = username.strip().lower()
    if not username or "@" in username or any(c.isspace() for c in username):
        raise ValueError("Enter a username without @ or whitespace.")
    return username


def create_inbox(transport: Transport, username: str) -> Inbox:
    username = normalize_username(username)
    reply = transport.rpc(
        "CreateGrokBotEmailInbox", {"username": username, "displayName": ""}
    )
    return _parse(reply.get("inbox"))
