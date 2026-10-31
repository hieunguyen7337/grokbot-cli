"""Gateway alerts and their advertised actions."""

from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite

from .transport import Transport

COMMANDS = {"getTrays": "none", "dismissTray": "object", "clearTrays": "none"}
DEMO_COMMANDS = {"getTrays": [], "dismissTray": None, "clearTrays": None}


def _string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _number(value: object) -> float | None:
    return (
        float(value)
        if isinstance(value, (int, float))
        and not isinstance(value, bool)
        and isfinite(value)
        else None
    )


@dataclass(frozen=True)
class TrayAction:
    kind: str
    label: str | None = None
    url: str | None = None
    session_id: str | None = None
    from_seq: float | None = None
    entrypoint: str | None = None
    emphasis: str | None = None

    @classmethod
    def from_raw(cls, raw: object) -> "TrayAction | None":
        if not isinstance(raw, Mapping) or not isinstance(raw.get("kind"), str):
            return None
        kind = raw["kind"]
        for key in ("label", "url", "sessionId", "entrypoint", "emphasis"):
            if key in raw and raw[key] is not None and not isinstance(raw[key], str):
                return None
        if "fromSeq" in raw and _number(raw["fromSeq"]) is None:
            return None
        required = {
            "dashboard-action": ("label", "action"),
            "open-buy-credits": ("label",),
            "roll-back": ("sessionId",),
            "start-fresh": ("sessionId",),
            "open-url": ("label", "url"),
            "upgrade": ("url",),
            "upgradeChoice": ("url",),
        }
        if any(not isinstance(raw.get(key), str) for key in required.get(kind, ())):
            return None
        return cls(
            kind,
            _string(raw.get("label")),
            _string(raw.get("url")),
            _string(raw.get("sessionId")),
            _number(raw.get("fromSeq")),
            _string(raw.get("entrypoint")),
            _string(raw.get("emphasis")),
        )


@dataclass(frozen=True)
class Tray:
    id: str
    agent_id: str
    title: str
    created_at: float
    detail: str | None
    severity: str | None
    count: float
    actions: tuple[TrayAction, ...]
    raw: Mapping[str, object]

    @classmethod
    def from_raw(cls, raw: object) -> "Tray | None":
        if not isinstance(raw, Mapping):
            return None
        tray_id, agent_id, title = (
            _string(raw.get(key)) for key in ("id", "agentId", "title")
        )
        created = _number(raw.get("createdAt"))
        if tray_id is None or agent_id is None or title is None or created is None:
            return None
        actions = raw.get("actions")
        return cls(
            tray_id,
            agent_id,
            title,
            created,
            _string(raw.get("detail")),
            _string(raw.get("severity")),
            _number(raw.get("count")) or 1,
            tuple(
                action
                for item in (actions if isinstance(actions, list) else [])
                if (action := TrayAction.from_raw(item)) is not None
            ),
            dict(raw),
        )


def trays(transport: Transport) -> list[Tray]:
    reply = transport.command("getTrays")
    if reply is None:
        return []
    if not isinstance(reply, list):
        raise ValueError("Unexpected reply to getTrays")  # noqa: TRY004 - protocol contract
    return sorted(
        (tray for raw in reply if (tray := Tray.from_raw(raw)) is not None),
        key=lambda tray: tray.created_at,
        reverse=True,
    )


def dismiss(transport: Transport, tray_id: str) -> None:
    transport.command("dismissTray", {"id": tray_id})


def clear(transport: Transport) -> None:
    transport.command("clearTrays")
