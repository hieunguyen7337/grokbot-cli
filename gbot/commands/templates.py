import argparse
from dataclasses import asdict

from gbot.commands.approvals import _confirm, _require_confirmation
from gbot.context import Context
from gbot.service import templates
from gbot.service.transport import ContextTransport


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "templates", help="Browse and import public bot templates"
    )
    parser.add_argument("--category")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--yes", action="store_true")
    parser.set_defaults(func=run)
    children = parser.add_subparsers(dest="template_action")
    for name in ("show", "use"):
        child = children.add_parser(name)
        child.add_argument("share_id", metavar="SHARE_ID")
        child.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
        if name == "use":
            child.add_argument("--yes", action="store_true", default=argparse.SUPPRESS)
        child.set_defaults(func=run)


def run(args: argparse.Namespace, ctx: Context) -> int:
    transport = ContextTransport(ctx)
    if args.template_action is None:
        market = templates.marketplace(transport, args.category)
        ctx.out.write(
            asdict(market),
            "\n".join(
                f"{item.share_id}: {item.name} — {item.description} ({item.creator_name})"
                for item in (*market.featured_listings, *market.listings)
            ),
        )
        return 0
    if args.template_action == "use":
        _require_confirmation(args.yes)
    detail = templates.details(transport, args.share_id)
    if args.template_action == "show":
        ctx.out.write(
            asdict(detail),
            f"{detail.template.get('name', '')}\n{detail.template.get('description', '')}\nCreator: {detail.creator_display_name}\nVersion: {detail.expected_active_version}",
        )
    else:
        # The reviewed summary and version are the same ones sent to the importer.
        if not args.yes:
            import sys

            from gbot.output import terminal_safe

            print(
                terminal_safe(
                    f"Create from {detail.template.get('name', '')} by {detail.creator_display_name}?"
                ),
                file=sys.stderr,
            )
        _confirm(args.yes, json_mode=args.json)
        result = templates.create_from_template(transport, detail)
        ctx.out.write(
            {
                "bot": dict(result.bot.raw),
                "setup_handled_by_server": result.setup_handled_by_server,
                "note": result.note,
            },
            f"Created {result.bot.name} [{result.bot.id}]"
            + (f"\n{result.note}" if result.note else ""),
        )
    return 0
