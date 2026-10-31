"""Cloud computer run state, recreate, upgrade schedule and user runtime settings."""

import re
import zoneinfo
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

from groken.client import ConnectError

from .errors import refusal
from .models import _record, _strings, _text
from .transport import Transport

RPCS = (
    "GetSandBoxRunState",
    "RecreateSandBox",
    "ForceRecreateSandBox",
    "GetSandBoxUpgradeSchedule",
    "ScheduleSandBoxUpgrade",
    "RescheduleSandBoxUpgrade",
    "CancelSandBoxUpgrade",
    "UpdateGrokBotUserRuntimeSettings",
)
RUN_STATES = ("unspecified", "absent", "hibernated", "running", "starting")
SCHEDULE_STATES = (
    "unspecified",
    "scheduled",
    "claimed",
    "running",
    "waiting_for_image",
    "completed",
    "missed",
    "failed",
    "cancelled",
)
_RUN_PREFIX = "SAND_BOX_RUN_STATE"
_SCHEDULE_PREFIX = "SAND_BOX_UPGRADE_SCHEDULE_STATE"
_LOCAL_TIME = re.compile(r"([01][0-9]|2[0-3]):[0-5][0-9]")
_AREA_ZONE = re.compile(r"[A-Za-z_]+(/[A-Za-z0-9_+-]+)+")


def _enum(value: object, names: Sequence[str], prefix: str) -> str:
    if isinstance(value, int) and not isinstance(value, bool):
        return names[value] if 0 <= value < len(names) else "unknown"
    name = str(value).lower().removeprefix(prefix.lower() + "_")
    if name.isdecimal():
        return _enum(int(name), names, prefix)
    return name if name in names else "unknown"


def _flag(value: object, default: bool = False) -> bool:
    return value if isinstance(value, bool) else default


def _millis(value: object) -> int | None:
    # int64 fields arrive as decimal strings; a JSON number is accepted too.
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
        return int(value)
    return None


def _when(milliseconds: int) -> str:
    try:
        moment = datetime.fromtimestamp(milliseconds / 1000, UTC)
    except (OverflowError, OSError, ValueError):
        # A time past the calendar's range is an odd reply, not a reason to fail the read.
        return "unknown time"
    return moment.strftime("%Y-%m-%d %H:%M UTC")


@dataclass(frozen=True)
class RunState:
    state: str = "unknown"
    image_tag: str | None = None
    snapshot_path: str | None = field(default=None, repr=False)
    image_update_available: bool = False
    egress_tunnel_ownership: bool = False


@dataclass(frozen=True)
class RecreateResult:
    started: bool
    reason: str = ""
    operation_id: str = ""


@dataclass(frozen=True)
class UpgradeSchedule:
    timezone: str = ""
    local_time: str = ""
    recurring: bool = False
    target_image_tag: str | None = None
    next_fire_at_ms: int | None = None
    state: str = "unknown"
    last_completed_image_tag: str | None = None
    failure_reason: str | None = None


@dataclass(frozen=True)
class Overview:
    """The run state and upgrade schedule, with a plain sentence for any part the server refused.

    A refused part is left out of the rows; its sentence is in notice.
    """

    run: RunState = field(default_factory=RunState)
    schedule: UpgradeSchedule | None = None
    notice: str = ""
    run_refused: bool = False
    schedule_refused: bool = False


@dataclass(frozen=True)
class RuntimeSettings:
    pinned_agent_ids: tuple[str, ...] = ()
    auto_review_enabled: bool = False
    has_seen_onboarding: bool = False
    main_agent_id: str | None = None
    email_provider: str = ""
    updated_at_ms: int | None = None
    # The last read's auto-review message: writes resend it with only isEnabled changed, keeping its lists.
    raw_auto_review: dict[str, object] = field(
        default_factory=dict, compare=False, repr=False
    )


def _run_state(row: Mapping[str, object]) -> RunState:
    image = _record(row.get("image"))
    state = _enum(row.get("state", 0), RUN_STATES, _RUN_PREFIX)
    return RunState(
        "unknown" if state == "unspecified" else state,
        _text(image.get("registryTag")) or None,
        _text(image.get("staticSnapshotPath")) or None,
        _flag(row.get("imageUpdateAvailable")),
        _flag(row.get("egressTunnelOwnership")),
    )


def _recreate(row: Mapping[str, object]) -> RecreateResult:
    return RecreateResult(
        _flag(row.get("started")),
        _text(row.get("reason")),
        _text(row.get("operationId")),
    )


