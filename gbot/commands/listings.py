"""Where a bot's skills can be published, and skill and plugin listing changes."""

import argparse
from collections.abc import Callable
from dataclasses import asdict
from typing import TypeVar

from gbot.bots import resolve_bot
from gbot.commands.approvals import _confirm, _require_confirmation
from gbot.commands.plugins import find_plugin
from gbot.context import Context
from gbot.service import listings as service
from gbot.service import plugins as plugin_service
from gbot.service import workflows
from gbot.service.errors import refusal
from gbot.service.transport import ContextTransport
from groken.client import ConnectError

T = TypeVar("T")
CHANGES = ("publish-skill", "resync-skill", "unpublish-skill", "unpublish-plugin")


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "listings", help="Publish skills and take plugin listings down"
    )
    children = parser.add_subparsers(dest="listing", required=True)
    for name in ("targets", "plugin", *CHANGES):
        child = children.add_parser(name)
        if name != "targets":
            child.add_argument("bot", metavar="BOT")
            child.add_argument(
                "item", metavar="PLUGIN" if name.endswith("plugin") else "SKILL"
            )
        if name in {"publish-skill", "unpublish-plugin"}:
            child.add_argument("--team", metavar="ID")
        if name in CHANGES:
            child.add_argument("--yes", action="store_true")
        child.add_argument("--json", action="store_true")
        child.set_defaults(func=run)


def _call(work: Callable[[], T]) -> T:
    try:
        return work()
    except ConnectError as error:
        notice = refusal(error)
        if notice is None:
            raise
        raise ValueError(notice.message) from None


def _checked(result: service.ListingResult) -> service.ListingResult:
    if not result.ok:
        raise ValueError(result.message or "The server did not accept this change.")
    return result


def _line(done: str, result: service.ListingResult) -> str:
    return " · ".join(part for part in (done, result.state, result.message) if part)


def run(args: argparse.Namespace, ctx: Context) -> int:
    change = args.listing in CHANGES
    if change:
        _require_confirmation(args.yes)
        _confirm(args.yes, json_mode=args.json)
    transport = ContextTransport(ctx)
    if args.listing == "targets":
        found = _call(lambda: service.publish_targets(transport))
        ctx.out.write(
            {
                "teams": [asdict(team) for team in found.teams],
                "unavailable_reason": found.unavailable_reason,
                "unavailable_kind": found.unavailable_kind,
            },
            "\n".join(f"{team.team_id}  {team.name}" for team in found.teams)
            or found.unavailable_reason
            or "No publish targets",
        )
        return 0
    bot_id, _ = resolve_bot(ctx, args.bot)
    if args.listing.endswith("plugin"):
        plugin = find_plugin(
            _call(lambda: plugin_service.bot_plugins(transport, bot_id)), args.item
        )
        key = str(plugin.plugin_id)
        if args.listing == "plugin":
            restorable = _call(lambda: service.has_restorable_copy(transport, key))
            ctx.out.write(
                {
                    "plugin_id": plugin.plugin_id,
                    "name": plugin.display_name,
                    "restorable_copy": restorable,
                },
                f"{plugin.display_name}: "
                + (
                    "a private copy stays if the listing is removed."
                    if restorable
                    else "no private copy remains if the listing is removed."
                ),
            )
            return 0
        result = _checked(
            _call(lambda: service.unpublish_plugin_listing(transport, key, args.team))
        )
        ctx.out.write(
            {"plugin_id": plugin.plugin_id, **asdict(result)},
            _line(f"Removed the {plugin.display_name} listing", result),
        )
        return 0
    skill = workflows.find(
        _call(lambda: workflows.skills(transport, bot_id)), args.item
    )
    if args.listing == "publish-skill":
        result = _checked(
            _call(lambda: service.publish_skill(transport, skill.id, args.team))
        )
        done = f"Published {skill.name}"
    elif args.listing == "resync-skill":
        result = _checked(_call(lambda: service.resync_skill(transport, skill.id)))
        done = f"Resynced {skill.name}"
    else:
        result = _checked(_call(lambda: service.unpublish_skill(transport, skill.id)))
        done = f"Unpublished {skill.name}"
    ctx.out.write({"workflow_id": skill.id, **asdict(result)}, _line(done, result))
    return 0
