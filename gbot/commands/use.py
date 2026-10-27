import argparse

from gbot import config
from gbot.bots import resolve_bot
from gbot.context import Context


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("use", help="Select the default bot")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("bot", nargs="?")
    group.add_argument("--clear", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace, ctx: Context) -> int:
    if args.clear:
        config.set_default(None)
        ctx.out.write({"default_bot": None}, "Default bot cleared.")
    else:
        bot_id, name = resolve_bot(ctx, args.bot)
        config.set_default((bot_id, name))
        ctx.out.write(
            {"default_bot": {"id": bot_id, "name": name}},
            f"Default bot: {name} ({bot_id})",
        )
    return 0
