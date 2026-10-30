"""Task threads, background work and conversation navigation."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, TypeVar

from .models import Bot
from .transport import Transport

COMMANDS = dict.fromkeys(
    (
        "getAgentTasks",
        "markAgentTaskDone",
        "markAgentTaskRead",
        "setAgentTaskPinned",
        "getAsyncTasks",
        "getSubagents",
        "getConversationOutline",
        "dismissAgentSuggestions",
        "setAgentUnread",
    ),
    "object",
)


@dataclass(frozen=True)
class AgentTask:
    id: str
    name: str | None = None
    description: str | None = None
    status: str | None = None
    updated_at_ms: int | None = None
    pinned_at_ms: int | None = None
    unread_entry_id: str | None = None
    unread_preview: str | None = None
    unread_at_ms: int | None = None
    followed: bool | None = None
    subagent_ids: tuple[str, ...] | None = None
    raw: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class AsyncTask:
    id: str
    kind: str | None = None
    label: str | None = None
    started_at_ms: int | None = None
    status: str | None = None
    detail: str | None = None
    raw: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class Subagent:
    id: str
    type: str | None = None
    title: str | None = None
    status: str | None = None
    started_at_ms: int | None = None
    raw: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class OutlineItem:
    id: str
    kind: str | None = None
    text: str | None = None
    status: str | None = None
    name: str | None = None
    summary: str | None = None
    timestamp_ms: int | None = None
    duration_ms: int | None = None
    raw: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class Suggestion:
    id: str
    title: str | None = None
    detail: str | None = None
    prompt: str | None = None
    icon: str | None = None
    raw: Mapping[str, object] = field(default_factory=dict)


def _rows(reply: object, command: str) -> list[Mapping[str, object]]:
    if reply is None:
        return []
    if not isinstance(reply, list):
        raise ValueError(f"Unexpected reply to {command}")  # noqa: TRY004 - protocol contract
    return [
        r
        for r in reply
        if isinstance(r, Mapping)
        and isinstance(r.get("subagentId" if command == "getSubagents" else "id"), str)
    ]


T = TypeVar("T", AgentTask, AsyncTask, Subagent, OutlineItem, Suggestion)


def _parse(cls: type[T], row: Mapping[str, object]) -> T:
    values = {}
    for name, info in cls.__dataclass_fields__.items():
        if name == "raw":
            continue
        key = name.split("_")[0] + "".join(s.title() for s in name.split("_")[1:])
        if cls is Subagent:
            key = {"id": "subagentId", "type": "subagentType"}.get(name, key)
        value = row.get(key)
        if (
            name == "text"
            and row.get("kind") == "send-message"
            and isinstance(row.get("message"), Mapping)
        ):
            message = row["message"]
            assert isinstance(message, Mapping)
            value = message.get("text")
        if "tuple" in str(info.type):
            value = (
                tuple(v for v in value if isinstance(v, str))
                if isinstance(value, list)
                else None
            )
        elif "int" in str(info.type):
            value = (
                int(value)
                if isinstance(value, (int, float)) and not isinstance(value, bool)
                else None
            )
        elif "bool" in str(info.type):
            value = value if isinstance(value, bool) else None
        else:
            value = value if isinstance(value, str) else None
        values[name] = value
    return cls(**values, raw=dict(row))


def _tasks(
    transport: Transport, command: str, args: dict[str, object]
) -> list[AgentTask]:
    return [
        _parse(AgentTask, r) for r in _rows(transport.command(command, args), command)
    ]


def tasks(transport: Transport, bot_id: str) -> list[AgentTask]:
    return _tasks(transport, "getAgentTasks", {"agentId": bot_id})


def mark_done(transport: Transport, bot_id: str, task_id: str) -> list[AgentTask]:
    return _tasks(
        transport, "markAgentTaskDone", {"agentId": bot_id, "taskId": task_id}
    )


def mark_read(
    transport: Transport, bot_id: str, task_id: str, entry_id: str
) -> list[AgentTask]:
    return _tasks(
        transport,
        "markAgentTaskRead",
        {"agentId": bot_id, "taskId": task_id, "entryId": entry_id},
    )


def set_pinned(
    transport: Transport, bot_id: str, task_id: str, pinned: bool
) -> list[AgentTask]:
    return _tasks(
        transport,
        "setAgentTaskPinned",
        {"agentId": bot_id, "taskId": task_id, "isPinned": pinned},
    )


def background(transport: Transport, bot_id: str) -> list[AsyncTask]:
    return [
        _parse(AsyncTask, r)
        for r in _rows(
            transport.command("getAsyncTasks", {"id": bot_id}), "getAsyncTasks"
        )
    ]


def subagents(transport: Transport, bot_id: str) -> list[Subagent]:
    return [
        _parse(Subagent, r)
        for r in _rows(
            transport.command("getSubagents", {"id": bot_id}), "getSubagents"
        )
    ]


def outline(transport: Transport, bot_id: str) -> list[OutlineItem]:
    return [
        _parse(OutlineItem, r)
        for r in _rows(
            transport.command("getConversationOutline", {"id": bot_id}),
            "getConversationOutline",
        )
    ]


def suggestions(bot: Bot) -> list[Suggestion]:
    return [
        _parse(Suggestion, r) for r in _rows(bot.raw.get("suggestions"), "suggestions")
    ]


def dismiss_suggestions(
    transport: Transport,
    bot_id: str,
    ids: list[str],
    reason: Literal["acted", "hidden"],
) -> None:
    transport.command(
        "dismissAgentSuggestions",
        {"agentId": bot_id, "suggestionIds": ids, "reason": reason},
    )


def set_unread(transport: Transport, bot_id: str, unread: bool) -> None:
    args: dict[str, object] = {"id": bot_id, "isUnread": unread}
    if not unread:
        args["markFollowedThreadsRead"] = True
    transport.command("setAgentUnread", args)


def thread_session(task_id: str, parent_session_id: str | None) -> str:
    return f"task:{task_id}" + (f":{parent_session_id}" if parent_session_id else "")


_DEMO_TASKS = [
    {
        "id": "plan",
        "name": "Plan the release",
        "description": "Review the launch checklist",
        "status": "open",
        "updatedAtMs": 2000,
        "pinnedAtMs": 1000,
    },
    {
        "id": "research",
        "name": "Research findings",
        "description": "Compare the options",
        "status": "open",
        "updatedAtMs": 3000,
        "unreadEntryId": "result",
        "unreadPreview": "The comparison is ready",
    },
]
DEMO_COMMANDS = dict.fromkeys(COMMANDS)
DEMO_COMMANDS.update(
    {
        "getAgentTasks": _DEMO_TASKS,
        "getAsyncTasks": [
            {
                "id": "build",
                "kind": "shell",
                "label": "Build preview",
                "startedAtMs": 0,
                "status": "running",
                "detail": "Preparing assets",
            }
        ],
        "getSubagents": [
            {
                "subagentId": "review",
                "subagentType": "research",
                "title": "Review options",
                "status": "running",
                "startedAtMs": 0,
            }
        ],
        "getConversationOutline": [
            {"id": "u", "kind": "user", "text": "Compare the options"},
            {
                "id": "t",
                "kind": "thinking",
                "text": "Reviewing sources",
                "durationMs": 1200,
            },
            {
                "id": "c",
                "kind": "tool-call",
                "name": "search",
                "summary": "Find references",
                "status": "done",
            },
            {"id": "a", "kind": "assistant-text", "text": "The comparison is ready"},
        ],
    }
)