def _schedule(
    row: Mapping[str, object],
    timezone: str = "",
    local_time: str = "",
    recurring: bool = False,
) -> UpgradeSchedule:
    return UpgradeSchedule(
        timezone=_text(row.get("timezone")) or timezone,
        local_time=_text(row.get("localTime")) or local_time,
        recurring=_flag(row.get("recurring"), recurring),
        target_image_tag=_text(row.get("targetImageTag")) or None,
        next_fire_at_ms=_millis(row.get("nextFireAtMs")),
        state=_enum(row["state"], SCHEDULE_STATES, _SCHEDULE_PREFIX)
        if "state" in row
        else "unknown",
        last_completed_image_tag=_text(row.get("lastCompletedImageTag")) or None,
        failure_reason=_text(row.get("failureReason")) or None,
    )


def _optional_schedule(value: object) -> UpgradeSchedule | None:
    # An empty schedule message means no schedule, as an absent one does.
    row = _record(value)
    return _schedule(row) if row else None


def _settings(row: Mapping[str, object]) -> RuntimeSettings:
    pinned = _record(row.get("pinnedAgents"))
    review = _record(row.get("autoReviewInstructions"))
    return RuntimeSettings(
        pinned_agent_ids=_strings(pinned.get("agentIds")),
        auto_review_enabled=_flag(review.get("isEnabled")),
        has_seen_onboarding=_flag(row.get("hasSeenOnboarding")),
        main_agent_id=_text(row.get("mainAgentId")) or None,
        email_provider=_text(row.get("emailProvider")),
        updated_at_ms=_millis(row.get("updatedAtMs")),
        raw_auto_review=dict(review),
    )


def _refused(error: ConnectError) -> str:
    found = refusal(error)
    if found is None:
        raise error
    return found.message


def run_state(transport: Transport) -> RunState:
    return _run_state(transport.rpc("GetSandBoxRunState", {}))


def recreate(
    transport: Transport,
    *,
    preserve_data: bool = True,
    force: bool = False,
    acknowledge_terminal_upgrade_schedule: bool = False,
) -> RecreateResult:
    return _recreate(
        transport.rpc(
            "RecreateSandBox",
            {
                "preserveData": preserve_data,
                "force": force,
                "acknowledgeTerminalUpgradeSchedule": acknowledge_terminal_upgrade_schedule,
            },
        )
    )


def force_recreate(transport: Transport) -> RecreateResult:
    return _recreate(transport.rpc("ForceRecreateSandBox", {}))


def upgrade_schedule(transport: Transport) -> UpgradeSchedule | None:
    return _optional_schedule(
        transport.rpc("GetSandBoxUpgradeSchedule", {}).get("schedule")
    )


def check_schedule(timezone: str, local_time: str) -> None:
    """Raise ValueError before any call when the local time or the time zone is not usable."""
    if not _LOCAL_TIME.fullmatch(local_time):
        raise ValueError("Local time must be HH:MM on a 24-hour clock, such as 03:30.")
    names = zoneinfo.available_timezones()
    if names:
        known = timezone == "UTC" or timezone in names
    else:
        known = timezone == "UTC" or _AREA_ZONE.fullmatch(timezone) is not None
    if not known:
        raise ValueError("Time zone must be an IANA name such as Europe/Paris or UTC.")


def _schedule_payload(
    timezone: str, local_time: str, recurring: bool
) -> dict[str, object]:
    check_schedule(timezone, local_time)
    return {"timezone": timezone, "localTime": local_time, "recurring": recurring}


def schedule_upgrade(
    transport: Transport, timezone: str, local_time: str, recurring: bool
) -> UpgradeSchedule:
    reply = transport.rpc(
        "ScheduleSandBoxUpgrade", _schedule_payload(timezone, local_time, recurring)
    )
    return _schedule(_record(reply.get("schedule")), timezone, local_time, recurring)


def reschedule_upgrade(
    transport: Transport, timezone: str, local_time: str, recurring: bool
) -> UpgradeSchedule:
    reply = transport.rpc(
        "RescheduleSandBoxUpgrade", _schedule_payload(timezone, local_time, recurring)
    )
    return _schedule(_record(reply.get("schedule")), timezone, local_time, recurring)


def cancel_upgrade(
    transport: Transport, dismiss_terminal_outcome: bool = False
) -> UpgradeSchedule | None:
    reply = transport.rpc(
        "CancelSandBoxUpgrade", {"dismissTerminalOutcome": dismiss_terminal_outcome}
    )
    return _optional_schedule(reply.get("schedule"))


def overview(transport: Transport) -> Overview:
    notices: list[str] = []
    run = RunState()
    run_refused = schedule_refused = False
    schedule: UpgradeSchedule | None = None
    try:
        run = run_state(transport)
    except ConnectError as error:
        notices.append(_refused(error))
        run_refused = True
    try:
        schedule = upgrade_schedule(transport)
    except ConnectError as error:
        notices.append(_refused(error))
        schedule_refused = True
    return Overview(
        run,
        schedule,
        " ".join(notices),
        run_refused=run_refused,
        schedule_refused=schedule_refused,
    )


def runtime_settings(transport: Transport) -> RuntimeSettings:
    return _settings(
        _record(transport.rpc("GetGrokBotUserRuntimeSettings", {}).get("settings"))
    )


