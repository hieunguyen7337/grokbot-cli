"""Scheduled and event-triggered bot prompts."""

import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from threading import Event
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from .handoff import wait_until
from .models import Bot, _int, _record, _text
from .transport import Transport

COMMANDS = {
    "getAgentAutomations": "object",
    "listAllAutomations": "none",
    "createAgentAutomation": "object",
    "updateAgentAutomation": "object",
    "deleteAgentAutomation": "object",
    "setAgentAutomationEnabled": "object",
    "runAgentAutomationNow": "object",
}
RPCS = (
    "ListGrokBotAgentAutomations",
    "ListGrokBotAccountAutomations",
    "DeleteGrokBotAgentAutomation",
    "SetGrokBotAgentAutomationEnabled",
)


@dataclass(frozen=True)
class Run:
    id: str
    status: str
    started_at_ms: int | None


@dataclass(frozen=True)
class Automation:
    id: str
    server_id: str
    bot_id: str
    name: str
    prompt: str
    is_enabled: bool
    created_at_ms: int
    last_run_at_ms: int | None
    next_run_at_ms: int | None
    schedule: str
    trigger_description: str
    trigger: dict[str, object]
    runs: tuple[Run, ...]
    provenance: object
    allowed: frozenset[str] | None
    raw: Mapping[str, object] = field(default_factory=dict, repr=False, compare=False)

    def permits(self, action: str) -> bool:
        return self.allowed is None or action.upper() in self.allowed


def _parse(row: object, bot_id: str) -> Automation | None:
    outer = _record(row)
    data = outer
    if "recordJson" in outer:
        try:
            data = _record(json.loads(_text(outer.get("recordJson"))))
        except (ValueError, TypeError):
            return None
    if any(
        not isinstance(data.get(key), str)
        for key in (
            "id",
            "name",
            "prompt",
            "schedule",
            "triggerDescription",
            "filePath",
        )
    ) or (
        type(data.get("isEnabled")) is not bool
        or _int(data.get("createdAt")) is None
        or not isinstance(data.get("runs"), list)
    ):
        return None
    permissions = _record(outer.get("viewerPermissions"))
    allowed = permissions.get("allowedActions")
    runs = []
    run_rows = data.get("runs")
    for value in run_rows if isinstance(run_rows, list) else []:
        run = _record(value)
        if isinstance(run.get("id"), str) and run.get("id"):
            runs.append(
                Run(
                    _text(run.get("id")),
                    _text(run.get("status")),
                    _int(run.get("startedAt")),
                )
            )
    raw = dict(data)
    raw.pop("viewerCapabilities", None)
    return Automation(
        _text(data.get("id")),
        _text(outer.get("automationId")),
        bot_id,
        _text(data.get("name")),
        _text(data.get("prompt")),
        data.get("isEnabled") is True,
        _int(data.get("createdAt")) or 0,
        _int(data.get("lastRunAt")),
        _int(data.get("nextRunAt")),
        _text(data.get("schedule")),
        _text(data.get("triggerDescription")),
        dict(_record(data.get("trigger"))),
        tuple(runs),
        data.get("provenance"),
        frozenset(
            action.removeprefix("GROK_BOT_AUTOMATION_ACTION_")
            for action in allowed
            if isinstance(action, str)
        )
        if isinstance(allowed, list)
        else None,
        raw,
    )


def _sorted(items: Sequence[Automation]) -> list[Automation]:
    return sorted(
        items,
        key=lambda a: (
            a.next_run_at_ms if a.next_run_at_ms is not None else math.inf,
            a.created_at_ms,
        ),
    )


def _rows(rows: object, bot_id: str) -> list[Automation]:
    return (
        _sorted([item for row in rows if (item := _parse(row, bot_id)) is not None])
        if isinstance(rows, list)
        else []
    )


def list_for_bot(transport: Transport, bot: Bot) -> list[Automation]:
    if bot.raw.get("harness") == "temporal":
        return _rows(
            transport.rpc("ListGrokBotAgentAutomations", {"agentId": bot.id}).get(
                "automations"
            ),
            bot.id,
        )
    return _rows(transport.command("getAgentAutomations", {"id": bot.id}), bot.id)


def list_for_account(transport: Transport, bots: Sequence[Bot]) -> list[Automation]:
    temporal = [b.id for b in bots if b.raw.get("harness") == "temporal"]
    others = {b.id for b in bots if b.raw.get("harness") != "temporal"}
    result = []
    for offset in range(0, len(temporal), 200):
        batch = temporal[offset : offset + 200]
        reply = transport.rpc("ListGrokBotAccountAutomations", {"agentIds": batch})
        agents = reply.get("agents")
        for row in agents if isinstance(agents, list) else []:
            data = _record(row)
            bot_id = _text(data.get("agentId"))
            if bot_id in batch:
                result.extend(_rows(data.get("automations"), bot_id))
    if others:
        rows = transport.command("listAllAutomations")
        for row in rows if isinstance(rows, list) else []:
            data = _record(row)
            bot_id = _text(data.get("agentId"))
            if bot_id in others:
                item = _parse(data.get("automation"), bot_id)
                if item:
                    result.append(item)
    return _sorted(result)


