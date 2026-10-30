"""Bot identity, creation and user runtime settings."""

import base64
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from . import conversation
from .demo import demo_state
from .models import Bot
from .transport import Transport

COMMANDS = {
    "createAgent": "object",
    "kickstartAgent": "object",
    "updateAgent": "object",
    "deleteAgents": "object",
    "setAgentHiddenFromSidebar": "object",
    "setAgentNotifyOnUpdates": "object",
    "setAgentDraftingDisabled": "object",
    "readMainAgentContext": "object",
}
RPCS = (
    "GetGrokBotRuntimeCapabilities",
    "CreateGrokBotTemporalAgent",
    "GetGrokBotUserRuntimeSettings",
    "SetGrokBotMainAgent",
    "EnsureGrokBotDefaultMainAgent",
    "ListGrokBotAgents",
)
SHAPES = (
    "blob",
    "pebble",
    "bean",
    "egg",
    "squircle",
    "tablet",
    "capsule",
    "cylinder",
    "hex",
    "gem",
    "crystal",
    "wedge",
    "shield",
    "dome",
    "arch",
    "cloud",
    "teardrop",
    "leaf",
    "square",
    "sparkle",
    "clover",
    "flower",
    "heart",
    "house",
    "star",
    "pumpkin",
)
COLORS = (
    "black",
    "brown",
    "red",
    "orange",
    "yellow",
    "green",
    "cyan",
    "blue",
    "violet",
    "magenta",
    "gray",
)
_OWNER_ERROR = "Only the bot's owner can change this in gbot; use the app"


@dataclass(frozen=True)
class Capabilities:
    temporal_creation_enabled: bool = False
    durable_identity_enabled: bool = False
    durable_identity_writes_enabled: bool = False
    agent_messaging_enabled: bool = False
    server_rooms_enabled: bool = False


@dataclass(frozen=True)
class ServerBot:
    server_id: str
    harness: str
    is_group: bool
    drafting_disabled: bool
    owner: bool
    can_manage: bool | None
    voice_id: str | None
    voice_speed: float | None
    voice_language: str | None


@dataclass(frozen=True)
class DeleteResult:
    refused_ids: tuple[str, ...] = ()
    failed_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class MainContext:
    agent_id: str
    is_working: bool


