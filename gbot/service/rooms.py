"""Group creation and bot and human membership."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .models import Bot
from .transport import Transport

COMMANDS = {"createGroup": "object", "setGroupMembers": "object"}
RPCS = ("SetGrokBotRoomMembers", "RemoveGrokBotRoomPeople")
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
DEMO_RPCS = {name: {} for name in RPCS}


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
