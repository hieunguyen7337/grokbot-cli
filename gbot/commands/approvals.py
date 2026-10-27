import argparse
import getpass
import sys
import warnings

from gbot.context import Context
from gbot.pending import (
    APP_ONLY,
    PendingItem,
    command_block,
    discover,
    render,
    resolve_ref,
)


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("approvals", help="List what bots are waiting on")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--bot")
    selection.add_argument("--all", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.set_defaults(func=list_pending)
    for name, help_text in (
        ("approve", "Approve a pending review or tool permission"),
        ("deny", "Deny a pending review or tool permission"),
        ("respond", "Answer a widget or user form"),
        ("dismiss", "Dismiss a widget or user form"),
        ("secret", "Supply a requested secret without echoing it"),
    ):
        parser = subparsers.add_parser(name, help=help_text)
        parser.add_argument("ref", metavar="REF")
        parser.add_argument("--yes", action="store_true")
        if name == "approve":
            parser.add_argument("--always", action="store_true")
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


def _plan(args: argparse.Namespace, item: PendingItem) -> tuple[str, dict[str, object]]:
    if not item.allowed_actions:
        raise ValueError(f"{item.type}: {APP_ONLY}.")
    action = args.command
    if action not in item.allowed_actions:
        right = " or ".join(f"gbot {name} REF" for name in item.allowed_actions)
        raise ValueError(f"{action} cannot answer {item.type}. Use: {right}")
    payload: dict[str, object] = {"agentId": item.bot_id, "entryId": item.entry_id}
    if item.session_id is not None:
        payload["sessionId"] = item.session_id
    if action in {"approve", "deny"}:
        tool = item.type == "local-tool-permission"
        if not item.request_id:
            raise ValueError("Pending approval is missing its requestId.")
        if action == "deny" and args.never and not tool:
            raise ValueError(
                "--never applies only to local-tool-permission. Use: gbot deny REF"
            )
        resolution = "approved" if action == "approve" else "denied"
        if tool:
            resolution = "allow-once" if action == "approve" else "deny"
        if action == "approve" and args.always:
            resolution = "always"
        elif action == "deny" and args.never:
            resolution = "never"
        payload.update(requestId=item.request_id, resolution=resolution)
        return (
            "resolveLocalToolPermission" if tool else "resolveAutoReviewApproval"
        ), payload
    if action == "respond":
        if item.type == "widget":
            if args.value is None or args.field:
                raise ValueError("Use: gbot respond REF VALUE for a widget.")
            payload["value"] = args.value
            return "respondToWidget", payload
        if args.value is not None or not args.field:
            raise ValueError(
                "Use: gbot respond REF --field NAME=VALUE for a user-form."
            )
        values: dict[str, str] = {}
        for field in args.field:
            name, separator, value = field.partition("=")
            if not separator or not name or name in values:
                raise ValueError(
                    "Each --field must have a unique, nonempty NAME=VALUE."
                )
            values[name] = value
        payload.update(values=values, saveToVault=False)
        return "submitUserForm", payload
    if action == "dismiss":
        if item.type == "widget":
            return "dismissWidget", payload
        payload["mode"] = "dismissed"
        return "dismissUserForm", payload
    return "submitSecret", payload


def _require_confirmation(yes: bool) -> None:
    if not yes and not sys.stdin.isatty():
        raise ValueError("Re-run with --yes to confirm")


def _confirm(yes: bool) -> None:
    _require_confirmation(yes)
    if not yes and input("Confirm [y/N]: ").strip().casefold() not in {"y", "yes"}:
        raise ValueError("Cancelled.")


def _submit_secret(ctx: Context, payload: dict[str, object], yes: bool) -> None:
    # This boundary must sanitize even transport exceptions and disable getpass's
    # fallback to echoed input. Never expose the gateway reply or exception body.
    failed = False
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            value = getpass.getpass("Secret (hidden): ")
        _confirm(yes)
        ctx.manager().command("submitSecret", {**payload, "value": value})
    except Exception:  # noqa: BLE001 - secret submission is a redaction boundary
        failed = True
    if failed:
        raise ValueError(
            "Secret was not submitted successfully; no value is displayed."
        )


def answer(args: argparse.Namespace, ctx: Context) -> int:
    if args.command == "secret" and args.unexpected_values:
        raise ValueError("Secret values must be entered at the hidden prompt.")
    item = resolve_ref(ctx, args.ref)
    method, payload = _plan(args, item)
    print(
        f"Bot: {item.bot_name} ({item.bot_id})  Type: {item.type}  REF: {item.entry_id}"
    )
    print(f"Summary: {item.summary}")
    if item.tool_text:
        print(command_block(item.tool_text))
    print(
        f"Answer: {method}"
        + (f" ({payload['resolution']})" if "resolution" in payload else "")
    )
    _require_confirmation(args.yes)
    if method == "submitSecret":
        _submit_secret(ctx, payload, args.yes)
    else:
        _confirm(args.yes)
        ctx.manager().command(method, payload)
    print("Answered.")
    return 0