def update_runtime_settings(
    transport: Transport,
    current: RuntimeSettings,
    *,
    pinned_agent_ids: Sequence[str] | None = None,
    auto_review_enabled: bool | None = None,
) -> RuntimeSettings:
    payload: dict[str, object] = {}
    changes: dict[str, object] = {}
    if pinned_agent_ids is not None:
        ids = tuple(pinned_agent_ids)
        payload["pinnedAgents"] = {"agentIds": list(ids)}
        changes["pinned_agent_ids"] = ids
    if auto_review_enabled is not None:
        # Resend the whole message so the allow and block lists survive the change.
        payload["autoReviewInstructions"] = {
            **current.raw_auto_review,
            "isEnabled": auto_review_enabled,
        }
        changes["auto_review_enabled"] = auto_review_enabled
    if not payload:
        raise ValueError("Nothing to change.")
    row = _record(
        transport.rpc("UpdateGrokBotUserRuntimeSettings", payload).get("settings")
    )
    return _settings(row) if row else replace(current, **changes)


def schedule_fields(schedule: UpgradeSchedule | None) -> tuple[tuple[str, str], ...]:
    if schedule is None:
        return (("Upgrade", "none scheduled"),)
    return (
        ("Upgrade", schedule.state),
        ("Local time", schedule.local_time or "none"),
        ("Time zone", schedule.timezone or "none"),
        ("Recurring", "yes" if schedule.recurring else "no"),
        (
            "Next run",
            _when(schedule.next_fire_at_ms) if schedule.next_fire_at_ms else "none",
        ),
        ("Failure reason", schedule.failure_reason or "none"),
    )


def fields(value: Overview) -> tuple[tuple[str, str], ...]:
    rows: tuple[tuple[str, str], ...] = ()
    if not value.run_refused:
        run = value.run
        rows += (
            ("State", run.state),
            ("Image", run.image_tag or "unknown"),
            ("Update available", "yes" if run.image_update_available else "no"),
        )
    if not value.schedule_refused:
        rows += schedule_fields(value.schedule)
    return rows


def settings_fields(
    value: RuntimeSettings, names: Mapping[str, str]
) -> tuple[tuple[str, str], ...]:
    main = value.main_agent_id
    return (
        (
            "Pinned bots",
            ", ".join(names.get(bot_id, bot_id) for bot_id in value.pinned_agent_ids)
            or "none",
        ),
        ("Auto-review", "on" if value.auto_review_enabled else "off"),
        ("Onboarding", "seen" if value.has_seen_onboarding else "not seen"),
        ("Main bot", names.get(main, main) if main else "none"),
        ("Email provider", value.email_provider or "none"),
    )


DEMO_RPCS: dict[str, object] = {name: {} for name in RPCS}
DEMO_RPCS.update(
    {
        "GetSandBoxRunState": {
            "state": "SAND_BOX_RUN_STATE_RUNNING",
            "image": {
                "registryTag": "grok-bot-box:2026.10",
                "staticSnapshotPath": "snapshots/demo",
            },
            "imageUpdateAvailable": True,
            "egressTunnelOwnership": False,
        },
        "GetSandBoxUpgradeSchedule": {
            "schedule": {
                "timezone": "Europe/Paris",
                "localTime": "03:30",
                "recurring": True,
                "targetImageTag": "grok-bot-box:2026.11",
                "nextFireAtMs": "1800086200000",
                "state": "SAND_BOX_UPGRADE_SCHEDULE_STATE_SCHEDULED",
            }
        },
        "RecreateSandBox": {
            "started": True,
            "reason": "",
            "operationId": "demo-operation",
        },
        "ForceRecreateSandBox": {
            "started": True,
            "reason": "",
            "operationId": "demo-force-operation",
        },
        "ScheduleSandBoxUpgrade": lambda args: {
            "schedule": {
                "timezone": args["timezone"],
                "localTime": args["localTime"],
                "recurring": args["recurring"],
                "state": "SAND_BOX_UPGRADE_SCHEDULE_STATE_SCHEDULED",
            }
        },
        "RescheduleSandBoxUpgrade": lambda args: {
            "schedule": {
                "timezone": args["timezone"],
                "localTime": args["localTime"],
                "recurring": args["recurring"],
                "state": "SAND_BOX_UPGRADE_SCHEDULE_STATE_SCHEDULED",
            }
        },
        "UpdateGrokBotUserRuntimeSettings": lambda args: {
            "settings": {
                "pinnedAgents": args.get("pinnedAgents", {"agentIds": []}),
                "autoReviewInstructions": args.get(
                    "autoReviewInstructions", {"isEnabled": False}
                ),
                "hasSeenOnboarding": True,
                "mainAgentId": "demo-helper",
                "updatedAtMs": "1800000000000",
            }
        },
    }
)
