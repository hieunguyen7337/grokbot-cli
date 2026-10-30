import argparse
import getpass
import sys
import warnings
from dataclasses import asdict
from datetime import UTC, datetime

from gbot.bots import resolve_bot
from gbot.commands.approvals import _confirm, _require_confirmation
from gbot.context import Context
from gbot.service import secrets
from gbot.service.transport import ContextTransport


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "secrets", help="Manage bot secrets and computer secret names"
    )
    parser.add_argument("bot", metavar="BOT", nargs="?")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--computer", action="store_true")
    actions.add_argument("--set", metavar="NAME")
    actions.add_argument("--delete", metavar="NAME")
    actions.add_argument("--copy-from-computer", metavar="NAME", nargs="+")
    parser.add_argument("--description", default="")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.set_defaults(func=run)


def _when(stamp_ms: int) -> str:
    if not stamp_ms:
        return "unknown"
    stamp = datetime.fromtimestamp(stamp_ms / 1000, tz=UTC).astimezone()
    return stamp.strftime("%Y-%m-%d %H:%M")


def run(args: argparse.Namespace, ctx: Context) -> int:
    mutation = (
        args.set is not None
        or args.delete is not None
        or args.copy_from_computer is not None
    )
    if mutation:
        _require_confirmation(args.yes)
        if not args.yes:
            raise ValueError("Re-run with --yes to confirm")
    if args.computer and args.bot:
        raise ValueError("Use --computer without BOT.")
    if not args.computer and not args.bot:
        raise ValueError("Specify BOT or --computer.")
    transport = ContextTransport(ctx)
    if args.computer:
        box = secrets.box_secrets(transport)
        ctx.out.write(
            asdict(box),
            "\n".join(box.keys) + ("\nApplied" if box.is_applied else "\nNot applied"),
        )
        return 0
    bot_id, _ = resolve_bot(ctx, args.bot)
    if mutation:
        _confirm(args.yes, json_mode=args.json)
    if args.set is not None:
        name = secrets.normalize_name(args.set)
        value = ""
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                value = (
                    getpass.getpass(f"Value for {name} (hidden): ")
                    if sys.stdin.isatty()
                    else sys.stdin.readline()
                )
        except getpass.GetPassWarning:
            raise ValueError(
                "This terminal cannot hide input; pipe the value on stdin instead."
            ) from None
        try:
            # put_secret redacts transport failures; its own refusals name no value.
            secrets.put_secret(
                transport, bot_id, name, secrets.check_value(value), args.description
            )
        finally:
            value = ""
        ctx.out.write({"name": name, "saved": True}, f"Saved secret {name}.")
    elif args.delete is not None:
        name = secrets.normalize_name(args.delete)
        secrets.delete_secret(transport, bot_id, name)
        ctx.out.write({"name": name, "deleted": True}, f"Deleted secret {name}.")
    elif args.copy_from_computer is not None:
        results = secrets.carry_to_bot(transport, bot_id, args.copy_from_computer)
        ctx.out.write(
            [{"name": name, "outcome": outcome} for name, outcome in results],
            "\n".join(f"{name}: {outcome}" for name, outcome in results),
        )
    else:
        rows = secrets.list_secrets(transport, bot_id)
        ctx.out.write(
            [asdict(row) for row in rows],
            "\n".join(
                f"{row.name}  {row.description}  updated {_when(row.updated_at_ms)}"
                for row in rows
            )
            or "No secrets",
        )
    return 0
