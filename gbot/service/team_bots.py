"""Team bots: activity, shared context, the review queue, shared memories and team link previews.

Every call here is a team-only server read or change. On a personal account (no team) the server refuses them with a
readable message; callers show `gbot.service.errors.refusal(error).message` as a notice. Memory and review text,
prose and user ids are personal: show them to the user only.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from groken.client import ConnectError

from .errors import refusal
from .models import _record, _text
from .transport import Transport

RPCS = (
    "ListGrokBotTeamAgents",
    "GetGrokBotTeamContextSummary",
    "ListGrokBotTeamReviewItems",
    "ResolveGrokBotTeamReviewItem",
    "ListGrokBotUserBotMemories",
    "PromoteGrokBotMemoriesToTeam",
    "GetGrokBotTeamLinkPreview",
    "SetGrokBotTeamLinkPreview",
)

ITEM_STATUSES = ("unspecified", "pending", "approved", "rejected")
MEMORY_ACTIONS = ("unspecified", "write", "forget")
SKILL_ACTIONS = ("unspecified", "add", "update", "remove")
_CHANGE_KINDS = (
    ("memory", "memory"),
    ("skill", "skill"),
    ("folderMemory", "folder_memory"),
    ("folder_memory", "folder_memory"),
)


@dataclass(frozen=True)
class TeamAgent:
    agent_id: str
    name: str
    user_turns: int = 0
    teammate_turns: int = 0
    last_turn_at_ms: int = 0


@dataclass(frozen=True)
class TeamAgents:
    entries: tuple[TeamAgent, ...] = ()
    slack_connections: int = 0
    teams_connections: int = 0


@dataclass(frozen=True)
class MemoryFact:
    fact_id: str
    text: str
    learned_at_ms: int = 0


@dataclass(frozen=True)
class ContextSummary:
    prose: str = ""
    generated_at_ms: int = 0
    memory_version: int = 0
    summary_model: str = ""
    stale: bool = False
    skills: tuple[str, ...] = ()
    learned: tuple[MemoryFact, ...] = ()
    memory_count: int = 0


@dataclass(frozen=True)
class ReviewChange:
    # kind is memory, skill, folder_memory or unknown, from the change's oneof key.
    kind: str
    action: str = "unspecified"
    text: str = ""
    name: str = ""
    description: str = ""
    content: str = ""
    path: str = ""
    memory_type: str = ""
    method: str = ""
    summary: str = ""


@dataclass(frozen=True)
class ReviewItem:
    item_id: str
    status: str
    proposed_by_user_id: int = 0
    reviewed_by_user_id: int = 0
    created_at_ms: int = 0
    reviewed_at_ms: int = 0
    change: ReviewChange = field(default_factory=lambda: ReviewChange("unknown"))


@dataclass(frozen=True)
class PromoteResult:
    created: tuple[MemoryFact, ...] = ()
    already_in_team: tuple[MemoryFact, ...] = ()
    kept_private_count: int = 0


def _enum(value: object, names: Sequence[str]) -> str:
    """A short name, a full GROK_BOT_..._VALUE name or a number, as the lowercase short name or unknown."""
    if isinstance(value, int) and not isinstance(value, bool):
        return names[value] if 0 <= value < len(names) else "unknown"
    text = str(value).strip().casefold()
    if text.isdecimal():
        return _enum(int(text), names)
    if text.startswith("grok_bot_"):
        text = text.rsplit("_", 1)[-1]
    return text if text in names else "unknown"


def _number(value: object) -> int:
    """An int, or a decimal string (int64 on the wire); anything else is 0."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return int(value) if isinstance(value, str) and value.isdecimal() else 0


def _rows(value: object) -> list[Mapping[str, object]]:
    return (
        [row for row in value if isinstance(row, Mapping)]
        if isinstance(value, list)
        else []
    )


def _count(value: object) -> int:
    return len(value) if isinstance(value, list) else 0


def _skill_names(value: object) -> tuple[str, ...]:
    names = []
    for item in value if isinstance(value, list) else []:
        name = _text(item.get("name")) if isinstance(item, Mapping) else _text(item)
        if name:
            names.append(name)
    return tuple(names)


def _memory(row: Mapping[str, object]) -> MemoryFact:
    return MemoryFact(
        _text(row.get("factId")),
        _text(row.get("text")),
        _number(row.get("learnedAtMs")),
    )


def _agent(row: Mapping[str, object]) -> TeamAgent:
    # The entry is an agent plus signals: the agent may be nested, the signals sit beside it.
    agent = _record(row.get("agent")) or row
    signals = _record(row.get("signals")) or row
    return TeamAgent(
        _text(agent.get("agentId")) or _text(agent.get("id")),
        _text(agent.get("name")),
        _number(signals.get("userTurns")),
        _number(signals.get("teammateTurns")),
        _number(signals.get("lastTurnAtMs")),
    )


def _change(row: Mapping[str, object]) -> ReviewChange:
    kind = "unknown"
    body: Mapping[str, object] = {}
    for key, name in _CHANGE_KINDS:
        if isinstance(row.get(key), Mapping):
            kind, body = name, _record(row[key])
            break
    actions = SKILL_ACTIONS if kind == "skill" else MEMORY_ACTIONS
    return ReviewChange(
        kind,
        _enum(body.get("action", 0), actions),
        _text(body.get("text")),
        _text(body.get("name")),
        _text(body.get("description")),
        _text(body.get("content")),
        _text(body.get("path")),
        _text(body.get("memoryType")),
        _text(row.get("method")),
        _text(row.get("summary")) or _text(body.get("summary")),
    )


