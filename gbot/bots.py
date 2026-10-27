from typing import cast

from groken.gateway import UnknownBotError

from . import config
from .context import Context


def record(value: object) -> dict[str, object]:
    return cast(dict[str, object], value) if isinstance(value, dict) else {}


def list_bots(ctx: Context) -> list[dict[str, object]]:
    result = ctx.manager().command("listAgents")
    # The 0.72 gateway replies with a bare array; accept {"agents": [...]} too.
    rows = result if isinstance(result, list) else record(result).get("agents", [])
    if not isinstance(rows, list):
        raise TypeError("Invalid bot list from gateway.")
    return [
        record(row) for row in rows if record(row).get("id") and record(row).get("name")
    ]


def resolve_bot(ctx: Context, requested: str | None) -> tuple[str, str]:
    bots = list_bots(ctx)
    names = [str(bot["name"]) for bot in bots]
    if requested is None:
        default = config.default_bot()
        if default is None:
            raise ValueError(
                "No bot selected. Run: gbot use <name> (available: "
                + ", ".join(names)
                + ")"
            )
        matches = [bot for bot in bots if bot["id"] == default["id"]]
        if not matches:
            raise ValueError(
                f"Default bot {default['name']} ({default['id']}) no longer exists."
                " Run: gbot use <name> (available: " + ", ".join(names) + ")"
            )
        selected = (str(matches[0]["id"]), str(matches[0]["name"]))
        if selected[1] != default["name"]:
            config.set_default(selected)
        return selected
    matches = [bot for bot in bots if bot["id"] == requested]
    if not matches:
        matches = [bot for bot in bots if bot["name"] == requested]
    if not matches:
        matches = [
            bot for bot in bots if str(bot["name"]).casefold() == requested.casefold()
        ]
    if len(matches) > 1:
        raise ValueError(
            "Ambiguous bot: "
            + requested
            + " (matches: "
            + ", ".join(f"{bot['name']} [{bot['id']}]" for bot in matches)
            + ")"
        )
    if not matches:
        raise UnknownBotError(requested, names)
    return str(matches[0]["id"]), str(matches[0]["name"])
