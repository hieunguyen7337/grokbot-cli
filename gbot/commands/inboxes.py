import argparse
from dataclasses import asdict

from gbot.commands.approvals import _confirm, _require_confirmation
from gbot.context import Context
from gbot.service import inboxes
from gbot.service.transport import ContextTransport


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("inboxes", help="List or create email inboxes")
    parser.add_argument("--create", metavar="USERNAME")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace, ctx: Context) -> int:
    transport = ContextTransport(ctx)
    if args.create is not None:
        _require_confirmation(args.yes)
        username = inboxes.normalize_username(args.create)
        _confirm(args.yes, json_mode=args.json)
        item = inboxes.create_inbox(transport, username)
        ctx.out.write(asdict(item), item.email)
    else:
        rows = inboxes.list_inboxes(transport)
        ctx.out.write(
            [asdict(row) for row in rows],
            "\n".join(
                f"{row.email}  {'assigned' if row.assigned else 'unassigned'}"
                for row in rows
            )
            or "No inboxes",
        )
    return 0
