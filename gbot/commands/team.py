"""Team bots: list them, read a bot's context and review queue, change reviews, share memories, team link previews."""

import argparse
from dataclasses import asdict

from gbot.bots import resolve_bot
from gbot.commands.approvals import _confirm, _require_confirmation
from gbot.context import Context
from gbot.service import team_bots
from gbot.service.errors import refusal
from gbot.service.transport import ContextTransport
from groken.client import ConnectError

_CHANGES = ("--approve", "--reject", "--promote")


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "team", help="Review team bots (needs a team account)"
    )
    parser.add_argument("bot", metavar="BOT", nargs="?")
    parser.add_argument("--role", help="List only team bots with this role")
    parser.add_argument(
        "--summary", action="store_true", help="Show the bot's shared context"
    )
    parser.add_argument(
        "--review", action="store_true", help="List the bot's review items"
    )
    parser.add_argument(
        "--status",
        action="append",
        choices=("pending", "approved", "rejected"),
        help="With --review: a status to list, repeatable (default pending)",
    )
    parser.add_argument(
        "--limit", type=int, help="With --review: most items to list (default 100)"
    )
    parser.add_argument(
        "--memories",
        action="store_true",
        help="List the memories you can share with the team",
    )
    parser.add_argument("--approve", metavar="ITEM", help="Approve a review item")
    parser.add_argument("--reject", metavar="ITEM", help="Reject a review item")
    parser.add_argument(
        "--promote",
        nargs="+",
        metavar="FACT_ID",
        help="Share these memories with the team",
    )
    parser.add_argument(
        "--link-preview",
        metavar="TEAM_ID",
        help="Show a team's link previews; change them with --set",
    )
    parser.add_argument(
        "--set",
        dest="setting",
        choices=("on", "off"),
        help="With --link-preview: turn link previews on or off",
    )
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace, ctx: Context) -> int:
    try:
        return _run(args, ctx)
    except ConnectError as error:
        found = refusal(error)
        if found is None:
            raise
        # A refused call is a notice: its message, exit 1, no traceback.
        raise ValueError(found.message) from None


def _run(args: argparse.Namespace, ctx: Context) -> int:
    actions = [
        flag
        for flag, chosen in (
            ("--summary", args.summary),
            ("--review", args.review),
            ("--memories", args.memories),
            ("--approve", args.approve is not None),
            ("--reject", args.reject is not None),
            ("--promote", args.promote is not None),
        )
        if chosen
    ]
    if args.link_preview is not None:
        if (
            args.bot is not None
            or actions
            or args.role is not None
            or args.status
            or args.limit is not None
        ):
            raise ValueError("Use --link-preview with --set, alone.")
        return _link_preview(args, ctx)
    if args.setting is not None:
        raise ValueError("Use --set with --link-preview.")
    if args.bot is None:
        if actions or args.status or args.limit is not None:
            raise ValueError("Name a BOT for that option.")
        return _team_bots(args, ctx)
    if args.role is not None:
        raise ValueError("Use --role without BOT.")
    if len(actions) != 1:
        raise ValueError(
            "Choose one of --summary, --review, --memories, --approve, --reject, --promote."
        )
    if actions[0] != "--review" and (args.status or args.limit is not None):
        raise ValueError("Use --status and --limit with --review.")
    if actions[0] in _CHANGES:
        _require_confirmation(args.yes)
        _confirm(args.yes, json_mode=args.json)
    return _bot(args, ctx, actions[0])


def _team_bots(args: argparse.Namespace, ctx: Context) -> int:
    agents = team_bots.team_agents(ContextTransport(ctx), args.role).entries
    ctx.out.write(
        [asdict(agent) for agent in agents],
        "\n".join(_agent_line(agent) for agent in agents) or "No team bots.",
    )
    return 0


def _bot(args: argparse.Namespace, ctx: Context, action: str) -> int:
    transport = ContextTransport(ctx)
    bot_id, _ = resolve_bot(ctx, args.bot)
    if action == "--summary":
        summary = team_bots.context_summary(transport, bot_id)
        ctx.out.write(asdict(summary), _summary_text(summary))
    elif action == "--review":
        limit = 100 if args.limit is None else args.limit
        if limit < 1:
            raise ValueError("--limit must be at least 1.")
        items = team_bots.review_items(
            transport, bot_id, tuple(args.status or ("pending",)), limit
        )
        ctx.out.write(
            [asdict(item) for item in items],
            "\n".join(_item_line(item) for item in items) or "No review items.",
        )
    elif action == "--memories":
        facts = team_bots.bot_memories(transport, bot_id)
        ctx.out.write(
            [asdict(fact) for fact in facts],
            "\n".join(f"{fact.fact_id}  {fact.text}" for fact in facts)
            or "No memories to share.",
        )
    elif action in ("--approve", "--reject"):
        approve = action == "--approve"
        item_id = args.approve if approve else args.reject
        if not item_id or not item_id.strip():
            raise ValueError("Give the review item ID.")
        item = team_bots.resolve_review_item(transport, bot_id, item_id, approve)
        ctx.out.write(
            asdict(item),
            f"{'Approved' if approve else 'Rejected'} review item {item_id}.",
        )
    else:
        result = team_bots.promote_memories(transport, bot_id, args.promote)
        ctx.out.write(asdict(result), team_bots.promote_sentence(result))
    return 0


def _link_preview(args: argparse.Namespace, ctx: Context) -> int:
    if not args.link_preview.strip().isdecimal():
        raise ValueError("TEAM_ID must be a number.")
    team_id = int(args.link_preview)
    transport = ContextTransport(ctx)
    if args.setting is not None:
        _require_confirmation(args.yes)
        _confirm(args.yes, json_mode=args.json)
        enabled = team_bots.set_link_preview(transport, team_id, args.setting == "on")
    else:
        enabled = team_bots.link_preview(transport, team_id)
    ctx.out.write(
        {"team_id": team_id, "enabled": enabled},
        f"Link previews are {'on' if enabled else 'off'} for team {team_id}.",
    )
    return 0


def _agent_line(agent: team_bots.TeamAgent) -> str:
    signals = f"{agent.user_turns} user turns, {agent.teammate_turns} teammate turns"
    last = team_bots.date_text(agent.last_turn_at_ms)
    return f"{agent.name or agent.agent_id}  {signals}" + (
        f"  last turn {last}" if last else ""
    )


def _item_line(item: team_bots.ReviewItem) -> str:
    change = item.change
    kind = " ".join(
        part
        for part in (change.kind.replace("_", " "), change.action)
        if part and part != "unspecified"
    )
    return f"{item.item_id}  {item.status}  {kind}  {change.summary}".rstrip()


def _summary_text(summary: team_bots.ContextSummary) -> str:
    lines = [
        summary.prose or "No summary yet.",
        f"Memories: {summary.memory_count} ({'stale' if summary.stale else 'current'})",
    ]
    if summary.skills:
        lines.append("Skills: " + ", ".join(summary.skills))
    lines.extend(f"Learned: {fact.text}" for fact in summary.learned)
    return "\n".join(lines)
