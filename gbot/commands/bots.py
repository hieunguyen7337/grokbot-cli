import argparse

from gbot import config
from gbot.bots import list_bots
from gbot.context import Context


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("bots", help="List existing bots")
    parser.add_argument("--json", action="store_true")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace, ctx: Context) -> int:
    default = config.default_bot() or {}
    rows = [
        {
            "id": bot["id"],
            "name": bot["name"],
            "state": "composing"
            if bot.get("isComposingMessage")
            else "running"
            if bot.get("isRunning")
            else "idle",
            "default": bot["id"] == default.get("id"),
        }
        for bot in list_bots(ctx)
    ]
    name_width = max([len("NAME"), *(len(str(row["name"])) for row in rows)])
    state_width = max([len("STATE"), *(len(str(row["state"])) for row in rows)])
    lines = [f"   {'NAME':<{name_width}}  {'STATE':<{state_width}}  ID"]
    lines.extend(
        f"{'*' if row['default'] else ' '}  {row['name']!s:<{name_width}}  "
        f"{row['state']!s:<{state_width}}  {row['id']}"
        for row in rows
    )
    ctx.out.write(rows, "\n".join(lines))
    return 0
