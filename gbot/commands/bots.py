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
    ctx.out.write(
        rows,
        "DEFAULT  ID  NAME  STATE\n"
        + "\n".join(
            f"{'*' if row['default'] else ' '}  {row['id']}  {row['name']}  {row['state']}"
            for row in rows
        ),
    )
    return 0
