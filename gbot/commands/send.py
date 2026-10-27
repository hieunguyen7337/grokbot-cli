import argparse

from gbot.bots import resolve_bot
from gbot.context import Context, prompt


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("send", help="Send a prompt without waiting")
    parser.add_argument("--bot")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("text", nargs="+")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace, ctx: Context) -> int:
    text = prompt(args)
    bot_id, name = resolve_bot(ctx, args.bot)
    result = ctx.manager().send_prompt(bot_id, text)
    ctx.out.write(result, f"Sent to {name}.")
    return 0
