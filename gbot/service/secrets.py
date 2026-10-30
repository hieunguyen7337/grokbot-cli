"""Write-only bot secret values and computer secret name metadata."""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from . import bots
from .models import _record
from .transport import Transport

COMMANDS = {"getBoxSecretsStatus": "none", "carryBoxSecretsToBot": "object"}
RPCS = ("ListGrokBotSecrets", "PutGrokBotSecret", "DeleteGrokBotSecret")
_RESERVED = {
    "PATH",
    "HOME",
    "USER",
    "SHELL",
    "TERM",
    "PWD",
    "DISPLAY",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "CURSOR_SANDBOX",
}
_PREFIXES = ("LD_", "CURSOR_", "CLOUD_AGENT_", "SAND_")


@dataclass(frozen=True)
class SecretInfo:
    name: str
    description: str
    updated_at_ms: int


@dataclass(frozen=True)
class BoxSecrets:
    keys: tuple[str, ...]
    card_keys: tuple[str, ...]
    is_applied: bool
    last_applied_at_ms: int | None


def normalize_name(name: str) -> str:
    name = name.strip().upper()
    if not 1 <= len(name) <= 128:
        raise ValueError("Secret names must contain 1 to 128 characters.")
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", name):
        raise ValueError(
            "Secret names must start with a letter and contain only letters, digits or underscore."
        )
    if name in _RESERVED:
        raise ValueError("This secret name is reserved.")
    if name.startswith(_PREFIXES):
        raise ValueError(
            "Secret names cannot use reserved prefixes LD_, CURSOR_, CLOUD_AGENT_ or SAND_."
        )
    return name


def check_value(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Secret value must not be empty.")
    if len(value.encode("utf-8")) > 4096:
        raise ValueError("Secret value must be at most 4,096 UTF-8 bytes.")
    return value


def _identity(transport: Transport, bot_id: str, *, write: bool = False) -> str:
    row = bots.server_bots(transport).get(bot_id)
    if row is None or not row.server_id:
        raise ValueError(
            "This bot has no server identity; manage its secrets in the Grok Bot app."
        )
    if write and not row.owner:
        raise ValueError(bots._OWNER_ERROR)
    return row.server_id


def _info(value: object) -> SecretInfo:
    row = _record(value)
    return SecretInfo(
        str(row.get("name") or ""),
        str(row.get("description") or ""),
        int(str(row.get("updatedAtMs") or 0)),
    )


def list_secrets(transport: Transport, bot_id: str) -> list[SecretInfo]:
    reply = transport.rpc("ListGrokBotSecrets", {"id": _identity(transport, bot_id)})
    rows = reply.get("secrets")
    return [_info(row) for row in rows] if isinstance(rows, list) else []


def put_secret(
    transport: Transport, bot_id: str, name: str, value: str, description: str = ""
) -> SecretInfo | None:
    name, value = normalize_name(name), check_value(value)
    server_id = _identity(transport, bot_id, write=True)
    try:
        reply = transport.rpc(
            "PutGrokBotSecret",
            {"id": server_id, "name": name, "description": description, "value": value},
        )
    except Exception:  # noqa: BLE001 - secret transport redaction boundary
        # Transport failures may quote the request body. Keep that boundary opaque.
        raise ValueError(
            "Secret was not saved successfully; no value is displayed."
        ) from None
    finally:
        value = ""
    return _info(reply["secret"]) if reply.get("secret") is not None else None


def delete_secret(transport: Transport, bot_id: str, name: str) -> None:
    name = normalize_name(name)
    transport.rpc(
        "DeleteGrokBotSecret",
        {"id": _identity(transport, bot_id, write=True), "name": name},
    )


def box_secrets(transport: Transport) -> BoxSecrets:
    reply = _record(transport.command("getBoxSecretsStatus"))

    def keys(key: str) -> tuple[str, ...]:
        rows = reply.get(key)
        return (
            tuple(row for row in rows if isinstance(row, str))
            if isinstance(rows, list)
            else ()
        )

    stamp = reply.get("lastAppliedAtMs")
    return BoxSecrets(
        keys("keys"),
        keys("cardKeys"),
        reply.get("isApplied") is True,
        int(str(stamp)) if stamp is not None else None,
    )


def carry_to_bot(
    transport: Transport, bot_id: str, names: Sequence[str]
) -> list[tuple[str, str]]:
    names = list(dict.fromkeys(names))
    reply = transport.command(
        "carryBoxSecretsToBot",
        {"serverId": _identity(transport, bot_id, write=True), "names": names},
    )
    return (
        [
            (
                str(_record(row).get("name") or ""),
                str(_record(row).get("outcome") or ""),
            )
            for row in reply
        ]
        if isinstance(reply, list)
        else []
    )


DEMO_COMMANDS: dict[str, object] = {
    "getBoxSecretsStatus": {
        "keys": ["DEMO_TOKEN", "DEMO_KEY"],
        "cardKeys": [],
        "isApplied": True,
        "lastAppliedAtMs": None,
    },
    "carryBoxSecretsToBot": lambda args: [
        {"name": name, "outcome": "copied"} for name in args["names"]
    ],
}
DEMO_RPCS: dict[str, object] = {
    "ListGrokBotSecrets": {
        "secrets": [
            {
                "name": "DEMO_TOKEN",
                "description": "Demo integration",
                "updatedAtMs": "1800000000000",
            }
        ]
    },
    "PutGrokBotSecret": {},
    "DeleteGrokBotSecret": {},
}