def _item(row: Mapping[str, object]) -> ReviewItem:
    return ReviewItem(
        _text(row.get("itemId")),
        _enum(row.get("status", 0), ITEM_STATUSES),
        _number(row.get("proposedByUserId")),
        _number(row.get("reviewedByUserId")),
        _number(row.get("createdAtMs")),
        _number(row.get("reviewedAtMs")),
        _change(_record(row.get("change"))),
    )


def _summary(reply: Mapping[str, object]) -> ContextSummary:
    summary = _record(reply.get("summary"))
    return ContextSummary(
        _text(summary.get("prose")),
        _number(summary.get("generatedAtMs")),
        _number(summary.get("memoryVersion")),
        _text(summary.get("summaryModel")),
        reply.get("stale") is True,
        _skill_names(reply.get("skills")),
        tuple(_memory(row) for row in _rows(reply.get("learned"))),
        _number(reply.get("memoryCount")),
    )


def _status_name(value: str) -> str:
    name = value.strip().casefold()
    if name not in ITEM_STATUSES[1:]:
        raise ValueError("Review status must be pending, approved or rejected.")
    return "GROK_BOT_TEAM_REVIEW_ITEM_STATUS_" + name.upper()


def team_agents(transport: Transport, role: str | None = None) -> TeamAgents:
    payload: dict[str, object] = {} if role is None else {"role": role}
    try:
        reply = _record(transport.rpc("ListGrokBotTeamAgents", payload))
    except ConnectError as error:
        found = refusal(error)
        if found is not None and found.code == "unimplemented":
            return TeamAgents()
        raise
    return TeamAgents(
        tuple(_agent(row) for row in _rows(reply.get("entries"))),
        _count(reply.get("slackConnections")),
        _count(reply.get("teamsConnections")),
    )


def context_summary(transport: Transport, bot_id: str) -> ContextSummary:
    reply = transport.rpc("GetGrokBotTeamContextSummary", {"agentId": bot_id})
    return _summary(_record(reply))


def review_items(
    transport: Transport,
    bot_id: str,
    statuses: Sequence[str] = ("pending",),
    limit: int = 100,
) -> tuple[ReviewItem, ...]:
    # The server refuses a request without a status, so an empty choice means pending.
    names = [_status_name(status) for status in statuses or ("pending",)]
    reply = _record(
        transport.rpc(
            "ListGrokBotTeamReviewItems",
            {"agentId": bot_id, "statuses": names, "limit": limit},
        )
    )
    return tuple(_item(row) for row in _rows(reply.get("items")))


def resolve_review_item(
    transport: Transport, bot_id: str, item_id: str, approve: bool
) -> ReviewItem:
    decision = "APPROVE" if approve else "REJECT"
    reply = _record(
        transport.rpc(
            "ResolveGrokBotTeamReviewItem",
            {
                "agentId": bot_id,
                "itemId": item_id,
                "decision": "GROK_BOT_TEAM_REVIEW_DECISION_" + decision,
            },
        )
    )
    return _item({"itemId": item_id, **_record(reply.get("item"))})


def bot_memories(transport: Transport, bot_id: str) -> tuple[MemoryFact, ...]:
    reply = _record(transport.rpc("ListGrokBotUserBotMemories", {"agentId": bot_id}))
    return tuple(_memory(row) for row in _rows(reply.get("memories")))


def promote_memories(
    transport: Transport, bot_id: str, fact_ids: Sequence[str]
) -> PromoteResult:
    reply = _record(
        transport.rpc(
            "PromoteGrokBotMemoriesToTeam",
            {"agentId": bot_id, "factIds": list(fact_ids)},
        )
    )
    return PromoteResult(
        tuple(_memory(row) for row in _rows(reply.get("created"))),
        tuple(_memory(row) for row in _rows(reply.get("alreadyInTeam"))),
        _number(reply.get("keptPrivateCount")),
    )


def promote_sentence(result: PromoteResult) -> str:
    return (
        f"Shared with the team: {len(result.created)} created, "
        f"{len(result.already_in_team)} already in the team, "
        f"{result.kept_private_count} kept private."
    )


def link_preview(transport: Transport, team_id: int) -> bool:
    reply = _record(transport.rpc("GetGrokBotTeamLinkPreview", {"teamId": team_id}))
    return _record(reply.get("setting")).get("enabled") is True


def set_link_preview(transport: Transport, team_id: int, enabled: bool) -> bool:
    reply = _record(
        transport.rpc(
            "SetGrokBotTeamLinkPreview", {"teamId": team_id, "enabled": enabled}
        )
    )
    # A reply without a setting echoes the request: the server leaves a false flag out.
    if "setting" not in reply:
        return enabled
    return _record(reply["setting"]).get("enabled") is True


def date_text(ms: int) -> str:
    """The UTC date of a millisecond timestamp, or "" when it is unset or out of range."""
    if not ms:
        return ""
    try:
        return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%d")
    except (OverflowError, OSError, ValueError):
        return ""


DEMO_RPCS: dict[str, object] = {name: {} for name in RPCS}
