import argparse

from gbot.bots import resolve_bot
from gbot.context import Context, prompt


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("ask", help="Ask a bot and wait for its reply")
    parser.add_argument("--bot")
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--idle", type=float, default=45)
    parser.add_argument("--stream", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("text", nargs="+")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace, ctx: Context) -> int:
    text = prompt(args)
    bot_id, name = resolve_bot(ctx, args.bot)
    if args.stream:
        reply = ctx.manager().ask_stream(
            bot_id,
            text,
            args.timeout,
            args.idle,
            on_chunk=None if ctx.out.json_mode else ctx.out.chunk,
        )
        if not ctx.out.json_mode:
            print()
            return 0
    else:
        reply = ctx.manager().ask(bot_id, text, args.timeout, args.idle)
    ctx.out.write({"bot": {"id": bot_id, "name": name}, "reply": reply}, reply)
    return 0