def get(transport: Transport, bot: Bot, automation_id: str) -> Automation:
    rows = list_for_bot(transport, bot)
    matches = [a for a in rows if a.id == automation_id or a.name == automation_id]
    if not matches and len(automation_id) >= 6:
        matches = [a for a in rows if a.id.startswith(automation_id)]
    if len(matches) != 1:
        raise ValueError(
            "Automation not found or ambiguous; use its record id or exact name."
        )
    _require(matches[0], "OPEN")
    return matches[0]


def _check_zone(name: str) -> None:
    try:
        ZoneInfo(name)
    except ZoneInfoNotFoundError:
        # Windows has no system time-zone database unless tzdata is installed; the
        # server validates the zone then, so only the name's shape is checked here.
        if available_timezones() or not re.fullmatch(
            r"[A-Za-z][A-Za-z0-9_+-]*(?:/[A-Za-z0-9_+-]+)*", name
        ):
            raise ValueError("Invalid timezone field.") from None
    except ValueError:
        raise ValueError("Invalid timezone field.") from None


def check_schedule(text: str) -> str:
    text = text.strip()
    parts = text.split()
    if parts and parts[0].startswith(("TZ=", "CRON_TZ=")):
        _check_zone(parts.pop(0).split("=", 1)[1])
    if len(parts) == 1 and parts[0] in {
        "@hourly",
        "@daily",
        "@midnight",
        "@weekly",
        "@monthly",
        "@yearly",
        "@annually",
    }:
        return text
    if parts and parts[0] == "@every":
        durations = "".join(parts[1:]).split("/")

        def duration(value: str) -> float:
            chunks = re.findall(r"(\d+(?:\.\d+)?|\.\d+)(ms|s|m|h|d)", value)
            if not chunks or "".join(n + u for n, u in chunks) != value:
                raise ValueError("Invalid duration field.")
            return sum(
                float(n) * {"ms": 0.001, "s": 1, "m": 60, "h": 3600, "d": 86400}[u]
                for n, u in chunks
            )

        if len(durations) > 2:
            raise ValueError("Invalid duration field.")
        interval = duration(durations[0])
        if not math.isfinite(interval) or interval <= 0:
            raise ValueError("Duration field must be positive.")
        if len(durations) == 2 and not 0 <= duration(durations[1]) < interval:
            raise ValueError("Phase field must be shorter than duration.")
        return text
    if len(parts) != 5:
        raise ValueError(
            "Schedule requires five fields: minute hour day month weekday."
        )
    for value, label, low, high in zip(
        parts,
        ("minute", "hour", "day", "month", "weekday"),
        (0, 0, 1, 1, 0),
        (59, 23, 31, 12, 7),
    ):
        for item in value.split(","):
            match = re.fullmatch(r"(\*|\d+(?:-\d+)?)(?:/(\d+))?", item)
            if not match or (match[2] is not None and int(match[2]) <= 0):
                raise ValueError(f"Invalid {label} field.")
            if match[1] != "*":
                bounds = [int(n) for n in match[1].split("-")]
                if any(not low <= n <= high for n in bounds) or bounds[0] > bounds[-1]:
                    raise ValueError(f"Invalid {label} field ({low}–{high}).")
    return text


def describe_trigger(trigger: Mapping[str, object]) -> str:
    kind = _text(trigger.get("type"))
    if kind == "cron":
        return _text(trigger.get("schedule"))
    if kind == "group":
        listeners = trigger.get("listeners")
        return (
            "Group: "
            + "; ".join(
                describe_trigger(_record(t))
                for t in listeners
                if _record(t).get("type") != "group"
            )
            if isinstance(listeners, list)
            else "Group"
        )
    fields = {
        "slack": ("channel", "match"),
        "github": ("repo", "events", "pr", "userAllowlist", "ciBranch"),
        "origin": ("repo", "events", "pr", "userAllowlist"),
        "microsoftTeams": ("tenantId", "teamIds", "channelIds", "messageContains"),
        "linear": ("event", "projectIds", "teamIds"),
        "sentry": ("event", "projectIds"),
        "pagerduty": ("event", "serviceIds"),
        "email": ("inbox", "from", "requireAuthPass"),
        "webhook": (),
    }
    values = [
        f"{key}={json.dumps(trigger[key], ensure_ascii=False)}"
        for key in fields.get(kind, ())
        if key in trigger
    ]
    return (kind + (": " + " · ".join(values) if values else "")).replace("\n", " ")


def _require(automation: Automation, action: str) -> None:
    if not automation.permits(action):
        raise ValueError(f"Automation permission denied: {action.lower()}.")


