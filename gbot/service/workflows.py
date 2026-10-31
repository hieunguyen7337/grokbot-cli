"""Bot instruction skills, optional workflow schedules and catalog imports."""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from groken.client import ConnectError

from .models import _int, _record, _text
from .transport import Transport

COMMANDS = {
    "getAgentWorkflows": "object",
    "createAgentWorkflow": "object",
    "updateAgentWorkflow": "object",
    "deleteAgentWorkflow": "object",
    "runAgentWorkflowNow": "object",
    "importAgentWorkflowText": "object",
    "importAgentWorkflowUrl": "object",
    "skillsCatalog": "none",
}
RPCS = ("ListGrokBotAgentSkills",)
_DEMO_ROWS = [
    {
        "id": "demo-notes",
        "name": "Meeting notes",
        "description": "Summarize a meeting",
        "body": "Collect decisions and next steps.",
        "source": "user",
    },
    {
        "id": "demo-brief",
        "name": "Morning brief",
        "description": "Prepare a daily brief",
        "body": "Review today's priorities.",
        "source": "user",
        "trigger": {"schedule": "0 9 * * 1-5", "isEnabled": True},
        "scheduleDescription": "Weekdays at 9 AM",
    },
    {
        "id": "demo-research",
        "name": "Research",
        "description": "Research a topic",
        "body": "Find sources and summarize the evidence.",
        "source": "managed",
    },
]
DEMO_COMMANDS = {
    "getAgentWorkflows": _DEMO_ROWS,
    "createAgentWorkflow": _DEMO_ROWS,
    "updateAgentWorkflow": _DEMO_ROWS,
    "deleteAgentWorkflow": _DEMO_ROWS,
    "runAgentWorkflowNow": None,
    "importAgentWorkflowText": {"workflows": _DEMO_ROWS, "result": {}},
    "importAgentWorkflowUrl": {"workflows": _DEMO_ROWS, "result": {}},
    "skillsCatalog": [
        {
            "id": "demo-catalog",
            "name": "Weekly review",
            "description": "Review progress and plan the week ahead.",
            "publisher": "Demo",
            "install": {
                "kind": "content",
                "content": "Review progress.",
                "name": "Weekly review",
            },
        }
    ],
}
DEMO_RPCS = {"ListGrokBotAgentSkills": {}}


@dataclass(frozen=True)
class Skill:
    id: str
    name: str
    description: str
    body: str
    source: str
    source_ref: str | None
    plugin_id: object
    schedule: str | None
    schedule_enabled: bool
    schedule_description: str
    last_run_at_ms: int | None
    next_run_at_ms: int | None
    created_at_ms: int | None
    editable: bool


@dataclass(frozen=True)
class CatalogSkill:
    id: str
    name: str
    description: str
    publisher: str
    install_kind: str
    install: Mapping[str, object] = field(default_factory=dict, repr=False)


def _parse(value: object) -> Skill:
    row = _record(value)
    trigger = _record(row.get("trigger"))
    source, plugin = _text(row.get("source")), row.get("pluginId")
    return Skill(
        _text(row.get("id")),
        _text(row.get("name")),
        _text(row.get("description")),
        _text(row.get("body")),
        source,
        _text(row.get("sourceRef")) or None,
        plugin,
        _text(trigger.get("schedule")) or None,
        trigger.get("isEnabled") is True,
        _text(row.get("scheduleDescription")),
        _int(row.get("lastRunAt")),
        _int(row.get("nextRunAt")),
        _int(row.get("createdAt")),
        source not in {"managed", "template", "plugin"} and plugin is None,
    )


def _rows(value: object) -> list[Skill]:
    if not isinstance(value, list):
        raise TypeError("Expected a workflow list.")
    return [_parse(row) for row in value if isinstance(row, Mapping)]


def skills(transport: Transport, bot_id: str) -> list[Skill]:
    merged = {
        row.id: row
        for row in _rows(transport.command("getAgentWorkflows", {"id": bot_id}))
    }
    try:
        reply = transport.rpc("ListGrokBotAgentSkills", {"agentId": bot_id})
    except ConnectError as error:
        try:
            code = _record(json.loads(error.body)).get("code")
        except ValueError:
            code = error.body.strip()
        if code != "not_found":
            raise
        reply = {}
    for row in _rows(reply.get("skills", [])):
        merged[row.id] = row
    return sorted(
        merged.values(), key=lambda row: (not row.editable, row.name.casefold(), row.id)
    )


def find(skills: Sequence[Skill], query: str) -> Skill:
    exact = [row for row in skills if row.id == query]
    matches = exact or [
        row for row in skills if row.name.casefold() == query.casefold()
    ]
    if not matches and len(query) >= 6:
        matches = [row for row in skills if row.id.startswith(query)]
    if len(matches) == 1:
        return matches[0]
    choices = ", ".join(f"{row.name} ({row.id})" for row in skills)
    raise ValueError(f"Unknown or ambiguous skill {query!r}. Choose: {choices}")


