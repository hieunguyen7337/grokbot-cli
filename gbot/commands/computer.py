import argparse
import webbrowser
from dataclasses import asdict

from gbot.bots import resolve_bot
from gbot.commands.approvals import _confirm, _require_confirmation
from gbot.context import Context
from gbot.service import computer, conversation
from gbot.service.transport import ContextTransport


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("computer", help="Inspect or manage a bot computer")
    parser.add_argument("bot", metavar="BOT")
    actions = parser.add_mutually_exclusive_group()
    for flag in ("wake", "update", "hand-back", "open"):
        actions.add_argument("--" + flag, action="store_true")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace, ctx: Context) -> int:
    mutation = args.wake or args.update or args.hand_back
    if mutation:
        _require_confirmation(args.yes)
    transport = ContextTransport(ctx)
    bot_id, _ = resolve_bot(ctx, args.bot)
    value = computer.status(transport, bot_id)
    if mutation:
        if args.hand_back and not value.handoff_request_id:
            raise ValueError("Nothing to hand back.")
        _confirm(args.yes, json_mode=args.json)
        if args.wake:
            value = computer.wake(transport, bot_id)
        elif args.update:
            value = computer.update(transport, bot_id)
        else:
            bot = next(b for b in conversation.roster(transport) if b.id == bot_id)
            computer.hand_back(transport, bot, value.handoff_request_id)
            value = computer.status(transport, bot_id)
    if args.open:
        if not value.vnc_url:
            raise ValueError("No live view available.")
        try:
            webbrowser.open(value.vnc_url)
        except Exception:  # noqa: BLE001 - browser errors may contain access tokens
            # Browser failures may contain the access URL.
            raise ValueError("Could not open the live view.") from None
        ctx.out.write({"opened": True}, "Opened the live view.")
    else:
        result = asdict(value)
        result.pop("vnc_url")
        result.pop("windows")
        text = "\n".join(f"{key}: {val}" for key, val in computer.fields(value))
        if value.handoff_request_id:
            text += "\nHand-off: " + value.handoff_instruction
        ctx.out.write(result, text)
    return 0