def _spec(
    name: str, prompt: str, trigger: dict[str, object], enabled: bool
) -> dict[str, object]:
    if not name.strip() or not prompt.strip():
        raise ValueError("Name and prompt must not be blank.")
    return {"name": name, "prompt": prompt, "trigger": trigger, "isEnabled": enabled}


def create(
    transport: Transport,
    bot: Bot,
    *,
    name: str,
    prompt: str,
    schedule: str,
    enabled: bool = True,
) -> list[Automation]:
    spec = _spec(
        name, prompt, {"type": "cron", "schedule": check_schedule(schedule)}, enabled
    )
    return _rows(
        transport.command("createAgentAutomation", {"id": bot.id, "spec": spec}), bot.id
    )


def update(
    transport: Transport,
    bot: Bot,
    automation: Automation,
    *,
    name: str | None = None,
    prompt: str | None = None,
    schedule: str | None = None,
    enabled: bool | None = None,
) -> list[Automation]:
    _require(automation, "EDIT")
    if enabled is not None:
        _require(automation, "TOGGLE")
    trigger = dict(automation.trigger)
    if schedule is not None:
        if trigger.get("type") != "cron":
            raise ValueError("Change this trigger in the Grok Bot app.")
        trigger["schedule"] = check_schedule(schedule)
    spec = _spec(
        name if name is not None else automation.name,
        prompt if prompt is not None else automation.prompt,
        trigger,
        enabled if enabled is not None else automation.is_enabled,
    )
    return _rows(
        transport.command(
            "updateAgentAutomation",
            {"id": bot.id, "automationId": automation.id, "spec": spec},
        ),
        bot.id,
    )


def set_enabled(
    transport: Transport, bot: Bot, automation: Automation, enabled: bool
) -> list[Automation]:
    _require(automation, "TOGGLE")
    args = {"automationId": automation.id, "isEnabled": enabled}
    if bot.raw.get("harness") == "temporal":
        return _rows(
            transport.rpc(
                "SetGrokBotAgentAutomationEnabled", {"agentId": bot.id, **args}
            ).get("automations"),
            bot.id,
        )
    return _rows(
        transport.command("setAgentAutomationEnabled", {"id": bot.id, **args}), bot.id
    )


def delete(transport: Transport, bot: Bot, automation: Automation) -> list[Automation]:
    _require(automation, "DELETE")
    if bot.raw.get("harness") == "temporal":
        return _rows(
            transport.rpc(
                "DeleteGrokBotAgentAutomation",
                {"agentId": bot.id, "automationId": automation.id},
            ).get("automations"),
            bot.id,
        )
    return _rows(
        transport.command(
            "deleteAgentAutomation", {"id": bot.id, "automationId": automation.id}
        ),
        bot.id,
    )


def run_now(transport: Transport, bot: Bot, automation: Automation) -> None:
    _require(automation, "OPEN")
    transport.command(
        "runAgentAutomationNow", {"id": bot.id, "automationId": automation.id}
    )


def wait_for_run(
    transport: Transport,
    bot: Bot,
    automation: Automation,
    *,
    cancel: Event,
    wake: Event | None = None,
    timeout_s: float = 120,
) -> Run | None:
    previous = {r.id for r in automation.runs}

    def check() -> Run | None:
        rows = get(transport, bot, automation.id).runs
        return max(
            (r for r in rows if r.id not in previous),
            key=lambda r: r.started_at_ms or 0,
            default=None,
        )

    result = wait_until(check, cancel=cancel, wake=wake, timeout_s=timeout_s)
    return result.value if isinstance(result.value, Run) else None


_DEMO = {
    "id": "demo-automation",
    "name": "Morning briefing",
    "prompt": "Summarize today's priorities.",
    "isEnabled": True,
    "createdAt": 1_800_000_000_000,
    "lastRunAt": 1_800_000_000_000,
    "nextRunAt": None,
    "schedule": "0 9 * * 1-5",
    "triggerDescription": "Weekday mornings",
    "trigger": {"type": "cron", "schedule": "0 9 * * 1-5"},
    "filePath": "automations/briefing",
    "provenance": "user",
    "runs": [{"id": "demo-run", "status": "completed", "startedAt": 1_800_000_000_000}],
}
DEMO_COMMANDS: dict[str, object] = {name: [_DEMO] for name in COMMANDS}
DEMO_COMMANDS["listAllAutomations"] = [{"agentId": "demo-helper", "automation": _DEMO}]
DEMO_COMMANDS["runAgentAutomationNow"] = None
DEMO_RPCS: dict[str, object] = {
    name: {
        "automations": [
            {"automationId": "demo-server-automation", "recordJson": json.dumps(_DEMO)}
        ]
    }
    for name in RPCS
}
DEMO_RPCS["ListGrokBotAccountAutomations"] = {
    "agents": [
        {
            "agentId": "demo-helper",
            "automations": [
                {
                    "automationId": "demo-server-automation",
                    "recordJson": json.dumps(_DEMO),
                }
            ],
        }
    ]
}