def _editable(skill: Skill) -> None:
    if not skill.editable:
        raise ValueError("This skill is managed by Grok Bot; copy it to make your own.")


def _required(value: str, label: str) -> str:
    if not value.strip():
        raise ValueError(f"{label} must not be blank.")
    return value


def _spec(
    name: str, description: str, body: str, schedule: str | None, enabled: bool = True
) -> dict[str, object]:
    return {
        "name": _required(name, "Name").strip(),
        "description": _required(description, "Description").strip(),
        "body": _required(body, "Body"),
        "trigger": {
            "schedule": _required(schedule, "Schedule").strip(),
            "isEnabled": enabled,
        }
        if schedule is not None
        else None,
    }


def create(
    transport: Transport,
    bot_id: str,
    *,
    name: str,
    description: str,
    body: str,
    schedule: str | None = None,
) -> list[Skill]:
    spec = _spec(name, description, body, schedule)
    return _rows(transport.command("createAgentWorkflow", {"id": bot_id, "spec": spec}))


class _Unset:
    pass


_UNSET = _Unset()


def update(
    transport: Transport,
    bot_id: str,
    skill: Skill,
    *,
    name: str | None = None,
    description: str | None = None,
    body: str | None = None,
    schedule: str | None | _Unset = _UNSET,
    schedule_enabled: bool | None = None,
) -> list[Skill]:
    _editable(skill)
    selected = skill.schedule if isinstance(schedule, _Unset) else schedule
    enabled = skill.schedule_enabled if skill.schedule else True
    if schedule_enabled is not None:
        if selected is None:
            raise ValueError("This skill has no schedule.")
        enabled = schedule_enabled
    spec = _spec(
        skill.name if name is None else name,
        skill.description if description is None else description,
        skill.body if body is None else body,
        selected,
        enabled,
    )
    if skill.source_ref is not None:
        spec["sourceRef"] = skill.source_ref
    return _rows(
        transport.command(
            "updateAgentWorkflow", {"id": bot_id, "workflowId": skill.id, "spec": spec}
        )
    )


def delete(transport: Transport, bot_id: str, skill: Skill) -> list[Skill]:
    _editable(skill)
    return _rows(
        transport.command("deleteAgentWorkflow", {"id": bot_id, "workflowId": skill.id})
    )


def run_now(transport: Transport, bot_id: str, skill: Skill) -> None:
    if not skill.schedule:
        raise ValueError("This skill has no schedule.")
    transport.command("runAgentWorkflowNow", {"id": bot_id, "workflowId": skill.id})


def _import(
    transport: Transport,
    bot_id: str,
    command: str,
    payload: dict[str, object],
    name: str | None,
) -> tuple[int, list[Skill]]:
    before = _rows(transport.command("getAgentWorkflows", {"id": bot_id}))
    if name is not None:
        payload["name"] = name
    reply = _record(transport.command(command, {"id": bot_id, **payload}))
    after = _rows(reply.get("workflows"))
    return len(after) - len(before), after


def import_text(
    transport: Transport, bot_id: str, markdown: str, name: str | None = None
) -> tuple[int, list[Skill]]:
    _required(markdown, "Markdown")
    return _import(
        transport, bot_id, "importAgentWorkflowText", {"markdown": markdown}, name
    )


def import_url(
    transport: Transport, bot_id: str, url: str, name: str | None = None
) -> tuple[int, list[Skill]]:
    url = url.strip()
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError("Skill URL must use http or https.")
    return _import(transport, bot_id, "importAgentWorkflowUrl", {"url": url}, name)


def catalog(transport: Transport) -> list[CatalogSkill]:
    reply = transport.command("skillsCatalog")
    result = []
    for value in reply if isinstance(reply, list) else []:
        row = _record(value)
        install = dict(_record(row.get("install")))
        result.append(
            CatalogSkill(
                _text(row.get("id")),
                _text(row.get("name")),
                _text(row.get("description")),
                _text(row.get("publisher")),
                _text(install.get("kind")),
                install,
            )
        )
    return result


def install(
    transport: Transport, bot_id: str, entry: CatalogSkill
) -> tuple[int, list[Skill]]:
    if entry.install_kind == "url":
        return import_url(transport, bot_id, _text(entry.install.get("url")))
    if entry.install_kind == "content":
        return import_text(
            transport,
            bot_id,
            _text(entry.install.get("content")),
            _text(entry.install.get("name")) or None,
        )
    raise ValueError("Add this skill in the Grok Bot app.")
