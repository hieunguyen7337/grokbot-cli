"""Message reactions, feedback and threads."""

from collections.abc import Mapping, Sequence
from typing import Literal

from .models import Entry
from .transport import Transport

COMMANDS: dict[str, str] = dict.fromkeys(
    ("reactToMessage", "voteFeedback", "createThreadFromMessage"), "object"
)
DEMO_COMMANDS: dict[str, object] = {
    "reactToMessage": None,
    "voteFeedback": None,
    "createThreadFromMessage": None,
}
FEEDBACK_CATEGORIES = ("not_what_i_asked", "inaccurate", "low_quality", "too_slow")
FEEDBACK_LABELS = ("Not what I asked", "Inaccurate", "Low quality", "Too slow")


def react(
    transport: Transport,
    bot_id: str,
    entry_id: str,
    emoji: str,
    session_id: str | None = None,
) -> None:
    args: dict[str, object] = {"agentId": bot_id, "entryId": entry_id, "emoji": emoji}
    if session_id is not None:
        args["sessionId"] = session_id
    transport.command("reactToMessage", args)


def vote(
    transport: Transport,
    bot_id: str,
    entry_id: str,
    action: Literal["up", "down", "submit", "revert"],
    *,
    session_id: str | None = None,
    categories: Sequence[str] = (),
    comment: str = "",
) -> None:
    args: dict[str, object] = {"agentId": bot_id, "entryId": entry_id, "action": action}
    if session_id is not None:
        args["sessionId"] = session_id
    if categories:
        args["categories"] = list(categories)
    if comment:
        args["comment"] = comment
    transport.command("voteFeedback", args)


def thread_from(transport: Transport, bot_id: str, entry_id: str) -> None:
    transport.command(
        "createThreadFromMessage", {"agentId": bot_id, "entryId": entry_id}
    )


def entry_reactions(entry: Entry) -> list[tuple[str, int, bool]]:
    rows = entry.raw.get("reactions")
    grouped: dict[str, tuple[int, bool]] = {}
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            by, emoji = row.get("by"), row.get("emoji")
            if (
                not isinstance(by, str)
                or not by
                or not isinstance(emoji, str)
                or not emoji
            ):
                continue
            count, own = grouped.get(emoji, (0, False))
            grouped[emoji] = (count + 1, own or by == "user")
    return [(emoji, count, own) for emoji, (count, own) in grouped.items()]