def _record(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def capabilities(transport: Transport) -> Capabilities:
    data = _record(
        transport.rpc("GetGrokBotRuntimeCapabilities", {}).get("capabilities")
    )
    return Capabilities(
        *(
            data.get(key) is True
            for key in (
                "temporalCreationEnabled",
                "durableIdentityEnabled",
                "durableIdentityWritesEnabled",
                "agentMessagingEnabled",
                "serverRoomsEnabled",
            )
        )
    )


def creation_route(transport: Transport) -> Literal["temporal", "box"]:
    flags = capabilities(transport)
    if not flags.temporal_creation_enabled:
        return "box"
    if not (flags.durable_identity_enabled and flags.durable_identity_writes_enabled):
        raise ValueError(
            "Temporal creation requires durable identity and durable identity writes."
        )
    return "temporal"


def server_bot(row: object) -> Bot | None:
    """Normalize backend identity; backend id is never the gateway id."""
    data = dict(_record(row))
    data["serverId"] = data.get("id")
    data["id"] = data.get("agentId")
    data["isGroup"] = data.get("kind") in ("ROOM", 2)
    data["memberIds"] = data.get("memberAgentIds", [])
    return Bot.from_row(data)


def create(
    transport: Transport,
    name: str,
    *,
    description: str = "",
    shape: str = "blob",
    color: str = "blue",
    png: bytes | None = None,
    nonce: str | None = None,
    language: str | None = None,
) -> Bot:
    name = name.strip()
    if not name or len(name) > 255:
        raise ValueError("Bot name must contain 1 to 255 characters.")
    if shape not in SHAPES or color not in COLORS:
        raise ValueError("Unknown bot shape or color.")
    nonce = nonce if nonce is not None else str(uuid.uuid4())
    if not nonce:
        raise ValueError("Creation nonce must not be empty.")
    args: dict[str, object] = {
        "name": name,
        "description": description,
        "avatarShape": shape,
        "avatarColor": color,
    }
    if language is not None:
        args["language"] = language
    if creation_route(transport) == "temporal":
        args.update(
            agentId=nonce,
            title="",
            # GrokBotAgentHarnessKind.TEMPORAL; protobuf JSON accepts the enum number.
            harness=2,
            kickstartRequested=True,
            introductionSuppressed=False,
        )
        if png is not None:
            args["avatarDataUrl"] = "data:image/png;base64," + base64.b64encode(
                png
            ).decode("ascii")
        reply = transport.rpc("CreateGrokBotTemporalAgent", args)
        row = _record(reply.get("agent"))
        if row.get("agentId") != nonce or row.get("harness") != "temporal":
            raise ValueError(
                "Temporal creation returned a different agent identity or harness."
            )
        bot = server_bot(row)
    else:
        args.update(origin="user", isKickstartRequested=True, clientNonce=nonce)
        if png is not None:
            args["avatarPngBase64"] = base64.b64encode(png).decode("ascii")
        bot = Bot.from_row(_record(transport.command("createAgent", args)).get("agent"))
        if bot is not None:
            transport.command("kickstartAgent", {"id": bot.id})
    if bot is None:
        raise ValueError("Creation returned no valid bot.")
    return bot


def server_bots(transport: Transport) -> dict[str, ServerBot]:
    rows = transport.rpc("ListGrokBotAgents", {}).get("agents")
    result = {}
    for row in rows if isinstance(rows, list) else []:
        data = _record(row)
        agent_id = _text(data.get("agentId"))
        if not agent_id:
            continue
        speed = data.get("voiceSpeed")
        manage = data.get("viewerCanManage")
        result[agent_id] = ServerBot(
            _text(data.get("id")),
            _text(data.get("harness")),
            data.get("kind") in ("ROOM", 2),
            data.get("draftingDisabled") is True,
            data.get("viewerIsOwner") is not False,
            manage if isinstance(manage, bool) else None,
            _text(data.get("voiceId")) or None,
            float(speed)
            if isinstance(speed, (float, int)) and not isinstance(speed, bool)
            else None,
            _text(data.get("voiceLanguage")) or None,
        )
    return result


def _owned(transport: Transport, bot_ids: Sequence[str]) -> dict[str, ServerBot]:
    rows = server_bots(transport)
    if any(bot_id in rows and not rows[bot_id].owner for bot_id in bot_ids):
        raise ValueError(_OWNER_ERROR)
    return rows


def update(
    transport: Transport,
    bot: Bot,
    *,
    name: str | None = None,
    description: str | None = None,
    title: str | None = None,
    shape: str | None = None,
    color: str | None = None,
) -> Bot | None:
    if (shape is not None and shape not in SHAPES) or (
        color is not None and color not in COLORS
    ):
        raise ValueError("Unknown bot shape or color.")
    profile: dict[str, object] = {"name": bot.name, "description": bot.description}
    edited = []
    for key, value, old in (
        ("name", name, bot.name),
        ("description", description, bot.description),
        ("title", title, bot.title),
        ("avatarShape", shape, bot.raw.get("avatarShape")),
        ("avatarColor", color, bot.avatar_color),
    ):
        if value is not None and value != old:
            profile[key] = value
            edited.append(key)
    if not edited:
        raise ValueError("No bot fields changed.")
    _owned(transport, [bot.id])
    return Bot.from_row(
        transport.command(
            "updateAgent", {"id": bot.id, "profile": profile, "editedFields": edited}
        )
    )


def delete(transport: Transport, bot_ids: Sequence[str]) -> DeleteResult:
    ids = list(bot_ids)
    if not ids:
        raise ValueError("Select at least one bot to delete.")
    if main_agent(transport) in ids:
        raise ValueError(
            "Cannot delete the current main bot; set another main bot first."
        )
    _owned(transport, ids)
    data = _record(transport.command("deleteAgents", {"ids": ids}))

    def strings(key: str) -> tuple[str, ...]:
        value = data.get(key)
        return (
            tuple(item for item in value if isinstance(item, str))
            if isinstance(value, list)
            else ()
        )

    return DeleteResult(strings("refusedAgentIds"), strings("failedAgentIds"))


def set_hidden(transport: Transport, bot_id: str, value: bool) -> None:
    _owned(transport, [bot_id])
    transport.command("setAgentHiddenFromSidebar", {"id": bot_id, "isHidden": value})


def set_notify_on_updates(transport: Transport, bot_id: str, value: bool) -> None:
    _owned(transport, [bot_id])
    transport.command("setAgentNotifyOnUpdates", {"id": bot_id, "isEnabled": value})


def set_drafting_disabled(transport: Transport, bot_id: str, value: bool) -> None:
    rows = _owned(transport, [bot_id])
    if bot_id in rows and rows[bot_id].is_group:
        raise ValueError("Drafting settings are available only for non-group bots.")
    # Box groups may exist only in the gateway roster.
    if any(bot.id == bot_id and bot.is_group for bot in conversation.roster(transport)):
        raise ValueError("Drafting settings are available only for non-group bots.")
    transport.command("setAgentDraftingDisabled", {"id": bot_id, "isDisabled": value})


def main_agent(transport: Transport) -> str | None:
    reply = transport.rpc("GetGrokBotUserRuntimeSettings", {})
    return _text(_record(reply.get("settings")).get("mainAgentId")) or None


def set_main(transport: Transport, bot_id: str) -> None:
    transport.rpc("SetGrokBotMainAgent", {"agentId": bot_id})


def ensure_main(transport: Transport) -> tuple[str, str]:
    reply = transport.rpc("EnsureGrokBotDefaultMainAgent", {})
    outcomes = (
        "unspecified",
        "created",
        "present",
        "has_main_agent",
        "tombstoned",
        "pinned_full",
        "busy",
    )
    value = reply.get("outcome")
    outcome = (
        outcomes[value]
        if type(value) is int and 0 <= value < len(outcomes)
        else _text(value).lower()
    )
    return _text(reply.get("agentId")), outcome or "unspecified"


def main_context(transport: Transport, bot_id: str) -> MainContext:
    data = _record(transport.command("readMainAgentContext", {"id": bot_id}))
    return MainContext(_text(data.get("agentId")), data.get("isWorking") is True)


DEMO_COMMANDS: dict[str, object] = {name: None for name in COMMANDS}
DEMO_COMMANDS.update(
    {
        "listAgents": demo_state(1_800_000_000_000).rows,
        "createAgent": {"agent": {"id": "demo-new-bot", "name": "New bot"}},
        "updateAgent": {"id": "demo-helper", "name": "Helper"},
        "deleteAgents": {"transcript": [], "refusedAgentIds": [], "failedAgentIds": []},
        "readMainAgentContext": {"agentId": "demo-helper", "isWorking": False},
    }
)
DEMO_RPCS: dict[str, object] = {name: {} for name in RPCS}
DEMO_RPCS.update(
    {
        "ListGrokBotAgents": {"agents": []},
        "EnsureGrokBotDefaultMainAgent": {
            "agentId": "demo-helper",
            "outcome": "PRESENT",
        },
        "CreateGrokBotTemporalAgent": lambda args: {
            "agent": {
                **args,
                "id": "demo-server-bot",
                "harness": "temporal",
            }
        },
    }
)
