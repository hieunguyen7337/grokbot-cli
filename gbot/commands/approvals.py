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
from groken.client import GROK_BOT


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
    if item.session_id:
        payload["sessionId"] = item.session_id
    if item.type in {"email-draft", "slack-draft", "meeting-chat-draft"}:
        if getattr(args, "always", False) or getattr(args, "never", False):
            raise ValueError("--always and --never do not apply to drafts.")
        if item.draft is None:
            raise ValueError("Pending draft is missing its draft record.")
        if action == "deny":
            return "DiscardGrokBotDraft", payload
        if item.type == "email-draft":
            payload["email"] = {
                key: item.draft.get(key, [] if key == "cc" else "")
                for key in ("from", "to", "cc", "subject", "body")
            }
        else:
            payload["slack"] = {
                key: item.draft[key]
                for key in ("target", "body", "workspace", "thread")
                if key in item.draft
            }
        return "SendGrokBotDraft", payload
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
        payload.update(
            requestId=item.request_id,
            resolution={
                "approved": 1,
                "denied": 2,
                "allow-once": 1,
                "deny": 2,
                "always": 3,
                "never": 4,
            }[resolution],
        )
        if not tool:
            payload.pop("entryId")
            payload["approvalPlatform"] = "desktop"
        return (
            "ResolveGrokBotLocalToolPermission"
            if tool
            else "ResolveGrokBotAutoReviewApproval"
        ), payload
    if action == "respond":
        if item.type == "widget":
            if args.value is None or args.field:
                raise ValueError("Use: gbot respond REF VALUE for a widget.")
            if (
                item.validate_options
                and item.options is not None
                and args.value not in item.options
            ):
                raise ValueError(
                    "Invalid widget value. Options: " + " | ".join(item.options)
                )
            payload["value"] = args.value
            return "RespondGrokBotWidget", payload
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
        if item.fields is not None:
            valid = [
                field["id"] for field in item.fields if isinstance(field.get("id"), str)
            ]
            unknown = [name for name in values if name not in valid]
            if unknown:
                raise ValueError(
                    "Unknown field id: "
                    + ", ".join(unknown)
                    + ". Valid ids: "
                    + ", ".join(str(name) for name in valid)
                )
            for field in item.fields:
                if (
                    field.get("required")
                    and isinstance(field.get("id"), str)
                    and field["id"] not in values
                ):
                    raise ValueError(f"Missing required field: {field['id']}")
        payload.update(values=values, saveToVault=False, platform=1)
        return "SubmitGrokBotUserForm", payload
    if action == "dismiss":
        if item.type == "widget":
            return "DismissGrokBotWidget", payload
        payload.update(mode=1, platform=1)
        return "DismissGrokBotUserForm", payload
    return "SubmitGrokBotSecret", payload


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


def _check_reply(
    reply: dict[str, object], method: str, *, secret: bool = False
) -> None:
    refusal = reply.get("refusal")
    if isinstance(refusal, dict):
        code = refusal.get("failureCode", "unknown")
        message = refusal.get("message")
        detail = f"Answer refused: {code}"
        if message and not secret:
            detail += f": {message}"
        raise ValueError(detail)  # noqa: TRY004 - refusal is a service error
    flag = "dispatched" if method.startswith("ResolveGrokBot") else "accepted"
    if reply.get(flag) is not True:
        raise ValueError(
            "Answer was not accepted; the item may already be answered. Run: gbot approvals"
        )


def _submit_secret(ctx: Context, payload: dict[str, object], yes: bool) -> None:
    # This boundary must sanitize even transport exceptions and disable getpass's
    # fallback to echoed input. Never expose the reply body or a refusal message.
    failure = None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            value = getpass.getpass("Secret (hidden): ")
        _confirm(yes, json_mode=ctx.out.json_mode)
        reply = ctx.backend().unary(
            GROK_BOT, "SubmitGrokBotSecret", {**payload, "value": value}
        )
        try:
            _check_reply(reply, "SubmitGrokBotSecret", secret=True)
        except ValueError as exc:
            failure = str(exc)
    except Exception:  # noqa: BLE001 - secret submission is a redaction boundary
        failure = "Secret was not submitted successfully; no value is displayed."
    if failure:
        raise ValueError(failure)


def _resolution_word(args: argparse.Namespace, item: PendingItem) -> str:
    if getattr(args, "always", False):
        return "always"
    if getattr(args, "never", False):
        return "never"
    if item.type == "local-tool-permission":
        return "allow-once" if args.command == "approve" else "deny"
    return "approved" if args.command == "approve" else "denied"


def answer(args: argparse.Namespace, ctx: Context) -> int:
    if args.command == "secret" and args.unexpected_values:
        raise ValueError("Secret values must be entered at the hidden prompt.")
    item = resolve_ref(ctx, args.ref)
    method, payload = _plan(args, item)
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
    effect = {
        "SendGrokBotDraft": "sends it now",
        "DiscardGrokBotDraft": "discards it",
    }.get(method)
    if effect is None and "resolution" in payload:
        effect = _resolution_word(args, item)
    print(f"Answer: {method}" + (f" ({effect})" if effect else ""), file=preview)
    _require_confirmation(args.yes)
    if method == "SubmitGrokBotSecret":
        _submit_secret(ctx, payload, args.yes)
    else:
        _confirm(args.yes, json_mode=ctx.out.json_mode)
        reply = ctx.backend().unary(GROK_BOT, method, payload)
        _check_reply(reply, method)
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
