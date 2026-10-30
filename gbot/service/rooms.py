"""Group creation and bot and human membership."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from groken.client import ConnectError

from .bots import creation_route, server_bot
from .models import Bot
from .transport import Transport

COMMANDS = {"createGroup": "object", "setGroupMembers": "object"}
RPCS = (
    "SetGrokBotRoomMembers",
    "RemoveGrokBotRoomPeople",
    "GetGrokBotRuntimeCapabilities",
    "CreateGrokBotRoom",
)
DEMO_COMMANDS = {
    "createGroup": {
        "agent": {
            "id": "demo-new-group",
            "name": "New group",
            "isGroup": True,
            "memberIds": ["demo-helper", "demo-researcher"],
        },
        "transcript": [],
    },
    "setGroupMembers": None,
}
DEMO_RPCS: dict[str, object] = {name: {} for name in RPCS}
DEMO_RPCS["CreateGrokBotRoom"] = lambda args: {
    "agent": {
        **args,
        "id": "demo-server-room",
        "kind": "ROOM",
        "harness": "temporal",
    }
}


@dataclass(frozen=True)
class Person:
    display_name: str
    is_viewer: bool
    user_id: int | None = None


def create_group(
    transport: Transport,
    name: str,
    member_ids: Sequence[str],
    *,
    description: str = "",
    nonce: str,
) -> Bot | None:
    try:
        route = creation_route(transport)
    except ConnectError as exc:
        # Older box-only backends do not expose runtime capabilities.
        if exc.status != 404:
            raise
        route = "box"
    if route == "temporal":
        reply = transport.rpc(
            "CreateGrokBotRoom",
            {
                "agentId": nonce,
                "name": name,
                "description": description,
                "memberAgentIds": list(member_ids),
                "humanMemberUserIds": [],
            },
        )
        bot = server_bot(reply.get("agent"))
        if (
            bot is None
            or bot.id != nonce
            or not bot.is_group
            or bot.raw.get("harness") != "temporal"
        ):
            raise ValueError(
                "Room creation returned a different identity, kind or harness."
            )
        return bot
    args: dict[str, object] = {
        "name": name,
        "memberAgentIds": list(member_ids),
        "namedBy": "user",
        "clientNonce": nonce,
    }
    if description:
        args["description"] = description
    reply = transport.command("createGroup", args)
    return Bot.from_row(reply.get("agent")) if isinstance(reply, Mapping) else None


create = create_group


def set_members(transport: Transport, group: Bot, member_ids: Sequence[str]) -> None:
    if group.raw.get("harness") == "temporal":
        transport.rpc(
            "SetGrokBotRoomMembers",
            {"agentId": group.id, "memberAgentIds": list(member_ids)},
        )
    else:
        transport.command(
            "setGroupMembers", {"id": group.id, "memberAgentIds": list(member_ids)}
        )


def remove_people(transport: Transport, group_id: str, user_ids: Sequence[int]) -> None:
    transport.rpc(
        "RemoveGrokBotRoomPeople", {"agentId": group_id, "userIds": list(user_ids)}
    )


def people(bot: Bot) -> list[Person]:
    rows = bot.raw.get("people")
    result = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, Mapping):
            continue
        name, viewer, user_id = (
            row.get("displayName"),
            row.get("isViewer"),
            row.get("userId"),
        )
        if not isinstance(name, str) or not name or not isinstance(viewer, bool):
            continue
        if user_id is not None and type(user_id) is not int:
            continue
        result.append(Person(name, viewer, user_id))
    return result
