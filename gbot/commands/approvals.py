import argparse
import getpass
import sys
import warnings

from gbot.context import Context
from gbot.pending import (
    PendingItem,
    command_block,
    discover,
    render,
    resolve_ref,
)
from gbot.service import cards
from gbot.service.models import Action
from gbot.service.transport import ContextTransport


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("approvals", help="List what bots are waiting on")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--bot")
    selection.add_argument("--all", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.set_defaults(func=list_pending)
    for name, help_text in (
        ("approve", "Approve a pending review, tool permission or draft"),
        ("deny", "Deny a pending review, tool permission or draft"),
        ("respond", "Answer a widget or user form"),
        ("dismiss", "Dismiss a widget or user form"),
        ("secret", "Supply a requested secret without echoing it"),
    ):
        parser = subparsers.add_parser(name, help=help_text)
        parser.add_argument("ref", metavar="REF")
        parser.add_argument("--yes", action="store_true")
        parser.add_argument("--json", action="store_true")
        parser.add_argument("--bot", help="Bot that owns REF, when REF is ambiguous")
        if name == "approve":
            parser.add_argument("--always", action="store_true")
            parser.add_argument(
                "--all-bots",
                action="store_true",
                help="connector grant: always allow for all team bots",
            )
        elif name == "deny":
            parser.add_argument("--never", action="store_true")
        elif name == "respond":
            parser.add_argument("value", metavar="VALUE", nargs="?")
            parser.add_argument(
                "--field", action="append", default=[], metavar="NAME=VALUE"
            )
        elif name == "secret":
            # Reject accidental positional secrets without argparse echoing them.
            parser.add_argument("unexpected_values", nargs="*", help=argparse.SUPPRESS)
        parser.set_defaults(func=answer)


def list_pending(args: argparse.Namespace, ctx: Context) -> int:
    items = discover(ctx, args.bot, all_bots=args.all)
    ctx.out.write([item.to_dict() for item in items], render(items))
    return 2 if items else 0


def _require_confirmation(yes: bool) -> None:
    if not yes and not sys.stdin.isatty():
        raise ValueError("Re-run with --yes to confirm")


def _confirm(yes: bool, *, json_mode: bool = False) -> None:
    _require_confirmation(yes)
    if not yes and json_mode:
        print("Confirm [y/N]: ", end="", file=sys.stderr, flush=True)
    if not yes and input(
        "" if json_mode else "Confirm [y/N]: "
    ).strip().casefold() not in {"y", "yes"}:
        raise ValueError("Cancelled.")


def _submit_secret(ctx: Context, item: PendingItem, yes: bool) -> None:
    # This boundary must sanitize even transport exceptions and disable getpass's
    # fallback to echoed input. Never expose the reply body or a refusal message.
    failure = None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            value = getpass.getpass("Secret (hidden): ")
        _confirm(yes, json_mode=ctx.out.json_mode)
        try:
            cards.answer(ContextTransport(ctx), item, Action("secret", secret=value))
        except ValueError as exc:
            failure = str(exc)
    except Exception:  # noqa: BLE001 - secret submission is a redaction boundary
        failure = "Secret was not submitted successfully; no value is displayed."
    if failure:
        raise ValueError(failure)


def answer(args: argparse.Namespace, ctx: Context) -> int:
    if args.command == "secret" and args.unexpected_values:
        raise ValueError("Secret values must be entered at the hidden prompt.")
    item = resolve_ref(ctx, args.ref, args.bot)
    fields = []
    for raw in getattr(args, "field", ()):
        name, separator, value = raw.partition("=")
        fields.append((name if separator else "", value))
    action = Action(
        args.command,
        always=getattr(args, "always", False),
        never=getattr(args, "never", False),
        value=getattr(args, "value", None),
        fields=tuple(fields),
        all_bots=getattr(args, "all_bots", False),
    )
    method, payload = cards.plan(item, action)
    preview = sys.stderr if ctx.out.json_mode else sys.stdout
    print(
        f"Bot: {item.bot_name} ({item.bot_id})  Type: {item.type}  REF: {item.entry_id}",
        file=preview,
    )
    print(f"Summary: {item.summary}", file=preview)
    if item.tool_text:
        heading = (
            "Draft ({count} lines, sent exactly as shown if approved):"
            if item.draft is not None
            else None
        )
        print(command_block(item.tool_text, heading), file=preview)
    effect = cards.effect(item, action, method, payload)
    print(f"Answer: {method}" + (f" ({effect})" if effect else ""), file=preview)
    _require_confirmation(args.yes)
    if method == "SubmitGrokBotSecret":
        _submit_secret(ctx, item, args.yes)
    else:
        _confirm(args.yes, json_mode=ctx.out.json_mode)
        cards.answer(ContextTransport(ctx), item, action)
    if ctx.out.json_mode:
        ctx.out.write(
            {
                "answered": True,
                "bot_id": item.bot_id,
                "bot_name": item.bot_name,
                "entry_id": item.entry_id,
                "type": item.type,
                "rpc": method,
                "effect": effect,
            },
            "",
        )
    else:
        print("Answered.")
    return 0
