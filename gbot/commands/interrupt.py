import argparse

from gbot.bots import resolve_bot
from gbot.commands.approvals import _confirm
from gbot.context import Context
from gbot.service import runs
from gbot.service.transport import ContextTransport


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("interrupt", help="Stop a bot's active run")
    parser.add_argument("--bot")
    parser.add_argument("--session", metavar="ID")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace, ctx: Context) -> int:
    bot_id, name = resolve_bot(ctx, args.bot)
    _confirm(args.yes, json_mode=args.json)
    stopped = runs.interrupt(ContextTransport(ctx), bot_id, session_id=args.session)
    ctx.out.write(
        {
            "interrupted": stopped,
            "bot": {"id": bot_id, "name": name},
            "session_id": args.session,
        },
        f"Stopped {name}." if stopped else f"{name} had nothing running.",
    )
    return 0
