"""Pure, tolerant decoding of gateway event frames."""

from collections.abc import Mapping

from .events import (
    BotChanged,
    BotOverlay,
    BoxChanged,
    EntryAdded,
    EntryChanged,
    EntryRemoved,
    Event,
    Other,
    RosterReplaced,
    RosterResync,
    TranscriptReset,
)
from .models import Bot, Entry


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _identity(payload: Mapping[str, object]) -> tuple[str, str | None]:
    ordered = payload.get("ordered")
    if isinstance(ordered, Mapping):
        key = ordered.get("replicaKey")
        if isinstance(key, str) and key.startswith("transcript:"):
            bot, separator, session = key[len("transcript:") :].partition("\0")
            return bot, session if separator and session else None
    bot = _text(payload.get("agentId"))
    if not bot and payload.get("type") == "snapshot":
        bot = _text(payload.get("activeAgentId"))
    return bot, None


def parse_frame(data: Mapping[str, object]) -> list[Event]:
    """Decode one frame; malformed or unmodelled payloads remain observable as Other."""
    if not isinstance(data, Mapping):
        return [Other("", data)]
    channel = _text(data.get("channel"))
    payload = data.get("payload")
    other: list[Event] = [Other(channel, payload)]
    if not isinstance(payload, Mapping):
        return other
    if channel == "agents":
        rows = payload.get("agents")
        if isinstance(rows, list):
            return [
                RosterReplaced(tuple(bot for row in rows if (bot := Bot.from_row(row))))
            ]
    elif channel == "agent-upserted":
        bot = Bot.from_row(payload.get("agent"))
        if bot:
            return [BotChanged(bot)]
    elif channel == "agent-activity":
        bot_id = _text(payload.get("agentId"))
        live, client = payload.get("live"), payload.get("client")
        if bot_id and all(
            side is None or isinstance(side, Mapping) for side in (live, client)
        ):
            fields = {}
            for side in (live, client):
                if isinstance(side, Mapping):
                    fields.update(side)
            return [BotOverlay(bot_id, fields)]
    elif channel == "transcript":
        bot_id, session = _identity(payload)
        if not bot_id:
            return []
        kind = payload.get("type")
        if kind in ("appended", "updated"):
            entry = Entry.from_raw(bot_id, payload.get("entry"), session)
            if entry:
                return [
                    EntryAdded(entry) if kind == "appended" else EntryChanged(entry)
                ]
        elif kind == "removed":
            entry_id = payload.get("id")
            if isinstance(entry_id, str):
                return [EntryRemoved(bot_id, session, entry_id)]
        elif kind == "cleared":
            return [TranscriptReset(bot_id, session)]
        elif kind == "snapshot":
            rows = payload.get("entries")
            if isinstance(rows, list):
                entries = tuple(
                    entry
                    for row in rows
                    if (entry := Entry.from_raw(bot_id, row, session))
                )
                return [TranscriptReset(bot_id, session, entries)]
    elif channel == "forever-box":
        bot_id, state = _text(payload.get("agentId")), payload.get("state")
        if bot_id and state in ("absent", "hibernated", "running"):
            return [BoxChanged(bot_id, str(state))]
    elif channel == "server-roster-changed":
        if payload.get("kind") == "resync":
            return [RosterResync()]
        bot_id = _text(payload.get("agentId"))
        if payload.get("kind") == "agent" and bot_id:
            return [RosterResync(bot_id)]
    return other
