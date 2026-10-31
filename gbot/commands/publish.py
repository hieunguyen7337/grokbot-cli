"""Marketplace listing and template publishing for one bot."""

import argparse
import sys
from dataclasses import asdict

from gbot.bots import resolve_bot
from gbot.commands.approvals import _confirm, _require_confirmation
from gbot.context import Context
from gbot.output import terminal_safe
from gbot.service import conversation, publishing
from gbot.service.errors import refusal
from gbot.service.transport import ContextTransport
from groken.client import ConnectError


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "publish", help="List a bot in the marketplace and publish its template"
    )
    parser.add_argument("bot", metavar="BOT", nargs="?")
    parser.add_argument("--listing", choices=("on", "off"))
    parser.add_argument("--template-version", type=int, metavar="N")
    parser.add_argument("--template-visibility", choices=("public", "team"))
    parser.add_argument("--delete-template", action="store_true")
    parser.add_argument("--share-id", metavar="ID")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.set_defaults(func=run)


def _refused(error: ConnectError) -> ValueError | ConnectError:
    refused = refusal(error)
    return ValueError(refused.message) if refused else error


def _confirm_delete(name: str, yes: bool) -> None:
    if yes:
        return
    _require_confirmation(yes)
    print(
        terminal_safe(f"Type the template name ({name}) to delete it: "),
        end="",
        file=sys.stderr,
        flush=True,
    )
    if input("").strip() != name:
        raise ValueError("Cancelled.")


def run(args: argparse.Namespace, ctx: Context) -> int:
    template_change = (
        args.template_version is not None
        or args.template_visibility is not None
        or args.delete_template
    )
    changing = template_change or args.listing is not None
    if args.share_id and not template_change:
        raise ValueError(
            "Use --share-id with --template-version, --template-visibility or --delete-template."
        )
    if args.template_version is not None and args.template_version < 1:
        raise ValueError("--template-version must be 1 or more.")
    if args.delete_template and (
        args.template_version is not None or args.template_visibility is not None
    ):
        raise ValueError(
            "--delete-template cannot be combined with other template changes."
        )
    transport = ContextTransport(ctx)
    bot_id, _ = resolve_bot(ctx, args.bot)
    bot = next(
        (item for item in conversation.roster(transport) if item.id == bot_id), None
    )
    if bot is None:
        raise ValueError("Unknown bot: " + str(args.bot))
    try:
        state = publishing.overview(transport, bot)
    except ConnectError as error:
        raise _refused(error) from error
    template = state.template
    if args.share_id and (template is None or template.share_id != args.share_id):
        template = None
    share_id = args.share_id or (template.share_id if template else "")
    if template_change:
        if state.policy == "none":
            raise ValueError(publishing.policy_sentence("none"))
        if args.template_visibility == "public" and state.policy == "team_only":
            raise ValueError(publishing.policy_sentence("team_only"))
        if not share_id:
            raise ValueError("This bot has no template to change.")
    if changing:
        # Nothing is sent before the person has confirmed.
        if args.delete_template:
            _confirm_delete(
                template.name if template and template.name else share_id, args.yes
            )
        else:
            _require_confirmation(args.yes)
            _confirm(args.yes, json_mode=args.json)
    result: dict[str, object] = {}
    lines: list[str] = []
    try:
        if args.listing is not None:
            listed = (
                publishing.publish_bot(transport, bot_id)
                if args.listing == "on"
                else publishing.unpublish_bot(transport, bot_id)
            )
            result["listing"] = {**asdict(listed), "sentence": listed.sentence}
            lines.append(listed.sentence)
        if args.template_version is not None:
            changed = publishing.publish_template(
                transport, share_id, args.template_version
            )
            result["template"] = asdict(changed)
            lines.append(
                f"Published version {args.template_version} of {changed.name or share_id}."
            )
        if args.template_visibility is not None:
            changed = publishing.set_template_visibility(
                transport, share_id, args.template_visibility
            )
            result["template"] = asdict(changed)
            lines.append(
                f"{changed.name or share_id} is now visible to {args.template_visibility}."
            )
        if args.delete_template:
            publishing.delete_template(transport, share_id)
            result["deleted"] = share_id
            lines.append("Template deleted.")
    except ConnectError as error:
        raise _refused(error) from error
    if changing:
        ctx.out.write(result, "\n".join(lines))
        return 0
    ctx.out.write(
        {
            "bot_id": bot_id,
            "marketplace": state.listing,
            "published_at_ms": state.published_at_ms,
            "template": asdict(template) if template else None,
            "export_policy": state.policy,
            "export_policy_sentence": publishing.policy_sentence(state.policy),
            "notes": list(state.notes),
        },
        _describe(state, template),
    )
    return 0


def _describe(
    state: publishing.Overview, template: publishing.OwnTemplate | None
) -> str:
    lines = [f"Marketplace: {state.listing}"]
    if template is None:
        lines.append("Template: none")
    else:
        lines.extend(
            (
                f"Template: {template.name}",
                f"Share ID: {template.share_id}",
                f"Published: {'yes' if template.published else 'no'}",
                f"Active version: {template.active_version or 'none'}",
                f"Visibility: {template.visibility}",
            )
        )
    lines.append(publishing.policy_sentence(state.policy))
    lines.extend(state.notes)
    return "\n".join(lines)
