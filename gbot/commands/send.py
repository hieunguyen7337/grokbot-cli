import argparse

from gbot.bots import resolve_bot
from gbot.context import Context, prompt
from gbot.service import conversation
from gbot.service.transport import ContextTransport


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("send", help="Send a prompt without waiting")
    parser.add_argument("--bot")
    parser.add_argument("--session", metavar="ID")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("text", nargs="+")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace, ctx: Context) -> int:
    text = prompt(args)
    bot_id, name = resolve_bot(ctx, args.bot)
    result = conversation.send(
        ContextTransport(ctx), bot_id, text, session_id=args.session
    )
    ctx.out.write(
        {
            "accepted": result.accepted,
            "bot": {"id": bot_id, "name": name},
            "last_seq": result.last_seq,
        },
        f"Sent to {name}.",
    )
    return 0
