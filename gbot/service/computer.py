"""Desktop computer state and explicit lifecycle actions."""

from dataclasses import dataclass, field

from .models import Bot, _record
from .transport import Transport

COMMANDS = dict.fromkeys(
    (
        "getForeverBoxStatus",
        "ensureForeverBox",
        "updateForeverBox",
        "handBackForeverBox",
    ),
    "object",
)
RPCS = ("EndGrokBotBoxHandoff",)
_DEMO = {
    "state": "running",
    "hostVersion": "0.77.0",
    "hostUpdateAvailable": True,
    "imageUpdateAvailable": False,
    "handoff": {"requestId": "demo-handoff", "instruction": "Review the desktop"},
}
DEMO_COMMANDS = {
    "getForeverBoxStatus": _DEMO,
    "ensureForeverBox": _DEMO,
    "updateForeverBox": _DEMO,
    "handBackForeverBox": None,
}
DEMO_RPCS = {"EndGrokBotBoxHandoff": {"dispatched": True}}


@dataclass(frozen=True)
class ComputerStatus:
    state: str = "absent"
    phase: str = "off"
    vnc_url: str | None = field(default=None, repr=False)
    windows: tuple[dict[str, object], ...] = field(default=(), repr=False)
    handoff_request_id: str = ""
    handoff_instruction: str = ""
    pull_percent: float | None = None
    host_version: str | None = None
    host_update_available: bool | None = None
    image_update_available: bool | None = None
    disk_pressure: str | None = None


def _parse(value: object) -> ComputerStatus:
    row = _record(value)
    state = str(row.get("state", "absent"))
    pull, handoff = row.get("pull"), _record(row.get("handoff"))
    windows = row.get("windows", [])
    percent = _record(pull).get("percent")
    host_update = row.get("hostUpdateAvailable")
    image_update = row.get("imageUpdateAvailable")
    return ComputerStatus(
        state=state,
        phase="pulling"
        if pull is not None
        else {"running": "running", "hibernated": "sleeping"}.get(state, "off"),
        vnc_url=str(row["vncUrl"]) if row.get("vncUrl") else None,
        windows=tuple(dict(w) for w in windows if isinstance(w, dict))
        if isinstance(windows, list)
        else (),
        handoff_request_id=str(handoff.get("requestId", "")),
        handoff_instruction=str(handoff.get("instruction", "")),
        pull_percent=float(percent) if isinstance(percent, (int, float)) else None,
        host_version=str(row["hostVersion"]) if row.get("hostVersion") else None,
        host_update_available=host_update if isinstance(host_update, bool) else None,
        image_update_available=image_update if isinstance(image_update, bool) else None,
        disk_pressure=str(_record(row.get("diskPressure"))["level"])
        if _record(row.get("diskPressure")).get("level")
        else None,
    )


def status(transport: Transport, bot_id: str) -> ComputerStatus:
    return _parse(transport.command("getForeverBoxStatus", {"id": bot_id}))


def wake(transport: Transport, bot_id: str) -> ComputerStatus:
    return _parse(transport.command("ensureForeverBox", {"id": bot_id}))


def update(transport: Transport, bot_id: str) -> ComputerStatus:
    return _parse(transport.command("updateForeverBox", {"id": bot_id}))


def hand_back(
    transport: Transport, bot: Bot, request_id: str, trigger: str = "button"
) -> None:
    if not request_id.strip():
        raise ValueError("Nothing to hand back.")
    triggers = {"button": 1, "viewer-closed": 2, "dismissed": 3}
    if trigger not in triggers:
        raise ValueError("Unknown hand-back trigger.")
    if bot.raw.get("harness") == "temporal":
        transport.rpc(
            "EndGrokBotBoxHandoff",
            {"agentId": bot.id, "requestId": request_id, "trigger": triggers[trigger]},
        )
    else:
        transport.command(
            "handBackForeverBox",
            {"id": bot.id, "requestId": request_id, "trigger": trigger},
        )


def fields(value: ComputerStatus) -> tuple[tuple[str, str], ...]:
    updates = [
        name
        for name, available in (
            ("host", value.host_update_available),
            ("image", value.image_update_available),
        )
        if available
    ]
    return (
        ("State", value.state),
        ("Phase", value.phase),
        ("Host version", value.host_version or "unknown"),
        ("Updates", ", ".join(updates) or "none"),
        ("Disk pressure", value.disk_pressure or "none"),
    )
