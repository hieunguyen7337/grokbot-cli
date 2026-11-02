import argparse
from datetime import UTC, datetime

from gbot.bots import resolve_bot
from gbot.context import Context
from gbot.service import conversation
from gbot.service.transport import ContextTransport


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "sessions", help="List a bot's sessions (routing contexts)"
    )
    parser.add_argument("--bot")
    parser.add_argument("--json", action="store_true")
    parser.set_defaults(func=run)


def _when(ms: object) -> str:
    if not isinstance(ms, int) or ms <= 0:
        return "-"
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%d %H:%M")


def run(args: argparse.Namespace, ctx: Context) -> int:
    bot_id, name = resolve_bot(ctx, args.bot)
    rows = conversation.list_sessions(ContextTransport(ctx), bot_id)
    lines = [
        f"{row['kind']:<16}  {_when(row.get('lastActivityAtMs', row['updatedAtMs']))}"
        f"  {row['sessionId'] or '(default)'}"
        for row in rows
    ]
    ctx.out.write(
        {"bot": {"id": bot_id, "name": name}, "sessions": rows},
        "\n".join(lines) if lines else f"No sessions for {name}.",
    )
    return 0
